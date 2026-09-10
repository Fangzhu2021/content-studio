"""DeepSeek AI 层：改写 + 审稿（OpenAI 兼容协议）；无 Key 时模拟模式"""
import json
import time

import httpx

from .config import get_settings

# 各格式的改写要求（写进 system prompt）
PROMPTS = {
    "tv_script": "你是一名资深电视新闻编辑。请把提供的素材改写成电视新闻口播稿：先写适合主持人播报的导语，"
                 "再按时间/逻辑顺序组织正文，语言口语化、节奏明快，最后给一句收尾。只输出改写后的稿件正文，不要任何解释。",
    "newspaper": "你是一名报社通联编辑。请把素材改写成通讯社通稿：规范新闻结构（导语-主体-结尾），"
                 "事实准确、要素齐全（时间地点人物事件），行文书面、严谨。只输出稿件正文，不要任何解释。",
    "wechat": "你是一名公众号资深编辑。请把素材扩写成公众号深度长文：有吸引人的开篇、小标题分段、"
              "结论或行动引导，适合手机阅读。只输出 Markdown 正文，不要任何解释。",
    "weibo": "你是一名微博运营。请把素材改写为一条微博文案：140 字左右核心内容 + 2~3 个相关话题标签，"
             "自然不生硬。只输出最终文案。",
    "douyin": "你是一名短视频编导。请把素材改写为抖音口播脚本：含开头 3 秒钩子、正文口语化短句、结尾引导关注/互动。"
              "只输出脚本正文。",
    "xiaohongshu": "你是一名小红书博主/运营。请把素材改写为小红书笔记：吸睛标题式开头、分段+emoji 适度、"
                   "结尾话题标签。只输出笔记正文。",
    "toutiao": "你是一名头条号编辑。请把素材改写为头条新闻体：标题感开头、信息密度高、段落短、重点加粗。"
               "只输出正文。",
}

FORMAT_LABELS = {
    "tv_script": "电视口播稿", "newspaper": "报刊通稿", "wechat": "公众号长文",
    "weibo": "微博文案", "douyin": "抖音口播脚本", "xiaohongshu": "小红书笔记", "toutiao": "头条新闻",
}


DEFAULT_MODEL = "deepseek-chat"
AVAILABLE_MODELS = ["deepseek-chat", "deepseek-reasoner"]


async def rewrite(format_type: str, content: str, title: str = "",
                  custom_prompt: str | None = None, model: str | None = None,
                  style_hint: str | None = None) -> tuple[str, str, dict]:
    """返回 (改写文本, 模型名)。

    - custom_prompt：节点级自定义提示词（node.config.prompt），为空则用该格式的默认模板
    - model：节点级模型档位（node.config.model），默认 deepseek-chat
    - 未配置 DEEPSEEK_API_KEY 时走 mock，保证流程可演示
    """
    s = get_settings()
    if not s.deepseek_api_key:
        text = _mock_rewrite(format_type, content, title)
        return text, "mock(未配置Key)", _zero_usage(len(content or ""), len(text))
    prompt = (custom_prompt or "").strip() or PROMPTS.get(format_type)
    if not prompt:
        raise ValueError(f"不支持的格式: {format_type}")
    if style_hint and style_hint.strip():
        prompt = prompt + "\n\n【参考风格要求（由「风格提取」节点提供，请一并遵循）】\n" + style_hint.strip()
    use_model = (model or "").strip() or DEFAULT_MODEL
    if use_model not in AVAILABLE_MODELS:
        use_model = DEFAULT_MODEL
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"标题/主题：{title or '（无）'}\n\n素材内容：\n{content}"},
    ]
    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 8000,
    }
    headers = {"Authorization": f"Bearer {s.deepseek_api_key}"}
    text, usage = await _post_chat(s.deepseek_base_url.rstrip("/") + "/chat/completions", payload, headers)
    return text, use_model, usage


