# 部署须知（DEPLOY）

面向运维/开发者的部署与运维手册。示例以 **Ubuntu + 宝塔面板 + Nginx + systemd + PostgreSQL** 为例，纯命令行环境同样适用。

---

## 1. 环境要求

| 组件 | 版本要求 | 说明 |
|---|---|---|
| 操作系统 | Ubuntu 22.04+ / 其他主流 Linux | 需能访问外网（调用 AI API） |
| Python | 3.11+（实测 3.14） | 需 `venv` |
| Node.js | 20+（实测 22） | 仅用于构建前端产物 |
| PostgreSQL | 14+（实测 18） | 业务库 |
| Nginx | 任意稳定版 | 静态站 + 反向代理 |
| 宝塔面板 | 可选 | 用于站点/进程/备份的可视化管理 |

**端口与网络**：后端只监听 `127.0.0.1:8000`（不对外），对外只暴露 Nginx 的 80/443；需要能访问 AI 服务域名（如 `api.deepseek.com`）。

---

## 2. 部署拓扑

```
浏览器 ──→ Nginx(80/443)
            ├── /             → 静态站 frontend/dist
            ├── /api/         → 127.0.0.1:8000（FastAPI）
            └── /ws/          → 127.0.0.1:8000（WebSocket，需 Upgrade 头）
                                  └── PostgreSQL(127.0.0.1:5432)
                                  └── AI API（外网 HTTPS）
```

---

## 3. 部署步骤

### 3.1 建库建用户
```bash
sudo -u postgres psql -c "CREATE ROLE content_studio LOGIN PASSWORD '强密码';"
sudo -u postgres psql -c "CREATE DATABASE content_studio OWNER content_studio ENCODING 'UTF8';"
```
> PostgreSQL 默认只监听 `127.0.0.1`，**不要**对外开放 5432。

### 3.2 后端
```bash
cd /path/to/content-studio/backend
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt      # 含 fastapi/uvicorn/sqlalchemy/asyncpg/pymupdf/python-multipart
cp .env.example .env
```

`.env` 关键项：
```ini
DATABASE_URL=postgresql+asyncpg://content_studio:强密码@127.0.0.1:5432/content_studio
JWT_SECRET=请替换为足够长的随机串          # 必改！
DEEPSEEK_API_KEY=sk-xxxx                   # 留空则进入「模拟模式」，流程仍可跑通
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEBUG=false
```

冒烟测试：
```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/api/health
```
首次启动会：**建表 → 执行幂等迁移 → 写入默认设置 → 播种内置节点库与提示词 → 提升 `BOOTSTRAP_ADMIN_USERNAMES`（默认 `admin`）为管理员**。

### 3.3 前端
```bash
cd ../frontend
npm install          # 若中途失败，务必删掉 node_modules 重装（见排障）
npm run build        # 产物：dist/
```

### 3.4 systemd 托管后端
```bash
sudo cp deploy/content-studio-backend.service /etc/systemd/system/
# 按实际路径修改 WorkingDirectory / ExecStart / User
sudo systemctl daemon-reload
sudo systemctl enable --now content-studio-backend
systemctl status content-studio-backend --no-pager
journalctl -u content-studio-backend -f
```
> 服务单元已配置 `Restart=always`，崩溃自动重启。

### 3.5 Nginx 站点
参考 `deploy/nginx.conf.example`：静态指向 `frontend/dist`，`/api` 与 `/ws` 反向代理到 `127.0.0.1:8000`。
⚠️ WebSocket 段必须带：
```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```
启用多站点时建议用 `server_name` 区分，避免与已有站点冲突。

**建议同时**：启用 HTTPS（内网自签亦可），否则部分浏览器会限制剪贴板富文本复制。

### 3.6 生成邀请码（注册默认关闭）
```bash
cd /path/to/content-studio/backend
.venv/bin/python scripts/admin.py invite --role editor --days 7 --note "给某同事"
# 也可登录 /admin → 用户管理 → ＋ 生成邀请码（会给出带码注册链接）
```
运维 CLI 速查：
```bash
.venv/bin/python scripts/admin.py users                       # 用户与角色
.venv/bin/python scripts/admin.py promote <用户名>             # 提升管理员
.venv/bin/python scripts/admin.py reset-password <用户名> <新密码>
.venv/bin/python scripts/admin.py registration on|off          # 临时开关公开注册
.venv/bin/python scripts/admin.py sync-prompt <key> [--apply]  # 把内置提示词同步到数据库
```

