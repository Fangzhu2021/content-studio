"""DeepSeek AI 层：改写 + 审稿（OpenAI 兼容协议）；无 Key 时模拟模式"""
import json

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
                  style_hint: str | None = None) -> tuple[str, str]:
    """返回 (改写文本, 模型名)。

    - custom_prompt：节点级自定义提示词（node.config.prompt），为空则用该格式的默认模板
    - model：节点级模型档位（node.config.model），默认 deepseek-chat
    - 未配置 DEEPSEEK_API_KEY 时走 mock，保证流程可演示
    """
    s = get_settings()
    if not s.deepseek_api_key:
        return _mock_rewrite(format_type, content, title), "mock(未配置Key)"
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
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(s.deepseek_base_url.rstrip("/") + "/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
    return text, use_model


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
                    strict: bool = False) -> tuple[bool, str, str]:
    """AI 审稿：返回 (是否通过, 审稿意见, 模型名)。无 Key 时模拟通过。"""
    s = get_settings()
    if not s.deepseek_api_key:
        return True, "【模拟模式】未配置 DeepSeek Key，默认通过。", "mock(未配置Key)"
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
        raw = resp.json()["choices"][0]["message"]["content"].strip()

    data = None
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start:end + 1])
    except Exception:
        data = None

    if not isinstance(data, dict):
        return True, f"（AI 返回格式异常，已默认通过，建议人工抽查）{raw[:80]}", use_model

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
    return passed, f"{comment}（评分 {score}·{tag}）", use_model

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
                   ratio: float | None = None) -> tuple[str, str]:
    """工具节点：kind = condense（稿件精简）| style_prompt（风格提取）。"""
    if kind not in TOOL_KINDS:
        raise ValueError(f"不支持的工具类型: {kind}")
    s = get_settings()
    if not s.deepseek_api_key:
        return _mock_tool(kind, title, content), "mock(未配置Key)"
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
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(s.deepseek_base_url.rstrip("/") + "/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()

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
                text = await _compress_to(text, target, use_model, s.deepseek_api_key, s.deepseek_base_url)
            except Exception:
                break
    return text, use_model


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
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(base_url.rstrip("/") + "/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
