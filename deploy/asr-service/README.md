# Audio8 ASR —— 本地语音识别服务（录音转文字）

「内容工坊」的「🎙️ 录音转文字」节点依赖本服务。它在本机做语音识别，
**音频不出内网**，也不需要 GPU。

## 技术选型

| 项 | 选择 | 说明 |
|---|---|---|
| 识别引擎 | sherpa-onnx 1.13+ / SenseVoice-Small（int8） | 中文准确、带标点与数字规范化（ITN），CPU 上约 **8~10 倍实时** |
| 音频解码 | PyAV（自带 FFmpeg 库） | 支持 mp3 / m4a / wav / aac / amr / ogg / flac，**无需系统安装 ffmpeg** |
| 长音频 | 按 ~28 秒切段 + 低能量处对齐断点 | 避免把一句话劈开；逐段回报进度 |
| 服务框架 | FastAPI + uvicorn，systemd 托管，只监听 127.0.0.1 | 只给同机的内容工坊后端调用 |

## 部署（Ubuntu + Python 3.12/3.13/3.14 均可）

```bash
mkdir -p /www/wwwroot/Audio8_ASR/model && cd /www/wwwroot/Audio8_ASR
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install sherpa-onnx av numpy fastapi uvicorn python-multipart

# 模型（约 240MB，可从 HuggingFace 镜像下载）
cd model
curl -L -o model.int8.onnx https://hf-mirror.com/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx
curl -L -o tokens.txt      https://hf-mirror.com/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt

# 服务与单元
cp service.py /www/wwwroot/Audio8_ASR/service.py
sudo cp audio8-asr.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now audio8-asr
curl -s http://127.0.0.1:8030/health | python3 -m json.tool
```

## 接口

| 接口 | 说明 |
|---|---|
| `GET /health` | 健康检查（模型、线程数、队列、运行中的任务） |
| `GET /v1/models` | 模型列表（OpenAI 风格） |
| `POST /v1/audio/transcriptions` | OpenAI 兼容：`file` → `{"text": ...}`（短音频直接返回） |
| `POST /jobs` | 提交转写任务 → `{"job_id": ...}`（长录音用这个） |
| `GET /jobs/{id}` | 状态 / 进度 / **边转写边增长的中间文本** / 音频时长 / 实时率 |
| `DELETE /jobs/{id}` | 取消任务 |

## 环境变量（见 audio8-asr.service）

`ASR_MODEL_DIR`、`ASR_THREADS`（默认 3，留一个核给 Web 服务）、`ASR_CHUNK_SECONDS`（默认 28）、
`ASR_MAX_UPLOAD_MB`（默认 300）、`ASR_LANGUAGE`（auto / zh / en / yue…）、`ASR_USE_ITN`（数字规范化）。

## 实测性能（4 核 Xeon E5-2609 v3，无 GPU）

| 音频 | 时长 | 转写耗时 | 实时率 | 字错率（对照人工字幕） |
|---|---|---|---|---|
| 演讲片段 m4a | 4.5 分钟 | 29 秒 | 0.107 | 3.66% |
| 同段 mp3 | 4.5 分钟 | 33 秒 | 0.121 | 3.66% |
| 拼接长音频 m4a | 27 分钟 | 191 秒 | 0.117 | 3.91% |

推算：**1 小时录音约 7 分钟出稿**；常驻内存约 700MB（首次推理需 3~6 秒预热，服务启动时已预热）。
