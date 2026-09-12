"""路径配置：上传目录等可部署路径

默认放在后端目录下的 uploads/，可通过环境变量覆盖（便于容器化或自定义数据盘）。
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT") or (BACKEND_DIR / "uploads")).resolve()
