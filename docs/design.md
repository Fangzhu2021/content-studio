# 内容工坊 (Content Studio) — 在线无限画布稿件改写系统

## Context

用户需要一个在线无限画布系统，实现稿件的流转和改写：
1. 输入草拟稿件 → 2. AI 生成电视稿和报刊稿 → 3. 人工审定 → 4. 生成多平台新媒体风格稿件 → 5. 生成各平台最终成稿 → 6. 用户复制粘贴，在各平台自行发布

技术选型：React + React Flow（前端）、Python FastAPI（后端）、DeepSeek AI、部署于内网宝塔面板（YOUR_SERVER_IP）。

---

## 项目结构

```
/path/to/content-studio/   # 服务器 YOUR_SERVER_IP 直接开发部署
├── .env.example
├── deploy/
│   ├── nginx.conf.example           # 宝塔站点反代参考配置
│   └── README.md                    # 部署步骤说明
├── backend/
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   └── app/
│       ├── main.py                    # FastAPI 入口
│       ├── config.py                  # 配置管理 (pydantic-settings)
│       ├── db.py                      # SQLAlchemy async engine + session
│       ├── models/                    # SQLAlchemy ORM 模型
│       │   ├── user.py
│       │   ├── project.py
│       │   ├── node.py
│       │   └── revision.py
│       ├── schemas/                   # Pydantic 请求/响应 schema
│       │   ├── auth.py
│       │   ├── project.py
│       │   ├── workflow.py
│       │   └── ai.py
│       ├── routers/                   # API 路由
│       │   ├── auth.py                # 注册/登录/JWT
│       │   ├── projects.py            # 项目管理 CRUD
│       │   ├── workflows.py           # 画布节点/边 CRUD + 执行
│       │   └── ai.py                  # AI 改写接口
│       ├── services/
│       │   ├── auth_service.py
│       │   ├── workflow_service.py    # 工作流编排：按边顺序执行节点
│       │   ├── rewrite_service.py     # 稿件改写核心逻辑
│       │   └── export_service.py      # 成稿汇总：合并审定稿为最终排版文本
│       ├── ai/                        # DeepSeek AI 层
│       │   ├── base.py                # 抽象基类
│       │   ├── deepseek_provider.py   # DeepSeek 实现（OpenAI 兼容协议）
│       │   └── router.py              # 任务 → 模型档位 + prompt 模板
│       └── ws.py                      # WebSocket：节点状态实时推送
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/                       # 后端 API 调用封装
│       │   ├── client.ts             # axios 实例 + JWT 拦截器
│       │   ├── auth.ts
│       │   ├── projects.ts
│       │   └── workflows.ts
│       ├── store/                     # Zustand 状态管理
│       │   ├── authStore.ts
│       │   ├── canvasStore.ts
│       │   └── projectStore.ts
│       ├── components/
│       │   ├── layout/
│       │   │   ├── AppShell.tsx       # 整体布局（顶栏 + 画布区）
│       │   │   └── Header.tsx         # 项目切换、用户菜单
│       │   ├── auth/
│       │   │   └── LoginModal.tsx
│       │   ├── canvas/
│       │   │   ├── InfiniteCanvas.tsx # React Flow 画布主体
│       │   │   ├── NodePalette.tsx    # 左侧节点拖入面板
│       │   │   ├── CanvasToolbar.tsx  # 缩放、自动布局等工具
│       │   │   └── nodes/            # 自定义节点组件
│       │   │       ├── DraftInputNode.tsx   # 稿件输入节点
│       │   │       ├── RewriteNode.tsx      # AI 改写节点 (TV/报刊)
│       │   │       ├── ReviewNode.tsx       # 人工审定节点
│       │   │       ├── TransformNode.tsx    # 新媒体风格转换节点
│       │   │       └── ExportNode.tsx         # 成稿节点：生成最终排版稿，供复制发布
│       │   ├── panels/               # 右侧滑出配置面板
│       │   │   ├── NodeConfigPanel.tsx     # 根据节点类型动态渲染配置
│       │   │   ├── DraftEditor.tsx         # 稿件编辑区
│       │   │   ├── RevisionViewer.tsx      # 改写结果查看+对比
│       │   │   └── ExportPanel.tsx         # 成稿预览 + 一键复制/下载
│       │   └── common/
│       │       ├── StatusBadge.tsx
│       │       └── LoadingSpinner.tsx
│       └── hooks/
│           ├── useWebSocket.ts        # WebSocket 连接 hook
│           └── useAutoLayout.ts      # 画布自动布局
```

