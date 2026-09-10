"""依赖：当前登录用户、角色校验"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = decode_token(cred.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    user = await db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系管理员")
    if int(payload.get("ver") or 1) != int(user.token_version or 1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")
    return user


def require_role(*roles: str):
    """角色校验依赖：Depends(require_role("admin"))"""
    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user
    return _checker
