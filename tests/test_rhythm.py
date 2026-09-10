import pytest

from shadow.analysis.rhythm import analyse_rhythm, span, speech_time
from shadow.models import Word


def make(spec):
    """spec: [(text, start, duration), ...]"""
    return tuple(Word(text=t, start=s, end=s + d) for t, s, d in spec)


REF = make([("a", 0.0, 0.4), ("b", 0.9, 0.4), ("c", 1.3, 0.4)])   # a 后停 0.5s
ALL = ((0, 0), (1, 1), (2, 2))


def test_span_uses_first_and_last_word_not_file_length():
    assert span(REF) == pytest.approx(1.7)
    assert span(()) == 0.0


def test_speech_time_excludes_gaps():
    assert speech_time(REF) == pytest.approx(1.2)


def test_speech_and_pause_deviations_can_cancel_in_the_total():
    # 发声慢一半、停顿全丢：总时长却几乎不变，单看 span_ratio 会掩盖问题
    usr = make([("a", 0.0, 0.6), ("b", 0.6, 0.6), ("c", 1.2, 0.6)])
    r = analyse_rhythm(REF, usr, ALL)
    assert r.speech_ratio == pytest.approx(1.5)
    assert r.pause_ratio == pytest.approx(0.0)
    assert r.span_ratio == pytest.approx(1.06, abs=0.01)


def test_missed_pause_is_detected():
    usr = make([("a", 0.0, 0.4), ("b", 0.45, 0.4), ("c", 0.85, 0.4)])
    r = analyse_rhythm(REF, usr, ALL)
    by_text = {g.text: g for g in r.gaps}
    assert by_text["a"].ref_gap == pytest.approx(0.5)
    assert by_text["a"].usr_gap == pytest.approx(0.05)
    assert by_text["a"].missed is True
    assert by_text["b"].missed is False


def test_matched_pause_is_not_flagged():
    usr = make([("a", 0.0, 0.4), ("b", 0.9, 0.4), ("c", 1.3, 0.4)])
    r = analyse_rhythm(REF, usr, ALL)
    assert all(not g.missed for g in r.gaps)


def test_lag_accumulates_from_the_first_word():
    usr = make([("a", 0.0, 0.8), ("b", 1.3, 0.4), ("c", 1.7, 0.4)])
    r = analyse_rhythm(REF, usr, ALL)
    assert dict(r.lags)[0] == pytest.approx(0.0)
    assert dict(r.lags)[1] == pytest.approx(0.4)


def test_handles_unmatched_words():
    r = analyse_rhythm(REF, make([("a", 0.0, 0.4)]), ((0, 0),))
    assert r.gaps[0].usr_gap is None
    assert r.gaps[0].missed is False


def test_overdone_pause_is_detected():
    # 原声停 0.5s，用户停 1.2s：停过头和不停一样是毛病
    usr = make([("a", 0.0, 0.4), ("b", 1.6, 0.4), ("c", 2.0, 0.4)])
    gap = analyse_rhythm(REF, usr, ALL).gaps[0]
    assert gap.overdone is True
    assert gap.missed is False


def test_extra_pause_where_reference_has_none():
    # 原声 b→c 没有停顿，用户停了 0.4s
    usr = make([("a", 0.0, 0.4), ("b", 0.9, 0.4), ("c", 1.7, 0.4)])
    gap = analyse_rhythm(REF, usr, ALL).gaps[1]
    assert gap.ref_gap == pytest.approx(0.0)
    assert gap.overdone is True


def test_slightly_longer_pause_is_not_flagged():
    usr = make([("a", 0.0, 0.4), ("b", 0.98, 0.4), ("c", 1.38, 0.4)])
    assert analyse_rhythm(REF, usr, ALL).gaps[0].overdone is False


def test_pause_gap_carries_user_index():
    usr = make([("a", 0.0, 0.4), ("b", 0.9, 0.4), ("c", 1.3, 0.4)])
    assert analyse_rhythm(REF, usr, ALL).gaps[0].usr_index == 0


def _prosody(duration, loud_from, loud_to):
    import numpy as np

    from shadow.analysis.prosody import Prosody

    times = np.arange(0.0, duration, 0.01)
    energy = np.full(times.shape, -40.0)
    energy[(times >= loud_from) & (times <= loud_to)] = -5.0
    return Prosody(times=times, f0_hz=np.full(times.shape, 100.0),
                   semitones=np.zeros(times.shape), energy_db=energy,
                   duration=duration)


