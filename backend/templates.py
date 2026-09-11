"""节点库与提示词模板：内置定义、数据化后的生效解析、启动播种

优先级：节点 config.prompt > 用户个人模板 > 全站模板 > 内置常量
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import FORMAT_LABELS, PROMPTS
from .models import NodeTemplate, PromptTemplate, User

# 内置节点库（前端节点库兜底，同时用于启动播种）
BUILTIN_NODES: list[dict] = [
    {"group": "输入", "kind": "draft_input", "subtype": "", "label": "草稿输入", "icon": "📝", "color": "#64748b", "sort": 10},
    {"group": "工具", "hint": "（从草稿取稿）", "kind": "tool", "subtype": "condense", "label": "稿件精简", "icon": "✂️", "color": "#7c3aed", "sort": 20},
    {"group": "工具", "hint": "（从草稿取稿）", "kind": "tool", "subtype": "style_prompt", "label": "风格提取", "icon": "🎨", "color": "#7c3aed", "sort": 21},
    {"group": "工具", "hint": "（上传 PDF 提取）", "kind": "tool", "subtype": "pdf_extract", "label": "PDF 版面提取", "icon": "📄", "color": "#7c3aed", "sort": 22},
    {"group": "工具", "hint": "（从草稿策划选题）", "kind": "tool", "subtype": "topic_plan", "label": "新闻选题策划", "icon": "💡", "color": "#7c3aed", "sort": 23},
    {"group": "AI 改写", "hint": "（原稿 → TV/报刊稿）", "kind": "rewriter", "subtype": "tv_script", "label": "电视口播稿", "icon": "📺", "color": "#6366f1", "sort": 30},
    {"group": "AI 改写", "hint": "（原稿 → TV/报刊稿）", "kind": "rewriter", "subtype": "newspaper", "label": "报刊通稿", "icon": "📰", "color": "#6366f1", "sort": 31},
    {"group": "审稿", "hint": "（人工 或 AI）", "kind": "reviewer", "subtype": "", "label": "人工审定", "icon": "✅", "color": "#d97706", "sort": 40},
    {"group": "审稿", "hint": "（人工 或 AI）", "kind": "ai_reviewer", "subtype": "", "label": "AI 审稿", "icon": "🤖", "color": "#0891b2", "sort": 41},
    {"group": "新媒体转换", "hint": "（转成平台风格）", "kind": "transformer", "subtype": "wechat", "label": "公众号长文", "icon": "💬", "color": "#0ea5e9", "sort": 50},
    {"group": "新媒体转换", "hint": "（转成平台风格）", "kind": "transformer", "subtype": "weibo", "label": "微博文案", "icon": "🔥", "color": "#0ea5e9", "sort": 51},
    {"group": "新媒体转换", "hint": "（转成平台风格）", "kind": "transformer", "subtype": "douyin", "label": "抖音口播脚本", "icon": "🎬", "color": "#0ea5e9", "sort": 52},
    {"group": "新媒体转换", "hint": "（转成平台风格）", "kind": "transformer", "subtype": "xiaohongshu", "label": "小红书笔记", "icon": "📕", "color": "#0ea5e9", "sort": 53},
    {"group": "新媒体转换", "hint": "（转成平台风格）", "kind": "transformer", "subtype": "toutiao", "label": "头条新闻", "icon": "🗞️", "color": "#0ea5e9", "sort": 54},
    {"group": "成稿导出", "hint": "（终稿·复制发布）", "kind": "exporter", "subtype": "wechat", "label": "公众号长文", "icon": "📤", "color": "#16a34a", "sort": 60},
    {"group": "成稿导出", "hint": "（终稿·复制发布）", "kind": "exporter", "subtype": "weibo", "label": "微博文案", "icon": "📤", "color": "#16a34a", "sort": 61},
    {"group": "成稿导出", "hint": "（终稿·复制发布）", "kind": "exporter", "subtype": "douyin", "label": "抖音口播脚本", "icon": "📤", "color": "#16a34a", "sort": 62},
    {"group": "成稿导出", "hint": "（终稿·复制发布）", "kind": "exporter", "subtype": "xiaohongshu", "label": "小红书笔记", "icon": "📤", "color": "#16a34a", "sort": 63},
    {"group": "成稿导出", "hint": "（终稿·复制发布）", "kind": "exporter", "subtype": "toutiao", "label": "头条新闻", "icon": "📤", "color": "#16a34a", "sort": 64},
]

PROMPT_KEYS = list(PROMPTS.keys())   # tv_script/newspaper/wechat/weibo/douyin/xiaohongshu/toutiao/ai_review/condense/style_prompt


def _default_prompt_for(spec: dict) -> str:
    """节点的默认提示词：导出节点用 export_* 排版提示词，其余用格式提示词"""
    kind, subtype = spec.get("kind", ""), spec.get("subtype", "")
    if kind == "exporter" and subtype:
        return PROMPTS.get(f"export_{subtype}", "") or PROMPTS.get(subtype, "")
    return PROMPTS.get(subtype, "") or ""


def node_key(kind: str, subtype: str) -> str:
    return f"{kind}:{subtype}" if subtype else kind


async def seed_templates(db: AsyncSession) -> None:
    """首次启动把内置节点与提示词写入数据库（已存在则跳过，不覆盖管理员改动）"""
    existing_nodes = {(n.kind, n.subtype) for n in (await db.execute(select(NodeTemplate))).scalars()}
    for spec in BUILTIN_NODES:
        if (spec["kind"], spec["subtype"]) in existing_nodes:
            continue
        db.add(NodeTemplate(
            group=spec["group"], kind=spec["kind"], subtype=spec["subtype"], label=spec["label"],
            icon=spec.get("icon", ""), color=spec.get("color", "#64748b"), hint=spec.get("hint", ""),
            sort=spec.get("sort", 100), scope="global", enabled=True,
            prompt=_default_prompt_for(spec),
        ))
    # 纠正历史数据：导出节点的默认提示词曾被写成转换节点提示词
    exporters = (await db.execute(select(NodeTemplate).where(NodeTemplate.kind == "exporter"))).scalars().all()
    for t in exporters:
        want = _default_prompt_for({"kind": "exporter", "subtype": t.subtype})
        if want and t.prompt != want and (t.prompt or "") == PROMPTS.get(t.subtype, ""):
            t.prompt = want

    existing_prompts = {p.key for p in (await db.execute(select(PromptTemplate))).scalars()}
    for key in PROMPT_KEYS:
        if key in existing_prompts:
            continue
        db.add(PromptTemplate(key=key, name=FORMAT_LABELS.get(key, key), content=PROMPTS.get(key, ""),
                              scope="global", enabled=True))
    await db.commit()


async def effective_nodes(db: AsyncSession, user: User | None = None) -> list[dict]:
    """当前用户可见的节点库：全站启用项 + 自己的个人项（默认全站优先）"""
    rows = (await db.execute(select(NodeTemplate).where(NodeTemplate.enabled.is_(True)))).scalars().all()
    mine = {r.id for r in rows if r.scope == "user" and user and r.owner_id == user.id}
    items = [r for r in rows if r.scope == "global" or r.id in mine]
    items.sort(key=lambda r: (r.group, r.sort or 100, r.label or ""))
    return [{
        "id": r.id, "group": r.group, "kind": r.kind, "subtype": r.subtype, "label": r.label,
        "icon": r.icon, "color": r.color, "hint": r.hint, "sort": r.sort,
        "default_config": r.default_config or {}, "scope": r.scope,
    } for r in items]


async def effective_prompts(db: AsyncSession, user: User | None = None) -> dict[str, str]:
    """生效提示词：内置常量 → 全站模板（管理员维护，自动对所有人生效）

    说明：用户个人模板（scope=user）不自动生效，仅作为"我的模板库"由用户在节点里
    手动载入并保存到该节点（节点 config.prompt 优先级最高），避免个人历史模板意外覆盖全局规范。
    """
    result = dict(PROMPTS)
    rows = (await db.execute(select(PromptTemplate).where(PromptTemplate.enabled.is_(True)))).scalars().all()
    for r in rows:
        if r.scope == "global" and r.content:
            result[r.key] = r.content
    return result


async def resolve_prompt(db: AsyncSession, user: User | None, key: str) -> str | None:
    if not key:
        return None
    return (await effective_prompts(db, user)).get(key)
