from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import get_setting, log
from ..db import get_db
from ..deps import get_current_user
from ..models import Invite, User
from ..ratelimit import clear, is_blocked, record_fail
from ..schemas import ChangePasswordIn, LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_token, hash_password, verify_password

router = APIRouter()

PASSWORD_RULE = "密码至少 8 位，且需同时包含字母和数字"


def _client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def validate_password(pw: str) -> None:
    if len(pw) < 8 or not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        raise HTTPException(400, PASSWORD_RULE)


def _token_out(user: User) -> TokenOut:
    return TokenOut(
        token=create_token(user.id, user.token_version or 1),
        user=UserOut(id=user.id, username=user.username, role=user.role or "editor"),
    )


@router.get("/register-mode")
async def register_mode(db: AsyncSession = Depends(get_db)):
    """公开接口：前端据此决定是否显示邀请码输入框"""
    open_ = bool(await get_setting(db, "registration_open", False))
    return {"registration_open": open_, "invite_required": not open_, "password_rule": PASSWORD_RULE}


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)):
    validate_password(body.password)
    reg_open = bool(await get_setting(db, "registration_open", False))
    invite = None
    role = "editor"

    if not reg_open:
        code = (body.invite_code or "").strip().upper()
        if not code:
            raise HTTPException(403, "注册已关闭，请输入邀请码")
        invite = (await db.execute(select(Invite).where(Invite.code == code))).scalar_one_or_none()
        if invite is None or invite.revoked:
            raise HTTPException(403, "邀请码无效")
        if invite.used_by:
            raise HTTPException(403, "该邀请码已被使用")
        if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
            raise HTTPException(403, "邀请码已过期")
        role = invite.role or "editor"

    exists = await db.execute(select(User).where(User.username == body.username))
    if exists.scalar_one_or_none():
        raise HTTPException(400, "用户名已存在")

    user = User(
        username=body.username, hashed_password=hash_password(body.password),
        role=role, is_active=True, token_version=1,
        created_by=invite.created_by if invite else None,
        last_login_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()
    if invite:
        invite.used_by = user.id
        invite.used_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    await log(db, action="register", user=user,
              detail={"role": role, "invite": invite.code if invite else None},
              ip=_client_ip(request))
    return _token_out(user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    ip = _client_ip(request)
    key = f"{body.username}|{ip}"
    blocked, retry = is_blocked(key)
    if blocked:
        raise HTTPException(429, f"登录失败次数过多，请 {retry} 秒后重试")

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        record_fail(key)
        await log(db, action="login_failed", username=body.username, ip=ip)
        raise HTTPException(401, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(403, "账号已被禁用，请联系管理员")

    clear(key)
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    await log(db, action="login", user=user, ip=ip)
    return _token_out(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, username=user.username, role=user.role or "editor")


@router.post("/change-password", response_model=TokenOut)
async def change_password(body: ChangePasswordIn, request: Request,
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(400, "原密码不正确")
    validate_password(body.new_password)
    user.hashed_password = hash_password(body.new_password)
    user.token_version = (user.token_version or 1) + 1     # 使其他会话失效
    await db.commit()
    await db.refresh(user)
    await log(db, action="change_password", user=user, ip=_client_ip(request))
    return _token_out(user)
