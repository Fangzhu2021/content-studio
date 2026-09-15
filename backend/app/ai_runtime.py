"""AI 运行配置：优先取「管理后台 · 系统设置」里填的值，回落服务器 .env。

- 管理后台保存后立即刷新缓存，因此改 Key / 模型不需要重启服务
- Key 只在这里进出，接口从不回传原文（只回传掩码与来源）
"""
from .audit import get_setting
from .config import get_settings

FALLBACK_MODEL = "standard"     # 中性别名；真实模型名只存在于后端实现里
_cache: dict | None = None


def _from_env() -> dict:
    s = get_settings()
    key = (s.deepseek_api_key or "").strip()
    return {"api_key": key, "base_url": (s.deepseek_base_url or "").rstrip("/"),
            "default_model": FALLBACK_MODEL, "key_from": "env" if key else "none",
            "base_from": "env"}


async def load_ai_config(db) -> dict:
    """从数据库读取管理后台配置（缺省项回落 .env）并刷新进程内缓存。"""
    global _cache
    env = _from_env()
    key = str(await get_setting(db, "ai_api_key", "") or "").strip()
    base = str(await get_setting(db, "ai_base_url", "") or "").strip()
    model = str(await get_setting(db, "ai_default_model", FALLBACK_MODEL) or FALLBACK_MODEL).strip()
    _cache = {
        "api_key": key or env["api_key"],
        "base_url": (base or env["base_url"]).rstrip("/"),
        "default_model": model or FALLBACK_MODEL,
        "key_from": "admin" if key else env["key_from"],
        "base_from": "admin" if base else env["base_from"],
    }
    return _cache


def ai_config() -> dict:
    """同步读取当前生效配置（未初始化时回落 .env）。"""
    global _cache
    if _cache is None:
        _cache = _from_env()
    return _cache


def mask_key(key: str | None) -> str:
    """掩码展示：sk-••••••abcd"""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "•" * len(k)
    return f"{k[:3]}{'•' * 6}{k[-4:]}"
