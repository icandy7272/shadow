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


def _source_with_a_gap(tmp_path):
    """0-1.2s 在说话，1.2-3.8s 一片静，3.8-6s 又在说话。"""
    sr = 16000
    t = np.arange(6 * sr) / sr
    voice = (0.4 * np.sin(2 * np.pi * 180 * t)).astype("float32")
    voice[int(1.2 * sr):int(3.8 * sr)] = 0.0
    path = tmp_path / "gap.wav"
    sf.write(path, voice, sr)
    return path


def _phantom():
    from shadow.models import Word

    return (Word(text="You", start=1.6, end=1.9), Word(text="know.", start=2.4, end=3.2))


def test_a_sentence_laid_over_silence_is_silent(tmp_path):
    """转写凭空编的句子会被强制对齐摊到停顿上：词速正常，音频里却没人说话。"""
    from shadow.models import Word

    source = _source_with_a_gap(tmp_path)
    spoken = (Word(text="One", start=0.1, end=0.5), Word(text="two.", start=0.6, end=1.0))

    assert not media.silent(source, spoken)
    assert media.silent(source, _phantom())


def test_a_missing_source_is_not_called_silent(tmp_path):
    """素材文件不在就判断不了。判不了就别拦——拦错了，那句就再也练不到。"""
    from shadow.models import Word

    words = (Word(text="a", start=0.1, end=0.5),)

    assert not media.silent(tmp_path / "gone.wav", words)
    assert not media.silent(None, words)


def test_an_unreadable_source_is_not_called_silent(tmp_path):
    """文件在、却读不出来（下到一半、坏了）也是判断不了，照样别拦——
    素材库页面也要数能练几句，不能因为一个坏文件整页报错。"""
    from shadow.models import Word

    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"RIFF")
    words = (Word(text="a", start=0.1, end=0.5),)

    assert not media.silent(broken, words)


def test_silence_is_rechecked_when_the_source_changes(tmp_path):
    """一份素材的能量只算一次——但文件换了，缓存得跟着失效。"""
    import os

    source = _source_with_a_gap(tmp_path)
    assert media.silent(source, _phantom())

    write_tone(source, seconds=6.0)
    stamp = source.stat().st_mtime + 10
    os.utime(source, (stamp, stamp))

    assert not media.silent(source, _phantom())


def test_unit_problem_names_why_a_sentence_cannot_be_practised(tmp_path):
    from shadow.models import Word

    source = _source_with_a_gap(tmp_path)
    crushed = tuple(Word(text=f"w{i}", start=4.0 + i * 0.02, end=4.02 + i * 0.02)
                    for i in range(14))
    spoken = (Word(text="Last", start=4.1, end=4.5), Word(text="one.", start=4.6, end=5.0))

    assert media.unit_problem(source, crushed) == media.PROBLEM_CRUSHED
    assert media.unit_problem(source, _phantom()) == media.PROBLEM_SILENT
    assert media.unit_problem(source, spoken) is None
