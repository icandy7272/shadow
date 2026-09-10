import numpy as np
import pytest
import soundfile as sf

import parselmouth

from shadow import config
from shadow.analysis.prosody import (
    adaptive_pitch_bounds,
    analyse,
    bounds_from_voiced,
)

SR = 16000


def write_tone(path, *, seconds=2.0, freq=220.0, amplitude=0.5):
    t = np.arange(int(seconds * SR)) / SR
    sf.write(path, (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32), SR)
    return path


def write_two_tones(path, *, first=220.0, second=440.0, seconds=1.0, amplitude=0.5):
    t = np.arange(int(seconds * SR)) / SR
    head = amplitude * np.sin(2 * np.pi * first * t)
    tail = amplitude * np.sin(2 * np.pi * second * t)
    sf.write(path, np.concatenate([head, tail]).astype(np.float32), SR)
    return path


def write_two_levels(path, *, seconds=1.0, loud=0.5, quiet=0.25, freq=220.0):
    t = np.arange(int(seconds * SR)) / SR
    head = loud * np.sin(2 * np.pi * freq * t)
    tail = quiet * np.sin(2 * np.pi * freq * t)
    sf.write(path, np.concatenate([head, tail]).astype(np.float32), SR)
    return path


def test_detects_fundamental_frequency(tmp_path):
    result = analyse(write_tone(tmp_path / "a.wav", freq=220.0))
    assert np.nanmedian(result.f0_hz) == pytest.approx(220.0, abs=5.0)


def test_steady_tone_has_flat_semitone_contour(tmp_path):
    result = analyse(write_tone(tmp_path / "a.wav", freq=220.0))
    assert np.nanmax(np.abs(result.semitones)) < 1.0


def test_octave_jump_spans_about_twelve_semitones(tmp_path):
    result = analyse(write_two_tones(tmp_path / "a.wav"))
    span = np.nanmax(result.semitones) - np.nanmin(result.semitones)
    assert span == pytest.approx(12.0, abs=1.5)


def test_semitones_are_speaker_independent(tmp_path):
    """低音与高音说话人唱同样的八度跳跃，归一化后轮廓跨度应一致。"""
    low = analyse(write_two_tones(tmp_path / "low.wav", first=110.0, second=220.0))
    high = analyse(write_two_tones(tmp_path / "high.wav", first=220.0, second=440.0))
    low_span = np.nanmax(low.semitones) - np.nanmin(low.semitones)
    high_span = np.nanmax(high.semitones) - np.nanmin(high.semitones)
    assert low_span == pytest.approx(high_span, abs=1.5)


def test_energy_drop_is_about_six_db(tmp_path):
    result = analyse(write_two_levels(tmp_path / "a.wav"))
    half = len(result.energy_db) // 2
    # 信号 2.0s / 步长 0.01s = 200 帧，half = 100。裁边必须远小于 100，
    # 否则 [100:half-100] 会切出空数组，np.median 返回 nan。
    margin = 20
    loud = np.median(result.energy_db[margin:half - margin])
    quiet = np.median(result.energy_db[half + margin:-margin])
    assert loud - quiet == pytest.approx(6.0, abs=1.5)


def test_all_arrays_share_one_time_grid(tmp_path):
    result = analyse(write_tone(tmp_path / "a.wav", seconds=1.5))
    assert result.times.shape == result.f0_hz.shape == result.semitones.shape
    assert result.times.shape == result.energy_db.shape
    assert result.duration == pytest.approx(1.5, abs=0.05)


def test_silence_yields_no_pitch_but_still_returns_grid(tmp_path):
    result = analyse(write_tone(tmp_path / "a.wav", amplitude=0.0))
    assert np.all(np.isnan(result.semitones))
    assert result.times.size > 0


def test_adaptive_bounds_narrow_around_a_low_voice(tmp_path):
    # 固定的 75-500 Hz 对低男声太宽，追踪器会把谐波当基频
    sound = parselmouth.Sound(str(write_tone(tmp_path / "low.wav", freq=95.0)))
    low, high = adaptive_pitch_bounds(
        sound, step=0.01,
        floor=config.PITCH_FLOOR_HZ, ceiling=config.PITCH_CEILING_HZ,
    )
    assert low >= config.PITCH_FLOOR_HZ
    assert high < config.PITCH_CEILING_HZ
    assert low < 95.0 < high


def test_adaptive_bounds_keep_originals_when_nothing_is_voiced(tmp_path):
    sound = parselmouth.Sound(str(write_tone(tmp_path / "q.wav", amplitude=0.0)))
    assert adaptive_pitch_bounds(
        sound, step=0.01,
        floor=config.PITCH_FLOOR_HZ, ceiling=config.PITCH_CEILING_HZ,
    ) == (config.PITCH_FLOOR_HZ, config.PITCH_CEILING_HZ)