def _mock_rewrite(format_type: str, content: str, title: str) -> str:
    """模拟模式：仅做版式标注，不改变原文字面事实，明确标示模拟输出。"""
    label = FORMAT_LABELS.get(format_type, format_type)
    body = content.strip()
    if format_type == "tv_script":
        return (f"【电视口播稿 · 模拟模式】\n标题：{title}\n\n"
                f"【导语】{body[:80]}……\n\n【正文】\n{body}\n\n"
                f"【收尾】以上就是本次报道，感谢收看。")
    if format_type == "newspaper":
        return (f"【报刊通稿 · 模拟模式】\n标题：{title}\n\n"
                f"（本报讯）{body[:60]}……\n\n{body}\n\n"
                f"（完）")
    if format_type == "weibo":
        seg = body[:120]
        return f"【微博文案 · 模拟模式】\n{seg}…… #云阳身边事# #融媒体#"
    if format_type == "douyin":
        return (f"【抖音口播 · 模拟模式】\n（开头3秒）你知道吗，{body[:40]}……\n\n"
                f"{body}\n\n（结尾）觉得有用就点个关注，下期更精彩！")
    if format_type == "xiaohongshu":
        return f"【小红书笔记 · 模拟模式】\n{title}\n\n{body}\n\n#云阳 #内容工坊 #媒体"
    if format_type == "toutiao":
        return f"【头条新闻 · 模拟模式】\n{title}\n\n{body}\n\n（来源：云阳县融媒体中心）"
    # wechat / 兜底
    return (f"【{label} · 模拟模式】\n# {title}\n\n{body}\n\n"
            f"---\n（模拟模式：请在 backend/.env 配置 DEEPSEEK_API_KEY 后获得真实 AI 改写）")

# ---------------- AI 审稿 ----------------
REVIEW_PROMPT = (
    "你是一名务实的新闻审稿编辑，目标是放行可以发布的稿件、只拦下真正有问题的稿件。\n"
    "审阅要点：1) 有无与标题/正文自身明显矛盾或事实错误；2) 有无敏感、违规、夸大失实、主观臆断的表述；"
    "3) 有无影响理解的严重错别字或语病；4) 结构是否完整（有标题/导语/正文即可）。\n"
    "评分标准：90-100 可直接发布；70-89 有小瑕疵但可发布；50-69 有明显问题建议修改；50 以下存在严重问题。\n"
    "重要：不要因为细节不够充分（如未写明年份、未列全参与人员、篇幅长短）而打回；"
    "只有当存在上述 1)~4) 类的实质问题时才判 reject。\n"
    '严格只输出一个 JSON 对象，不要任何多余文字，格式：'
    '{"verdict": "pass" 或 "reject", "score": 0-100 的整数, '
    '"comment": "不超过 60 字的审稿意见；若 reject 请指出具体问题"}'
)
PROMPTS["ai_review"] = REVIEW_PROMPT
FORMAT_LABELS["ai_review"] = "AI 审稿"


async def ai_review(title: str, content: str,
                    custom_prompt: str | None = None,
                    model: str | None = None,
                    strict: bool = False) -> tuple[bool, str, str, dict]:
    """AI 审稿：返回 (是否通过, 审稿意见, 模型名)。无 Key 时模拟通过。"""
    s = get_settings()
    if not s.deepseek_api_key:
        return True, "【模拟模式】未配置 DeepSeek Key，默认通过。", "mock(未配置Key)", _zero_usage(len(content or ""), 0)
    prompt = (custom_prompt or "").strip() or REVIEW_PROMPT
    use_model = (model or "").strip() or DEFAULT_MODEL
    if use_model not in AVAILABLE_MODELS:
        use_model = DEFAULT_MODEL
    payload = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"标题：{title or '（无）'}\n\n稿件正文：\n{content}"},
        ],
        "temperature": 0.2,
        "max_tokens": 1000,
    }
    headers = {"Authorization": f"Bearer {s.deepseek_api_key}"}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(s.deepseek_base_url.rstrip("/") + "/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        raw = (await _post_chat(s.deepseek_base_url.rstrip("/") + "/chat/completions", payload,
                                {"Authorization": f"Bearer {s.deepseek_api_key}"}))[0]

    data = None
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start:end + 1])
    except Exception:
        data = None

    if not isinstance(data, dict):
        return True, f"（AI 返回格式异常，已默认通过，建议人工抽查）{raw[:80]}", use_model, _zero_usage(len(content or ""), len(raw))

    verdict = str(data.get("verdict", "")).strip().lower()
    try:
        score = int(data.get("score", 100))
    except Exception:
        score = 100
    comment = str(data.get("comment", "")).strip()

    reject_words = ("reject", "rejected", "打回", "fail", "failed")
    pass_words = ("pass", "passed", "通过", "approve", "approved")
    is_reject = verdict in reject_words
    is_pass = verdict in pass_words

    if strict:
        # 严格模式：模型判打回或评分偏低即打回
        passed = (not is_reject) and score >= 80
    else:
        # 默认宽松：只有模型明确判 reject 且存在严重问题（评分 < 50）才打回，避免误伤可发布稿件
        passed = not (is_reject and score < 50)
        if is_pass and score >= 50:
            passed = True
    tag = "严格" if strict else "标准"
    return passed, f"{comment}（评分 {score}·{tag}）", use_model, _zero_usage(len(content or ""), len(raw))

