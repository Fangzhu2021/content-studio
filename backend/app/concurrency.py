"""AI 调用并发限制（全局 + 单用户）

进程内实现（单机部署足够）。超出并发时排队等待，并把等待时间返回给调用方，
便于前端显示"排队中"；排队超过上限则快速失败，避免请求悬挂。
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import get_setting
from .models import User


class Limiter:
    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._active = 0
        self._per_user: dict[str, int] = {}

    async def acquire(self, key: str, global_limit: int, user_limit: int) -> float:
        """获取一个并发名额，返回排队等待秒数"""
        t0 = time.time()
        async with self._cond:
            while True:
                if self._active < global_limit and self._per_user.get(key, 0) < user_limit:
                    self._active += 1
                    self._per_user[key] = self._per_user.get(key, 0) + 1
                    return time.time() - t0
                await self._cond.wait()

    async def release(self, key: str) -> None:
        async with self._cond:
            self._active = max(0, self._active - 1)
            self._per_user[key] = max(0, self._per_user.get(key, 0) - 1)
            self._cond.notify_all()

    def snapshot(self) -> dict:
        return {"active": self._active, "per_user": dict(self._per_user)}


limiter = Limiter()


@asynccontextmanager
async def ai_slot(db: AsyncSession, user: User):
    """占用一个 AI 并发名额；yield 排队等待秒数"""
    glimit = max(1, int(await get_setting(db, "max_concurrency_global", 8) or 8))
    ulimit = max(1, int(await get_setting(db, "max_concurrency_user", 2) or 2))
    wait_limit = max(5, int(await get_setting(db, "max_queue_wait_seconds", 120) or 120))
    try:
        waited = await asyncio.wait_for(limiter.acquire(user.id, glimit, ulimit), timeout=wait_limit)
    except asyncio.TimeoutError:
        raise HTTPException(429, f"AI 服务当前繁忙（已排队等待超过 {wait_limit} 秒），请稍后重试")
    try:
        yield waited
    finally:
        await limiter.release(user.id)