def test_low_voice_produces_no_octave_outliers(tmp_path):
    # 回归：真实录音（94 Hz 男声）曾有 12% 的帧跳到 494 Hz，撑爆纵轴
    result = analyse(write_tone(tmp_path / "low.wav", freq=95.0))
    finite = result.semitones[np.isfinite(result.semitones)]
    assert finite.size > 0
    assert np.abs(finite).max() < 3.0


def test_bounds_are_median_based_not_quartile_based():
    # 取 200 Hz，除以跨度后仍高于 75 Hz 的地板，才测得出规则本身
    voiced = np.full(60, 200.0)
    low, high = bounds_from_voiced(voiced, floor=75.0, ceiling=500.0)
    assert low == pytest.approx(200.0 / config.PITCH_ADAPT_SPAN, abs=1.0)
    assert high == pytest.approx(200.0 * config.PITCH_ADAPT_SPAN, abs=1.0)


def test_bounds_never_go_below_the_floor():
    low, _ = bounds_from_voiced(np.full(60, 100.0), floor=75.0, ceiling=500.0)
    assert low == 75.0


def test_bounds_survive_heavy_octave_contamination():
    """实测某次录音三成帧被谐波骗到 470 Hz，四分位数因此失效，中位数不受影响。"""
    clean = np.full(40, 110.0)
    contaminated = np.concatenate([clean, np.full(18, 470.0)])
    low, high = bounds_from_voiced(contaminated, floor=75.0, ceiling=500.0)
    assert high < 300.0          # 没有被 470 Hz 拉走
    assert low < 110.0 < high


def test_bounds_work_with_only_a_handful_of_frames():
    # 0.7 秒的短句只有十来个浊音帧，门槛必须低于此
    low, high = bounds_from_voiced(np.full(6, 100.0), floor=75.0, ceiling=500.0)
    assert high < 500.0


def test_bounds_fall_back_when_almost_nothing_is_voiced():
    assert bounds_from_voiced(np.full(2, 100.0), floor=75.0, ceiling=500.0) == (75.0, 500.0)


def _speech(segments, duration=3.0):
    """按 (start, end, 起始半音, 结束半音) 造一段合成韵律。"""
    from shadow.analysis.prosody import Prosody

    times = np.arange(0.0, duration, 0.01)
    st = np.full(times.shape, np.nan)
    for start, end, head, tail in segments:
        mask = (times >= start) & (times < end)
        if mask.any():
            st[mask] = np.linspace(head, tail, mask.sum())
    return Prosody(times=times, f0_hz=np.full(times.shape, 120.0), semitones=st,
                   energy_db=np.zeros(times.shape), duration=duration)


def _words(spec):
    from shadow.models import Word

    return tuple(Word(text=t, start=a, end=b) for t, a, b in spec)


def test_terminal_fall_catches_a_drop_across_the_word_boundary():
    """was 收在 −2.7、born 从 −4.9 起：下坠跨在词边界上，词内指标会报成「升」。"""
    from shadow.analysis.prosody import terminal_fall, word_pitch

    prosody = _speech([(1.0, 1.4, -0.7, -2.7), (1.5, 2.0, -4.9, -1.7)])
    words = _words([("was", 1.0, 1.4), ("born", 1.5, 2.0)])
    within = word_pitch(prosody, 1.5, 2.0)
    assert within.move > 0                       # 词内看起来是升的
    assert terminal_fall(prosody, words) < -3.0  # 跨词看是明显下坠


def test_terminal_fall_also_covers_a_within_word_drop():
    from shadow.analysis.prosody import terminal_fall

    prosody = _speech([(1.0, 1.4, 0.0, 0.5), (1.5, 2.0, 1.0, -6.0)])
    words = _words([("that's", 1.0, 1.4), ("it", 1.5, 2.0)])
    assert terminal_fall(prosody, words) < -6.0


def test_terminal_fall_is_none_without_pitch():
    from shadow.analysis.prosody import terminal_fall

    prosody = _speech([])
    assert terminal_fall(prosody, _words([("a", 0.0, 0.5)])) is None
    assert terminal_fall(prosody, ()) is None


