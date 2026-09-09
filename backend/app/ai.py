"""DeepSeek AI 改写层：真实 API（OpenAI 兼容协议）+ 无 Key 时的模拟模式"""
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


async def rewrite(format_type: str, content: str, title: str = "") -> tuple[str, str]:
    """返回 (改写文本, 模型名)。未配置 DEEPSEEK_API_KEY 时走 mock，保证流程可演示。"""
    s = get_settings()
    if not s.deepseek_api_key:
        return _mock_rewrite(format_type, content, title), "mock(未配置Key)"
    prompt = PROMPTS.get(format_type)
    if not prompt:
        raise ValueError(f"不支持的格式: {format_type}")
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"标题/主题：{title or '（无）'}\n\n素材内容：\n{content}"},
    ]
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4000,
    }
    headers = {"Authorization": f"Bearer {s.deepseek_api_key}"}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(s.deepseek_base_url.rstrip("/") + "/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
    return text, "deepseek-chat"


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
