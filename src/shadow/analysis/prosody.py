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


def word_trace(prosody: "Prosody", start: float, end: float, *,
               points: int = config.WORD_TRACE_POINTS) -> tuple[float | None, ...]:
    """词内音高的实际走向：等分成 points 段，每段取中位数，无浊音的段为 None。

    只取首尾两个数会把「先扬后抑」抹平——句尾降调恰恰是这个形状，
    两点摘要会把它画成上扬，与耳朵听到的相反。
    每段取中位数而非均值：词尾常有气声、嘎裂声，单帧跳变很常见。
    """
    if end <= start or points < 1:
        return ()
    edges = np.linspace(start, end, points + 1)
    out: list[float | None] = []
    for low, high in zip(edges[:-1], edges[1:]):
        window = prosody.semitones[(prosody.times >= low) & (prosody.times < high)]
        window = window[np.isfinite(window)]
        out.append(float(np.median(window)) if window.size else None)
    return tuple(out)


def _longest_voiced_run(trace) -> list[float]:
    """词内最长的一段连续浊音。

    词边界是估出来的，末尾常蹭到下一个词的开头——那一小段会把判定整个带偏，
    只认最长的连续段就自然甩掉它。
    """
    best: list[float] = []
    run: list[float] = []
    for value in trace:
        if value is None:
            best = run if len(run) > len(best) else best
            run = []
            continue
        run.append(value)
    return run if len(run) > len(best) else best


@dataclass(frozen=True, slots=True)
class WordPitch:
    """一个词的音高摘要。head/tail 是词头、词尾的音高（半音）。"""

    head: float
    tail: float
    move: float | None      # 净升降。形状不单调时为 None，见下


def word_pitch(prosody: "Prosody", start: float, end: float) -> "WordPitch | None":
    """词头音高、词尾音高，以及词内净升降。浊音太少时整个返回 None。

    move 在形状不单调时为 None：「先扬后抑」用一个数描述必然失真，
    真出过把降调判成升调的事。宁可不判，也别给出与听感相反的结论。
    句尾另有 terminal_fall，不靠这个。
    """
    run = _longest_voiced_run(word_trace(prosody, start, end))
    if len(run) < config.WORD_MOVE_MIN_POINTS:
        return None
    third = max(1, len(run) // 3)
    head = float(np.median(run[:third]))
    tail = float(np.median(run[-third:]))
    # 中间冒出比两端都高（或都低）一截，说明是拱形或谷形，两点之差说明不了它
    arch = (max(run) - max(head, tail) > config.WORD_MOVE_ARCH_ST
            or min(head, tail) - min(run) > config.WORD_MOVE_ARCH_ST)
    return WordPitch(head=head, tail=tail, move=None if arch else tail - head)


def bounds_from_voiced(
    voiced: np.ndarray, *, floor: float, ceiling: float
) -> tuple[float, float]:
    """由粗测得到的浊音基频定出收窄后的搜索范围。纯函数，便于单测。

    用中位数而非四分位数：八度错误一旦超过四分之一的帧，Q3 本身就被拉走了。
    中位数只要错误帧不过半就稳，而人在一句话里的音域极少超过 ±1 个八度。
    """
    if voiced.size < config.PITCH_ADAPT_MIN_VOICED:
        return floor, ceiling
    median = float(np.median(voiced))
    if median <= 0:
        return floor, ceiling
    low = max(floor, median / config.PITCH_ADAPT_SPAN)
    high = min(ceiling, median * config.PITCH_ADAPT_SPAN)
    return low, max(high, low * 2.0)


def _word_values(prosody: "Prosody", start: float, end: float) -> np.ndarray:
    values = prosody.semitones[(prosody.times >= start) & (prosody.times < end)]
    return values[np.isfinite(values)]


def terminal_fall(prosody: "Prosody", words) -> float | None:
    """句尾降幅：末词的最低点相对末两词的最高点。负得越多，收得越沉。

    只看词内起止是错的——句尾降调常常跨在词边界上。实测 "It started before
    I was born." 里 was 收在 −2.7、born 从 −4.9 起，那 2.2 个半音的下坠
    完全落在词与词之间，词内指标反而报成「升 3.2」，与听感相反。

    取末两词的最高点作参照，既覆盖词内下坠（短句如 "That's it."），
    也覆盖跨词下坠（长句），且不受句子长短影响。
    """
    if not words:
        return None
    last = _word_values(prosody, words[-1].start, words[-1].end)
    if last.size == 0:
        return None
    tail = words[-2:] if len(words) > 1 else words[-1:]
    window = np.concatenate([_word_values(prosody, w.start, w.end) for w in tail])
    if window.size == 0:
        return None
    return float(last.min() - window.max())


def adaptive_pitch_bounds(
    sound: parselmouth.Sound,
    *,
    step: float,
    floor: float,
    ceiling: float,
) -> tuple[float, float]:
    """按说话人自身的基频分布收窄搜索范围。

    固定上限对低男声太宽，追踪器会把谐波当成基频。先用宽范围跑一遍，
    再据其中位数收窄重跑。浊音帧太少时保持原边界，不瞎猜。
    """
    rough = sound.to_pitch(time_step=step, pitch_floor=floor, pitch_ceiling=ceiling)
    values = np.asarray(rough.selected_array["frequency"], dtype=float)
    return bounds_from_voiced(values[values > 0.0], floor=floor, ceiling=ceiling)


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
