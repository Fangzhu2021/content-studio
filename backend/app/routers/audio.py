"""录音转文字：上传音频 → 本机 ASR 服务异步转写 → 生成稿件供下游节点使用。

设计要点
- 音频文件落在项目上传目录，删除节点/项目时会一起清理
- 转写是**异步任务**：接口立即返回，后台协程轮询进度并写回节点（WS 实时推送）
- 后端重启也能自愈：前端下次查询时若发现任务仍在跑，会自动重新挂上监听
- 台账（run_logs）与用量（ai_usage）沿用既有口径，额外记录音频秒数
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import asr
from ..audit import log as audit_log
from ..db import async_session, get_db
from ..deps import get_current_user
from ..models import CanvasNode, Project, Revision, RunLog, User
from ..paths import UPLOAD_ROOT
from ..usage import record_usage
from ..ws import manager

router = APIRouter()

MAX_MB = 200
AUDIO_KIND = "audio_transcribe"
ASR_MODEL_TAG = "sensevoice-small"
ALLOWED_EXT = {".mp3", ".m4a", ".wav", ".aac", ".amr", ".ogg", ".oga", ".opus", ".flac",
               ".wma", ".3gp", ".mp4", ".mov", ".mkv", ".aiff", ".caf"}
POLL_SECONDS = 2.0
MAX_WATCH_SECONDS = 4 * 3600          # 兜底：最长监听 4 小时
MAX_QUERY_ERRORS = 5                  # 连续查询失败次数上限

_WATCHERS: dict[str, asyncio.Task] = {}


# ---------------------------------------------------------------- 工具
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audio_dir(node: CanvasNode) -> Path:
    d = UPLOAD_ROOT / node.project_id / node.id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audio_meta(node: CanvasNode) -> dict:
    cfg = node.config if isinstance(node.config, dict) else {}
    return dict(cfg.get("audio") or {})


def _save_meta(node: CanvasNode, **changes) -> dict:
    cfg = dict(node.config or {})
    meta = dict(cfg.get("audio") or {})
    meta.update(changes)
    cfg["audio"] = meta
    node.config = cfg
    return meta


def _title_from(text: str, filename: str) -> str:
    """标题：优先取转写文本的第一句话（更像稿件），否则用文件名"""
    first = re.split(r"[。！？!?\n]", (text or "").strip())[0].strip()
    first = re.sub(r"\s+", " ", first)
    if 4 <= len(first) <= 40:
        return first
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename or "").strip()
    return (stem or "录音转写")[:40]


async def _owned_audio_node(db: AsyncSession, nid: str, user: User) -> CanvasNode:
    node = await db.get(CanvasNode, nid)
    if not node:
        raise HTTPException(404, "节点不存在")
    project = await db.get(Project, node.project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "项目不存在")
    if not (node.type == "tool" and node.subtype == AUDIO_KIND):
        raise HTTPException(400, "该节点不是录音转文字节点")
    return node


def _file_path(node: CanvasNode, meta: dict | None = None) -> Path | None:
    m = meta if meta is not None else _audio_meta(node)
    name = m.get("stored_name") or m.get("filename")
    if not name:
        return None
    p = _audio_dir(node) / name
    return p if p.exists() else None


# ---------------------------------------------------------------- 转写任务
async def start_transcription(db: AsyncSession, node: CanvasNode, user: User,
                              run_id: str | None = None, trigger: str = "manual") -> dict:
    """提交转写任务（若已在跑则直接返回当前状态）"""
    meta = _audio_meta(node)
    path = _file_path(node, meta)
    if path is None:
        raise HTTPException(400, "请先上传录音文件")

    job_id = meta.get("job_id")
    if job_id and meta.get("status") in ("queued", "running"):
        ensure_watcher(node.id, job_id, user.id, run_id, node.project_id)
        return {"node_id": node.id, "status": "running", "job_id": job_id,
                "progress": meta.get("progress", 0.0), "message": "转写进行中，请稍候…"}

    job = await asr.submit_job(db, str(path), meta.get("filename") or path.name)
    _save_meta(node, status="queued", job_id=job.get("job_id", ""), progress=0.0, error="",
               started_at=_now(), trigger=trigger, run_id=run_id or "")
    node.status = "running"
    node.error = ""
    await db.commit()
    await manager.broadcast(node.project_id, {"type": "node_status", "node_id": node.id,
                                              "status": "running", "error": ""})
    ensure_watcher(node.id, job["job_id"], user.id, run_id, node.project_id)
    return {"node_id": node.id, "status": "running", "job_id": job["job_id"],
            "progress": 0.0, "message": "已提交转写任务"}


def ensure_watcher(node_id: str, job_id: str, user_id: str, run_id: str | None,
                   project_id: str) -> None:
    task = _WATCHERS.get(node_id)
    if task and not task.done():
        return
    _WATCHERS[node_id] = asyncio.create_task(
        _watch(node_id, job_id, user_id, run_id, project_id))


async def _watch(node_id: str, job_id: str, user_id: str, run_id: str | None,
                 project_id: str) -> None:
    """轮询 ASR 服务：更新进度 → 完成后写稿件、用量与台账"""
    started = time.time()
    errors = 0
    last_progress = -1.0
    try:
        while time.time() - started < MAX_WATCH_SECONDS:
            await asyncio.sleep(POLL_SECONDS)
            try:
                async with async_session() as db:
                    st = await asr.job_status(db, job_id)
                errors = 0
            except Exception:                              # noqa: BLE001
                errors += 1
                if errors >= MAX_QUERY_ERRORS:
                    await _finish_failed(node_id, run_id, project_id, "无法查询转写进度（服务异常）")
                    return
                continue

            status = st.get("status")
            progress = float(st.get("progress") or 0.0)
            if abs(progress - last_progress) >= 0.01 or status in ("done", "error", "canceled"):
                last_progress = progress
                await _update_progress(node_id, project_id, st)

            if status == "done":
                await _finish_done(node_id, run_id, project_id, user_id, st)
                return
            if status in ("error", "canceled"):
                await _finish_failed(node_id, run_id, project_id,
                                     st.get("error") or ("任务已取消" if status == "canceled" else "转写失败"))
                return
        await _finish_failed(node_id, run_id, project_id, "转写超时（超过 4 小时未完成）")
    except asyncio.CancelledError:                          # pragma: no cover
        raise
    except Exception as exc:                                # noqa: BLE001
        await _finish_failed(node_id, run_id, project_id, f"转写监听异常：{exc}")
    finally:
        _WATCHERS.pop(node_id, None)


async def _update_progress(node_id: str, project_id: str, st: dict) -> None:
    async with async_session() as db:
        node = await db.get(CanvasNode, node_id)
        if not node:
            return
        _save_meta(node, status="running", progress=float(st.get("progress") or 0.0),
                   segments_done=st.get("segments_done", 0), segments_total=st.get("segments_total", 0),
                   duration_s=st.get("duration_s", 0), elapsed_s=st.get("elapsed_s", 0),
                   chars=st.get("chars", 0))
        if node.status != "running":
            node.status = "running"
        await db.commit()
    await manager.broadcast(project_id, {"type": "node_status", "node_id": node_id, "status": "running",
                                         "progress": float(st.get("progress") or 0.0),
                                         "chars": st.get("chars", 0), "error": ""})


async def _finish_done(node_id: str, run_id: str | None, project_id: str, user_id: str,
                       st: dict) -> None:
    text = (st.get("text") or "").strip()
    async with async_session() as db:
        node = await db.get(CanvasNode, node_id)
        if not node:
            return
        meta = _audio_meta(node)
        cfg = await asr.get_asr_config(db)
        duration = float(st.get("duration_s") or 0)
        if not text:
            _save_meta(node, status="failed", error="没有识别到任何语音内容（可能全是静音或噪声）")
            node.status = "failed"
            node.error = "没有识别到任何语音内容"
            await db.commit()
            await manager.broadcast(project_id, {"type": "node_status", "node_id": node_id,
                                                 "status": "failed", "error": node.error})
            return

        rev = Revision(project_id=project_id, node_id=node_id,
                       title=_title_from(text, meta.get("filename") or ""),
                       content=text, format_type="audio_transcript",
                       status="draft", model=ASR_MODEL_TAG)
        db.add(rev)
        await db.flush()
        _save_meta(node, status="done", progress=1.0, chars=len(text), duration_s=duration,
                   elapsed_s=st.get("elapsed_s", 0), rtf=st.get("rtf", 0),
                   revision_id=rev.id, finished_at=_now(), error="")
        node.status = "done"
        node.error = ""
        await db.commit()

        user = await db.get(User, user_id)
        await record_usage(db, user=user, kind="asr", model=ASR_MODEL_TAG,
                           prompt_chars=int(duration), output_chars=len(text),
                           duration_ms=int(float(st.get("elapsed_s") or 0) * 1000),
                           project_id=project_id, node_id=node_id, audio_seconds=int(duration))
        if run_id:
            run = await db.get(RunLog, run_id)
            if run:
                run.status = "ok"
                run.output_revision_id = rev.id
                run.output_chars = len(text)
                run.output_preview = text[:500]
                run.model = ASR_MODEL_TAG
                run.duration_ms = int(float(st.get("elapsed_s") or 0) * 1000)
                run.params = {**(run.params or {}), "audio_seconds": round(duration, 1),
                              "rtf": st.get("rtf"), "segments": st.get("segments_total"),
                              "asr_model": cfg["model"], "asr_local": cfg["is_local"]}
                await db.commit()

    await manager.broadcast(project_id, {"type": "node_status", "node_id": node_id, "status": "done",
                                         "error": "", "chars": len(text)})
    await audit_log_db(audit_action="audio_transcribe_done", project_id=project_id, node_id=node_id)


async def _finish_failed(node_id: str, run_id: str | None, project_id: str, error: str) -> None:
    async with async_session() as db:
        node = await db.get(CanvasNode, node_id)
        if not node:
            return
        _save_meta(node, status="failed", error=error[:200])
        node.status = "failed"
        node.error = error[:200]
        await db.commit()
        if run_id:
            run = await db.get(RunLog, run_id)
            if run:
                run.status = "failed"
                run.error = error[:500]
                await db.commit()
    await manager.broadcast(project_id, {"type": "node_status", "node_id": node_id,
                                         "status": "failed", "error": error[:200]})


async def audit_log_db(*, audit_action: str, project_id: str, node_id: str) -> None:
    try:
        async with async_session() as db:
            await audit_log(db, action=audit_action, target_type="node", target_id=node_id,
                            detail={"project_id": project_id})
    except Exception:                                    # noqa: BLE001
        pass


# ---------------------------------------------------------------- 接口
@router.post("/nodes/{nid}/audio")
async def upload_audio(nid: str, file: UploadFile = File(...),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    node = await _owned_audio_node(db, nid, user)
    name = file.filename or "recording.m4a"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的音频格式：{ext or '未知'}（支持 mp3/m4a/wav/aac/amr/ogg/flac 等）")
    safe = re.sub(r"[^\w\u4e00-\u9fa5.\-]", "_", name)[:80] or f"recording{ext}"
    dest = _audio_dir(node) / safe
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_MB * 1024 * 1024:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"录音文件过大（上限 {MAX_MB}MB）")
            fh.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "空文件")

    _save_meta(node, filename=name, stored_name=safe, size=size, ext=ext,
               status="uploaded", progress=0.0, error="", job_id="", revision_id="",
               uploaded_at=_now(), duration_s=0, chars=0)
    await db.commit()
    await audit_log(db, action="audio_upload", user=user, target_type="node", target_id=nid,
                    detail={"name": name, "size": size})
    return {"ok": True, "audio": _audio_meta(node)}


@router.get("/nodes/{nid}/audio")
async def audio_state(nid: str, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """音频元信息 + 转写状态（前端进度轮询；顺带自愈重启后的监听）"""
    node = await _owned_audio_node(db, nid, user)
    meta = _audio_meta(node)
    if meta.get("status") in ("queued", "running") and meta.get("job_id"):
        ensure_watcher(node.id, meta["job_id"], user.id, meta.get("run_id"), node.project_id)
    return {"audio": meta, "node_status": node.status}


@router.get("/nodes/{nid}/audio/file")
async def audio_file(nid: str, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    node = await _owned_audio_node(db, nid, user)
    path = _file_path(node)
    if path is None:
        raise HTTPException(404, "音频文件不存在")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@router.delete("/nodes/{nid}/audio")
async def delete_audio(nid: str, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    node = await _owned_audio_node(db, nid, user)
    meta = _audio_meta(node)
    job_id = meta.get("job_id")
    if job_id:
        await asr.cancel_job(db, job_id)
    task = _WATCHERS.pop(node.id, None)
    if task and not task.done():
        task.cancel()
    path = _file_path(node)
    if path is not None:
        path.unlink(missing_ok=True)
    cfg = dict(node.config or {})
    cfg.pop("audio", None)
    node.config = cfg
    node.status = "idle"
    node.error = ""
    await db.commit()
    await manager.broadcast(node.project_id, {"type": "node_status", "node_id": node.id,
                                              "status": "idle", "error": ""})
    return {"ok": True}


@router.post("/nodes/{nid}/audio/transcribe")
async def transcribe(nid: str, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    node = await _owned_audio_node(db, nid, user)
    return await start_transcription(db, node, user, trigger="manual")