---

## 核心数据模型

### User
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| username | str(50) | 唯一 |
| hashed_password | str | bcrypt |
| created_at | datetime | |

### Project (项目 = 一个画布)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| name | str(200) | 项目名称 |
| owner_id | FK(User) | 所有者 |
| created_at / updated_at | datetime | |

### CanvasNode (画布节点)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| project_id | FK(Project) | 所属项目 |
| type | enum | draft_input / rewriter / reviewer / transformer / exporter |
| subtype | str(50) | 子类型：tv_script / newspaper / wechat / weibo / douyin / xiaohongshu / toutiao |
| position_x / position_y | float | 画布坐标 |
| config | JSON | 节点配置（prompt 模板、模型档位等）；API Key 走后端环境变量 |
| status | enum | idle / running / done / failed / approved |
| created_at / updated_at | datetime | |

### CanvasEdge (连线)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| project_id | FK(Project) | |
| source_node_id | FK(CanvasNode) | |
| target_node_id | FK(CanvasNode) | |

### Revision (改写记录)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| node_id | FK(CanvasNode) | 哪个节点产生的 |
| parent_revision_id | FK(self) | 上游改写（追溯链） |
| title | str(500) | 稿件标题 |
| content | text | 稿件正文 |
| format_type | str(50) | tv_script / newspaper / wechat / weibo / douyin / xiaohongshu / toutiao |
| status | enum | draft / rewritten / reviewed / approved / finalized | finalized=已成稿，发布由用户站外人工完成 |
| review_comment | text | 审定意见 |
| created_at / updated_at | datetime | |

> 无外部推送：系统不调用任何平台发布 API，不设 PushLog；最终成稿由用户复制后到各平台后台人工发布，平台侧信息（已发链接等）可手填在 review_comment 或追加到导出记录。

### RunLog (运行台账，一次节点执行 = 一行)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| user_id / username | str | 谁执行的（用户被删后仍保留用户名） |
| project_id / project_name | str | 哪个项目（项目被删后解绑，保留名称以延续统计） |
| node_id / node_type / node_subtype / node_label | str | 哪个节点 |
| trigger | enum | manual 手动 / auto 一键执行 / retry 重试 |
| status | enum | ok / failed / blocked（配额或排队拦截） / running |
| error | text | 可读失败原因 |
| input_revision_id / input_chars / input_preview | str/int/text | 输入快照（预览 500 字） |
| output_revision_id / output_chars / output_preview | str/int/text | 生成物快照（预览 500 字） |
| params | JSONB | 参数快照 + 生效提示词预览 |
| model / prompt_tokens / completion_tokens / cost_est | str/int/float | 模型与成本 |
| duration_ms / retries / queued_ms | int | 耗时、重试次数、排队时长 |
| template_key | str(40) | 画布模板来源：standard_v1 / ai_review_v1 / blank |
| node_template_id / node_template_version | str/int | 节点模板与其版本 |
| prompt_source / prompt_hash / prompt_template_id / prompt_template_version | str | 生效提示词来自 node/global/builtin 及其指纹与版本 |
| created_at | datetime | 默认保留 12 个月 |

> **录音转文字**：音频文件存放在 `uploads/<project_id>/<node_id>/`，转写状态记在 `node.config.audio`
> （文件名、大小、时长、进度、切段数、job_id、revision_id）；转写结果作为 `Revision(format_type=audio_transcript)`
> 进入稿件池，下游节点零改动复用。用量表 `ai_usage.audio_seconds` 记音频秒数（本地识别费用为 0）。
>
> 识别由同机独立服务提供：`deploy/asr-service/`（sherpa-onnx + SenseVoice，只监听 127.0.0.1:8030，音频不出内网）。