# ---------------- 工具节点：稿件精简 / 风格提取 ----------------
CONDENSE_PROMPT = (
    "你是一名新闻编辑助手。请把下面的稿件精简为「精简稿」：\n"
    "1) 目标篇幅约为原稿的 1/3~1/2；若原稿本身较短（不足 300 字），则只删除冗余、套话与重复表述，保留全部核心事实，不必强行压缩；\n"
    "2) 必须保留：时间、地点、主体、事件、关键数据与明确要求；\n"
    "3) 保留原标题；\n"
    "4) 语句通顺、可直接使用。只输出精简后的稿件正文，不要任何解释或前后缀说明。"
)
STYLE_PROMPT = (
    "你是一名文体分析专家。请阅读下面的稿件，提炼出可直接复用的『写作风格提示词』，"
    "覆盖：语气与视角、句式节奏、段落结构、用词偏好、开头与结尾手法、标点/格式习惯。"
    "输出要求：以「你是一位……」开头的、可直接粘贴到其他 AI 节点使用的提示词，不超过 300 字，"
    "不要复述原文的具体事实内容。只输出提示词本身。"
)
PROMPTS["condense"] = CONDENSE_PROMPT
PROMPTS["style_prompt"] = STYLE_PROMPT
FORMAT_LABELS["condense"] = "稿件精简"
FORMAT_LABELS["style_prompt"] = "风格提取"

TOOL_KINDS = ("condense", "style_prompt")


async def tool_run(kind: str, title: str, content: str,
                   custom_prompt: str | None = None,
                   model: str | None = None,
                   ratio: float | None = None) -> tuple[str, str, dict]:
    """工具节点：kind = condense（稿件精简）| style_prompt（风格提取）。"""
    if kind not in TOOL_KINDS:
        raise ValueError(f"不支持的工具类型: {kind}")
    s = get_settings()
    if not s.deepseek_api_key:
        text = _mock_tool(kind, title, content)
        return text, "mock(未配置Key)", _zero_usage(len(content or ""), len(text))
    prompt = (custom_prompt or "").strip() or PROMPTS[kind]
    use_model = (model or "").strip() or DEFAULT_MODEL
    if use_model not in AVAILABLE_MODELS:
        use_model = DEFAULT_MODEL
    if kind == "condense" and ratio:
        try:
            pct = max(10, min(90, int(float(ratio) * 100)))
            prompt = prompt + f"\n（本次要求：压缩到原稿约 {pct}% 的篇幅，请严格遵守）"
        except Exception:
            pass
    payload = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"标题：{title or '（无）'}\n\n稿件正文：\n{content}"},
        ],
        "temperature": 0.4,
        "max_tokens": 4000,
    }
    headers = {"Authorization": f"Bearer {s.deepseek_api_key}"}
    text, usage = await _post_chat(s.deepseek_base_url.rstrip("/") + "/chat/completions", payload, headers)

    # 精简节点：首轮若超出目标字数较多，做 1~2 次强制压缩到明确字数上限
    if kind == "condense" and ratio:
        try:
            target = max(50, int(len(content or "") * float(ratio)))
        except Exception:
            target = None
        for _ in range(2):
            if not target or len(text) <= target * 1.15:
                break
            try:
                text, extra = await _compress_to(text, target, use_model, s.deepseek_api_key, s.deepseek_base_url)
                usage["prompt_tokens"] += extra["prompt_tokens"]
                usage["completion_tokens"] += extra["completion_tokens"]
                usage["duration_ms"] += extra["duration_ms"]
            except Exception:
                break
    usage["output_chars"] = len(text)
    return text, use_model, usage


