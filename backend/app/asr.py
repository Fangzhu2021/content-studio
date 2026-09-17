"""本地语音识别（ASR）服务客户端。

默认对接本机 Audio8 ASR 服务（sherpa-onnx + SenseVoice，127.0.0.1:8030）：
音频只在服务器内部流转，**不出内网**。

管理员可在「系统设置 · 语音识别服务」里改地址 / Token / 模型；
若填的不是内网地址，必须显式打开「允许音频出内网」，否则拒绝调用（防止误把
未公开的采访素材传到公网）。
"""
from __future__ import annotations

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import get_setting

DEFAULT_BASE_URL = "http://127.0.0.1:8030"
SUBMIT_TIMEOUT = httpx.Timeout(900.0, connect=10.0)      # 上传大文件要留足时间
QUERY_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


async def get_asr_config(db: AsyncSession) -> dict:
    base = str(await get_setting(db, "asr_base_url", "") or "").strip() or DEFAULT_BASE_URL
    token = str(await get_setting(db, "asr_api_key", "") or "").strip()
    label = str(await get_setting(db, "asr_model", "") or "").strip() or "sensevoice-small"
    allow_cloud = bool(await get_setting(db, "asr_allow_cloud", False))
    try:
        price = float(await get_setting(db, "asr_price_per_hour", 0) or 0)
    except (TypeError, ValueError):
        price = 0.0
    return {"base_url": base.rstrip("/"), "api_key": token, "model": label,
            "allow_cloud": allow_cloud, "price_per_hour": price, "is_local": is_private_url(base)}


def is_private_url(url: str) -> bool:
    """判断是否内网地址（127./10./172.16-31./192.168./localhost）"""
    host = url.split("//")[-1].split("/")[0].split(":")[0].strip().lower()
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        return a == 10 or a == 127 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
    return False


def _headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}


def _guard(cfg: dict) -> None:
    if not cfg["is_local"] and not cfg["allow_cloud"]:
        raise HTTPException(400, "语音识别服务地址不是内网地址，且未在系统设置里允许音频出内网")


async def service_health(db: AsyncSession) -> dict:
    cfg = await get_asr_config(db)
    url = f"{cfg['base_url']}/health"
    try:
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(cfg))
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:                     # noqa: BLE001
        return {"ok": False, "base_url": cfg["base_url"], "is_local": cfg["is_local"],
                "message": f"无法连接语音识别服务：{exc}"}
    return {"ok": bool(data.get("ok")), "base_url": cfg["base_url"], "is_local": cfg["is_local"],
            "model": data.get("model", ""), "threads": data.get("threads"),
            "queued": data.get("queued"), "running": data.get("running", []),
            "message": "服务正常" if data.get("ok") else "服务可达但模型未就绪"}


async def submit_job(db: AsyncSession, path: str, filename: str) -> dict:
    """把音频文件提交给 ASR 服务，返回 {job_id, ...}"""
    cfg = await get_asr_config(db)
    _guard(cfg)
    url = f"{cfg['base_url']}/jobs"
    try:
        async with httpx.AsyncClient(timeout=SUBMIT_TIMEOUT) as client:
            with open(path, "rb") as fh:
                resp = await client.post(url, headers=_headers(cfg),
                                         files={"file": (filename, fh, "application/octet-stream")})
            if resp.status_code >= 400:
                raise HTTPException(502, f"语音识别服务拒绝任务（HTTP {resp.status_code}）：{resp.text[:200]}")
            return resp.json()
    except HTTPException:
        raise
    except Exception as exc:                     # noqa: BLE001
        raise HTTPException(503, f"无法连接本地语音识别服务：{exc}")


async def job_status(db: AsyncSession, job_id: str) -> dict:
    cfg = await get_asr_config(db)
    _guard(cfg)
    url = f"{cfg['base_url']}/jobs/{job_id}"
    try:
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(cfg))
            if resp.status_code == 404:
                raise HTTPException(404, "转写任务已过期或不存在")
            resp.raise_for_status()
            return resp.json()
    except HTTPException:
        raise
    except Exception as exc:                     # noqa: BLE001
        raise HTTPException(503, f"查询转写进度失败：{exc}")


async def cancel_job(db: AsyncSession, job_id: str) -> dict:
    cfg = await get_asr_config(db)
    url = f"{cfg['base_url']}/jobs/{job_id}"
    try:
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT) as client:
            resp = await client.delete(url, headers=_headers(cfg))
            if resp.status_code == 404:
                return {"status": "gone"}
            resp.raise_for_status()
            return resp.json()
    except Exception:                            # noqa: BLE001
        return {"status": "unknown"}
