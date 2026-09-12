# 部署说明（宝塔/服务器 YOUR_SERVER_IP）

## 架构
- 80 端口：Nginx（系统源）→ 静态站 frontend/dist，server_name YOUR_SERVER_IP
- /api、/ws：反代到 127.0.0.1:8000（uvicorn，systemd 托管）
- 数据库：PostgreSQL 18 本机 content_studio 库

## 配置文件
- nginx.conf.example          → /etc/nginx/conf.d/content-studio.conf
- content-studio-backend.service → /etc/systemd/system/content-studio-backend.service

## 后端服务管理（systemd）
    sudo systemctl restart content-studio-backend   # 重启
    sudo systemctl status content-studio-backend    # 状态
    journalctl -u content-studio-backend -f         # 日志
（改完代码：cd backend && sudo systemctl restart content-studio-backend）

## 前端
    cd /path/to/content-studio/frontend
    npm run build        # 产物 dist/（重载 nginx 不需要，静态直读）
可选宝塔「Node 项目」托管 dev/build。

## 验证
    curl http://YOUR_SERVER_IP/api/health
