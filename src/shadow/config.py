"""集中管理路径与常量。

路径以函数形式暴露而非模块级常量，这样测试可以通过 monkeypatch 环境变量隔离数据目录，
不会污染用户真实的 ~/.shadow。
"""

from __future__ import annotations

import os
from pathlib import Path

# --- 转写 ---
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
WHISPER_LANGUAGE = "en"
SAMPLE_RATE = 16_000

# --- 导入约束 ---
MAX_SOURCE_MINUTES = 60.0

# --- 切片 ---
SEGMENT_MIN_SEC = 30.0
SEGMENT_MAX_SEC = 90.0
PAUSE_GAP_SEC = 0.4

# --- 挖空 ---
BLANK_RATIO_MAX = 0.15
BLANK_MIN = 3
BLANK_MAX = 12
WEAK_RATIO_STRICT = 0.6
WEAK_RATIO_RELAXED = 0.8

# --- 练习单元（在片段内部按句子再切）---
# 素材单元 30-90s 是为了「完整语义块」，但跟读时太长会跟丢，图上也挤不下。
# 下限不只是人体工学：0.7s 提不出有意义的音高轮廓，少于 3 个匹配词时
# 时间对齐会退化成整体线性缩放，反馈直接失效。
UNIT_MIN_SEC = 3.0
UNIT_MAX_SEC = 8.0
UNIT_MIN_WORDS = 5

# --- 韵律分析 ---
FRAME_STEP_SEC = 0.01
ENERGY_WINDOW_SEC = 0.025
PITCH_FLOOR_HZ = 75.0
PITCH_CEILING_HZ = 500.0

# --- 录音校验 ---
MIN_ATTEMPT_SEC = 1.0
MIN_ATTEMPT_RMS_DB = -50.0

# --- 外部命令超时（秒）---
# 无超时的 subprocess.run 会在网络卡住时永久挂起，状态停在 downloading 且无恢复路径。
PROBE_TIMEOUT_SEC = 60.0
DOWNLOAD_TIMEOUT_SEC = 1800.0
FFMPEG_TIMEOUT_SEC = 900.0


def data_dir() -> Path:
    return Path(os.environ.get("SHADOW_DATA_DIR", Path.home() / ".shadow"))


def db_path() -> Path:
    return data_dir() / "shadow.db"


def source_audio_dir() -> Path:
    return data_dir() / "audio" / "sources"


def segment_audio_dir() -> Path:
    return data_dir() / "audio" / "segments"


def attempt_audio_dir() -> Path:
    return data_dir() / "audio" / "attempts"


def ensure_dirs() -> None:
    for directory in (
        data_dir(),
        source_audio_dir(),
        segment_audio_dir(),
        attempt_audio_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)