### TemplateVersion (模板版本快照)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| template_type | enum | node / prompt |
| template_id | str | 对应 NodeTemplate / PromptTemplate 的主键 |
| version | int | 第几版（新建=v1，每次保存 +1） |
| snapshot | JSONB | 该版本的关键字段快照 |
| changed_by / note | str | 修改人 / 新建或编辑 |
| created_at | datetime | |

> 正文只存 500 字预览，权威副本仍在 `revisions`；删除项目或用户时清空预览与参数快照但保留统计行，使"模板使用量、人均调用、成功率"等指标不出现断层。

---

## API 设计

### Auth
- `POST /api/auth/register` — 注册
- `POST /api/auth/login` — 登录，返回 JWT

### Projects
- `GET /api/projects` — 我的项目列表
- `POST /api/projects` — 新建项目
- `GET /api/projects/{id}` — 项目详情（含所有节点和边）
- `PUT /api/projects/{id}` — 更新项目名
- `DELETE /api/projects/{id}` — 删除

### Workflow (节点和边)
- `GET /api/projects/{id}/canvas` — 获取画布全部节点+边
- `POST /api/projects/{id}/nodes` — 添加节点
- `PUT /api/nodes/{id}` — 更新节点（位置/配置）
- `DELETE /api/nodes/{id}` — 删除节点
- `POST /api/projects/{id}/edges` — 添加连线
- `DELETE /api/edges/{id}` — 删除连线
- `POST /api/nodes/{id}/execute` — 执行单个节点（AI 改写）
- `POST /api/projects/{id}/execute` — 按拓扑顺序执行工作流

### AI（改写）
- `POST /api/ai/rewrite` — 执行改写 { node_id, input_content, format_type }
  - 统一调用 DeepSeek（`deepseek-chat` 为主，复杂稿可选 `deepseek-reasoner`），差异在 prompt 模板
  - `format_type=tv_script` → TV 口播稿风格
  - `format_type=newspaper` → 通讯社通稿风格
  - `format_type=wechat` → 公众号深度长文
  - `format_type=weibo` → 微博文案（含话题）
  - `format_type=douyin` → 短视频口播脚本
  - `format_type=xiaohongshu` → 小红书种草笔记
  - `format_type=toutiao` → 头条号新闻体

### Export（成稿导出）
- `POST /api/export/{revision_id}/finalize` — 将 Revision 标记为 finalized（已成稿）
- `GET /api/export/{revision_id}` — 获取最终成稿（Markdown/纯文本）
- 发布动作在系统外完成：前端 ExportPanel 提供「复制全文 / 下载 .md」，由用户粘贴到平台后台发布

### WebSocket
- `WS /ws/{project_id}` — 节点状态实时推送

### Admin（仅管理员）
- `GET /api/admin/run-logs` — 运行台账列表（days / username / project_id / node_type / status / q / only_failed / 分页）
- `GET /api/admin/run-logs/{id}` — 台账详情（输入输出预览、参数快照、生成物开头）
- `GET /api/admin/run-logs/summary` — 台账统计（总量、成败、被拦截、按节点/按人/按模板/按天）
- `GET /api/admin/run-logs/export.csv` — 导出 CSV（默认不含正文预览，`with_preview=true` 才带）
- `POST /api/admin/run-logs/prune?months=12` — 按保留期归档清理
- `GET /api/admin/template-versions` — 模板版本历史（节点库 / 提示词）
- `POST /api/admin/asr/test` — 测试语音识别服务连通性（录音转文字节点依赖）
- `POST /api/nodes/{id}/audio` · `GET /api/nodes/{id}/audio` · `GET /api/nodes/{id}/audio/file` · `DELETE /api/nodes/{id}/audio` · `POST /api/nodes/{id}/audio/transcribe` — 录音上传 / 进度 / 回听 / 删除 / 提交转写

---

## AI 策略（统一 DeepSeek）