def test_word_trace_keeps_a_rise_then_fall_that_two_points_would_flatten(tmp_path):
    """句尾降调常是「先扬后抑」。只取首尾均值会把它画成上扬——真出过这个错。"""
    import numpy as np
    import soundfile as sf

    from shadow.analysis.prosody import analyse, word_trace

    sr = 16000
    t_ = np.arange(sr) / sr                       # 1 秒
    # 前半升 120→200 Hz，后半降回 100 Hz
    freq = np.where(t_ < 0.5, 120 + 160 * t_, 200 - 200 * (t_ - 0.5))
    phase = 2 * np.pi * np.cumsum(freq) / sr
    path = tmp_path / "arch.wav"
    sf.write(path, (0.4 * np.sin(phase)).astype("float32"), sr)

    prosody = analyse(path)
    trace = [v for v in word_trace(prosody, 0.05, 0.95) if v is not None]
    assert len(trace) >= 6

    peak = max(range(len(trace)), key=lambda i: trace[i])
    assert 0 < peak < len(trace) - 1                 # 峰在中间
    assert trace[peak] - trace[-1] > 3               # 峰之后确实沉下去了

    # 只看首尾（旧做法）看不出这个峰，这正是两点摘要不够用的地方
    assert max(trace[0], trace[-1]) < trace[peak]


def test_word_trace_marks_unvoiced_slots_as_none(tmp_path):
    import numpy as np
    import soundfile as sf

    from shadow.analysis.prosody import analyse, word_trace

    sr = 16000
    tone = 0.4 * np.sin(2 * np.pi * 150 * np.arange(sr // 2) / sr)
    path = tmp_path / "half.wav"
    sf.write(path, np.concatenate([tone, np.zeros(sr // 2)]).astype("float32"), sr)

    trace = analyse(path)
    values = word_trace(trace, 0.0, 1.0, points=10)
    assert len(values) == 10
    assert values[0] is not None
    assert values[-1] is None


def _write_sweep(path, pieces, sr=16000):
    """pieces: [(起始 Hz, 结束 Hz, 秒)]；0 Hz 表示静音。"""
    import numpy as np
    import soundfile as sf

    out = []
    for lo, hi, seconds in pieces:
        n = int(seconds * sr)
        if lo == 0:
            out.append(np.zeros(n))
            continue
        freq = np.linspace(lo, hi, n)
        out.append(0.4 * np.sin(2 * np.pi * np.cumsum(freq) / sr))
    sf.write(path, np.concatenate(out).astype("float32"), sr)
    return path


def test_word_pitch_reports_a_plain_fall(tmp_path):
    from shadow.analysis.prosody import analyse, word_pitch

    prosody = analyse(_write_sweep(tmp_path / "fall.wav", [(220, 110, 1.0)]))
    move = word_pitch(prosody, 0.05, 0.95).move

    assert move is not None
    assert -14 < move < -6          # 一个八度是 12 个半音，两头各截掉一点


def test_word_pitch_refuses_to_judge_an_arch(tmp_path):
    """先扬后抑用一个数说不清。宁可不判，也别给出与听感相反的结论。"""
    from shadow.analysis.prosody import analyse, word_pitch

    prosody = analyse(_write_sweep(tmp_path / "arch.wav",
                                   [(110, 220, 0.5), (220, 100, 0.5)]))
    assert word_pitch(prosody, 0.05, 0.95).move is None


def test_word_pitch_ignores_a_detached_blip_at_the_word_edge(tmp_path):
    """词边界是估出来的，末尾常蹭到下一个词的头。只认最长的那段连续浊音。"""
    from shadow.analysis.prosody import analyse, word_pitch

    prosody = analyse(_write_sweep(
        tmp_path / "blip.wav",
        [(220, 110, 0.8), (0, 0, 0.15), (300, 300, 0.1)],
    ))
    move = word_pitch(prosody, 0.05, 1.05).move

    assert move is not None
    assert move < -5                # 蹭进来的高音没有把降调翻成升调


def test_word_pitch_is_none_when_there_is_barely_any_voicing(tmp_path):
    from shadow.analysis.prosody import analyse, word_pitch

    prosody = analyse(_write_sweep(tmp_path / "quiet.wav",
                                   [(200, 200, 0.05), (0, 0, 0.9)]))
    assert word_pitch(prosody, 0.2, 0.9) is None


def test_word_pitch_keeps_both_halves_across_a_stop_consonant(tmp_path):
    """dropped 中间的 /p/ 本来就没有浊音。只认最长的一段会把前半个词丢掉，
    升调因此被判成没升——真出过这个错。"""
    from shadow.analysis.prosody import analyse, word_pitch

    prosody = analyse(_write_sweep(
        tmp_path / "stop.wav",
        [(110, 150, 0.4), (0, 0, 0.12), (170, 230, 0.5)],
    ))
    move = word_pitch(prosody, 0.02, 1.0).move

    assert move is not None
    assert move > 4          # 从 110Hz 一路升到 230Hz，一个八度多一点


def test_word_pitch_still_ignores_a_detached_blip(tmp_path):
    from shadow.analysis.prosody import analyse, word_pitch

    prosody = analyse(_write_sweep(
        tmp_path / "blip2.wav",
        [(220, 110, 0.8), (0, 0, 0.15), (300, 300, 0.1)],
    ))
    assert word_pitch(prosody, 0.05, 1.05).move < -5
