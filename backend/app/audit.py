"""审计日志与全局设置辅助"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppSetting, AuditLog, User

DEFAULT_SETTINGS: dict[str, dict] = {
    "registration_open": {"value": False},                 # 关闭公开注册（凭邀请码注册）
    "default_monthly_call_limit": {"value": 600},          # 每人每月 AI 调用上限
    "global_monthly_budget_yuan": {"value": 300},          # 全局月度预算（仅看板提醒）
    "max_concurrency_global": {"value": 8},
    "max_concurrency_user": {"value": 2},
}


async def get_setting(db: AsyncSession, key: str, default=None):
    row = await db.get(AppSetting, key)
    if row and isinstance(row.value, dict) and "value" in row.value:
        return row.value["value"]
    if key in DEFAULT_SETTINGS:
        return DEFAULT_SETTINGS[key]["value"]
    return default


async def set_setting(db: AsyncSession, key: str, value) -> None:
    row = await db.get(AppSetting, key)
    if row:
        row.value = {"value": value}
    else:
        db.add(AppSetting(key=key, value={"value": value}))
    await db.commit()


async def ensure_defaults(db: AsyncSession) -> None:
    for key, payload in DEFAULT_SETTINGS.items():
        if await db.get(AppSetting, key) is None:
            db.add(AppSetting(key=key, value=payload))
    await db.commit()


async def log(db: AsyncSession, *, action: str, user: User | None = None, username: str = "",
              target_type: str = "", target_id: str = "", detail: dict | None = None,
              ip: str = "") -> None:
    """写一条审计记录（失败不影响主流程）"""
    try:
        db.add(AuditLog(
            user_id=getattr(user, "id", None), username=username or getattr(user, "username", "") or "",
            action=action, target_type=target_type, target_id=target_id or "",
            detail=detail or {}, ip=ip or "",
        ))
        await db.commit()
    except Exception:
        await db.rollback()