```
草拟稿件 ──→ [deepseek-chat] ──→ TV 稿 + 报刊稿
                                     │
                               人工审定 (Review Node)
                                     │
             ┌───────────────────────┼───────────────────────┐
             ↓                       ↓                       ↓
      [deepseek-chat]          [deepseek-chat]         [deepseek-chat]
      微信公众号长文           微博/抖音短文案           小红书/头条风格
             ↓                       ↓                       ↓
             └───────────────────────┼───────────────────────┘
                                     ↓
                               成稿输出（复制发布）
```

- **统一模型**：全部改写走 DeepSeek `deepseek-chat`（中文新闻改写性价比高、输出稳定），不再做多模型混合
- **可选增强**：复杂长稿可在节点 config 切换 `deepseek-reasoner`（深度思考），API 为 OpenAI 兼容协议，仅需换 model 名
- **风格差异靠 Prompt**：各 `format_type` 的差异收敛在 prompt 模板库 + 输出格式约束中，不走模型切换
- API Key 通过后端环境变量统一配置（`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`），不存节点 config

---

## 前端核心交互

### 画布操作
1. 从左侧 NodePalette 拖拽节点到画布
2. 连线节点形成工作流（source handle → target handle）
3. 点击节点 → 右侧滑出配置面板
4. 节点状态颜色：灰色(idle) → 蓝色(running) → 绿色(done) / 红色(failed) / 金色(approved)

### 典型工作流模板
新建项目时选择模板，自动创建节点+连线：
```
[Draft Input] → [Rewrite: TV Script] → [Review] → [Transform: WeChat] → [Export: 公众号成稿]
             → [Rewrite: Newspaper] ↗          → [Transform: Weibo]  → [Export: 微博成稿]
                                                 → [Transform: Douyin] → [Export: 抖音成稿]
```

### 稿件编辑体验
- DraftInputNode: 点击打开富文本/Markdown 编辑器
- 改写结果展示：并排对比（原文 vs 改写稿）
- Review Node: 审阅者可以批注、修改、打回或通过
- ExportNode / ExportPanel: 审定通过的稿件生成最终成稿（Markdown/纯文本预览），一键复制/下载；发布由用户到各平台后台人工完成，系统不调用任何平台 API

---

## 界面设计规范（「深空精密」）

界面按《UI 设计规范 v1.0》实现，令牌集中在 `frontend/src/tokens.css`（与规范的附录 B 逐项对应）：

| 项 | 值 |
|---|---|
| 表面层级 | `--bg-base #05080E` / `--bg-canvas #070B12` / `--surface-1 #0F1620` / `--surface-2 #141D29` / `--surface-3 #1B2634` / `--surface-4 #223044` |
| 描边与连线（必须分色） | `--border-node #4A5E80`、`--border-default #26344A`、`--edge-default #566D92`、`--edge-hover #7298FF` |
| 文字四级 | `#E8EEF7` / `#9AA9BF` / `#68788F` / `#414E60` |
| 品牌与渐变 | `--brand-500 #4F7CFF`、`--grad-brand linear-gradient(135deg,#3D66E8,#8B5CF6)`（仅品牌区/主按钮/登录页） |
| 状态色 | 成功 `#2DD4BF`、运行 `#38BDF8`、排队 `#8B93A7`、警告 `#F5A524`、失败 `#F4526A` |
| 分类色 | 输入 `#22D3EE`、工具 `#4F7CFF`、改写 `#8B5CF6`、审稿 `#F5A524`、转换 `#2DD4BF`、导出 `#7298FF` |
| 圆角 | `4/6/8/12/16/999`（图标容器 8 与节点 12 构成 2:3 嵌套） |
| 字号 | 28 / 20 / 16 / 14 / 13 / 12 / 11 + 等宽数字 |
| 动效 | 90 / 140 / 200 / 320ms + 呼吸 2000ms + 数据流 1200ms，响应 `prefers-reduced-motion` |

