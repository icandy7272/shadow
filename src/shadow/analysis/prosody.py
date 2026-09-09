"""音频 -> 韵律曲线：半音归一化音高 + 归一化能量包络。

归一化是本模块存在的理由。绝对 Hz 无法跨说话人比较（男声约 100 Hz vs 女声约 220 Hz），
转成相对各自浊音段中位数的半音数后，比较的是语调轮廓而非嗓音音高。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import parselmouth

from .. import config


@dataclass(frozen=True, slots=True)
class Prosody:
    times: np.ndarray       # 秒，等间距
    f0_hz: np.ndarray       # 基频，清音处为 nan
    semitones: np.ndarray   # 相对自身中位数的半音数，清音处为 nan
    energy_db: np.ndarray   # 相对自身 95 分位的 dB
    duration: float


def _rms_db(
    samples: np.ndarray, sample_rate: float, times: np.ndarray, window: float
) -> np.ndarray:
    """滑窗 RMS，用平方前缀和做到 O(n)。"""
    squared_prefix = np.concatenate(([0.0], np.cumsum(np.square(samples))))
    half = max(1, int(window * sample_rate / 2))
    centres = np.clip((times * sample_rate).astype(int), 0, max(samples.size - 1, 0))
    lower = np.clip(centres - half, 0, samples.size)
    upper = np.clip(centres + half, 0, samples.size)
    counts = np.maximum(upper - lower, 1)
    rms = np.sqrt((squared_prefix[upper] - squared_prefix[lower]) / counts)
    return 20.0 * np.log10(rms + 1e-10)


def word_contour(prosody: "Prosody", start: float, end: float) -> tuple[float, float] | None:
    """词内的起始与结束音高（各取前后三分之一的均值，比取单帧稳）。

    返回 (起, 止)；两者之差就是这个词内部的升降走向——句尾降调正是靠它看出来的。
    浊音帧不足时返回 None。
    """
    values = prosody.semitones[(prosody.times >= start) & (prosody.times < end)]
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    if values.size < 3:
        mean = float(np.mean(values))
        return mean, mean
    third = max(1, values.size // 3)
    return float(np.mean(values[:third])), float(np.mean(values[-third:]))


def adaptive_pitch_bounds(
    sound: parselmouth.Sound,
    *,
    step: float,
    floor: float,
    ceiling: float,
) -> tuple[float, float]:
    """按说话人自身的基频分布收窄搜索范围。

    固定上限对低男声太宽，追踪器会把谐波当成基频。先用宽范围跑一遍，
    取浊音帧的四分位数，再收到 0.75*Q1 ~ 1.5*Q3（Praat 的标准做法）。
    浊音帧太少时保持原边界，不瞎猜。
    """
    rough = sound.to_pitch(time_step=step, pitch_floor=floor, pitch_ceiling=ceiling)
    values = np.asarray(rough.selected_array["frequency"], dtype=float)
    voiced = values[values > 0.0]
    if voiced.size < config.PITCH_ADAPT_MIN_VOICED:
        return floor, ceiling

    q25, q75 = np.percentile(voiced, [25, 75])
    low = max(floor, config.PITCH_ADAPT_LOW * float(q25))
    high = min(ceiling, config.PITCH_ADAPT_HIGH * float(q75))
    high = max(high, low * 2.0)  # 搜索范围不能退化
    return low, min(high, ceiling)


def analyse(
    wav_path,
    *,
    step: float = config.FRAME_STEP_SEC,
    pitch_floor: float = config.PITCH_FLOOR_HZ,
    pitch_ceiling: float = config.PITCH_CEILING_HZ,
    energy_window: float = config.ENERGY_WINDOW_SEC,
) -> Prosody:
    sound = parselmouth.Sound(str(wav_path))
    duration = float(sound.get_total_duration())

    times = np.arange(0.0, duration, step)
    if times.size == 0:
        times = np.array([0.0])

    low, high = adaptive_pitch_bounds(
        sound, step=step, floor=pitch_floor, ceiling=pitch_ceiling
    )
    pitch = sound.to_pitch(time_step=step, pitch_floor=low, pitch_ceiling=high)
    pitch_times = np.asarray(pitch.xs(), dtype=float)
    pitch_values = np.asarray(pitch.selected_array["frequency"], dtype=float)

    if pitch_times.size:
        indices = np.clip(
            np.searchsorted(pitch_times, times), 0, pitch_times.size - 1
        )
        f0 = pitch_values[indices].copy()
    else:
        f0 = np.full(times.shape, np.nan)
    f0[f0 <= 0.0] = np.nan

    voiced = f0[~np.isnan(f0)]
    if voiced.size:
        semitones = 12.0 * np.log2(f0 / float(np.median(voiced)))
    else:
        semitones = np.full(times.shape, np.nan)

    values = np.asarray(sound.values, dtype=float)
    samples = values.mean(axis=0) if values.ndim > 1 else values
    energy = _rms_db(samples, float(sound.sampling_frequency), times, energy_window)
    energy = energy - float(np.percentile(energy, 95))

    return Prosody(
        times=times,
        f0_hz=f0,
        semitones=semitones,
        energy_db=energy,
        duration=duration,
    )
