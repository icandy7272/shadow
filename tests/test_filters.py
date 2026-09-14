"""从筛选点进去练时，下一句在同一个筛选里找。纯函数。"""

from datetime import date, timedelta

import pytest

from shadow import filters

TODAY = date(2026, 9, 14)
NEVER = filters.State(runs=0, issues=0, rating=None, last_day=None)


def _state(**changes):
    base = {"runs": 1, "issues": 0, "rating": 4, "last_day": TODAY - timedelta(days=7)}
    return filters.State(**{**base, **changes})


@pytest.mark.parametrize("raw, name", [
    ("review", "review"), ("issues", "issues"), ("unheard", "unheard"), ("fresh", "fresh"),
    ("all", None), ("", None), (None, None), ("<script>", None),
])
def test_only_known_filters_make_a_queue(raw, name):
    assert filters.parse(raw) == name


def test_each_filter_uses_the_same_rule_as_the_list():
    assert filters.matches("review", _state(last_day=TODAY - timedelta(days=1)), TODAY)
    assert not filters.matches("review", _state(), TODAY)
    assert filters.matches("issues", _state(issues=2), TODAY)
    assert not filters.matches("issues", _state(), TODAY)
    assert filters.matches("unheard", _state(rating=2), TODAY)
    assert not filters.matches("unheard", _state(rating=3), TODAY)
    assert not filters.matches("unheard", NEVER, TODAY)
    assert filters.matches("fresh", NEVER, TODAY)
    assert not filters.matches("fresh", _state(), TODAY)


def test_next_skips_what_does_not_match_and_comes_back_round():
    flags = [True, False, False, True, False]
    assert filters.after(flags, 0) == 3
    assert filters.after(flags, 3) == 0          # 从中间点进来的，前面那些也要轮到
    assert filters.after([True, False], 0) is None
    assert filters.after([False, False], 1) is None


def test_previous_does_not_come_back_round():
    flags = [True, False, True, True]
    assert filters.before(flags, 3) == 2
    assert filters.before(flags, 2) == 0
    assert filters.before(flags, 0) is None


def test_remaining_leaves_out_the_sentence_you_are_on():
    assert filters.remaining([True, False, True, True], 2) == 2
    assert filters.remaining([True, True], 1) == 1
    assert filters.remaining([False, True], 1) == 0


def test_the_pager_says_which_filter_you_are_walking_through():
    assert filters.view("review", remaining=3) == {
        "name": "review", "title": "该复习", "label": "复习下一句",
        "done": "今天该复习的都练完了", "remaining": 3, "query": "?from=review"}
    assert filters.view("fresh", remaining=0)["label"] == "练下一句新的"