### 3.7 每日备份（强烈建议）
```bash
# /usr/local/bin/cs-backup.sh
#!/bin/bash
BK=/path/to/backups; TS=$(date +%Y%m%d-%H%M)
su postgres -c "pg_dump -Fc content_studio -f /tmp/cs-$TS.dump"
mv /tmp/cs-$TS.dump "$BK/db-daily-$TS.dump"
cp /path/to/content-studio/backend/.env "$BK/env-$TS.bak"
find "$BK" -name 'db-daily-*.dump' -mtime +30 -delete
```
```bash
sudo chmod 750 /usr/local/bin/cs-backup.sh
echo "30 3 * * * root /usr/local/bin/cs-backup.sh" | sudo tee /etc/cron.d/content-studio-backup
```
> 备份目录需对 `postgres` 用户**可写可穿越**（`chmod 755` 父目录），否则 `pg_dump` 会因权限失败。

---

## 4. 升级流程

```bash
cd /path/to/content-studio
# 1) 先备份（数据库 + .env）
sudo /usr/local/bin/cs-backup.sh
# 2) 更新代码
git pull            # 或上传覆盖
# 3) 依赖与迁移（后端启动时自动执行幂等迁移）
cd backend && .venv/bin/pip install -r requirements.txt
# 4) 前端
cd ../frontend && npm install && npm run build
# 5) 重启并验证
sudo systemctl restart content-studio-backend
curl -s http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "%{http_code}\n" http://YOUR_SERVER_IP/
```
建议在低使用时段执行（重启约 5–10 秒）。

---

## 5. 回滚

```bash
# 代码回滚（若打了标签）
cd /path/to/content-studio && git checkout <tag或commit>
sudo systemctl restart content-studio-backend

# 数据库回滚（会覆盖当前数据，谨慎）
sudo -u postgres pg_restore -c -d content_studio /path/to/backups/db-daily-YYYYMMDD-HHMM.dump
```
> 数据库变更策略是**只增不改**（`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`、新增表），因此通常无需回滚数据库即可回滚代码。

---

## 6. 排障清单（均为实际踩过的坑）

| 现象 | 原因与处理 |
|---|---|
| `systemctl` 显示 `activating (auto-restart)`，日志报 `address already in use` | 有残留 uvicorn 占用 8000：`ss -tlnp \| grep 8000` 找到进程并 kill，再重启服务 |
| 启动报 `Form data requires "python-multipart"` | 缺文件上传依赖：`.venv/bin/pip install python-multipart` |
| 管理接口返回 500，日志 `MissingGreenlet` | 异步会话下提交后访问 `updated_at` 等列触发同步懒加载；已在代码内 `await db.refresh()` 处理，若自行扩展模型请沿用该写法 |
| 前端 `tsc` 报 `csstype/index.d.ts` 语法错 | `npm install` 曾中断导致类型文件截断：`rm -rf node_modules package-lock.json && npm install` |
| `pg_dump: Permission denied` | 备份目录父级缺少执行位或归属不对：`chmod 755` 父目录、备份目录归 `postgres` |
| WS 连不上（状态不刷新） | Nginx 缺少 `Upgrade`/`Connection` 头；或前端未带 `?token=` |
| 页面能开但接口 502 | 后端未启动或端口不符：查 `systemctl status` 与 `.env`、Nginx 代理地址 |
| 富文本复制粘贴到秀米只有纯文本 | 浏览器限制非安全上下文的剪贴板富文本：启用 HTTPS |

---

## 7. 上线验收清单

- [ ] `GET /api/health` 返回 `{"status":"ok"}`
- [ ] 首页可访问、`/admin` 可访问且非管理员被拒
- [ ] 注册已关闭，凭邀请码链接可完成注册
- [ ] 创建项目 → 选模板 → 画布出现节点
- [ ] 录入草稿 → 执行改写（真 Key 时为 `deepseek-chat`）
- [ ] AI 审稿或人工审定 → 通过
- [ ] 新媒体转换 → 成稿导出 → 一键复制富文本
- [ ] `/admin` 用量看板出现调用记录，审计日志有对应条目
- [ ] 每日备份任务已生效（手动跑一次并确认产物）
- [ ] 已设置强 `JWT_SECRET`，`.env` 未提交到任何仓库
