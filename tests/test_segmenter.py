import pytest

from shadow.ingest.segmenter import split_into_segments
from shadow.models import Word

MIN, MAX, GAP = 30.0, 90.0, 0.4


def make_words(count, *, dur=0.5, gaps=None):
    """构造等长词序列；gaps 形如 {index: 该词之后的停顿秒数}。"""
    gaps = gaps or {}
    words, t = [], 0.0
    for i in range(count):
        words.append(Word(text=f"w{i}", start=t, end=t + dur))
        t += dur + gaps.get(i, 0.0)
    return tuple(words)


def split(words):
    return split_into_segments(words, min_sec=MIN, max_sec=MAX, pause_gap=GAP)


def test_empty_input_returns_empty():
    assert split(()) == ()


def test_short_input_yields_one_segment_even_below_min():
    segments = split(make_words(10))
    assert len(segments) == 1
    assert segments[0].idx == 0
    assert len(segments[0].words) == 10


def test_hard_cut_at_max_when_no_pause_exists():
    # 300 词 x 0.5s = 150s，全程无停顿
    segments = split(make_words(300))
    assert len(segments) == 2
    assert segments[0].duration == pytest.approx(90.0)
    assert segments[1].duration == pytest.approx(60.0)


def test_cuts_at_pause_rather_than_running_to_max():
    # 160 词 x 0.5s，第 79 词后有 0.5s 停顿 -> 应在 40s 处切，而不是拖到 90s
    segments = split(make_words(160, gaps={79: 0.5}))
    assert len(segments) == 2
    assert segments[0].duration == pytest.approx(40.0)
    assert segments[0].words[-1].text == "w79"


def test_short_tail_is_merged_into_previous_segment():
    # 停顿后只剩 10s，不足 min，应并回前段
    segments = split(make_words(100, gaps={79: 0.5}))
    assert len(segments) == 1
    assert segments[0].duration == pytest.approx(50.5)


def test_short_tail_is_not_merged_when_it_would_exceed_max():
    # 201 词无停顿：前段硬切在 90s，尾段 10.5s 不足 min。
    # 合并会得到 100.5s 超出 max_sec，因此必须保留为两段。
    segments = split(make_words(201))
    assert len(segments) == 2
    assert segments[0].duration == pytest.approx(90.0)
    assert segments[1].duration == pytest.approx(10.5)


def test_segment_indices_are_sequential_and_bounds_match_words():
    segments = split(make_words(300))
    assert [s.idx for s in segments] == [0, 1]
    for segment in segments:
        assert segment.start == segment.words[0].start
        assert segment.end == segment.words[-1].end
