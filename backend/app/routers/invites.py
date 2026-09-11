"""邀请码管理（仅管理员）"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import log
from ..db import get_db
from ..deps import require_role
from ..models import Invite, User
from ..schemas import InviteCreate

router = APIRouter()


def invite_link(request: Request, code: str) -> str:
    """生成带邀请码的注册链接（适配 Nginx 反代：优先取 X-Forwarded-*）"""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host")
            or (request.url.hostname or ""))
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    return f"{proto}://{host}/?invite={code}"


def _out(i: Invite, request: Request | None = None) -> dict:
    return {
        "id": i.id, "code": i.code, "role": i.role, "note": i.note or "",
        "link": invite_link(request, i.code) if request is not None else "",
        "expires_at": i.expires_at.isoformat() if i.expires_at else None,
        "used_by": i.used_by, "used_at": i.used_at.isoformat() if i.used_at else None,
        "revoked": bool(i.revoked),
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


@router.get("/invites")
async def list_invites(request: Request, user: User = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    rows = await db.execute(select(Invite).order_by(Invite.created_at.desc()).limit(200))
    return [_out(i, request) for i in rows.scalars()]


@router.post("/invites")
async def create_invite(body: InviteCreate, request: Request, user: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    if body.role not in ("admin", "editor", "reviewer", "viewer"):
        raise HTTPException(400, "角色不合法")
    code = secrets.token_hex(4).upper()
    invite = Invite(code=code, role=body.role, note=body.note or "", created_by=user.id,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=max(1, body.expires_days)))
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    await log(db, action="invite_create", user=user, target_type="invite", target_id=invite.id,
              detail={"code": code, "role": invite.role, "days": body.expires_days})
    return _out(invite, request)


@router.post("/invites/{iid}/revoke")
async def revoke_invite(iid: str, user: User = Depends(require_role("admin")),
                        db: AsyncSession = Depends(get_db)):
    invite = await db.get(Invite, iid)
    if not invite:
        raise HTTPException(404, "邀请码不存在")
    invite.revoked = True
    await db.commit()
    await log(db, action="invite_revoke", user=user, target_type="invite", target_id=iid,
              detail={"code": invite.code})
    return {"ok": True}
