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
