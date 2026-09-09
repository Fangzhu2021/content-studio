# 内容工坊 (Content Studio)

在线无限画布稿件改写系统 —— 服务器 YOUR_SERVER_IP（宝塔面板）直接开发部署。

- 前端：React + React Flow (@xyflow/react)，Vite + TS
- 后端：Python FastAPI（async），PostgreSQL 18（库 content_studio）
- AI：DeepSeek（OpenAI 兼容协议）
- 发布：成稿导出（复制/下载），用户自行粘贴到各平台发布

## 结构
- backend/  FastAPI 后端
- frontend/ React 前端（Vite）
- deploy/   Nginx 反代参考配置
