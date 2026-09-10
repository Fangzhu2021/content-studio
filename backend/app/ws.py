"""WebSocket 连接管理：节点状态实时推送"""
from fastapi import WebSocket


class WSManager:
    def __init__(self):
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, project_id: str, ws: WebSocket, accept: bool = True) -> None:
        if accept:
            await ws.accept()
        self._rooms.setdefault(project_id, set()).add(ws)

    def disconnect(self, project_id: str, ws: WebSocket) -> None:
        room = self._rooms.get(project_id)
        if room:
            room.discard(ws)
            if not room:
                self._rooms.pop(project_id, None)

    async def broadcast(self, project_id: str, message: dict) -> None:
        room = list(self._rooms.get(project_id, set()))
        dead = []
        for ws in room:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(project_id, ws)


manager = WSManager()