def _mock_tool(kind: str, title: str, content: str) -> str:
    body = (content or "").strip()
    if kind == "condense":
        keep = body[: max(60, int(len(body) / 3))]
        return f"【精简稿 · 模拟模式】\n{title}\n\n{keep}……"
    return ("【风格提示词 · 模拟模式】\n你是一位语言平实、结构清晰的新闻编辑："
            "开篇直陈核心事实，中段按时间顺序展开，多用短句，结尾给出明确结论。（配置 DeepSeek Key 后为真实提炼结果）")

async def _compress_to(text: str, target: int, model: str, api_key: str, base_url: str) -> str:
    """二次压缩：把 text 压到不超过 target 个字符（模型首轮往往删得不够）。"""
    sys_prompt = (
        f"请把下面这段文字改写为 {target} 个字符左右的精简稿（可略多略少，但请尽量贴近）："
        "只保留最重要的事实（谁、何时、何地、何事、关键数据），删去所有修饰、套话与次要细节；"
        "语句通顺，可直接使用。只输出精简后的正文，不要标题以外的任何说明。"
    )
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": text}],
        "temperature": 0.3,
        "max_tokens": 2000,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    text, _u = await _post_chat(base_url.rstrip("/") + "/chat/completions", payload, headers)
    return text, _u

def _usage_of(data: dict, elapsed_ms: int, prompt_chars: int, output_chars: int) -> dict:
    u = (data or {}).get("usage") or {}
    return {
        "prompt_tokens": int(u.get("prompt_tokens") or 0),
        "completion_tokens": int(u.get("completion_tokens") or 0),
        "duration_ms": int(elapsed_ms),
        "prompt_chars": int(prompt_chars),
        "output_chars": int(output_chars),
    }


def _zero_usage(prompt_chars: int, output_chars: int) -> dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "duration_ms": 0,
            "prompt_chars": int(prompt_chars), "output_chars": int(output_chars)}


async def _post_chat(url: str, payload: dict, headers: dict) -> tuple[str, dict]:
    """统一调用入口，返回 (文本, usage)"""
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    elapsed = int((time.time() - t0) * 1000)
    text = data["choices"][0]["message"]["content"].strip()
    pchars = sum(len(m.get("content", "")) for m in payload.get("messages", []))
    return text, _usage_of(data, elapsed, pchars, len(text))

