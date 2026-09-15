# 智能编辑系统（Content Studio）

> 面向融媒体中心的**在线无限画布稿件改写系统**：把一篇草稿，经 AI 改写、人工/AI 审稿、多平台风格转换，最终产出可直接粘贴发布的成稿。

一套可私有化部署的「AI 写稿流水线」：画布即工作流，节点即环节，稿件版本全程留痕。

---

## ✨ 功能概览

### 画布化工作流（React Flow）
从节点库拖入节点、连线成流程，支持任意拓扑（可跳过环节、可分支）：

| 分组 | 节点 |
|---|---|
| 输入 | 📝 草稿输入 |
| 工具 | ✂️ 稿件精简（可选 1/4、1/3、1/2 篇幅）· 🎨 风格提取 · 📄 PDF 版面提取 · 💡 新闻选题策划 · 📋 报道方案生成 |
| AI 改写 | 📺 电视口播稿 · 📰 报刊通稿 |
| 审稿 | ✅ 人工审定（批注/通过/打回）· 🤖 AI 审稿（自动判定 + 审稿意见，可开严格模式） |
| 新媒体转换 | 💬 公众号长文 · 🔥 微博 · 🎬 抖音 · 📕 小红书 · 🗞️ 头条 |
| 成稿导出 | 5 平台排版成稿：公众号输出**内联样式 HTML**，一键复制富文本可直接粘贴进秀米 / 微信编辑器 |

- 节点状态实时推送（WebSocket）：待命 / 排队中 / 执行中 / 完成 / 失败 / 已通过
- **节点库分组可折叠**：每组标题带三角形按钮，点一下收起不常用的分组（折叠后显示该组条目数），标题栏可「全部折叠 / 全部展开」，折叠状态按人记住、刷新保持
- 执行失败显示真实原因 + **一键重试**；错误区分「限流 / 超时 / 网络 / Key 无效」
- 打开节点自动载入上次结果；稿件带 `parent_revision_id` 追溯链

### 平台适配的排版提示词（可在后台修改，全站生效）
| 平台 | 结构 | 话题格式 | 引流 |
|---|---|---|---|
| 公众号 | 内联样式 HTML：标题居中、导语浅灰引用块、小标题色块、正文 16px/行高 1.75 | — | 结尾引导关注 |
| 微博 | ≤180 字：钩子首行 + 事实分段 + 互动引导 | **双井号 `#话题#`** 3~4 个 | @官方账号 + 评论区引导 |
| 小红书 | 标题 ≤20 字带 emoji、正文 300~600 字、emoji 小标题 | **单井号 `#话题`** 5~8 个 | 收藏/评论引导 |
| 头条 | 导语 40~80 字 + 【小标题】分层，600~1200 字 | **双井号 `#话题#`** 1~3 个 | 关注 + 评论引导 |
| 抖音 | 【发布文案】+【口播脚本】分镜（镜头｜画面｜口播｜字幕） | **单井号 `#话题`** 3~5 个 | 片尾互动 |

### 多用户与治理
- JWT 鉴权、PBKDF2 密码哈希、**邀请码注册**（一次性、可设角色与有效期、后台可生成带码注册链接）
- 角色：管理员 / 编辑 / 审核 / 只读（管理员可调整，变更即令该用户旧会话失效）
- **AI 用量计量与配额**：按用户月度调用次数限额（空=继承、0=禁用、>0=上限），超额拦截且不消耗额度
- **并发限制与排队**：全局 / 单用户并发上限 + 排队等待上限，超限时节点显示「排队中」
- **审计日志**：注册、登录、登录失败、建删项目、节点执行（含失败）、审稿、邀请码与设置变更全部留痕
- **运行台账**：每次节点执行都留一条记录 —— 谁、在哪个项目、用哪个模板（含模板版本号）、触发方式（手动 / 一键 / 重试）、输入前 500 字、生成物前 500 字、参数快照、模型、token、费用、耗时、重试与排队；成功、失败、**被配额拦截**全都记；删除项目或用户时保留统计口径、清空正文预览，默认保留 12 个月并可一键归档
- **模板版本化**：节点库与提示词模板每次保存都留快照（v1 → v2 → …），台账里的版本号能对上"当时用的是哪一版"
- **管理后台** `/admin`：概览 · **运行台账** · 用户管理 · 项目管理 · 用量看板（可导出 CSV）· 审计日志 · 节点与提示词（含版本历史）· 系统设置

### AI 与工程能力
- **DeepSeek**（OpenAI 兼容协议）；未配置 Key 时自动进入「模拟模式」，全流程仍可演示与测试
- **界面统一显示「AI 模型」**：模型档位（标准 / 深度思考）、稿件信息、运行台账等所有界面文案都不暴露模型厂商与型号（内部用中性别名映射真实模型名）
- **指数退避重试**（429/5xx/超时/网络，共 3 次尝试）+ 用户可读的错误提示
- **节点库与提示词数据化**：管理员在后台改节点名称/图标/颜色/提示词，用户刷新即生效
- **我的模板**：用户可保存个人提示词模板并在节点间复用
- **PDF 版面提取**：上传文字版 PDF → 按版面**版块**（页/栏/字号判标题）切分 → 勾选版块生成稿件

