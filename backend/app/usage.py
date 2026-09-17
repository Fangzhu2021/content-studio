"""AI 用量计量与配额控制"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import get_setting
from .models import AiUsage, User

PRICE_IN_PER_MTOK = 1.0    # 元/百万 token（估算用，可在 app_settings 覆盖）
PRICE_OUT_PER_MTOK = 2.0


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def monthly_calls(db: AsyncSession, user_id: str) -> int:
    return int((await db.execute(
        select(func.count(AiUsage.id)).where(AiUsage.user_id == user_id, AiUsage.created_at >= _month_start())
    )).scalar() or 0)


async def ensure_quota(db: AsyncSession, user: User) -> None:
    """调用 AI 前检查配额；超额直接 429，不消耗额度。

    配额语义：None = 继承全局默认；0 = 禁止调用；>0 = 本月上限
    """
    if user.monthly_call_limit is None:
        limit = int(await get_setting(db, "default_monthly_call_limit", 600) or 600)
    else:
        limit = int(user.monthly_call_limit)
    if limit == 0:
        raise HTTPException(429, "该账号的 AI 调用已被管理员禁用，请联系管理员")
    used = await monthly_calls(db, user.id)
    if limit > 0 and used >= limit:
        raise HTTPException(429, f"本月 AI 调用额度已用完（{used}/{limit} 次），请联系管理员调整配额")


async def record_usage(db: AsyncSession, *, user: User | None, kind: str, model: str,
                       prompt_chars: int = 0, output_chars: int = 0,
                       prompt_tokens: int = 0, completion_tokens: int = 0,
                       duration_ms: int = 0, ok: bool = True,
                       project_id: str | None = None, node_id: str | None = None,
                       audio_seconds: int = 0) -> None:
    """写一条用量记录（失败不影响主流程）"""
    try:
        cost = prompt_tokens / 1_000_000 * PRICE_IN_PER_MTOK + completion_tokens / 1_000_000 * PRICE_OUT_PER_MTOK
        db.add(AiUsage(
            user_id=getattr(user, "id", None), project_id=project_id, node_id=node_id,
            kind=kind, model=model or "", prompt_chars=prompt_chars, output_chars=output_chars,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cost_est=round(cost, 6), duration_ms=duration_ms, ok=ok,
            audio_seconds=int(audio_seconds or 0),
        ))
        await db.commit()
    except Exception:
        await db.rollback()


async def usage_summary(db: AsyncSession, days: int = 7) -> dict:
    """后台看板用：近 N 天按日用量"""
    rows = await db.execute(
        select(func.date(AiUsage.created_at), func.count(AiUsage.id),
               func.coalesce(func.sum(AiUsage.prompt_tokens + AiUsage.completion_tokens), 0),
               func.coalesce(func.sum(AiUsage.cost_est), 0.0))
        .where(AiUsage.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))
        .group_by(func.date(AiUsage.created_at)).order_by(func.date(AiUsage.created_at).desc()).limit(days)
    )
    return {"daily": [
        {"date": str(d), "calls": int(c), "tokens": int(t), "cost_yuan": round(float(cost), 4)}
        for d, c, t, cost in rows.all()
    ]}