def test_speech_region_ignores_leading_and_trailing_silence():
    from shadow.analysis.rhythm import speech_region

    assert speech_region(_prosody(4.0, 0.5, 3.0)) == pytest.approx((0.5, 3.0), abs=0.02)


def test_speech_region_is_none_when_everything_is_quiet():
    from shadow.analysis.rhythm import speech_region

    assert speech_region(_prosody(2.0, 5.0, 5.0)) is None


def test_alignment_drift_catches_shifted_timestamps():
    """实测：0.17s 就开口，Whisper 却把整句定位到 3.64s 之后。"""
    from shadow.analysis.rhythm import alignment_drift

    words = make([("a", 3.64, 0.3), ("b", 4.0, 0.3)])
    assert alignment_drift(words, _prosody(6.0, 0.17, 3.0)) == pytest.approx(3.47, abs=0.05)


def test_alignment_drift_is_small_when_timestamps_are_sane():
    from shadow.analysis.rhythm import alignment_drift

    words = make([("a", 0.20, 0.3), ("b", 0.6, 0.3)])
    assert alignment_drift(words, _prosody(4.0, 0.17, 3.0)) < 0.1


def test_alignment_drift_is_none_without_audio_or_words():
    from shadow.analysis.rhythm import alignment_drift

    assert alignment_drift((), _prosody(2.0, 0.1, 1.0)) is None
    assert alignment_drift(make([("a", 0.0, 0.3)]), _prosody(2.0, 5.0, 5.0)) is None


def _tone_after(path, silence_sec, tone_sec=1.0, sr=16000):
    import numpy as np
    import soundfile as sf

    tone = 0.4 * np.sin(2 * np.pi * 150 * np.arange(int(tone_sec * sr)) / sr)
    sf.write(path, np.concatenate([np.zeros(int(silence_sec * sr)), tone]
                                  ).astype("float32"), sr)
    return path


def test_first_word_is_snapped_to_the_real_onset(tmp_path):
    """Whisper 常把首词起点铺到片段开头。词块因此被撑长、位置偏早，
    同时播放两条音轨也对不齐。"""
    from shadow.analysis.prosody import analyse
    from shadow.analysis.rhythm import snap_first_word
    from shadow.models import Word

    prosody = analyse(_tone_after(tmp_path / "late.wav", 0.4))
    words = (Word(text="a", start=0.0, end=0.7), Word(text="b", start=0.7, end=1.2))

    snapped = snap_first_word(words, prosody)

    assert snapped[0].start == pytest.approx(0.4, abs=0.05)
    assert snapped[0].end == 0.7          # 只挪起点
    assert snapped[1] == words[1]         # 后面的词不动
    assert words[0].start == 0.0          # 原序列没被改


def test_first_word_is_left_alone_when_it_already_matches(tmp_path):
    from shadow.analysis.prosody import analyse
    from shadow.analysis.rhythm import snap_first_word
    from shadow.models import Word

    prosody = analyse(_tone_after(tmp_path / "prompt.wav", 0.02))
    words = (Word(text="a", start=0.0, end=0.7),)

    assert snap_first_word(words, prosody) == words


def test_first_word_start_never_moves_earlier(tmp_path):
    """发声早于首词起点，说明可能漏了一个词，那是另一回事，别乱动。"""
    from shadow.analysis.prosody import analyse
    from shadow.analysis.rhythm import snap_first_word
    from shadow.models import Word

    prosody = analyse(_tone_after(tmp_path / "early.wav", 0.02))
    words = (Word(text="a", start=0.5, end=1.0),)

    assert snap_first_word(words, prosody) == words


def test_snapping_never_swallows_the_whole_word(tmp_path):
    from shadow.analysis.prosody import analyse
    from shadow.analysis.rhythm import snap_first_word
    from shadow.models import Word

    prosody = analyse(_tone_after(tmp_path / "very-late.wav", 0.8))
    words = (Word(text="a", start=0.0, end=0.5), Word(text="b", start=0.5, end=1.5))

    # 发声点已经越过首词的结尾，挪过去等于把这个词抹掉，那就别挪
    assert snap_first_word(words, prosody) == words