组件规格：画布节点 208×96、圆角 12、分类色条 3px、图标容器 28×28、状态胶囊 20px（状态色 18% 底 + 圆点 + 文字 + 图标）；连线 1.5px、曲率 0.45、带 7px 箭头；左栏 220px（含节点搜索）、右栏默认 380px 且可拖拽（300–1100px，为长稿输出保留大窗口）；顶栏 56px、底部状态栏 28px。

## 部署（宝塔面板 · YOUR_SERVER_IP）

不使用 Docker，前后端分离直接部署到内网宝塔机器 `YOUR_SERVER_IP`（面板装 Nginx；数据库装 PostgreSQL 16 或 MySQL 8，切换连接串即可）。

### 部署拓扑
| 组件 | 位置/方式 | 说明 |
|------|-----------|------|
| 前端 | `npm run build` 产物 → 宝塔网站目录（如 `/path/to/content-studio`） | 访问入口 `http://YOUR_SERVER_IP` |
| 后端 | 宝塔「Python 项目」或进程守护运行 uvicorn，监听 `127.0.0.1:8000` | 仅回环，不直接对外暴露 |
| 数据库 | 宝塔软件商店安装 PostgreSQL 16（或 MySQL 8） | 库名 `content_studio`，连接串走环境变量 |
| 反向代理 | 站点 Nginx 把 `/api`、`/ws` 转发到 `127.0.0.1:8000` | WebSocket 需带 Upgrade 头 |

### Nginx 反代关键配置
```
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### 开发与发布流程（直接在服务器开发）
1. 代码直接放服务器 `/path/to/content-studio`（`yyrm` 所有），SSH 或宝塔文件管理编辑
2. 项目内建 git 仓库做版本回滚（`git init` + 按阶段 commit；可选内网远程仓库备份）
3. 后端：venv + uvicorn 运行，改完由宝塔 Python 项目/进程守护重启生效；库表变更用 Alembic 迁移
4. 前端：宝塔 Node 项目管理器构建（或 SSH `npm run build`）后由 Nginx 托管
5. 密钥与模型配置放后端 `.env`（`DEEPSEEK_API_KEY`、`JWT_SECRET`、`DATABASE_URL`），不提交仓库
6. 访问入口 `http://YOUR_SERVER_IP`（前端）→ `/api`、`/ws` 反代到 `127.0.0.1:8000`（后端）

---

## 实施顺序

### Phase 1: 项目骨架 (Day 1-2)
1. 初始化前端 (Vite + React + React Flow)、后端 (FastAPI) 项目结构
2. 打通宝塔基础部署：Nginx 站点 + uvicorn + PostgreSQL + 反代（/api、/ws）
3. 用户认证（注册/登录/JWT）
4. 基础的 CRUD 项目管理 API

### Phase 2: 画布核心 (Day 3-4)
1. React Flow 画布 + 5 种自定义节点组件
2. 节点拖入、连线、删除、拖动定位
3. 画布数据持久化到后端
4. 右侧配置面板框架

### Phase 3: AI 改写引擎 (Day 5-6)
1. DeepSeek provider 抽象层（OpenAI 兼容协议）
2. 改写接口实现（草稿 → TV 稿/报刊稿）
3. 前端节点执行触发 + 结果展示
4. WebSocket 状态实时推送

### Phase 4: 新媒体转换 + 成稿导出 (Day 7-8)
1. 新媒体风格转换 prompt 模板（公众号/微博/抖音/小红书/头条）
2. Review Node 审定流程（通过/打回/批注）
3. ExportNode + ExportPanel：成稿排版、一键复制/下载 Markdown、finalize 标记
4. 工作流模板（一键创建标准流程）

### Phase 5: 完善 + 部署 (Day 9-10)
1. 错误处理、重试机制
2. 前端交互打磨（loading、空状态、拖拽动画）
3. 宝塔部署与运维文档（进程守护、Nginx 配置、备份策略）
4. 生产环境配置

---

## 验证方式

1. 宝塔部署完成（代码在 `/path/to/content-studio`），浏览器打开 `http://YOUR_SERVER_IP`，注册账号
2. 新建项目 → 选择工作流模板 → 自动创建节点+连线
3. 在 DraftInputNode 中输入测试稿件
4. 点击执行 → 观察节点状态变化（WebSocket 实时更新）
5. 查看改写结果 → 审定通过/打回
6. 继续执行下游新媒体转换节点
7. 在 ExportNode 查看最终成稿，点击「复制 / 下载」，粘贴到各平台后台人工发布

