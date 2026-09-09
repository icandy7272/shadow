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


def test_list_input_devices_parses_ffmpeg_output(monkeypatch):
    sample = (
        "[AVFoundation indev @ 0x1] AVFoundation video devices:\n"
        "[AVFoundation indev @ 0x1] [0] FaceTime HD Camera\n"
        "[AVFoundation indev @ 0x1] AVFoundation audio devices:\n"
        "[AVFoundation indev @ 0x1] [0] Studio Display XDR麦克风\n"
        "[AVFoundation indev @ 0x1] [1] MacBook Air麦克风\n"
        "[in#0 @ 0x2] Error opening input: Input/output error\n"
    )

    class Proc:
        returncode = 1
        stdout = ""
        stderr = sample

    monkeypatch.setattr(media.subprocess, "run", lambda *a, **k: Proc())
    assert media.list_input_devices() == (
        ("0", "Studio Display XDR麦克风"), ("1", "MacBook Air麦克风"),
    )


def test_record_surfaces_permission_hint_on_failure(monkeypatch, tmp_path):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "abort() called"

    monkeypatch.setattr(media.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(AudioError, match="麦克风"):
        media.record(tmp_path / "x.wav", seconds=1.0)


def test_play_repeats_and_counts(monkeypatch, tmp_path):
    source = write_tone(tmp_path / "p.wav", seconds=0.5)
    calls = []

    class Proc:
        returncode = 0
        stdout = stderr = ""

    monkeypatch.setattr(media.shutil, "which", lambda name: "/usr/bin/afplay")
    monkeypatch.setattr(media.subprocess, "run",
                        lambda cmd, **k: (calls.append(cmd), Proc())[1])
    monkeypatch.setattr(media.time, "sleep", lambda _: None)
    assert media.play(source, times=3, gap=0.1) == 3
    assert len(calls) == 3
    assert calls[0][0] == "/usr/bin/afplay" or "afplay" in calls[0][0]


def test_play_reports_when_no_player_exists(monkeypatch, tmp_path):
    source = write_tone(tmp_path / "p.wav", seconds=0.5)
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    with pytest.raises(AudioError, match="播放器"):
        media.play(source)