---

## 🏗 技术栈与架构

```
浏览器 ──→ Nginx
           ├── 静态资源：frontend/dist（React SPA）
           ├── /api/ ──→ 127.0.0.1:8000（FastAPI，systemd 托管）
           └── /ws/  ──→ 127.0.0.1:8000（WebSocket，节点状态推送）
                            │
                            ├── PostgreSQL（业务数据 + 用量 + 审计）
                            └── DeepSeek API（外部，HTTPS）
```

| 层 | 技术 |
|---|---|
| 前端 | React 19 · @xyflow/react 12（React Flow）· Vite 8 · TypeScript · Zustand · axios |
| 后端 | FastAPI · SQLAlchemy 2.0 async · asyncpg · Pydantic v2 · PyJWT · PyMuPDF · httpx |
| 数据库 | PostgreSQL 16+ |
| AI | DeepSeek（OpenAI 兼容 `/chat/completions`） |
| 测试 | Playwright 端到端脚本 + 后端单元脚本 |

### 目录结构
```
content-studio/
├── backend/
│   ├── app/
│   │   ├── main.py            # 入口：启动建表、幂等迁移、播种、WebSocket
│   │   ├── models.py          # User/Project/CanvasNode/CanvasEdge/Revision + 邀请码/审计/用量/模板
│   │   ├── ai.py              # DeepSeek：改写/审稿/精简/风格/选题/方案/排版 + 重试与错误分类
│   │   ├── pdf_tools.py       # PDF 版面解析（合并块、按字号判标题、断字还原）
│   │   ├── concurrency.py     # 并发限制器（全局 + 单用户 + 排队）
│   │   ├── templates.py       # 内置节点库与提示词 + 生效解析
│   │   ├── usage.py           # 用量计量与配额
│   │   ├── audit.py           # 审计日志与全局设置
│   │   ├── migrate.py         # 幂等迁移
│   │   ├── routers/           # auth / projects / workflows / admin / invites / pdf / templates_api
│   │   └── ...
│   ├── scripts/admin.py       # 运维 CLI：invite / users / promote / reset-password / sync-prompt / registration
│   └── requirements.txt
├── frontend/                  # React + React Flow 工作台（含 /admin 管理后台）
├── deploy/                    # Nginx 站点示例、systemd 单元、部署说明
├── docs/                      # 设计方案、开发过程总结、多人使用与后台管理方案
├── DEPLOY.md                  # 部署须知（环境要求、步骤、升级、回滚、排障）
└── NOTES.md                   # 注意事项与已知限制
```

---

## 🚀 快速开始

```bash
# 1. 数据库
sudo -u postgres psql -c "CREATE ROLE content_studio LOGIN PASSWORD 'your-password';"
sudo -u postgres psql -c "CREATE DATABASE content_studio OWNER content_studio ENCODING 'UTF8';"

# 2. 后端
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # 填 DATABASE_URL / JWT_SECRET / DEEPSEEK_API_KEY
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 前端
cd ../frontend
npm install && npm run build  # 产物在 dist/，交给 Nginx 托管

# 4. 生成邀请码（注册默认关闭）
cd ../backend && .venv/bin/python scripts/admin.py invite --role editor --days 7 --note "给同事"
```

> 首次启动会自动建表、执行幂等迁移、写入默认设置，并把 `BOOTSTRAP_ADMIN_USERNAMES`（默认 `admin`）中的用户提升为管理员。

完整部署（宝塔面板 / systemd / Nginx / 备份 / 升级 / 回滚）见 **[DEPLOY.md](DEPLOY.md)**；
上线前请务必阅读 **[NOTES.md](NOTES.md)**（密钥管理、配额、已知限制）。

---

## 📚 文档
| 文档 | 内容 |
|---|---|
| [docs/design.md](docs/design.md) | 系统设计方案：业务流程、数据模型、API、AI 路由、部署形态 |
| [docs/development-summary.md](docs/development-summary.md) | 开发过程总结：需求演进、关键决策、踩坑与修复、验证结果、经验教训 |
| [docs/multi-user-and-admin-console.md](docs/multi-user-and-admin-console.md) | 多人使用与后台管理方案：权限模型、配额策略、实施记录 |
| [DEPLOY.md](DEPLOY.md) | 部署须知与运维手册 |
| [NOTES.md](NOTES.md) | 注意事项、已知限制与安全建议 |

---

## ⚠️ 重要说明
- 本系统**不调用任何平台发布 API**：产出成稿后由人工复制到平台后台发布（微信/抖音/小红书等平台的发布接口存在资质与合规门槛，设计时已规避）。
- **AI 生成内容必须经人工或 AI 审稿后再发布**；系统提供审稿环节与审计留痕，但不能替代编辑责任。
- 生产环境请务必：设置强 `JWT_SECRET`、妥善保管 `DEEPSEEK_API_KEY`、保持公开注册关闭（改用邀请码）、开启每日备份并定期演练恢复。

## 📄 许可
本仓库未附带开源许可证（默认保留所有权利）。如需以特定许可证开源，请先添加 `LICENSE` 文件。
