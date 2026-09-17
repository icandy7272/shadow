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


def test_two_takes_require_both_to_agree():
    # 两遍时「半数以上」等于「出现过一次」，等于没过滤
    s = summarise([take(items=[advice("stretched", 0, 2.0)]), take()])
    assert s.issues == ()
    s = summarise([take(items=[advice("stretched", 0, 2.0)]),
                   take(items=[advice("stretched", 0, 1.8)])])
    assert len(s.issues) == 1


def test_single_take_reports_everything_it_saw():
    s = summarise([take(items=[advice("stretched", 0, 2.0)])])
    assert len(s.issues) == 1
    assert s.issues[0].hits == 1


def test_five_takes_need_a_real_majority():
    items = [advice("stretched", 0, 1.5)]
    s = summarise([take(items=items), take(items=items), take(), take(), take()])
    assert s.issues == ()          # 2/5 不算反复出现
    s = summarise([take(items=items), take(items=items), take(items=items),
                   take(), take()])
    assert len(s.issues) == 1      # 3/5 算


def test_a_stumbled_take_is_not_the_one_we_draw():
    """实测：三遍里卡壳那遍停顿是原声的 5.3 倍，却因为语速正好居中被选中。
    画出来的图和逐词试听全来自这一遍，整张图就废了。"""
    takes = [take(accuracy=1.00, speech=1.11, pause=1.92),
             take(accuracy=0.93, speech=1.05, pause=5.34),   # 卡壳
             take(accuracy=0.93, speech=1.00, pause=1.14)]

    assert summarise(takes).representative != 1


def test_a_take_that_lost_words_is_not_the_one_we_draw():
    takes = [take(accuracy=1.0, speech=1.10, pause=1.0),
             take(accuracy=0.5, speech=1.00, pause=1.0),     # 半句没说出来
             take(accuracy=1.0, speech=0.90, pause=1.0)]

    assert summarise(takes).representative != 1


def test_with_nothing_wrong_it_still_picks_the_typical_one():
    """都正常的时候，挑最有代表性的那遍，不挑最好的。"""
    takes = [take(speech=0.80), take(speech=1.00), take(speech=1.30)]

    assert summarise(takes).representative == 1


def test_all_takes_stumbled_still_yields_one():
    takes = [take(accuracy=0.6, speech=1.0, pause=6.0),
             take(accuracy=0.6, speech=1.1, pause=6.5)]

    assert summarise(takes).representative in (0, 1)


@pytest.mark.parametrize("broken", [0, 1])
def test_with_two_takes_the_broken_one_is_not_drawn(broken):
    """两遍没有中位可言：两遍离中位一样远，原来总是挑第 1 遍——哪怕它念砸了。
    实测第 1 遍发声 10.55×、停顿 14.36×，照样标「代表这轮」，图全画的是它。
    （数值取能精确打平的，别让浮点误差替它碰巧选对）"""
    fine = take(speech=0.75, pause=1.0)
    bad = take(speech=1.25, pause=4.0)
    takes = [bad, fine] if broken == 0 else [fine, bad]

    assert summarise(takes).representative != broken


def test_with_two_takes_a_long_stall_counts_against_it():
    """语速一样偏离时，停顿拖得离谱的那遍不该入选。"""
    takes = [take(speech=1.125, pause=5.0), take(speech=0.875, pause=1.0)]

    assert summarise(takes).representative == 1
