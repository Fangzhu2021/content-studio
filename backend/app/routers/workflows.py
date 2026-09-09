"""画布节点/连线 CRUD + 内容 + 执行（AI 改写/审定/成稿）+ WebSocket 状态广播"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import rewrite
from ..db import get_db
from ..deps import get_current_user
from ..models import CanvasEdge, CanvasNode, Project, Revision, User
from ..schemas import ContentIn, EdgeCreate, ExecuteIn, NodeCreate, NodeUpdate, ReviewIn
from ..ws import manager

router = APIRouter()

REWRITEABLE = ("rewriter", "transformer")


def _rev_out(r: Revision) -> dict:
    return {
        "id": r.id, "node_id": r.node_id, "parent_revision_id": r.parent_revision_id,
        "title": r.title or "", "content": r.content or "", "format_type": r.format_type or "",
        "status": r.status or "draft", "model": r.model or "", "review_comment": r.review_comment or "",
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _node_out(n: CanvasNode) -> dict:
    return {
        "id": n.id, "type": n.type, "subtype": n.subtype, "label": n.label,
        "position": {"x": n.position_x or 0, "y": n.position_y or 0},
        "config": n.config or {}, "status": n.status or "idle", "error": n.error or "",
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
    if body.type not in ("draft_input", "rewriter", "reviewer", "transformer", "exporter"):
        raise HTTPException(400, "未知节点类型")
    if body.type in REWRITEABLE and not body.subtype:
        raise HTTPException(400, "改写/转换节点需要 format_type（tv_script/newspaper/wechat/...）")
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
    await manager.broadcast(rev.project_id, {"type": "revision", "project_id": rev.project_id})
    return _rev_out(rev)


# ---------- 执行 ----------

async def _run_node(db: AsyncSession, node: CanvasNode, body: ExecuteIn) -> dict:
    """执行单个节点：rewriter/transformer → AI；reviewer → 审定；exporter → 成稿。"""
    await set_status(db, node, "running")
    try:
        if node.type in REWRITEABLE:
            candidates = await upstream_revisions(db, node)
            src = _pick_revision(candidates, body.revision_id)
            if not src or not (src.content or "").strip():
                raise HTTPException(400, "缺少上游稿件内容，请先填写草稿并执行上游节点")
            text, model = await rewrite(node.subtype, src.content, src.title or "")
            rev = Revision(project_id=node.project_id, node_id=node.id, parent_revision_id=src.id,
                           title=src.title or "", content=text, format_type=node.subtype,
                           status="rewritten", model=model)
            db.add(rev)
            await db.commit()
            await set_status(db, node, "done")
            return {"node_id": node.id, "status": "done", "revision_id": rev.id, "model": model}

        if node.type == "reviewer":
            pending = [r for r in await upstream_revisions(db, node) if r.status in ("rewritten", "reviewed")]
            if body.action == "approve":
                for r in pending:
                    r.status = "approved"
                    if body.comment:
                        r.review_comment = body.comment
                await db.commit()
                await set_status(db, node, "approved")
                return {"node_id": node.id, "status": "approved", "count": len(pending), "action": "approve"}
            if body.action == "reject":
                for r in pending:
                    r.status = "draft"
                    r.review_comment = body.comment or "被打回，请修改"
                await db.commit()
                await set_status(db, node, "done")
                return {"node_id": node.id, "status": "done", "count": len(pending), "action": "reject"}
            # 无 action：人工节点，返回待审数量
            await set_status(db, node, "done")
            return {"node_id": node.id, "status": "waiting", "pending": len(pending), "action": None}

        if node.type == "exporter":
            candidates = await upstream_revisions(db, node)
            src = _pick_revision(candidates, body.revision_id)
            if not src or not (src.content or "").strip():
                raise HTTPException(400, "没有可导出的成稿，请先完成上游改写/转换")
            src.status = "finalized"
            src.review_comment = body.comment or src.review_comment
            await db.commit()
            await set_status(db, node, "done")
            return {"node_id": node.id, "status": "done", "revision_id": src.id, "format_type": src.format_type}

        # draft_input
        await set_status(db, node, "done")
        return {"node_id": node.id, "status": "done", "message": "草稿节点：请在上方配置面板编辑内容"}
    except HTTPException:
        await set_status(db, node, "failed", node.error or "")
        raise
    except Exception as exc:  # noqa: BLE001
        await set_status(db, node, "failed", str(exc))
        raise HTTPException(500, f"执行失败: {exc}")


@router.post("/nodes/{nid}/execute")
async def execute_node(nid: str, body: ExecuteIn | None = None, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    node = await _owned_node(db, nid, user)
    return await _run_node(db, node, body or ExecuteIn())


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
            r = await _run_node(db, node, ExecuteIn())
            results.append({"node_id": nid, "label": node.label, "status": r.get("status"), "message": ""})
        except Exception as exc:  # noqa: BLE001
            results.append({"node_id": nid, "label": node.label, "status": "failed", "message": str(exc)})
    return {"project_id": pid, "results": results}
