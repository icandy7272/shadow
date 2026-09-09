"""音频文件操作：裁剪、格式统一、录音有效性校验。"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config


class AudioError(RuntimeError):
    pass


def probe_duration(path: Path) -> float:
    return float(sf.info(str(path)).duration)


def cut_segment(source: Path, dest: Path, *, start: float, end: float) -> Path:
    """从 source 裁出 [start, end) 并统一为 16k 单声道 wav。"""
    if end <= start:
        raise AudioError(f"无效的裁剪区间：start={start} end={end}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(source),
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-ar", str(config.SAMPLE_RATE), "-ac", "1",
            "-c:a", "pcm_s16le", str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg 裁剪失败：\n{proc.stderr.strip()}")
    return dest


def validate_attempt(path: Path) -> None:
    """录音提交前的守门：太短或全静音就地拦下，不浪费一次转写。"""
    duration = probe_duration(path)
    if duration < config.MIN_ATTEMPT_SEC:
        raise AudioError(
            f"录音过短（{duration:.2f}s，至少需要 {config.MIN_ATTEMPT_SEC}s）"
        )
    samples, _ = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
    rms_db = 20.0 * math.log10(rms + 1e-10)
    if rms_db < config.MIN_ATTEMPT_RMS_DB:
        raise AudioError(
            f"录音接近静音（{rms_db:.1f} dB）。检查麦克风是否被静音或选错设备。"
        )
