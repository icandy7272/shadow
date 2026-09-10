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


def test_cue_is_generated_once_and_reused(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    first = media.ensure_cue()
    assert first.exists()
    stamp = first.stat().st_mtime_ns
    assert media.ensure_cue().stat().st_mtime_ns == stamp   # 不重新生成
    info = sf.info(first)
    assert 0.05 < info.duration < 0.5
    assert info.samplerate == 16000


def test_beep_never_breaks_recording(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "play", lambda *a, **k: (_ for _ in ()).throw(
        AudioError("没有播放器")))
    media.beep()        # 吞掉异常，不抛


class FakeProcess:
    def __init__(self, dest, *, finishes_after=None):
        self.dest = dest
        self.stdin = self
        self.written = []
        self._polls = 0
        self._finishes_after = finishes_after

    def write(self, text):
        self.written.append(text)

    def flush(self):
        pass

    def poll(self):
        self._polls += 1
        if self._finishes_after is not None and self._polls > self._finishes_after:
            return 0
        return None

    def communicate(self, timeout=None):
        write_tone(self.dest, seconds=1.0)
        return "", ""

    def terminate(self):
        pass

    def kill(self):
        pass


def test_record_stops_when_you_press_enter(monkeypatch, tmp_path):
    dest = tmp_path / "r.wav"
    fake = FakeProcess(dest)
    monkeypatch.setattr(media.subprocess, "Popen", lambda *a, **k: fake)
    monkeypatch.setattr(media.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(media.sys.stdin, "readline", lambda: "\n", raising=False)
    monkeypatch.setattr(media.select, "select", lambda *a: ([media.sys.stdin], [], []))
    media.record(dest, seconds=30.0)
    assert fake.written == ["q"]        # 用 q 让 ffmpeg 正常收尾，别 kill 掉丢文件


def test_record_runs_to_the_cap_without_input(monkeypatch, tmp_path):
    dest = tmp_path / "r.wav"
    fake = FakeProcess(dest, finishes_after=2)
    monkeypatch.setattr(media.subprocess, "Popen", lambda *a, **k: fake)
    monkeypatch.setattr(media.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(media.select, "select", lambda *a: ([], [], []))
    media.record(dest, seconds=1.0)
    assert fake.written == []


def test_record_reports_failure_when_nothing_was_written(monkeypatch, tmp_path):
    class Empty(FakeProcess):
        def communicate(self, timeout=None):
            return "", "abort() called"

    dest = tmp_path / "missing.wav"
    monkeypatch.setattr(media.subprocess, "Popen", lambda *a, **k: Empty(dest))
    monkeypatch.setattr(media.sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(AudioError, match="麦克风"):
        media.record(dest, seconds=1.0)


def test_unit_bounds_cuts_in_the_pause_not_where_the_transcript_says(tmp_path):
    """转写常整体偏早几百毫秒。照它裁，上一句的尾巴会被带进来。"""
    import numpy as np
    import soundfile as sf

    from shadow import media
    from shadow.models import Word

    sr = 16000
    tone = lambda n: 0.4 * np.sin(2 * np.pi * 180 * np.arange(n) / sr)  # noqa: E731
    # 上一句 0.0-1.0，真正的停顿 1.0-1.25，本句 1.25-2.2
    source = tmp_path / "src.wav"
    sf.write(source, np.concatenate([
        tone(int(1.0 * sr)), np.zeros(int(0.25 * sr)), tone(int(0.95 * sr)),
    ]).astype("float32"), sr)

    # 转写偏早 0.3 秒：说本句从 0.95 开始
    words = (Word(text="but", start=0.95, end=1.6), Word(text="then", start=1.6, end=2.1))
    start, end = media.unit_bounds(source, words, low=0.0, high=2.2)

    assert 1.05 < start < 1.22          # 落在停顿里，而不是 0.85
    assert end == pytest.approx(2.2, abs=0.01)


def test_unit_bounds_falls_back_when_the_words_run_together(tmp_path):
    """句子之间没有停顿时，只能信时间戳，照旧留一点余量。"""
    import numpy as np
    import soundfile as sf

    from shadow import config, media
    from shadow.models import Word

    sr = 16000
    source = tmp_path / "solid.wav"
    sf.write(source, (0.4 * np.sin(2 * np.pi * 180 * np.arange(2 * sr) / sr)
                      ).astype("float32"), sr)

    words = (Word(text="a", start=0.6, end=1.4),)
    start, _end = media.unit_bounds(source, words, low=0.0, high=2.0)

    assert start == pytest.approx(0.6 - config.UNIT_PAD_SEC, abs=0.01)
