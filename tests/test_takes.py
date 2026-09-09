import pytest

from shadow.report.advice import Advice
from shadow.report.takes import TakeMetrics, summarise


def advice(kind, ref_index, score):
    return Advice(kind=kind, ref_index=ref_index, score=score, flag=kind,
                  title=f"{kind}@{ref_index}", detail="", action="")


def take(accuracy=1.0, speech=1.0, pause=1.0, items=()):
    return TakeMetrics(accuracy=accuracy, speech_ratio=speech,
                       pause_ratio=pause, advice=tuple(items))


def test_requires_at_least_one_take():
    with pytest.raises(ValueError):
        summarise([])


def test_reports_median_and_range():
    s = summarise([take(speech=1.0), take(speech=1.2), take(speech=1.1)])
    assert s.count == 3
    assert s.speech_ratio.median == pytest.approx(1.1)
    assert s.speech_ratio.low == pytest.approx(1.0)
    assert s.speech_ratio.high == pytest.approx(1.2)
    assert s.speech_ratio.width == pytest.approx(0.2)


def test_one_off_issue_is_filtered_out():
    # 只在 1/3 次里出现 —— 噪声，不该报
    s = summarise([
        take(items=[advice("stretched", 0, 2.0)]),
        take(), take(),
    ])
    assert s.issues == ()


def test_issue_in_majority_of_takes_is_kept():
    s = summarise([
        take(items=[advice("stretched", 0, 2.0)]),
        take(items=[advice("stretched", 0, 1.6)]),
        take(),
    ])
    assert len(s.issues) == 1
    assert s.issues[0].hits == 2
    assert s.issues[0].score == pytest.approx(1.8)   # 中位数
    assert s.issues[0].always is False


def test_consistency_outranks_severity():
    # 每次都犯的小问题，排在偶尔犯的大问题前面
    s = summarise([
        take(items=[advice("stretched", 0, 1.2), advice("flat_fall", 3, 9.0)]),
        take(items=[advice("stretched", 0, 1.3), advice("flat_fall", 3, 9.0)]),
        take(items=[advice("stretched", 0, 1.1)]),
    ])
    assert [i.advice.kind for i in s.issues] == ["stretched", "flat_fall"]
    assert s.issues[0].always is True


def test_duplicate_issue_within_one_take_counts_once():
    s = summarise([
        take(items=[advice("stretched", 0, 2.0), advice("stretched", 0, 1.0)]),
        take(), take(),
    ])
    assert s.issues == ()


def test_representative_take_is_closest_to_median_speed():
    s = summarise([take(speech=1.4), take(speech=1.0), take(speech=1.1)])
    assert s.representative == 2


def test_pause_ratio_absent_when_no_take_has_one():
    s = summarise([take(pause=None), take(pause=None)])
    assert s.pause_ratio is None
