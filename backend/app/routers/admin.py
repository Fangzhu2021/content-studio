"""管理后台接口（仅管理员）：概览 / 用户 / 项目 / 用量 / 审计 / 设置"""
import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import PUBLIC_MODELS, ping as ai_ping, public_model
from ..ai_runtime import ai_config, load_ai_config, mask_key
from ..audit import get_setting, log as audit_log, set_setting
from ..db import get_db
from ..paths import UPLOAD_ROOT
from ..deps import require_role
from ..models import (AiUsage, AppSetting, AuditLog, CanvasEdge, CanvasNode, NodeTemplate,
                       Project, PromptTemplate, Revision, RunLog, TemplateVersion, User)
from ..runlog import (clear_project_previews, node_template_snapshot, prompt_template_snapshot,
                      save_template_version)
from ..schemas import (
    AdminPasswordReset, AdminProjectTransfer, AdminSettingsIn, AdminUserUpdate, AiTestIn,
    NodeTemplateIn, NodeTemplateUpdate, PromptTemplateIn, PromptTemplateUpdate,
)
from ..security import hash_password

router = APIRouter()
admin_only = require_role("admin")


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _month_start() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ---------------- 概览 ----------------
@router.get("/admin/overview")
async def overview(days: int = 7, user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    total_users = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
    active_users = int((await db.execute(
        select(func.count(User.id)).where(User.is_active.is_(True)))).scalar() or 0)
    total_projects = int((await db.execute(select(func.count(Project.id)))).scalar() or 0)
    total_nodes = int((await db.execute(select(func.count(CanvasNode.id)))).scalar() or 0)
    total_revisions = int((await db.execute(select(func.count(Revision.id)))).scalar() or 0)

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today = (await db.execute(
        select(func.count(AiUsage.id), func.coalesce(func.sum(AiUsage.cost_est), 0.0))
        .where(AiUsage.created_at >= today_start))).one()
    month = (await db.execute(
        select(func.count(AiUsage.id), func.coalesce(func.sum(AiUsage.cost_est), 0.0),
               func.coalesce(func.sum(AiUsage.prompt_tokens + AiUsage.completion_tokens), 0))
        .where(AiUsage.created_at >= _month_start()))).one()
    window = (await db.execute(
        select(func.count(AiUsage.id), func.coalesce(func.sum(AiUsage.cost_est), 0.0))
        .where(AiUsage.created_at >= _since(days)))).one()
    failed = int((await db.execute(
        select(func.count(AiUsage.id)).where(AiUsage.ok.is_(False), AiUsage.created_at >= _since(days))
    )).scalar() or 0)

    budget = float(await get_setting(db, "global_monthly_budget_yuan", 300) or 0)
    return {
        "users": {"total": total_users, "active": active_users},
        "projects": total_projects, "nodes": total_nodes, "revisions": total_revisions,
        "today": {"calls": int(today[0] or 0), "cost_yuan": round(float(today[1] or 0), 4)},
        "month": {"calls": int(month[0] or 0), "cost_yuan": round(float(month[1] or 0), 4),
                  "tokens": int(month[2] or 0), "budget_yuan": budget,
                  "budget_used_pct": round(float(month[1] or 0) / budget * 100, 2) if budget else 0},
        "window": {"days": days, "calls": int(window[0] or 0), "cost_yuan": round(float(window[1] or 0), 4),
                   "failed": failed},
        "registration_open": bool(await get_setting(db, "registration_open", False)),
        "default_monthly_call_limit": int(await get_setting(db, "default_monthly_call_limit", 600) or 600),
    }


# ---------------- 用户 ----------------
async def _usage_by_user(db: AsyncSession, days: int = 30) -> dict[str, dict]:
    rows = await db.execute(
        select(AiUsage.user_id, func.count(AiUsage.id),
               func.coalesce(func.sum(AiUsage.prompt_tokens + AiUsage.completion_tokens), 0),
               func.coalesce(func.sum(AiUsage.cost_est), 0.0))
        .where(AiUsage.created_at >= _since(days)).group_by(AiUsage.user_id))
    return {r[0]: {"calls": int(r[1] or 0), "tokens": int(r[2] or 0), "cost_yuan": round(float(r[3] or 0), 4)}
            for r in rows.all()}


async def _projects_by_owner(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(select(Project.owner_id, func.count(Project.id)).group_by(Project.owner_id))
    return {r[0]: int(r[1] or 0) for r in rows.all()}


@router.get("/admin/users")
async def list_users(q: str = "", limit: int = 200, user: User = Depends(admin_only),
                     db: AsyncSession = Depends(get_db)):
    stmt = select(User).order_by(User.created_at.desc()).limit(min(limit, 500))
    if q:
        stmt = stmt.where(User.username.ilike(f"%{q}%"))
    users = (await db.execute(stmt)).scalars().all()
    usage = await _usage_by_user(db)
    counts = await _projects_by_owner(db)
    return [{
        "id": u.id, "username": u.username, "role": u.role or "editor", "is_active": bool(u.is_active),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_by": u.created_by, "token_version": u.token_version or 1,
        "monthly_call_limit": u.monthly_call_limit,
        "projects": counts.get(u.id, 0),
        "usage_30d": usage.get(u.id, {"calls": 0, "tokens": 0, "cost_yuan": 0.0}),
    } for u in users]


@router.patch("/admin/users/{uid}")
async def update_user(uid: str, body: AdminUserUpdate, user: User = Depends(admin_only),
                      db: AsyncSession = Depends(get_db)):
    target = await db.get(User, uid)
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.id == user.id and body.is_active is False:
        raise HTTPException(400, "不能禁用自己的账号")
    # 用 model_fields_set 判断"显式传入"，这样显式传 null 才能把配额清空为「继承全局」
    fields = body.model_fields_set
    changed = {}
    if "role" in fields and body.role is not None:
        if body.role not in ("admin", "editor", "reviewer", "viewer"):
            raise HTTPException(400, "角色不合法")
        changed["role"] = body.role
        target.role = body.role
    if "is_active" in fields and body.is_active is not None:
        changed["is_active"] = body.is_active
        target.is_active = body.is_active
    if "monthly_call_limit" in fields:
        changed["monthly_call_limit"] = body.monthly_call_limit
        target.monthly_call_limit = body.monthly_call_limit
    if changed.get("role") is not None or changed.get("is_active") is not None:
        target.token_version = (target.token_version or 1) + 1   # 强制下线，令新权限/禁用立即生效
    await db.commit()
    await audit_log(db, action="admin_user_update", user=user, target_type="user", target_id=uid,
                    detail={"username": target.username, **changed})
    return {"ok": True, "changed": changed}


@router.post("/admin/users/{uid}/reset-password")
async def reset_password(uid: str, body: AdminPasswordReset, user: User = Depends(admin_only),
                         db: AsyncSession = Depends(get_db)):
    target = await db.get(User, uid)
    if not target:
        raise HTTPException(404, "用户不存在")
    from ..routers.auth import validate_password
    validate_password(body.new_password)
    target.hashed_password = hash_password(body.new_password)
    target.token_version = (target.token_version or 1) + 1
    await db.commit()
    await audit_log(db, action="admin_reset_password", user=user, target_type="user", target_id=uid,
                    detail={"username": target.username})
    return {"ok": True}


# ---------------- 项目 ----------------
@router.get("/admin/projects")
async def list_projects(q: str = "", limit: int = 200, user: User = Depends(admin_only),
                        db: AsyncSession = Depends(get_db)):
    stmt = select(Project).order_by(Project.updated_at.desc()).limit(min(limit, 500))
    if q:
        stmt = stmt.where(or_(Project.name.ilike(f"%{q}%"), Project.owner_id.ilike(f"%{q}%")))
    projects = (await db.execute(stmt)).scalars().all()
    owners = {u.id: u.username for u in (await db.execute(select(User))).scalars()}
    node_rows = await db.execute(select(CanvasNode.project_id, func.count(CanvasNode.id)).group_by(CanvasNode.project_id))
    rev_rows = await db.execute(select(Revision.project_id, func.count(Revision.id)).group_by(Revision.project_id))
    nodes = {r[0]: int(r[1]) for r in node_rows.all()}
    revs = {r[0]: int(r[1]) for r in rev_rows.all()}
    return [{
        "id": p.id, "name": p.name, "owner": owners.get(p.owner_id, "(已删除)"), "owner_id": p.owner_id,
        "nodes": nodes.get(p.id, 0), "revisions": revs.get(p.id, 0),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    } for p in projects]


@router.delete("/admin/projects/{pid}")
async def admin_delete_project(pid: str, user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    name = project.name
    # 台账保留统计口径，仅清空内容预览（见 admin/run-logs）
    await clear_project_previews(db, pid, name)
    await db.execute(delete(Revision).where(Revision.project_id == pid))
    await db.execute(delete(CanvasEdge).where(CanvasEdge.project_id == pid))
    await db.execute(delete(CanvasNode).where(CanvasNode.project_id == pid))
    await db.execute(delete(Project).where(Project.id == pid))
    await db.commit()
    try:
        import shutil
        shutil.rmtree(UPLOAD_ROOT / pid, ignore_errors=True)
    except Exception:
        pass
    await audit_log(db, action="admin_project_delete", user=user, target_type="project", target_id=pid,
                    detail={"name": name})
    return {"ok": True}


@router.post("/admin/projects/{pid}/transfer")
async def transfer_project(pid: str, body: AdminProjectTransfer, user: User = Depends(admin_only),
                           db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, pid)
    if not project:
        raise HTTPException(404, "项目不存在")
    target = (await db.execute(select(User).where(User.username == body.owner_username))).scalar_one_or_none()
    if not target:
        raise HTTPException(404, f"用户不存在: {body.owner_username}")
    old_owner = project.owner_id
    project.owner_id = target.id
    await db.commit()
    await audit_log(db, action="admin_project_transfer", user=user, target_type="project", target_id=pid,
                    detail={"name": project.name, "from": old_owner, "to": target.username})
    return {"ok": True, "owner": target.username}


# ---------------- 用量 ----------------
@router.get("/admin/usage/daily")
async def usage_daily(days: int = 14, user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(func.date(AiUsage.created_at), func.count(AiUsage.id),
               func.coalesce(func.sum(AiUsage.prompt_tokens + AiUsage.completion_tokens), 0),
               func.coalesce(func.sum(AiUsage.cost_est), 0.0))
        .where(AiUsage.created_at >= _since(days))
        .group_by(func.date(AiUsage.created_at)).order_by(func.date(AiUsage.created_at).desc()))
    return {"daily": [{"date": str(d), "calls": int(c), "tokens": int(t), "cost_yuan": round(float(cost), 4)}
                      for d, c, t, cost in rows.all()]}


@router.get("/admin/usage/users")
async def usage_users(days: int = 30, limit: int = 50, user: User = Depends(admin_only),
                      db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(User.username, User.role, func.count(AiUsage.id),
               func.coalesce(func.sum(AiUsage.prompt_tokens + AiUsage.completion_tokens), 0),
               func.coalesce(func.sum(AiUsage.cost_est), 0.0),
               func.count(func.distinct(AiUsage.kind)))
        .join(AiUsage, AiUsage.user_id == User.id)
        .where(AiUsage.created_at >= _since(days))
        .group_by(User.username, User.role)
        .order_by(func.count(AiUsage.id).desc()).limit(limit))
    return {"days": days, "users": [
        {"username": u, "role": r, "calls": int(c), "tokens": int(t), "cost_yuan": round(float(cost), 4), "kinds": int(k)}
        for u, r, c, t, cost, k in rows.all()]}


@router.get("/admin/usage/export.csv")
async def usage_export(days: int = 30, user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(AiUsage.created_at, User.username, AiUsage.kind, AiUsage.model,
               AiUsage.prompt_tokens, AiUsage.completion_tokens, AiUsage.cost_est, AiUsage.duration_ms)
        .join(User, User.id == AiUsage.user_id, isouter=True)
        .where(AiUsage.created_at >= _since(days)).order_by(AiUsage.created_at.desc()).limit(5000))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["时间", "用户", "类型", "模型", "输入token", "输出token", "估算成本(元)", "耗时(ms)"])
    for row in rows.all():
        writer.writerow([row[0].isoformat() if row[0] else "", row[1] or "", row[2] or "", row[3] or "",
                         row[4] or 0, row[5] or 0, round(float(row[6] or 0), 6), row[7] or 0])
    csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(content=csv_bytes, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=ai-usage-{days}d.csv"})


# ---------------- 审计 ----------------
@router.get("/admin/audit")
async def audit_list(action: str = "", username: str = "", limit: int = 100, offset: int = 0,
                     user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).offset(max(offset, 0))
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if username:
        stmt = stmt.where(AuditLog.username.ilike(f"%{username}%"))
    rows = (await db.execute(stmt)).scalars().all()
    total = int((await db.execute(select(func.count(AuditLog.id)))).scalar() or 0)
    return {"total": total, "items": [{
        "id": a.id, "action": a.action, "username": a.username, "user_id": a.user_id,
        "target_type": a.target_type, "target_id": a.target_id, "detail": a.detail or {}, "ip": a.ip,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in rows]}


# ---------------- 设置 ----------------
SETTING_KEYS = ("registration_open", "default_monthly_call_limit", "global_monthly_budget_yuan",
                "max_concurrency_global", "max_concurrency_user", "max_queue_wait_seconds",
                # AI 服务配置：后台可改，留空回落 backend/.env
                "ai_api_key", "ai_base_url", "ai_default_model")


@router.get("/admin/settings")
async def get_settings_all(user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppSetting))).scalars().all()
    data = {s.key: (s.value or {}).get("value") for s in rows}
    out = {k: data.get(k, await get_setting(db, k)) for k in SETTING_KEYS}
    cfg = ai_config()
    out["ai_api_key"] = ""                      # 绝不回传 Token 原文
    out["ai_api_key_masked"] = mask_key(cfg["api_key"])
    out["ai_api_key_set"] = bool(cfg["api_key"])
    out["ai_key_source"] = cfg["key_from"]       # admin（后台填的）/ env（服务器 .env）/ none
    out["ai_base_url_effective"] = cfg["base_url"]
    return out


@router.put("/admin/settings")
async def update_settings(body: AdminSettingsIn, user: User = Depends(admin_only),
                          db: AsyncSession = Depends(get_db)):
    fields = body.model_fields_set
    changed = {}
    for key in SETTING_KEYS:
        if key == "ai_api_key":
            continue                    # Token 单独处理，避免被通用循环写进审计
        value = getattr(body, key, None)
        if key == "ai_default_model" and value is not None:
            if value not in PUBLIC_MODELS:
                raise HTTPException(400, f"模型档位不合法，可选：{'/'.join(PUBLIC_MODELS)}")
        if value is not None:
            await set_setting(db, key, value)
            changed[key] = value
    # Token：显式传参才改动；传空串/null = 清除并回落 .env；掩码回传视为「未修改」
    if "ai_api_key" in fields:
        raw = (body.ai_api_key or "").strip()
        if "•" in raw:
            pass                        # 前端把掩码原样回传，忽略
        else:
            await set_setting(db, "ai_api_key", raw)
            changed["ai_api_key"] = f"已更新（{len(raw)} 位）" if raw else "已清除，回落服务器 .env"
    cfg = await load_ai_config(db)       # 立即生效，无需重启服务
    await audit_log(db, action="admin_settings_update", user=user,
                    detail={**changed, "ai_key_source": cfg["key_from"]})
    return {"ok": True, "changed": changed, "ai_key_source": cfg["key_from"]}


@router.post("/admin/ai/test")
async def ai_test_connection(body: AiTestIn | None = None, user: User = Depends(admin_only),
                             db: AsyncSession = Depends(get_db)):
    """测试当前 AI 配置是否可用（发一次极小请求，约 8 token）。"""
    await load_ai_config(db)
    res = await ai_ping(body.model if body else None)
    await audit_log(db, action="admin_ai_test", user=user, detail={"ok": res.get("ok"),
                                                                  "model": res.get("model", ""),
                                                                  "latency_ms": res.get("latency_ms", 0)})
    return res


# ---------------- 节点库模板 ----------------
ALLOWED_KINDS = ("draft_input", "rewriter", "reviewer", "ai_reviewer", "transformer", "tool", "exporter")


def _node_tpl_out(t: NodeTemplate) -> dict:
    return {
        "id": t.id, "group": t.group, "kind": t.kind, "subtype": t.subtype, "label": t.label,
        "icon": t.icon, "color": t.color, "hint": t.hint, "sort": t.sort, "enabled": bool(t.enabled),
        "scope": t.scope, "owner_id": t.owner_id, "prompt": t.prompt or "",
        "default_config": t.default_config or {}, "version": int(t.version or 1),
    }


def _prompt_tpl_out(t: PromptTemplate) -> dict:
    return {"id": t.id, "key": t.key, "name": t.name, "content": t.content, "scope": t.scope,
            "owner_id": t.owner_id, "enabled": bool(t.enabled), "version": int(t.version or 1),
            "updated_at": t.updated_at.isoformat() if t.updated_at else None}


@router.get("/admin/node-templates")
async def admin_node_templates(user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(NodeTemplate).order_by(NodeTemplate.group, NodeTemplate.sort, NodeTemplate.label)
    )).scalars().all()
    return [_node_tpl_out(t) for t in rows]


@router.post("/admin/node-templates")
async def admin_create_node_template(body: NodeTemplateIn, user: User = Depends(admin_only),
                                     db: AsyncSession = Depends(get_db)):
    if body.kind not in ALLOWED_KINDS:
        raise HTTPException(400, f"节点类型不合法，可选：{'/'.join(ALLOWED_KINDS)}")
    t = NodeTemplate(group=body.group or "自定义", kind=body.kind, subtype=body.subtype, label=body.label or body.kind,
                     icon=body.icon or "🧩", color=body.color, hint=body.hint, sort=body.sort,
                     default_config=body.default_config or {}, prompt=body.prompt, scope="global",
                     enabled=True, version=1)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    await save_template_version(db, template_type="node", template_id=t.id, version=1,
                                snapshot=node_template_snapshot(t), changed_by=user.username, note="新建")
    await db.commit()
    await audit_log(db, action="admin_node_template_create", user=user, target_type="node_template", target_id=t.id,
                    detail={"kind": t.kind, "subtype": t.subtype, "label": t.label})
    return _node_tpl_out(t)


@router.patch("/admin/node-templates/{tid}")
async def admin_update_node_template(tid: str, body: NodeTemplateUpdate, user: User = Depends(admin_only),
                                     db: AsyncSession = Depends(get_db)):
    t = await db.get(NodeTemplate, tid)
    if not t:
        raise HTTPException(404, "节点模板不存在")
    changed = {}
    touched = False
    for field in ("group", "label", "icon", "color", "hint", "sort", "default_config", "prompt", "enabled"):
        value = getattr(body, field, None)
        if value is not None:
            setattr(t, field, value)
            changed[field] = value if field != "prompt" else f"({len(value)} 字)"
            touched = True
    if touched:
        # 每次改动都留一份版本快照，历史运行记录才能对上"当时用的是哪一版"
        t.version = int(t.version or 1) + 1
        changed["version"] = t.version
    await db.commit()
    await db.refresh(t)   # 异步会话：refresh 后才能安全读取 updated_at 等列
    if touched:
        await save_template_version(db, template_type="node", template_id=t.id, version=t.version,
                                    snapshot=node_template_snapshot(t), changed_by=user.username, note="编辑")
        await db.commit()
    await audit_log(db, action="admin_node_template_update", user=user, target_type="node_template", target_id=tid,
                    detail=changed)
    return _node_tpl_out(t)


@router.delete("/admin/node-templates/{tid}")
async def admin_delete_node_template(tid: str, user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    t = await db.get(NodeTemplate, tid)
    if not t:
        raise HTTPException(404, "节点模板不存在")
    label = t.label
    await db.execute(delete(NodeTemplate).where(NodeTemplate.id == tid))
    await db.commit()
    await audit_log(db, action="admin_node_template_delete", user=user, target_type="node_template", target_id=tid,
                    detail={"label": label})
    return {"ok": True}


# ---------------- 提示词模板 ----------------
@router.get("/admin/prompt-templates")
async def admin_prompt_templates(scope: str = "", user: User = Depends(admin_only),
                                 db: AsyncSession = Depends(get_db)):
    stmt = select(PromptTemplate).order_by(PromptTemplate.key, PromptTemplate.scope)
    if scope:
        stmt = stmt.where(PromptTemplate.scope == scope)
    rows = (await db.execute(stmt)).scalars().all()
    return [_prompt_tpl_out(t) for t in rows]


@router.post("/admin/prompt-templates")
async def admin_create_prompt_template(body: PromptTemplateIn, user: User = Depends(admin_only),
                                       db: AsyncSession = Depends(get_db)):
    t = PromptTemplate(key=body.key, name=body.name or body.key, content=body.content, scope="global",
                       enabled=True, version=1)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    await save_template_version(db, template_type="prompt", template_id=t.id, version=1,
                                snapshot=prompt_template_snapshot(t), changed_by=user.username, note="新建")
    await db.commit()
    await audit_log(db, action="admin_prompt_template_create", user=user, target_type="prompt_template", target_id=t.id,
                    detail={"key": t.key, "name": t.name})
    return _prompt_tpl_out(t)


@router.patch("/admin/prompt-templates/{tid}")
async def admin_update_prompt_template(tid: str, body: PromptTemplateUpdate, user: User = Depends(admin_only),
                                       db: AsyncSession = Depends(get_db)):
    t = await db.get(PromptTemplate, tid)
    if not t:
        raise HTTPException(404, "提示词模板不存在")
    changed = {}
    touched = False
    for field in ("name", "content", "enabled"):
        value = getattr(body, field, None)
        if value is not None:
            setattr(t, field, value)
            changed[field] = value if field != "content" else f"({len(value)} 字)"
            touched = True
    if touched:
        t.version = int(t.version or 1) + 1
        changed["version"] = t.version
    await db.commit()
    await db.refresh(t)   # 同上：避免 MissingGreenlet
    if touched:
        await save_template_version(db, template_type="prompt", template_id=t.id, version=t.version,
                                    snapshot=prompt_template_snapshot(t), changed_by=user.username, note="编辑")
        await db.commit()
    await audit_log(db, action="admin_prompt_template_update", user=user, target_type="prompt_template", target_id=tid,
                    detail=changed)
    return _prompt_tpl_out(t)


@router.delete("/admin/prompt-templates/{tid}")
async def admin_delete_prompt_template(tid: str, user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    t = await db.get(PromptTemplate, tid)
    if not t:
        raise HTTPException(404, "提示词模板不存在")
    if t.scope == "global":
        raise HTTPException(400, "全站模板不可删除，请改为停用（enabled=false）以保留记录")
    await db.execute(delete(PromptTemplate).where(PromptTemplate.id == tid))
    await db.commit()
    await audit_log(db, action="admin_prompt_template_delete", user=user, target_type="prompt_template", target_id=tid)
    return {"ok": True}


# ---------------- 运行台账 ----------------
def _run_log_out(r: RunLog, detail: bool = False) -> dict:
    out = {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "username": r.username, "user_id": r.user_id,
        "project_id": r.project_id, "project_name": r.project_name,
        "node_id": r.node_id, "node_type": r.node_type, "node_subtype": r.node_subtype,
        "node_label": r.node_label, "trigger": r.trigger, "status": r.status,
        "error": r.error or "",
        "input_chars": r.input_chars, "output_chars": r.output_chars, "model": public_model(r.model),
        "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
        "cost_est": r.cost_est, "duration_ms": r.duration_ms, "retries": r.retries,
        "queued_ms": r.queued_ms, "template_key": r.template_key,
        "node_template_version": r.node_template_version,
        "prompt_source": r.prompt_source, "prompt_hash": r.prompt_hash,
        "prompt_template_version": r.prompt_template_version,
    }
    if detail:
        out.update({
            "input_revision_id": r.input_revision_id, "output_revision_id": r.output_revision_id,
            "input_preview": r.input_preview or "", "output_preview": r.output_preview or "",
            "params": r.params or {}, "node_template_id": r.node_template_id,
            "prompt_template_id": r.prompt_template_id,
        })
    return out


def _run_filters(days: int, username: str, project_id: str, node_type: str, status: str,
                 q: str, only_failed: bool) -> list:
    conds = [RunLog.created_at >= _since(days)]
    if username:
        conds.append(RunLog.username == username)
    if project_id:
        conds.append(RunLog.project_id == project_id)
    if node_type:
        conds.append(or_(RunLog.node_type == node_type, RunLog.node_subtype == node_type))
    if status:
        conds.append(RunLog.status == status)
    if only_failed:
        conds.append(RunLog.status.in_(("failed", "blocked")))
    if q:
        like = f"%{q}%"
        conds.append(or_(RunLog.node_label.ilike(like), RunLog.project_name.ilike(like),
                         RunLog.username.ilike(like), RunLog.error.ilike(like),
                         RunLog.node_subtype.ilike(like)))
    return conds


@router.get("/admin/run-logs/summary")
async def run_logs_summary(days: int = 30, username: str = "", project_id: str = "",
                           node_type: str = "", status: str = "", q: str = "", only_failed: bool = False,
                           user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    """运行台账统计：总量/成败/被拦截、按节点、按人、按模板、按天。"""
    conds = _run_filters(days, username, project_id, node_type, status, q, only_failed)

    async def grouped(*cols):
        stmt = select(*cols, func.count()).where(*conds).group_by(*cols)
        return (await db.execute(stmt)).all()

    totals_row = (await db.execute(select(
        func.count(), func.coalesce(func.sum(RunLog.prompt_tokens), 0),
        func.coalesce(func.sum(RunLog.completion_tokens), 0),
        func.coalesce(func.sum(RunLog.cost_est), 0.0),
        func.coalesce(func.avg(RunLog.duration_ms), 0.0),
        func.count(func.distinct(RunLog.username)),
    ).where(*conds))).one()
    by_status = {r[0] or "unknown": r[1] for r in await grouped(RunLog.status)}
    by_node = [{"node_type": r[0], "node_subtype": r[1] or "", "count": r[2]}
               for r in await grouped(RunLog.node_type, RunLog.node_subtype)]
    by_node.sort(key=lambda x: -x["count"])
    by_user = [{"username": r[0] or "(已删除用户)", "count": r[1]} for r in await grouped(RunLog.username)]
    by_user.sort(key=lambda x: -x["count"])
    by_template = [{"template_key": r[0] or "(未标记)", "count": r[1]}
                   for r in await grouped(RunLog.template_key)]
    by_template.sort(key=lambda x: -x["count"])
    by_node_template = [{"label": r[0] or "(无)", "subtype": r[1] or "",
                         "version": int(r[2] or 0), "count": r[3]}
                        for r in await grouped(RunLog.node_label, RunLog.node_subtype,
                                               RunLog.node_template_version)]
    by_node_template.sort(key=lambda x: -x["count"])
    day_rows = (await db.execute(select(func.date(RunLog.created_at), RunLog.status, func.count())
                                 .where(*conds)
                                 .group_by(func.date(RunLog.created_at), RunLog.status)
                                 .order_by(func.date(RunLog.created_at)))).all()
    day_map: dict[str, dict] = {}
    for d, st, c in day_rows:
        item = day_map.setdefault(str(d), {"day": str(d), "count": 0, "failed": 0})
        item["count"] += c
        if st in ("failed", "blocked"):
            item["failed"] += c
    day_list = [day_map[k] for k in sorted(day_map)]
    recent = (await db.execute(select(RunLog).where(*conds, RunLog.status.in_(("failed", "blocked")))
                               .order_by(RunLog.created_at.desc()).limit(10))).scalars().all()
    return {
        "days": days,
        "totals": {"runs": totals_row[0], "prompt_tokens": int(totals_row[1]),
                   "completion_tokens": int(totals_row[2]), "cost_est": round(float(totals_row[3]), 4),
                   "avg_duration_ms": int(totals_row[4] or 0), "users": totals_row[5],
                   "ok": by_status.get("ok", 0), "failed": by_status.get("failed", 0),
                   "blocked": by_status.get("blocked", 0), "running": by_status.get("running", 0)},
        "by_status": by_status, "by_node": by_node, "by_user": by_user[:20],
        "by_template": by_template, "by_node_template": by_node_template[:20],
        "by_day": day_list,
        "recent_failures": [_run_log_out(r) for r in recent],
    }


@router.get("/admin/run-logs/export.csv")
async def run_logs_export(days: int = 30, username: str = "", project_id: str = "", node_type: str = "",
                          status: str = "", q: str = "", only_failed: bool = False,
                          with_preview: bool = False, limit: int = 20000,
                          user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    """导出 CSV。默认不含正文预览，避免稿件内容随表格外流。"""
    conds = _run_filters(days, username, project_id, node_type, status, q, only_failed)
    rows = (await db.execute(select(RunLog).where(*conds).order_by(RunLog.created_at.desc())
                             .limit(min(limit, 50000)))).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    header = ["时间", "用户", "项目", "节点", "节点类型", "子类型", "触发方式", "状态",
              "输入字数", "输出字数", "模型", "提示词tokens", "生成tokens", "预估费用(元)",
              "耗时(ms)", "重试次数", "排队(ms)", "画布模板", "节点模板版本", "提示词来源",
              "提示词版本", "错误原因"]
    if with_preview:
        header += ["输入预览", "输出预览", "参数快照"]
    w.writerow(header)
    label = {"manual": "手动", "auto": "一键执行", "retry": "重试"}
    src = {"node": "节点自定义", "global": "全站模板", "builtin": "系统内置", "none": "-"}
    for r in rows:
        line = [r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "", r.username or "",
                r.project_name or "(项目已删除)", r.node_label or "", r.node_type or "", r.node_subtype or "",
                label.get(r.trigger or "", r.trigger or ""), r.status or "",
                r.input_chars, r.output_chars, public_model(r.model), r.prompt_tokens, r.completion_tokens,
                r.cost_est, r.duration_ms, r.retries, r.queued_ms, r.template_key or "",
                r.node_template_version, src.get(r.prompt_source or "", r.prompt_source or ""),
                r.prompt_template_version, (r.error or "").replace("\n", " ")[:200]]
        if with_preview:
            line += [(r.input_preview or "").replace("\n", " "),
                     (r.output_preview or "").replace("\n", " "),
                     __import__("json").dumps(r.params or {}, ensure_ascii=False)[:500]]
        w.writerow(line)
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="run-logs-{stamp}.csv"'})


@router.post("/admin/run-logs/prune")
async def run_logs_prune(months: int = 12, user: User = Depends(admin_only),
                         db: AsyncSession = Depends(get_db)):
    """按保留期归档清理（默认保留 12 个月）。"""
    months = max(1, min(months, 60))
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    n = (await db.execute(delete(RunLog).where(RunLog.created_at < cutoff))).rowcount or 0
    await db.commit()
    await audit_log(db, action="admin_run_logs_prune", user=user, detail={"months": months, "deleted": n})
    return {"ok": True, "months": months, "deleted": n}


@router.get("/admin/run-logs")
async def run_logs_list(days: int = 30, username: str = "", project_id: str = "", node_type: str = "",
                        status: str = "", q: str = "", only_failed: bool = False,
                        limit: int = Query(50, ge=1, le=200), offset: int = 0,
                        user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    conds = _run_filters(days, username, project_id, node_type, status, q, only_failed)
    total = (await db.execute(select(func.count()).select_from(RunLog).where(*conds))).scalar() or 0
    rows = (await db.execute(select(RunLog).where(*conds).order_by(RunLog.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"total": total, "limit": limit, "offset": offset,
            "items": [_run_log_out(r) for r in rows]}


@router.get("/admin/run-logs/{rid}")
async def run_log_detail(rid: str, user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    r = await db.get(RunLog, rid)
    if not r:
        raise HTTPException(404, "记录不存在")
    out = _run_log_out(r, detail=True)
    if r.output_revision_id:
        rev = await db.get(Revision, r.output_revision_id)
        out["output_content"] = (rev.content or "")[:4000] if rev else ""
    return out


@router.get("/admin/template-versions")
async def template_versions(template_type: str = "", template_id: str = "", limit: int = 100,
                            user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    """模板改动历史：谁在什么时候把哪个模板改成了第几版。"""
    stmt = select(TemplateVersion).order_by(TemplateVersion.created_at.desc()).limit(min(limit, 500))
    if template_type:
        stmt = stmt.where(TemplateVersion.template_type == template_type)
    if template_id:
        stmt = stmt.where(TemplateVersion.template_id == template_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": r.id, "template_type": r.template_type, "template_id": r.template_id,
             "version": r.version, "changed_by": r.changed_by, "note": r.note,
             "snapshot": r.snapshot or {},
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