# ---------------- 成稿导出：排版处理（可粘贴进秀米/微信编辑器） ----------------
EXPORT_PROMPTS = {
    "wechat": (
        "你是一名公众号排版编辑。请把下面的稿件输出为「可直接粘贴进秀米 / 微信编辑器」的富文本 HTML 片段：\n"
        "1) 只输出 HTML 片段本身：不要 markdown 标记、不要 ```html 代码围栏、不要 <html>/<body> 标签；\n"
        "2) 所有样式必须写成内联 style：不要 class、不要 <style> 标签、不要外链 CSS；只使用微信编辑器支持的属性："
        "font-size、color、line-height、text-align、font-weight、background-color、padding、margin、border-radius、border-left；\n"
        "3) 结构规范：主标题（居中、加粗、约 22px）→ 导语（引用块：浅灰底 #f7f7f7、左侧 3px 主色竖线、内边距 12px）"
        "→ 正文分段（16px、行高 1.75、段间距 1em）→ 小标题（加粗、左侧 4px 主色竖线、内边距 6px 10px）"
        "→ 要点用 <p> 加「•」符号（避免 <ul> 被编辑器吞样式）→ 结尾一句引导关注；\n"
        "4) 段落要短，每段 1~3 句；正文标点统一用中文标点；数字与单位之间不要多余空格；\n"
        "5) 只做排版与轻微润色：不得新增事实、不得改动数字、人名、机构名等专有信息；\n"
        "6) 主色用 #c0392b，需要强调的词用 <strong> 并配主色。"
    ),
    "xiaohongshu": (
        "你是一名小红书笔记编辑。请把下面的稿件改写为「可直接粘贴进小红书编辑框发布」的笔记：\n"
        "1) 纯文本输出：小红书不解析 Markdown / HTML，严禁出现 ** 、## 、``` 、<p> 、- 列表 等符号或标签；"
        "可用 emoji 与「｜」分隔符；\n"
        "2) 标题：第一行写标题，不超过 20 字，信息前置并带 1~2 个 emoji（信息流以标题为主，必须抓人）；\n"
        "3) 正文：第二行起分段，每段 1~3 行、段间空行；用 ✨ / 📌 / ✅ / 💡 等 emoji 做小标题或要点符号；"
        "第一人称口语化、有现场感，像跟朋友分享，可用「收藏起来」「亲测」「码住」这类语感；\n"
        "4) 篇幅：正文 300~600 字，不少于 200 字，保证有内容感；\n"
        "5) 话题标签：正文之后另起一行给 5~8 个话题，格式为 #话题（一个 # 开头，不要写成 #话题#），"
        "优先本地＋垂类＋大流量词（如 #云阳 #重庆周边 #防汛知识）；\n"
        "6) 结尾一句互动引导（如「你们那边怎么做的？评论区聊聊」），可 @官方账号；\n"
        "7) 不写外链与联系方式；只做改写与排版：不得新增事实、不得改动数字、人名、机构名。\n"
        "只输出笔记本身（标题 + 正文 + 话题行），不要任何解释。"
    ),
    "toutiao": (
        "你是一名头条号编辑。请把下面的稿件整理为「可直接粘贴进头条号编辑器发布」的正文：\n"
        "1) 纯文本输出：头条编辑器不解析 Markdown，严禁出现 ** 、## 、``` 、<p> 等符号或标签；"
        "小标题与层次用【】或「一、二、」等中文序号表达；\n"
        "2) 结构：第一行为导语，概括核心事实（40~80 字，独立成段）→ 主体分段（每段 2~3 句）"
        "→ 需要分层时用【小标题】→ 结尾交代后续安排或信息来源；\n"
        "3) 语体：第三人称客观书面语，不用第一人称口吻，不用夸张形容词与主观感叹；\n"
        "4) 篇幅：600~1200 字，段落要短（手机端每段 2~3 行）；\n"
        "5) 引流：结尾加一句引导（如「欢迎在评论区留言讨论」「关注本账号，第一时间获取云阳本地资讯」）；"
        "文末另起一行给 1~3 个 #话题#（前后带 #）；\n"
        "6) 只做改写与排版：不得新增事实、不得改动数字、人名、机构名等专有信息；不写外链与联系方式。\n"
        "只输出可直接发布的正文（含结尾引导与话题行），不要任何解释。"
    ),
    "weibo": (
        "你是一名微博运营编辑。请把下面的稿件改写为「可直接粘贴进微博编辑框发布」的微博文案：\n"
        "1) 纯文本输出：微博不解析 Markdown / HTML，严禁出现 ** 、## 、``` 、<p> 、- 列表等符号或标签；\n"
        "2) 结构（用换行分隔，段与段之间空一行）：\n"
        "   · 第 1 行＝钩子：不超过 30 字，信息流只展示开头，要能抓住本地读者；\n"
        "   · 中段＝核心事实：时间、地点、主体、事件、关键数据，每段 1~2 句、短句为主；\n"
        "   · 末段＝互动引导：如「你怎么看？评论区聊聊」「转发让更多人看到」；\n"
        "3) 话题引流：正文之后另起一行，给出 3~4 个话题标签，格式必须是 #话题#（前后都带 #，微博会转成可点击话题）；"
        "优先本地与垂类流量词（例如 #重庆身边事# #云阳# #防汛#），其中可含 1 个政务或行业话题；\n"
        "4) 账号引流：结尾可加 @官方账号 引导；若稿件未给出账号名，统一写 @云阳县融媒体中心；\n"
        "5) 表情：最多 2~4 个 emoji 点缀，不要堆砌；\n"
        "6) 篇幅：正文控制在 180 字以内（话题行不计），便于在信息流完整展示；\n"
        "7) 只做改写与排版：不得新增事实、不得改动数字、人名、机构名等专有信息。\n"
        "只输出微博文案本身（正文 + 话题行），不要任何解释、标题或 markdown 标记。"
    ),
    "douyin": (
        "你是一名短视频编导。请把下面的稿件整理为「可直接粘贴使用的抖音发布物料」，分两部分输出：\n"
        "【发布文案】\n"
        "· 第一行＝视频标题：不超过 25 字，口语化、带钩子或悬念（信息流只显示开头）；\n"
        "· 第二行＝一句补充说明（可选，不超过 30 字）；\n"
        "· 最后一行＝3~5 个话题，格式为 #话题（一个 # 开头，不要写成 #话题# —— 抖音是单井号）；优先本地与垂类流量词；\n"
        "【口播脚本】\n"
        "· 按镜号分镜，每镜一行，格式：镜头1｜画面：……｜口播：……｜字幕：……；\n"
        "· 前三秒必须给出钩子（提问／悬念／冲突）；总时长 30~60 秒；口播用短句口语，避免书面语与长定语；\n"
        "· 每个镜头口播不超过 2 句；结尾引导互动（如「你怎么看？评论区聊聊」「关注我，看更多云阳现场」）。\n"
        "禁止 Markdown 标记（** 、## 、- ）与 HTML 标签，全文纯文本 + 【】小标题；\n"
        "只做改写与排版：不得新增事实、不得改动数字、人名、机构名。只输出上述两部分，不要解释。"
    ),
}
for _k, _v in EXPORT_PROMPTS.items():
    PROMPTS[f"export_{_k}"] = _v
    FORMAT_LABELS[f"export_{_k}"] = f"{FORMAT_LABELS.get(_k, _k)}排版成稿"

