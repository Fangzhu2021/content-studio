import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from . import models  # noqa: F401  确保模型注册
from .audit import ensure_defaults
from .config import get_settings
from .db import Base, async_session, engine
from .migrate import run_migrations
from .models import Project, User
from .routers import admin, auth, invites, pdf, projects, templates_api, workflows
from .security import decode_token
from .templates import seed_templates
from .ws import manager

settings = get_settings()


async def _bootstrap() -> None:
    """启动引导：建表 → 幂等迁移 → 默认设置 → 管理员提升"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations(engine)
    async with async_session() as db:
        await ensure_defaults(db)
        await seed_templates(db)
        names = [n.strip() for n in os.getenv("BOOTSTRAP_ADMIN_USERNAMES", "admin").split(",") if n.strip()]
        for name in names:
            user = (await db.execute(select(User).where(User.username == name))).scalar_one_or_none()
            if user and user.role != "admin":
                user.role = "admin"
                await db.commit()
                print(f"[bootstrap] {name} 已提升为管理员")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _bootstrap()
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(invites.router, prefix="/api", tags=["invites"])
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(templates_api.router, prefix="/api", tags=["templates"])
app.include_router(pdf.router, prefix="/api", tags=["pdf"])
app.include_router(projects.router, prefix="/api", tags=["projects"])
app.include_router(workflows.router, prefix="/api", tags=["workflow"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "version": "0.3.0"}


@app.websocket("/ws/{project_id}")
async def ws_endpoint(websocket: WebSocket, project_id: str, token: str = ""):
    """节点状态推送：必须校验 token 且该项目归属当前用户（P0 修复越权订阅）

    先 accept 再带业务码关闭，便于前端区分"未登录(4401)/无权访问(4403)/项目不存在(4404)"。
    """
    await websocket.accept()

    try:
        if not token:
            raise ValueError("missing token")
        payload = decode_token(token)
        uid = payload.get("sub")
    except Exception:
        await websocket.close(code=4401)
        return

    async with async_session() as db:
        user = await db.get(User, uid) if uid else None
        project = await db.get(Project, project_id)
        if user is None or project is None:
            await websocket.close(code=4404)
            return
        if not user.is_active or int(payload.get("ver") or 1) != int(user.token_version or 1):
            await websocket.close(code=4401)
            return
        if project.owner_id != user.id:
            await websocket.close(code=4403)   # 越权：非本人项目
            return

    await manager.connect(project_id, websocket, accept=False)
    try:
        while True:
            await websocket.receive_text()  # 保持连接；消息仅作心跳
    except WebSocketDisconnect:
        manager.disconnect(project_id, websocket)