---

## 进度与部署实况（2026-09-09 已上线）

> 开发过程完整记录见 [开发过程总结](development-summary.md)；多人使用与后台管理设计见 [多人使用与后台管理方案](multi-user-and-admin-console.md)
>
> **2026-09-10 更新**：P0 多人使用安全与配额已上线（WebSocket 越权修复、邀请码注册、登录限流、AI 用量计量与配额、审计日志、每日自动备份）。注册已关闭，新同事需凭管理员发放的邀请码注册。

### 访问
- **入口：http://YOUR_SERVER_IP**（Nginx 静态站 frontend/dist + /api、/ws 反代 127.0.0.1:8000）
- 代码：`/path/to/content-studio`（git 5 个提交），后端 systemd `content-studio-backend` 托管

### 已实现（Phase 1-4 全链路 MVP + Phase 5 基础）
- JWT 注册/登录；项目管理 + **标准工作流模板一键生成**（草稿→TV/报刊→审稿→公众号/微博/抖音转换→成稿导出）
- React Flow 无限画布：6 类节点拖拽/连线/持久化/删除，状态色（idle灰/running蓝/done绿/failed红/approved金）+ WebSocket 实时推送
- AI 改写引擎：DeepSeek（OpenAI 兼容协议，`backend/.env` 配 `DEEPSEEK_API_KEY`）；**未配置 Key 时自动模拟模式**（输出带「模拟模式」标注，保证流程可演示）
- 审稿两种方式：**人工审定**（逐篇批注/通过/打回）与 **🤖 AI 审稿**（自动判定 + 审稿意见，可拖入画布；新建项目勾选「使用 AI 审稿」即替代人工）
- **工具节点组**（可拖入画布，从草稿取稿）：
  - **✂️ 稿件精简**：提取精简稿，默认压缩到约 1/3（可选 1/4、1/3、1/2 档），保留时间/地点/主体/事件/关键数据/要求
  - **🎨 风格提取**：从草稿提炼「写作风格提示词」（语气、句式、段落结构、用词习惯），把该节点连到改写/转换节点后，**风格会自动注入下游提示词**
- 画布不限模板：可建空白项目自由拖拽节点与连线（支持分支、跳步、任意拓扑，无环）
- **每个 AI 节点可自定义提示词**：编辑器预填默认模板，可在默认版上修改后保存；可切 `deepseek-chat` / `deepseek-reasoner`；支持恢复默认
- 新媒体转换、成稿导出（来源稿点击即预览、一键复制全文、下载 .md）
- AI 审稿标尺：默认「标准模式」仅对实质问题（事实矛盾/夸大失实/敏感违规/严重语病）打回；可开「严格模式」（评分<80 即打回）

### 使用提示
1. 打开 http://YOUR_SERVER_IP 注册账号 → 「＋新建」勾选模板创建项目（默认勾选 AI 审稿，无需人工点头）
2. 点「草稿输入」节点 → 右侧填标题/正文 → 保存草稿
3. 依次点「AI 改写」节点执行 → 「AI 审稿」节点点「开始 AI 审稿」（或人工审定节点逐篇通过）
4. 点「新媒体转换」节点执行 → 「成稿导出」节点生成 → 来源稿预览 → 一键复制全文 → 到平台粘贴发布
5. 改提示词：任意 AI 节点 → 🧠 提示词设置 → 修改 → 保存（编辑器已预填默认模板，可直接在其上改）
6. 接入真 AI：编辑 `backend/.env` 填 `DEEPSEEK_API_KEY` 后 `sudo systemctl restart content-studio-backend`

### 服务管理
```
sudo systemctl restart content-studio-backend   # 后端重启
cd /path/to/content-studio/frontend && npm run build   # 前端构建
journalctl -u content-studio-backend -f         # 日志
```
