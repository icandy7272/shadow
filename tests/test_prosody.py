import numpy as np
import pytest
import soundfile as sf

import parselmouth

from shadow import config
from shadow.analysis.prosody import adaptive_pitch_bounds, analyse

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
