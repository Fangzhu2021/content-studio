"""
Audio8 ASR —— 本地语音识别服务（sherpa-onnx + SenseVoice-Small）

设计目标：录音**不出内网**，在 192.168.4.48 这台 4 核无 GPU 的机器上把
10~60 分钟的采访录音转成中文文字稿。

特点
- 完全本地推理（ONNX Runtime CPU），不依赖任何外部云服务
- 音频解码用 PyAV（自带 FFmpeg 库），无需系统装 ffmpeg，支持 mp3/m4a/wav/aac/amr/ogg/flac
- 长音频自动切段：在目标断点 ±N 秒内找能量最低处下刀，避免把一句话劈开
- 任务式接口：提交后立即返回 job_id，轮询取进度与"边转写边增长"的中间文本
  （长录音不占用长连接，前端进度条能实时动）

接口
  GET    /health                        健康检查
  GET    /v1/models                     模型列表（OpenAI 风格）
  POST   /v1/audio/transcriptions       OpenAI 兼容：multipart file → {"text": ...}（短音频用）
  POST   /jobs                          提交转写任务（file）→ {"job_id": ...}（长录音用）
  GET    /jobs/{id}                     查询任务：状态/进度/中间文本/耗时/实时率
  DELETE /jobs/{id}                     取消任务并清理
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import av
import numpy as np
import sherpa_onnx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.environ.get("ASR_MODEL_DIR", os.path.join(BASE_DIR, "model"))
MODEL_FILE = os.environ.get("ASR_MODEL_FILE", "model.int8.onnx")
TOKENS_FILE = os.environ.get("ASR_TOKENS_FILE", "tokens.txt")
NUM_THREADS = int(os.environ.get("ASR_THREADS", "3"))
SAMPLE_RATE = 16000
CHUNK_SECONDS = float(os.environ.get("ASR_CHUNK_SECONDS", "28"))
CHUNK_SEARCH = float(os.environ.get("ASR_CHUNK_SEARCH", "3"))
TAIL_MIN_SECONDS = 2.5
MAX_UPLOAD_MB = int(os.environ.get("ASR_MAX_UPLOAD_MB", "300"))
LANGUAGE = os.environ.get("ASR_LANGUAGE", "auto")
USE_ITN = os.environ.get("ASR_USE_ITN", "1") not in ("0", "false", "False")
TMP_DIR = os.environ.get("ASR_TMP_DIR", "/tmp/audio8-asr")

os.makedirs(TMP_DIR, exist_ok=True)
app = FastAPI(title="Audio8 ASR", version="1.0.0")
STARTED_AT = time.time()
_RECOGNIZER = None
_REC_LOCK = threading.Lock()


# ---------------------------------------------------------------- 模型
def get_recognizer():
    """懒加载识别器（进程内单例；sherpa-onnx 的 decode_stream 非线程安全，用锁串行化）"""
    global _RECOGNIZER
    if _RECOGNIZER is None:
        model_path = os.path.join(MODEL_DIR, MODEL_FILE)
        tokens_path = os.path.join(MODEL_DIR, TOKENS_FILE)
        if not (os.path.exists(model_path) and os.path.exists(tokens_path)):
            raise RuntimeError(f"模型文件缺失：{model_path} / {tokens_path}")
        _RECOGNIZER = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model_path,
            tokens=tokens_path,
            num_threads=NUM_THREADS,
            use_itn=USE_ITN,
            language=LANGUAGE,
            debug=False,
        )
    return _RECOGNIZER


# ---------------------------------------------------------------- 音频解码
def decode_audio(path: str) -> np.ndarray:
    """任意常见音频 → 16kHz 单声道 float32（用 PyAV，不依赖系统 ffmpeg）"""
    parts: list[np.ndarray] = []
    with av.open(path) as container:
        streams = [s for s in container.streams if s.type == "audio"]
        if not streams:
            raise ValueError("文件里没有音频轨（是否是纯视频或损坏文件？）")
        stream = streams[0]
        resampler = av.audio.resampler.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                parts.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):        # 冲刷重采样器尾部
            parts.append(out.to_ndarray().reshape(-1))
    if not parts:
        raise ValueError("没有解出任何音频数据")
    audio = np.concatenate(parts).astype(np.float32)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if 0 < peak < 0.1:                              # 录音增益过小时抬一下，识别更稳
        audio = audio * min(0.9 / peak, 8.0)
    return audio


def plan_segments(audio: np.ndarray, target: float = CHUNK_SECONDS,
                  search: float = CHUNK_SEARCH) -> list[tuple[int, int]]:
    """把长音频切成若干段：每段约 target 秒，断点落在目标点附近能量最低的位置（≈静音处）"""
    n = len(audio)
    if n <= int((target + TAIL_MIN_SECONDS) * SAMPLE_RATE):
        return [(0, n)]
    win = int(0.05 * SAMPLE_RATE)
    cuts: list[int] = []
    pos = 0
    while n - pos > int((target + TAIL_MIN_SECONDS) * SAMPLE_RATE):
        lo = max(pos + int(2 * SAMPLE_RATE), pos + int((target - search) * SAMPLE_RATE))
        hi = min(pos + int((target + search) * SAMPLE_RATE), n - int(TAIL_MIN_SECONDS * SAMPLE_RATE))
        if hi - lo <= win:
            break
        starts = np.arange(lo, hi - win, win)
        # 用 50ms 窗口的均方能量挑最安静的位置
        energy = np.empty(len(starts), dtype=np.float64)
        for i, s in enumerate(starts):
            seg = audio[s:s + win]
            energy[i] = float(np.mean(seg * seg)) if seg.size else 0.0
        cut = int(starts[int(np.argmin(energy))])
        cuts.append(cut)
        pos = cut
    cuts.append(n)
    segments, prev = [], 0
    for c in cuts:
        if c - prev > int(0.5 * SAMPLE_RATE):
            segments.append((prev, c))
        prev = c
    return segments or [(0, n)]


_TAG_RE = re.compile(r"<\|[^|]*\|>")
_CJK = r"\u4e00-\u9fff\u3400-\u4dbf"


def clean_text(text: str) -> str:
    """去掉 SenseVoice 的语言/情感标记，规整空白（中文之间不留空格）"""
    t = _TAG_RE.sub("", text or "")
    t = t.replace("▁", " ").replace("\u3000", " ")
    t = re.sub(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])", "", t)   # 中文字之间去空格
    t = re.sub(r"[ \t]+", " ", t).strip()
    if not re.search(r"[\w\u4e00-\u9fff]", t):
        return ""                                     # 整段只有标点/空白 → 丢弃
    t = re.sub(r"^[^\w\u4e00-\u9fff]+", "", t)     # 开头孤立的标点（SenseVoice 偶尔吐一个“.”）
    return t.strip()


def transcribe(audio: np.ndarray, start: int, end: int) -> str:
    rec = get_recognizer()
    with _REC_LOCK:
        s = rec.create_stream()
        s.accept_waveform(SAMPLE_RATE, audio[start:end])
        rec.decode_stream(s)
        return clean_text(s.result.text)


# ---------------------------------------------------------------- 任务队列
@dataclass
class Job:
    id: str
    filename: str
    path: str
    status: str = "queued"            # queued | running | done | error | canceled
    progress: float = 0.0
    segments_total: int = 0
    segments_done: int = 0
    text: str = ""
    error: str = ""
    duration_s: float = 0.0           # 音频时长
    elapsed_s: float = 0.0            # 已耗时
    rtf: float = 0.0                  # 实时率 = 耗时 / 音频时长（越小越快）
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancel: bool = False

    def public(self) -> dict:
        return {
            "job_id": self.id, "status": self.status, "filename": self.filename,
            "progress": self.progress, "segments_total": self.segments_total,
            "segments_done": self.segments_done, "duration_s": round(self.duration_s, 1),
            "elapsed_s": round(self.elapsed_s, 1), "rtf": self.rtf,
            "text": self.text, "chars": len(self.text), "error": self.error,
        }


JOBS: dict[str, Job] = {}
JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
JOBS_LOCK = threading.Lock()


def _warmup() -> None:
    """预热：ONNX Runtime 首次推理要分配内存池（实测 3~6 秒），先跑两次静音，
    避免第一个真实任务白等这么久（1 小时录音整体只要 ~6 分钟，预热占比可观）"""
    try:
        rec = get_recognizer()
        silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
        for _ in range(2):
            s = rec.create_stream()
            s.accept_waveform(SAMPLE_RATE, silence)
            rec.decode_stream(s)
        print("[warmup] 模型预热完成", flush=True)
    except Exception as exc:                     # noqa: BLE001
        print(f"[warmup] 失败：{exc}", flush=True)


def _worker() -> None:
    _warmup()
    while True:
        job_id = JOB_QUEUE.get()
        job = JOBS.get(job_id)
        if job is None or job.cancel:
            continue
        t0 = time.time()
        try:
            job.status = "running"
            audio = decode_audio(job.path)
            job.duration_s = len(audio) / SAMPLE_RATE
            segments = plan_segments(audio)
            job.segments_total = len(segments)
            texts: list[str] = []
            for i, (a, b) in enumerate(segments):
                if job.cancel:
                    job.status = "canceled"
                    break
                piece = transcribe(audio, a, b)
                if piece:
                    texts.append(piece)
                job.segments_done = i + 1
                job.progress = round((i + 1) / len(segments), 4)
                job.text = "\n\n".join(texts)      # 中间结果实时可见
                job.elapsed_s = time.time() - t0
            if job.status != "canceled":
                job.status = "done"
        except Exception as exc:                    # noqa: BLE001
            job.status = "error"
            job.error = str(exc)[:300]
        finally:
            job.elapsed_s = round(time.time() - t0, 1)
            job.finished_at = time.time()
            if job.duration_s:
                job.rtf = round(job.elapsed_s / job.duration_s, 3)
            try:
                os.remove(job.path)
            except OSError:
                pass


threading.Thread(target=_worker, daemon=True).start()


def _save_upload(upload: UploadFile) -> tuple[str, int]:
    job_id = uuid.uuid4().hex
    ext = os.path.splitext(upload.filename or "")[1][:10] or ".audio"
    path = os.path.join(TMP_DIR, f"{job_id}{ext}")
    size = 0
    with open(path, "wb") as fh:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                fh.close()
                os.remove(path)
                raise HTTPException(413, f"音频文件过大（上限 {MAX_UPLOAD_MB}MB）")
            fh.write(chunk)
    if size == 0:
        os.remove(path)
        raise HTTPException(400, "空文件")
    return path, size


# ---------------------------------------------------------------- 接口
@app.get("/health")
def health() -> dict:
    ok = os.path.exists(os.path.join(MODEL_DIR, MODEL_FILE))
    return {
        "ok": ok, "model": os.path.splitext(MODEL_FILE)[0], "model_dir": MODEL_DIR,
        "threads": NUM_THREADS, "language": LANGUAGE, "use_itn": USE_ITN,
        "sample_rate": SAMPLE_RATE, "chunk_seconds": CHUNK_SECONDS,
        "queued": JOB_QUEUE.qsize(), "running": [j.id for j in JOBS.values() if j.status == "running"],
        "uptime_s": round(time.time() - STARTED_AT, 1), "version": app.version,
    }


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [
        {"id": "sensevoice-small", "object": "model", "owned_by": "local",
         "note": "本地推理（音频不出内网）"}]}


@app.post("/jobs")
async def create_job(file: UploadFile = File(...)) -> dict:
    path, size = _save_upload(file)
    job = Job(id=os.path.splitext(os.path.basename(path))[0], filename=file.filename or "",
              path=path)
    with JOBS_LOCK:
        # 只保留最近 50 条任务元数据，避免长跑进程内存堆积
        if len(JOBS) > 50:
            for old in sorted(JOBS.values(), key=lambda j: j.created_at)[:len(JOBS) - 50]:
                if old.status in ("done", "error", "canceled"):
                    JOBS.pop(old.id, None)
        JOBS[job.id] = job
    JOB_QUEUE.put(job.id)
    return {"job_id": job.id, "status": job.status, "size_bytes": size}


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在或已过期")
    return job.public()


@app.delete("/jobs/{job_id}")
def job_cancel(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在或已过期")
    job.cancel = True
    if job.status in ("queued", "running"):
        job.status = "canceled"
    return {"job_id": job_id, "status": job.status}


@app.post("/v1/audio/transcriptions")
async def transcriptions(file: UploadFile = File(...),
                         language: Optional[str] = Form(None),
                         model: Optional[str] = Form(None),
                         timeout_s: Optional[float] = Form(600.0)) -> JSONResponse:
    """OpenAI 兼容接口：直接返回识别文本（短音频够用；长音频建议走 /jobs）"""
    path, _size = _save_upload(file)
    job = Job(id=os.path.splitext(os.path.basename(path))[0], filename=file.filename or "", path=path)
    with JOBS_LOCK:
        JOBS[job.id] = job
    JOB_QUEUE.put(job.id)
    deadline = time.time() + float(timeout_s or 600.0)
    while time.time() < deadline:
        if job.status == "done":
            return JSONResponse({"text": job.text, "model": model or "sensevoice-small",
                                 "duration_s": round(job.duration_s, 1),
                                 "elapsed_s": job.elapsed_s, "rtf": job.rtf})
        if job.status == "error":
            raise HTTPException(500, job.error or "转写失败")
        if job.status == "canceled":
            raise HTTPException(499, "任务已取消")
        time.sleep(0.5)
    raise HTTPException(504, "等待超时（音频较长，请改用 /jobs 异步接口）")
