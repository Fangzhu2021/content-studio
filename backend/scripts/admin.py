"""运维 CLI：管理员提升、邀请码、用户列表、注册开关

用法（在 backend 目录下）：
  .venv/bin/python scripts/admin.py promote <username>
  .venv/bin/python scripts/admin.py demote <username>
  .venv/bin/python scripts/admin.py invite [--role editor] [--days 7] [--note "给xx"]
  .venv/bin/python scripts/admin.py reset-password <username> <new_password>
  .venv/bin/python scripts/admin.py users
  .venv/bin/python scripts/admin.py registration on|off
"""
import asyncio
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.audit import get_setting, set_setting  # noqa: E402
from app.db import async_session, engine  # noqa: E402
from app.models import Invite, User  # noqa: E402
from app.security import hash_password  # noqa: E402


def arg(flag: str, default: str = "") -> str:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    async with async_session() as db:
        if cmd in ("promote", "demote"):
            username = sys.argv[2] if len(sys.argv) > 2 else ""
            user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
            if not user:
                print(f"用户不存在: {username}")
                return
            user.role = "admin" if cmd == "promote" else "editor"
            user.token_version = (user.token_version or 1) + 1
            await db.commit()
            print(f"{username} 角色 -> {user.role}（旧会话已失效）")

        elif cmd == "invite":
            role = arg("--role", "editor")
            days = int(arg("--days", "7"))
            note = arg("--note", "")
            code = secrets.token_hex(4).upper()
            db.add(Invite(code=code, role=role, note=note,
                          expires_at=datetime.now(timezone.utc) + timedelta(days=days)))
            await db.commit()
            print(f"邀请码: {code}  角色: {role}  有效期: {days} 天  备注: {note or '-'}")

        elif cmd == "reset-password":
            username = sys.argv[2] if len(sys.argv) > 2 else ""
            newpw = sys.argv[3] if len(sys.argv) > 3 else ""
            if len(newpw) < 8 or not any(c.isalpha() for c in newpw) or not any(c.isdigit() for c in newpw):
                print("密码至少 8 位，且需同时包含字母和数字")
                return
            user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
            if not user:
                print(f"用户不存在: {username}")
                return
            user.hashed_password = hash_password(newpw)
            user.token_version = (user.token_version or 1) + 1
            await db.commit()
            print(f"{username} 密码已重置，旧会话已失效")

        elif cmd == "users":
            rows = await db.execute(select(User).order_by(User.created_at))
            print(f"{'用户名':<16}{'角色':<10}{'启用':<6}{'最近登录':<22}{'邀请人':<10}")
            for u in rows.scalars():
                last = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "-"
                print(f"{u.username:<16}{u.role or 'editor':<10}{'是' if u.is_active else '否':<6}{last:<22}{u.created_by or '-':<10}")

        elif cmd == "registration":
            value = (sys.argv[2] if len(sys.argv) > 2 else "").lower()
            await set_setting(db, "registration_open", value == "on")
            print(f"公开注册: {'开启' if value == 'on' else '关闭'}（当前值={await get_setting(db, 'registration_open', False)}）")

        else:
            print(__doc__)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
