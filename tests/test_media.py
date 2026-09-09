import numpy as np
import pytest
import soundfile as sf

from shadow import media
from shadow.media import AudioError


def write_tone(path, *, seconds=3.0, freq=220.0, sr=16000, amplitude=0.5):
    t = np.arange(int(seconds * sr)) / sr
    sf.write(path, (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)
    return path


def test_cut_segment_produces_expected_duration(tmp_path):
    source = write_tone(tmp_path / "src.wav", seconds=3.0)
    dest = tmp_path / "cut.wav"
    media.cut_segment(source, dest, start=1.0, end=2.0)
    info = sf.info(dest)
    assert info.duration == pytest.approx(1.0, abs=0.05)
    assert info.samplerate == 16000
    assert info.channels == 1


def test_probe_duration_matches(tmp_path):
    source = write_tone(tmp_path / "src.wav", seconds=2.5)
    assert media.probe_duration(source) == pytest.approx(2.5, abs=0.01)


def test_validate_attempt_rejects_too_short(tmp_path):
    source = write_tone(tmp_path / "s.wav", seconds=0.3)
    with pytest.raises(AudioError, match="过短"):
        media.validate_attempt(source)


def test_validate_attempt_rejects_silence(tmp_path):
    source = write_tone(tmp_path / "s.wav", seconds=2.0, amplitude=0.0)
    with pytest.raises(AudioError, match="静音"):
        media.validate_attempt(source)


def test_validate_attempt_accepts_normal_recording(tmp_path):
    source = write_tone(tmp_path / "s.wav", seconds=2.0, amplitude=0.3)
    media.validate_attempt(source)  # 不抛异常即通过