EXPORT_HTML_KINDS = ("wechat",)


async def typeset(subtype: str, title: str, content: str,
                  custom_prompt: str | None = None,
                  model: str | None = None) -> tuple[str, str, dict]:
    """成稿导出：把稿件排版为可粘贴的成稿（公众号输出内联样式 HTML）。"""
    s = get_settings()
    key = f"export_{subtype}"
    if not s.deepseek_api_key:
        return _mock_typeset(subtype, title, content), "mock(未配置Key)", _zero_usage(len(content or ""), len(content or ""))
    prompt = (custom_prompt or "").strip() or PROMPTS.get(key) or PROMPTS.get("wechat")
    use_model = (model or "").strip() or DEFAULT_MODEL
    if use_model not in AVAILABLE_MODELS:
        use_model = DEFAULT_MODEL
    payload = {
        "model": use_model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"标题：{title or '（无）'}\n\n待排版稿件：\n{content}"},
        ],
        "temperature": 0.3,
        "max_tokens": 8000,
    }
    headers = {"Authorization": f"Bearer {s.deepseek_api_key}"}
    text, usage = await _post_chat(s.deepseek_base_url.rstrip("/") + "/chat/completions", payload, headers)
    # 去掉可能被包上的 markdown 代码围栏
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    usage["output_chars"] = len(text)
    return text, use_model, usage


def _mock_typeset(subtype: str, title: str, content: str) -> str:
    body = (content or "").strip()
    if subtype in EXPORT_HTML_KINDS:
        paras = "".join(
            f'<p style="font-size:16px;line-height:1.75;margin:1em 0;color:#333;">{ln.strip()}</p>'
            for ln in body.splitlines() if ln.strip()
        )
        return (f'<h1 style="font-size:22px;font-weight:700;text-align:center;margin:0 0 16px;color:#222;">{title}</h1>'
                f'{paras}'
                '<p style="font-size:14px;color:#888;text-align:center;margin-top:24px;">'
                '（模拟模式输出 · 配置 DeepSeek Key 后为真实排版）</p>')
    return f"{title}\n\n{body}"
