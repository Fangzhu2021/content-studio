from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  确保模型注册
from .config import get_settings
from .db import Base, engine
from .routers import auth, projects, workflows
from .security import decode_token
from .ws import manager

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api", tags=["projects"])
app.include_router(workflows.router, prefix="/api", tags=["workflow"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "version": "0.2.0"}


@app.websocket("/ws/{project_id}")
async def ws_endpoint(websocket: WebSocket, project_id: str, token: str = ""):
    try:
        if not token:
            await websocket.close(code=4401)
            return
        decode_token(token)
    except Exception:
        await websocket.close(code=4401)
        return
    await manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # 保持连接；消息仅作心跳
    except WebSocketDisconnect:
        manager.disconnect(project_id, websocket)
