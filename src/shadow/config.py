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
# 默认严格按句子切：一句一个单元。实测 0.7s / 2 词的短句仍有 25-54 个浊音帧，
# 高于音高自适应所需的 20 帧下限，反馈算得出来。太长的句子仍会在最大停顿处再断。
# （原先 3.0s 的下限有一半理由是帧级时间弯折需要 >=3 个锚点，
#   反馈层重做为一词一格之后该约束已不存在。）
UNIT_MIN_SEC = 0.0      # 0 = 严格一句一个，不把短句并进下一句
UNIT_MAX_SEC = 6.0
UNIT_PAD_SEC = 0.1        # 单元首尾各留一点余量，免得切掉词头的爆破音
UNIT_MIN_WORDS = 2      # 只有单词句会并走，避免出现只有一个词的单元

# --- 韵律分析 ---
FRAME_STEP_SEC = 0.01
ENERGY_WINDOW_SEC = 0.025
PITCH_FLOOR_HZ = 75.0
PITCH_CEILING_HZ = 500.0
# 固定的 75-500 Hz 对低男声太宽，会把谐波误判成基频（实测 94 Hz 的声音
# 有 12% 的帧跳到 494 Hz，把纵轴撑到 30 半音，真实语调全被压扁）。
# Praat 标准两遍法：先宽跑一遍取四分位数，再用 0.75*Q1 ~ 1.5*Q3 重跑。
# 用中位数而非四分位数定边界：八度错误超过 25% 的帧时四分位数本身就被污染
# （实测某次录音 Q75 = 470 Hz，中位数仍是 116 Hz，与同批另外两次一致）。
# 中位数只要错误帧不过半就稳。人在一句话内的音域也极少超过 ±1 个八度。
PITCH_ADAPT_MIN_VOICED = 5
PITCH_ADAPT_SPAN = 2.0

# --- 转写对齐校验 ---
# Whisper 的词级时间戳偶尔整体错位（实测某次录音 0.17s 就开口，
# 时间戳却把整句定位到 3.64s 之后）。错位的 take 每一项测量都取自错误的
# 音频位置，且完全无声——必须查出来剔除，而不是算进中位数。
ALIGNMENT_TOLERANCE_SEC = 1.0
WORD_TRACE_POINTS = 14   # 一个词的音高画成几段，够看出先扬后抑
SPEECH_FLOOR_DB = -20.0

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
