"""管理后台接口（仅管理员）：概览 / 用户 / 项目 / 用量 / 审计 / 设置"""
import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import get_setting, log as audit_log, set_setting
from ..db import get_db
from ..paths import UPLOAD_ROOT
from ..deps import require_role
from ..models import (AiUsage, AppSetting, AuditLog, CanvasEdge, CanvasNode, NodeTemplate,
                       Project, PromptTemplate, Revision, User)
from ..schemas import (
    AdminPasswordReset, AdminProjectTransfer, AdminSettingsIn, AdminUserUpdate,
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
                "max_concurrency_global", "max_concurrency_user", "max_queue_wait_seconds")


@router.get("/admin/settings")
async def get_settings_all(user: User = Depends(admin_only), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AppSetting))).scalars().all()
    data = {s.key: (s.value or {}).get("value") for s in rows}
    return {k: data.get(k, await get_setting(db, k)) for k in SETTING_KEYS}


@router.put("/admin/settings")
async def update_settings(body: AdminSettingsIn, user: User = Depends(admin_only),
                          db: AsyncSession = Depends(get_db)):
    changed = {}
    for key in SETTING_KEYS:
        value = getattr(body, key, None)
        if value is not None:
            await set_setting(db, key, value)
            changed[key] = value
    await audit_log(db, action="admin_settings_update", user=user, detail=changed)
    return {"ok": True, "changed": changed}


# ---------------- 节点库模板 ----------------
ALLOWED_KINDS = ("draft_input", "rewriter", "reviewer", "ai_reviewer", "transformer", "tool", "exporter")


def _node_tpl_out(t: NodeTemplate) -> dict:
    return {
        "id": t.id, "group": t.group, "kind": t.kind, "subtype": t.subtype, "label": t.label,
        "icon": t.icon, "color": t.color, "hint": t.hint, "sort": t.sort, "enabled": bool(t.enabled),
        "scope": t.scope, "owner_id": t.owner_id, "prompt": t.prompt or "",
        "default_config": t.default_config or {},
    }


def _prompt_tpl_out(t: PromptTemplate) -> dict:
    return {"id": t.id, "key": t.key, "name": t.name, "content": t.content, "scope": t.scope,
            "owner_id": t.owner_id, "enabled": bool(t.enabled),
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
                     default_config=body.default_config or {}, prompt=body.prompt, scope="global", enabled=True)
    db.add(t)
    await db.commit()
    await db.refresh(t)
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
    for field in ("group", "label", "icon", "color", "hint", "sort", "default_config", "prompt", "enabled"):
        value = getattr(body, field, None)
        if value is not None:
            setattr(t, field, value)
            changed[field] = value if field != "prompt" else f"({len(value)} 字)"
    await db.commit()
    await db.refresh(t)   # 异步会话：refresh 后才能安全读取 updated_at 等列
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
    t = PromptTemplate(key=body.key, name=body.name or body.key, content=body.content, scope="global", enabled=True)
    db.add(t)
    await db.commit()
    await db.refresh(t)
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
    for field in ("name", "content", "enabled"):
        value = getattr(body, field, None)
        if value is not None:
            setattr(t, field, value)
            changed[field] = value if field != "content" else f"({len(value)} 字)"
    await db.commit()
    await db.refresh(t)   # 同上：避免 MissingGreenlet
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
