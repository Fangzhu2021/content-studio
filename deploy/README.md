# 部署说明（宝塔 YOUR_SERVER_IP）

1. 后端：`cd /www/wwwroot/content-studio/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
   - 运行：`.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`
   - 生产可用宝塔「Python 项目」托管，或 systemd 守护
2. 前端：`cd ../frontend && npm install && npm run build`（产物在 dist/）
3. Nginx：站点指向 frontend/dist，`/api`、`/ws` 反代 127.0.0.1:8000（见 nginx.conf.example）
4. 数据库：PostgreSQL 18 本机，库 content_studio（已在 09-09 创建）
