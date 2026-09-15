"""画布节点/连线 CRUD + 内容 + 执行（AI 改写/审定/成稿）+ WebSocket 状态广播"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import hashlib

from ..ai_runtime import ai_config
from ..ai import (FORMAT_LABELS, PROMPTS, PUBLIC_MODELS, TOOL_KINDS, ai_review, public_model,
                  rewrite,
                  tool_run, typeset)
from ..pdf_tools import merge_blocks
from ..audit import log as audit_log
from ..concurrency import ai_slot
from ..templates import effective_prompts, resolve_prompt, resolve_prompt_detail
from ..usage import (PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK, ensure_quota,
                     record_usage)
from ..db import get_db
from ..paths import UPLOAD_ROOT
from ..deps import get_current_user
from ..models import CanvasEdge, CanvasNode, NodeTemplate, Project, Revision, RunLog, User
from ..schemas import ContentIn, EdgeCreate, ExecuteIn, NodeCreate, NodeUpdate, ReviewIn
from ..ws import manager

router = APIRouter()

REWRITEABLE = ("rewriter", "transformer")


def _rev_out(r: Revision) -> dict:
    return {
        "id": r.id, "node_id": r.node_id, "parent_revision_id": r.parent_revision_id,
        "title": r.title or "", "content": r.content or "", "format_type": r.format_type or "",
        "status": r.status or "draft", "model": public_model(r.model),
        "review_comment": r.review_comment or "",
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _public_config(cfg: dict | None) -> dict:
    """节点配置对外输出：把模型档位折算为别名（standard/reasoner），不暴露厂商型号。"""
    out = dict(cfg or {})
    if out.get("model"):
        out["model"] = public_model(str(out["model"]))
    return out


def _node_out(n: CanvasNode) -> dict:
    return {
        "id": n.id, "type": n.type, "subtype": n.subtype, "label": n.label,
        "position": {"x": n.position_x or 0, "y": n.position_y or 0},
        "config": _public_config(n.config), "status": n.status or "idle", "error": n.error or "",
    }


def _edge_out(e: CanvasEdge) -> dict:
    return {"id": e.id, "source": e.source_node_id, "target": e.target_node_id}


async def _owned_project(db: AsyncSession, pid: str, user: User) -> Project:
    p = await db.get(Project, pid)
    if not p or p.owner_id != user.id:
        raise HTTPException(404, "项目不存在")
    return p


async def _owned_node(db: AsyncSession, nid: str, user: User) -> CanvasNode:
    n = await db.get(CanvasNode, nid)
    if not n:
        raise HTTPException(404, "节点不存在")
    await _owned_project(db, n.project_id, user)
    return n


async def set_status(db: AsyncSession, node: CanvasNode, status: str, error: str = "") -> None:
    node.status = status
    node.error = error
    await db.commit()
    await manager.broadcast(node.project_id, {"type": "node_status", "node_id": node.id,
                                              "status": status, "error": error})


async def upstream_revisions(db: AsyncSession, node: CanvasNode) -> list[Revision]:
    """选择输入稿件池：先取直接上游；若直接上游不产内容（如 reviewer），
    再沿边向更上游扩展。返回候选 Revision（每节点取最新，整体最新在前）。"""
    all_edges = (
        await db.execute(select(CanvasEdge).where(CanvasEdge.project_id == node.project_id))
    ).scalars().all()
    reverse: dict[str, list[str]] = {}
    for e in all_edges:
        reverse.setdefault(e.target_node_id, []).append(e.source_node_id)

    async def collect(ids: list[str]) -> list[Revision]:
        if not ids:
            return []
        rows = await db.execute(
            select(Revision).where(Revision.node_id.in_(ids), Revision.project_id == node.project_id)
            .order_by(Revision.created_at.asc())
        )
        return list(rows.scalars())

    def newest_per_node(revisions: list[Revision]) -> list[Revision]:
        by_node: dict[str, Revision] = {}
        for r in revisions:
            prev = by_node.get(r.node_id)
            if prev is None or (r.created_at or r.id) >= (prev.created_at or prev.id):
                by_node[r.node_id] = r
        return sorted(by_node.values(), key=lambda r: r.created_at or r.id, reverse=True)

    # 1) 直接上游（优先）
    direct = await collect(reverse.get(node.id, []))
    if direct:
        return newest_per_node(direct)
    # 2) 直接上游为空 → 传递性回溯
    seen: set[str] = set()
    stack = list(reverse.get(node.id, []))
    upstream_ids: set[str] = set()
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        upstream_ids.add(nid)
        stack.extend(reverse.get(nid, []))
    return newest_per_node(await collect(list(upstream_ids)))


USAGE_KEYS = ("prompt_tokens", "completion_tokens", "duration_ms", "prompt_chars", "output_chars")


def _usage_kwargs(usage: dict) -> dict:
    """只取 record_usage 认识的字段（usage 里还带 retries 等展示用信息）"""
    return {k: int(usage.get(k) or 0) for k in USAGE_KEYS}


async def _queued_notice(node: CanvasNode, waited: float) -> None:
    """排队超过 0.8 秒时，实时提示前端该节点正在排队"""
    if waited > 0.8:
        await manager.broadcast(node.project_id, {"type": "node_status", "node_id": node.id,
                                                  "status": "queued", "error": "",
                                                  "waited_ms": int(waited * 1000)})


def _is_style(rev: Revision) -> bool:
    """风格提取节点的产物是「风格提示词」，不是稿件内容。"""
    return (rev.format_type or "") == "style_prompt"


def _pick_revision(candidates: list[Revision], prefer_id: str | None) -> Revision | None:
    if prefer_id:
        for r in candidates:
            if r.id == prefer_id:
                return r
    for r in candidates:                       # 优先已审定/已通过的
        if r.status in ("approved", "reviewed"):
            return r
    return candidates[0] if candidates else None


# ---------- 画布 ----------

@router.get("/prompts")
async def list_prompts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """返回各格式的**生效**提示词（全站模板覆盖内置）、格式名称与可选模型档位。

    注意：必须走 effective_prompts，否则管理员改的全站提示词不会体现在节点面板里。
    """
    return {"prompts": await effective_prompts(db, user), "labels": FORMAT_LABELS,
            "models": PUBLIC_MODELS,   # 只给中性别名，界面不出现模型厂商
            "default_model": public_model(ai_config().get("default_model"))}


@router.get("/projects/{pid}/canvas")
async def get_canvas(pid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_project(db, pid, user)
    nodes = (await db.execute(select(CanvasNode).where(CanvasNode.project_id == pid))).scalars().all()
    edges = (await db.execute(select(CanvasEdge).where(CanvasEdge.project_id == pid))).scalars().all()
    return {"nodes": [_node_out(n) for n in nodes], "edges": [_edge_out(e) for e in edges]}


@router.post("/projects/{pid}/nodes")
async def create_node(pid: str, body: NodeCreate, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    await _owned_project(db, pid, user)
    if body.type not in ("draft_input", "rewriter", "reviewer", "ai_reviewer", "transformer", "tool", "exporter"):
        raise HTTPException(400, "未知节点类型")
    if body.type in REWRITEABLE and not body.subtype:
        raise HTTPException(400, "改写/转换节点需要 format_type（tv_script/newspaper/wechat/...）")
    if body.type == "tool" and body.subtype and body.subtype not in TOOL_KINDS + ("pdf_extract",):
        raise HTTPException(400, f"不支持的工具类型：{body.subtype}")
    node = CanvasNode(project_id=pid, type=body.type, subtype=body.subtype, label=body.label or body.type,
                      position_x=body.position.x, position_y=body.position.y, config=body.config or {})
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return _node_out(node)


@router.put("/nodes/{nid}")
async def update_node(nid: str, body: NodeUpdate, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    node = await _owned_node(db, nid, user)
    if body.position is not None:
        node.position_x, node.position_y = body.position.x, body.position.y
    if body.config is not None:
        node.config = body.config
    if body.label is not None:
        node.label = body.label
    await db.commit()
    return _node_out(node)


@router.delete("/nodes/{nid}")
async def delete_node(nid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    node = await _owned_node(db, nid, user)
    # 清理该节点的上传文件（PDF 版面提取等）
    try:
        import shutil
        shutil.rmtree(UPLOAD_ROOT / node.project_id / nid, ignore_errors=True)
    except Exception:
        pass
    await db.execute(delete(CanvasEdge).where((CanvasEdge.source_node_id == nid) | (CanvasEdge.target_node_id == nid)))
    await db.execute(delete(Revision).where(Revision.node_id == nid))
    await db.execute(delete(CanvasNode).where(CanvasNode.id == nid))
    await db.commit()
    return {"ok": True}


@router.post("/projects/{pid}/edges")
async def create_edge(pid: str, body: EdgeCreate, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    await _owned_project(db, pid, user)
    if body.source == body.target:
        raise HTTPException(400, "不能连接自身")
    src = await db.get(CanvasNode, body.source)
    dst = await db.get(CanvasNode, body.target)
    if not src or not dst or src.project_id != pid or dst.project_id != pid:
        raise HTTPException(404, "节点不存在或不属于该项目")
    dup = await db.execute(select(CanvasEdge).where(CanvasEdge.source_node_id == body.source,
                                                    CanvasEdge.target_node_id == body.target))
    if dup.scalar_one_or_none():
        raise HTTPException(400, "连线已存在")
    edge = CanvasEdge(project_id=pid, source_node_id=body.source, target_node_id=body.target)
    db.add(edge)
    await db.commit()
    await db.refresh(edge)
    return _edge_out(edge)


@router.delete("/edges/{eid}")
async def delete_edge(eid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    edge = await db.get(CanvasEdge, eid)
    if not edge:
        raise HTTPException(404, "连线不存在")
    await db.execute(delete(CanvasEdge).where(CanvasEdge.id == eid))
    await db.commit()
    return {"ok": True}


# ---------- 内容与审稿 ----------

@router.post("/nodes/{nid}/content")
async def save_content(nid: str, body: ContentIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    node = await _owned_node(db, nid, user)
    if node.type != "draft_input":
        raise HTTPException(400, "只有草稿输入节点可保存原始稿件")
    latest = (await db.execute(
        select(Revision).where(Revision.node_id == nid).order_by(Revision.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if latest and latest.status == "draft":
        latest.title, latest.content = body.title, body.content
        rev = latest
    else:
        rev = Revision(project_id=node.project_id, node_id=nid, title=body.title, content=body.content,
                       format_type="draft", status="draft")
        db.add(rev)
    await db.commit()
    await db.refresh(rev)
    return _rev_out(rev)


@router.get("/nodes/{nid}/revision")
async def node_revision(nid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_node(db, nid, user)
    rev = (await db.execute(
        select(Revision).where(Revision.node_id == nid).order_by(Revision.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    return _rev_out(rev) if rev else None


@router.get("/nodes/{nid}/history")
async def node_history(nid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_node(db, nid, user)
    rows = await db.execute(
        select(Revision).where(Revision.node_id == nid).order_by(Revision.created_at.desc()).limit(20)
    )
    return [_rev_out(r) for r in rows.scalars()]


@router.get("/revisions/{rid}")
async def get_revision(rid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """按 ID 获取任意 Revision（用于成稿预览/追溯）。"""
    rev = await db.get(Revision, rid)
    if not rev:
        raise HTTPException(404, "稿件不存在")
    await _owned_project(db, rev.project_id, user)
    return _rev_out(rev)


@router.post("/revisions/{rid}/status")
async def review_revision(rid: str, body: ReviewIn, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    rev = await db.get(Revision, rid)
    if not rev:
        raise HTTPException(404, "稿件不存在")
    await _owned_project(db, rev.project_id, user)
    if body.status not in ("approved", "reviewed", "draft", "finalized"):
        raise HTTPException(400, "非法状态")
    rev.status = body.status
    rev.review_comment = body.comment or rev.review_comment
    await db.commit()
    await audit_log(db, action="review_manual", user=user, target_type="revision", target_id=rid,
                    detail={"status": body.status, "comment": (body.comment or "")[:100]})
    await manager.broadcast(rev.project_id, {"type": "revision", "project_id": rev.project_id})
    return _rev_out(rev)


# ---------- 执行 ----------



# ---------------- 运行台账（run_logs）埋点 ----------------
PREVIEW_CHARS = 500


def _preview(text: str | None, n: int = PREVIEW_CHARS) -> str:
    return (text or "").strip()[:n]


def _short_hash(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


async def _start_run(db: AsyncSession, user: User, node: CanvasNode, trigger: str) -> RunLog:
    """执行开始即建一条台账（状态先为 running，便于后台看到正在跑的任务）"""
    project = await db.get(Project, node.project_id)
    tpl = (await db.execute(
        select(NodeTemplate).where(NodeTemplate.kind == node.type, NodeTemplate.subtype == node.subtype,
                                   NodeTemplate.scope == "global").limit(1)
    )).scalar_one_or_none()
    run = RunLog(
        user_id=user.id, username=user.username, project_id=node.project_id,
        project_name=(project.name if project else ""), node_id=node.id, node_type=node.type,
        node_subtype=node.subtype, node_label=node.label or "", trigger=trigger, status="running",
        template_key=((project.template_key or "") if project else ""),
        node_template_id=(tpl.id if tpl else None),
        node_template_version=(int(tpl.version or 1) if tpl else 0),
    )
    db.add(run)
    return run


async def _prompt_info(db: AsyncSession, key: str, cfg: dict) -> dict:
    """本次实际生效的提示词来源（node > 全站模板 > 内置）"""
    custom = (cfg or {}).get("prompt")
    if custom:
        return {"prompt_source": "node", "prompt_hash": _short_hash(custom), "prompt_preview": _preview(custom, 200)}
    detail = await resolve_prompt_detail(db, key)
    return {"prompt_source": detail["source"], "prompt_hash": _short_hash(detail["text"]),
            "prompt_preview": _preview(detail["text"], 200),
            "prompt_template_id": detail.get("template_id"),
            "prompt_template_version": int(detail.get("version") or 0)}


async def _finish_run(db: AsyncSession, run: RunLog | None, *, status: str = "ok", error: str = "",
                      output: Revision | None = None, usage: dict | None = None, model: str = "",
                      params: dict | None = None, prompt: dict | None = None) -> None:
    if run is None:
        return
    run.status = status
    run.error = (error or "")[:1000]
    if output is not None:
        run.output_revision_id = output.id
        run.output_chars = len(output.content or "")
        run.output_preview = _preview(output.content)
    if model:
        run.model = model
    if usage:
        run.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        run.completion_tokens = int(usage.get("completion_tokens") or 0)
        run.duration_ms = int(usage.get("duration_ms") or 0)
        run.retries = int(usage.get("retries") or 0)
        run.queued_ms = int(usage.get("queued_ms") or 0)
        run.cost_est = round(run.prompt_tokens / 1_000_000 * PRICE_IN_PER_MTOK
                             + run.completion_tokens / 1_000_000 * PRICE_OUT_PER_MTOK, 6)
    merged = dict(params or {})
    if prompt:
        run.prompt_source = prompt.get("prompt_source") or ""
        run.prompt_hash = prompt.get("prompt_hash") or ""
        run.prompt_template_id = prompt.get("prompt_template_id")
        run.prompt_template_version = int(prompt.get("prompt_template_version") or 0)
        merged["prompt_preview"] = prompt.get("prompt_preview", "")
    if merged:
        run.params = {**(run.params or {}), **merged}
    try:
        await db.commit()
    except Exception:
        await db.rollback()


def _run_input(run: RunLog | None, rev: Revision | None, params: dict | None = None) -> None:
    if run is None:
        return
    if rev is not None:
        run.input_revision_id = rev.id
        run.input_chars = len(rev.content or "")
        run.input_preview = _preview(rev.content)
    if params:
        run.params = {**(run.params or {}), **params}


async def _run_node(db: AsyncSession, node: CanvasNode, body: ExecuteIn, user: User,
                    trigger: str = "manual") -> dict:
    """执行单个节点：rewriter/transformer → AI；reviewer → 审定；exporter → 成稿。

    trigger 为台账口径：manual 手动点击 / auto 一键执行 / retry 重试。
    """
    run = await _start_run(db, user, node, trigger)
    await set_status(db, node, "running")
    try:
        if node.type in REWRITEABLE:
            await ensure_quota(db, user)
            candidates = await upstream_revisions(db, node)
            style_hint = next((r.content for r in candidates if _is_style(r) and (r.content or "").strip()), None)
            src = _pick_revision([r for r in candidates if not _is_style(r)], body.revision_id)
            if not src or not (src.content or "").strip():
                raise HTTPException(400, "缺少上游稿件内容，请先填写草稿并执行上游节点")
            cfg = node.config or {}
            _run_input(run, src, {"kind": "rewrite", "style_chars": len(style_hint or "")})
            _pinfo = await _prompt_info(db, node.subtype, cfg)
            async with ai_slot(db, user) as waited:
                await _queued_notice(node, waited)
                text, model, usage = await rewrite(
                    node.subtype,
                    src.content,
                    src.title or "",
                    custom_prompt=cfg.get("prompt") or await resolve_prompt(db, user, node.subtype),
                    model=cfg.get("model"),
                    style_hint=style_hint,
                )
                await record_usage(db, user=user, kind="rewrite" if node.type == "rewriter" else "transform",
                                   model=model, project_id=node.project_id, node_id=node.id,
                                   **_usage_kwargs(usage))
            rev = Revision(project_id=node.project_id, node_id=node.id, parent_revision_id=src.id,
                           title=src.title or "", content=text, format_type=node.subtype,
                           status="rewritten", model=model)
            db.add(rev)
            await db.commit()
            await set_status(db, node, "done")
            await _finish_run(db, run, output=rev, model=model, prompt=_pinfo,
                              usage={**usage, "queued_ms": int((waited or 0) * 1000)})
            return {"node_id": node.id, "status": "done", "revision_id": rev.id,
                    "model": public_model(model),
                    "retries": int(usage.get("retries") or 0), "queued_ms": int((waited or 0) * 1000)}

        if node.type == "tool":
            kind = (node.subtype or "condense").strip()

            if kind == "pdf_extract":
                # PDF 版面提取：本地解析，不调用 AI、不消耗额度
                info = (node.config or {}).get("pdf") or {}
                blocks = info.get("blocks") or []
                if not blocks:
                    raise HTTPException(400, "请先上传 PDF 文件并选择版块")
                indexes = info.get("selected") or [b["index"] for b in blocks]
                title, content = merge_blocks(blocks, indexes)
                if not content.strip():
                    raise HTTPException(400, "所选版块没有可用的文字内容")
                if run is not None:
                    run.params = {"kind": kind, "blocks": len(indexes),
                                  "selected": list(indexes)[:80],
                                  "file": (info.get("filename") or "")[:200]}
                    run.input_preview = _preview(info.get("filename") or "PDF 就地解析")
                rev = Revision(project_id=node.project_id, node_id=node.id,
                               title=title, content=content, format_type="pdf_extract",
                               status="rewritten", model="pdf-parse")
                db.add(rev)
                await db.commit()
                await db.refresh(rev)
                await set_status(db, node, "done")
                await _finish_run(db, run, output=rev, model="pdf-parse",
                                  params={"kind": kind, "chars": len(content), "blocks": len(indexes)})
                return {"node_id": node.id, "status": "done", "revision_id": rev.id,
                        "kind": kind, "chars": len(content), "blocks": len(indexes)}

            await ensure_quota(db, user)
            if kind not in TOOL_KINDS:
                raise HTTPException(400, f"不支持的工具类型: {kind}")
            candidates = [r for r in await upstream_revisions(db, node) if not _is_style(r)]
            src = _pick_revision(candidates, body.revision_id)
            if not src or not (src.content or "").strip():
                raise HTTPException(400, "缺少上游稿件内容，请先填写草稿并执行上游节点")
            cfg = node.config or {}
            # 精简节点默认压缩目标 1/3（用户可在面板选 1/4、1/3、1/2）
            ratio = None
            if kind == "condense":
                try:
                    ratio = float(cfg.get("ratio")) if cfg.get("ratio") else 0.35
                except Exception:
                    ratio = 0.35
            _run_input(run, src, {"kind": kind, "ratio": ratio})
            _pinfo = await _prompt_info(db, kind, cfg)
            async with ai_slot(db, user) as waited:
                await _queued_notice(node, waited)
                text, model, usage = await tool_run(kind, src.title or "", src.content,
                                                    cfg.get("prompt") or await resolve_prompt(db, user, kind),
                                                    cfg.get("model"), ratio=ratio)
                await record_usage(db, user=user, kind=kind, model=model, project_id=node.project_id,
                                   node_id=node.id, **_usage_kwargs(usage))
            rev = Revision(project_id=node.project_id, node_id=node.id, parent_revision_id=src.id,
                           title=src.title or "", content=text, format_type=kind,
                           status="rewritten", model=model)
            db.add(rev)
            await db.commit()
            await set_status(db, node, "done")
            await _finish_run(db, run, output=rev, model=model, prompt=_pinfo,
                              params={"kind": kind, "ratio": ratio},
                              usage={**usage, "queued_ms": int((waited or 0) * 1000)})
            return {"node_id": node.id, "status": "done", "revision_id": rev.id,
                    "model": public_model(model), "kind": kind, "chars": len(text),
                    "retries": int(usage.get("retries") or 0), "queued_ms": int((waited or 0) * 1000)}

        if node.type == "reviewer":
            pending = [r for r in await upstream_revisions(db, node)
                       if r.status in ("rewritten", "reviewed") and not _is_style(r)]
            if run is not None:
                run.input_chars = sum(len(r.content or "") for r in pending)
                run.input_preview = _preview(pending[0].content) if pending else ""
                run.params = {"count": len(pending), "action": body.action,
                              "revision_ids": [r.id for r in pending][:50]}
            if body.action == "approve":
                for r in pending:
                    r.status = "approved"
                    if body.comment:
                        r.review_comment = body.comment
                await db.commit()
                await set_status(db, node, "approved")
                await _finish_run(db, run, params={"action": "approve", "count": len(pending)})
                return {"node_id": node.id, "status": "approved", "count": len(pending), "action": "approve"}
            if body.action == "reject":
                for r in pending:
                    r.status = "draft"
                    r.review_comment = body.comment or "被打回，请修改"
                await db.commit()
                await set_status(db, node, "done")
                await _finish_run(db, run, params={"action": "reject", "count": len(pending)})
                return {"node_id": node.id, "status": "done", "count": len(pending), "action": "reject"}
            # 无 action：人工节点，返回待审数量
            await set_status(db, node, "done")
            await _finish_run(db, run, params={"action": "query", "pending": len(pending)})
            return {"node_id": node.id, "status": "waiting", "pending": len(pending), "action": None}

        if node.type == "ai_reviewer":
            await ensure_quota(db, user)
            pending = [r for r in await upstream_revisions(db, node)
                       if r.status in ("rewritten", "reviewed") and not _is_style(r)]
            if not pending:
                await set_status(db, node, "done")
                await _finish_run(db, run, params={"pending": 0})
                return {"node_id": node.id, "status": "waiting", "pending": 0,
                        "message": "没有待审稿件（上游需先执行改写）"}
            cfg = node.config or {}
            if run is not None:
                run.input_chars = sum(len(r.content or "") for r in pending)
                run.input_preview = _preview(pending[0].content) if pending else ""
            _pinfo = await _prompt_info(db, "ai_review", cfg)
            reviews, passed_cnt = [], 0
            total = {"prompt_tokens": 0, "completion_tokens": 0, "duration_ms": 0,
                     "prompt_chars": 0, "output_chars": 0}
            last_model = ""
            retries_total, queued_ms = 0, 0
            async with ai_slot(db, user) as waited:
                await _queued_notice(node, waited)
                queued_ms = int(waited * 1000)
                for r in pending:
                    ok, comment, model, usage = await ai_review(r.title or "", r.content or "",
                                                                custom_prompt=cfg.get("prompt") or await resolve_prompt(db, user, "ai_review"),
                                                                model=cfg.get("model"),
                                                                strict=bool(cfg.get("strict")))
                    last_model = model
                    retries_total += int(usage.get("retries") or 0)
                    for k in total:
                        total[k] += int(usage.get(k) or 0)
                r.status = "approved" if ok else "draft"
                r.review_comment = f"[AI审稿] {comment}"
                if ok:
                    passed_cnt += 1
                reviews.append({"revision_id": r.id, "format_type": r.format_type,
                                "passed": ok, "comment": comment, "model": public_model(model)})
            await db.commit()
            await record_usage(db, user=user, kind="ai_review", model=last_model,
                               project_id=node.project_id, node_id=node.id, **_usage_kwargs(total))
            await set_status(db, node, "approved" if passed_cnt == len(pending) else "done")
            if run is not None:
                summary = "；".join(f"{r['revision_id'][:8]}:{'通过' if r['passed'] else '退回'} {r['comment']}"
                                   for r in reviews)
                run.output_preview = _preview(summary)
                run.output_chars = len(summary)
            await _finish_run(db, run, model=last_model, prompt=_pinfo,
                              params={"count": len(pending), "passed": passed_cnt,
                                      "strict": bool(cfg.get("strict"))},
                              usage={**total, "queued_ms": queued_ms})
            return {"node_id": node.id, "status": "approved" if passed_cnt == len(pending) else "done",
                    "count": len(pending), "passed": passed_cnt, "reviews": reviews,
                    "retries": retries_total, "queued_ms": queued_ms}

        if node.type == "exporter":
            candidates = [r for r in await upstream_revisions(db, node) if not _is_style(r)]
            src = _pick_revision(candidates, body.revision_id)
            if not src or not (src.content or "").strip():
                raise HTTPException(400, "没有可导出的成稿，请先完成上游改写/转换")

            cfg = node.config or {}
            export_key = f"export_{node.subtype}" if node.subtype else ""
            prompt = cfg.get("prompt") or (await resolve_prompt(db, user, export_key) if export_key else None)

            _run_input(run, src, {"export": node.subtype or "", "typeset": bool(prompt)})
            _pinfo = await _prompt_info(db, export_key or "", cfg)

            if not prompt:
                # 无排版提示词 → 保持"直接成稿"（不调用 AI，不消耗额度）
                src.status = "finalized"
                src.review_comment = body.comment or src.review_comment
                await db.commit()
                await set_status(db, node, "done")
                await _finish_run(db, run, output=src, prompt=_pinfo,
                                  params={"export": node.subtype or "", "typeset": False})
                return {"node_id": node.id, "status": "done", "revision_id": src.id,
                        "format_type": src.format_type, "typeset": False}

            await ensure_quota(db, user)
            async with ai_slot(db, user) as waited:
                await _queued_notice(node, waited)
                text, model, usage = await typeset(node.subtype, src.title or "", src.content,
                                                   custom_prompt=prompt, model=cfg.get("model"))
                await record_usage(db, user=user, kind="export", model=model, project_id=node.project_id,
                                   node_id=node.id, **_usage_kwargs(usage))
            rev = Revision(project_id=node.project_id, node_id=node.id, parent_revision_id=src.id,
                           title=src.title or "", content=text,
                           format_type=src.format_type or node.subtype,
                           status="finalized", model=model,
                           review_comment=body.comment or "")
            db.add(rev)
            src.status = "finalized"
            await db.commit()
            await db.refresh(rev)
            await set_status(db, node, "done")
            await _finish_run(db, run, output=rev, model=model, prompt=_pinfo,
                              params={"export": node.subtype or "", "typeset": True},
                              usage={**usage, "queued_ms": int((waited or 0) * 1000)})
            return {"node_id": node.id, "status": "done", "revision_id": rev.id,
                    "format_type": rev.format_type, "typeset": True, "model": public_model(model),
                    "chars": len(text), "retries": int(usage.get("retries") or 0),
                    "queued_ms": int((waited or 0) * 1000)}

        # draft_input
        await set_status(db, node, "done")
        await _finish_run(db, run, params={"kind": "draft_input"})
        return {"node_id": node.id, "status": "done", "message": "草稿节点：请在上方配置面板编辑内容"}
    except HTTPException as exc:
        # 把可读原因（配额不足/缺上游/文件未上传等）写入节点并实时推送，前端才能显示真实原因
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        await set_status(db, node, "failed", detail)
        # 429 = 配额/排队被拦截，与真实故障分开统计
        await _finish_run(db, run, status=("blocked" if exc.status_code == 429 else "failed"),
                          error=detail, params={"http_status": exc.status_code,
                                                "action": (body.action or "")})
        raise
    except Exception as exc:  # noqa: BLE001
        await set_status(db, node, "failed", str(exc))
        await _finish_run(db, run, status="failed", error=str(exc))
        raise HTTPException(500, f"执行失败: {exc}")


@router.post("/nodes/{nid}/execute")
async def execute_node(nid: str, body: ExecuteIn | None = None, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    node = await _owned_node(db, nid, user)
    try:
        payload = body or ExecuteIn()
        trigger = payload.trigger if payload.trigger in ("manual", "auto", "retry") else "manual"
        result = await _run_node(db, node, payload, user, trigger=trigger)
    except Exception as exc:
        await audit_log(db, action="node_execute_failed", user=user, target_type="node", target_id=nid,
                        detail={"type": node.type, "subtype": node.subtype, "error": str(exc)[:200]})
        raise
    await audit_log(db, action="node_execute", user=user, target_type="node", target_id=nid,
                    detail={"type": node.type, "subtype": node.subtype, "status": result.get("status")})
    return result


@router.post("/projects/{pid}/execute")
async def execute_project(pid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """按拓扑序自动执行画布中的自动节点（reviewer 需人工，跳过并标注）。"""
    await _owned_project(db, pid, user)
    nodes = {n.id: n for n in (await db.execute(select(CanvasNode).where(CanvasNode.project_id == pid))).scalars()}
    edges = (await db.execute(select(CanvasEdge).where(CanvasEdge.project_id == pid))).scalars().all()
    indeg = {nid: 0 for nid in nodes}
    out: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in edges:
        if e.source_node_id in nodes and e.target_node_id in nodes:
            indeg[e.target_node_id] += 1
            out[e.source_node_id].append(e.target_node_id)
    order: list[str] = []
    queue = [nid for nid, d in indeg.items() if d == 0]
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for t in out[nid]:
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    results = []
    for nid in order:
        node = nodes[nid]
        if node.type == "reviewer":
            results.append({"node_id": nid, "label": node.label, "status": "skipped",
                            "message": "审定节点需人工操作"})
            continue
        try:
            r = await _run_node(db, node, ExecuteIn(), user, trigger="auto")
            results.append({"node_id": nid, "label": node.label, "status": r.get("status"), "message": ""})
        except Exception as exc:  # noqa: BLE001
            results.append({"node_id": nid, "label": node.label, "status": "failed", "message": str(exc)})
    await audit_log(db, action="project_execute", user=user, target_type="project", target_id=pid,
                    detail={"nodes": len(order), "failed": len([r for r in results if r["status"] == "failed"])})
    return {"project_id": pid, "results": results}
