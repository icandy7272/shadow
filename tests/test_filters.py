"""从筛选点进去练时，下一句在同一个筛选里找。纯函数。"""

from datetime import date, timedelta

import pytest

from shadow import filters, plan

TODAY = date(2026, 9, 14)
NEVER = filters.State(runs=0, issues=0, rating=None, last_day=None)


def _state(**changes):
    base = {"runs": 1, "issues": 0, "rating": 4, "last_day": TODAY - timedelta(days=7),
            "due": TODAY + timedelta(days=7)}
    return filters.State(**{**base, **changes})


def _due(days_over=0, **changes):
    """一句到期该复习的话。days_over 是逾期几天。"""
    return _state(due=TODAY - timedelta(days=days_over), **changes)


def _queue(*states, usable=None):
    return filters.select(filters.REVIEW, states, TODAY, usable=usable)


@pytest.mark.parametrize("raw, name", [
    ("review", "review"), ("issues", "issues"), ("unheard", "unheard"), ("fresh", "fresh"),
    ("all", None), ("", None), (None, None), ("<script>", None),
])
def test_only_known_filters_make_a_queue(raw, name):
    assert filters.parse(raw) == name


def test_each_filter_uses_the_same_rule_as_the_list():
    assert filters.matches("review", _due(), TODAY)
    assert not filters.matches("review", _state(), TODAY)
    assert filters.matches("issues", _state(issues=2), TODAY)
    assert not filters.matches("issues", _state(), TODAY)
    assert filters.matches("unheard", _state(rating=2), TODAY)
    assert not filters.matches("unheard", _state(rating=3), TODAY)
    assert not filters.matches("unheard", NEVER, TODAY)
    assert filters.matches("fresh", NEVER, TODAY)
    assert not filters.matches("fresh", _state(), TODAY)


def test_most_filters_keep_the_order_of_the_material():
    picked = filters.select("fresh", [NEVER, _state(), NEVER], TODAY)
    assert picked == filters.Selection(order=(0, 2))


def test_a_sentence_you_cannot_practise_is_left_out():
    """音频里没有这句的，既不该占复习名额，也不该被「下一句」送进去。"""
    picked = _queue(_due(), _due(), usable=[False, True])
    assert picked.order == (1,)


def test_review_puts_the_worst_sentences_first():
    picked = _queue(_due(),                      # 单纯到期
                    _due(rating=1),              # 没听懂
                    _due(issues=2),              # 老问题没解决
                    _due(days_over=9))           # 逾期最久的到期句
    assert picked.order == (2, 1, 3, 0)
    assert picked.resorted


def test_review_stops_at_the_daily_cap_and_defers_the_rest():
    """不封顶的话积压会滚雪球，最后每天都在读前面那几句。"""
    picked = _queue(*[_due(days_over=over) for over in range(plan.DAILY_REVIEW + 3)])

    assert len(picked.order) == plan.DAILY_REVIEW
    assert len(picked.deferred) == 3
    assert picked.order[0] == plan.DAILY_REVIEW + 2      # 逾期最久的先练
    assert set(picked.order) | set(picked.deferred) == set(range(plan.DAILY_REVIEW + 3))


def test_what_you_reviewed_today_takes_up_the_days_quota():
    """练一句、后面又补上来一句的话，这个上限就形同虚设。"""
    done = _state(runs=2, last_day=TODAY)
    picked = _queue(*[done] * 3, *[_due()] * plan.DAILY_REVIEW)

    assert len(picked.order) == plan.DAILY_REVIEW - 3
    assert len(picked.deferred) == 3
    # 今天第一次练的那些不是复习，不占名额
    fresh_today = _state(runs=1, last_day=TODAY)
    assert len(_queue(*[fresh_today] * 3, *[_due()] * plan.DAILY_REVIEW).order) \
        == plan.DAILY_REVIEW


def test_next_skips_what_does_not_match_and_comes_back_round():
    picked = filters.Selection(order=(0, 3))
    assert filters.after(picked, 0) == 3
    assert filters.after(picked, 3) == 0          # 从中间点进来的，前面那些也要轮到
    assert filters.after(picked, 1) == 3
    assert filters.after(filters.Selection(order=(0,)), 0) is None
    assert filters.after(filters.Selection(), 1) is None


def test_next_does_not_come_back_round_when_walking_the_whole_material():
    picked = filters.Selection(order=(0, 1, 2))
    assert filters.after(picked, 1, wrap=False) == 2
    assert filters.after(picked, 2, wrap=False) is None


def test_the_review_queue_walks_by_urgency_not_by_the_order_of_the_material():
    picked = _queue(_due(), _due(issues=1))       # 第 1 句更急，排在前面
    assert picked.order == (1, 0)
    assert filters.after(picked, 1) == 0
    assert filters.before(picked, 0) == 1
    # 刚练完的那句已经不到期了，接着走队头那句——最急的
    assert filters.after(filters.Selection(order=(2, 0), resorted=True), 1) == 2


def test_previous_does_not_come_back_round():
    picked = filters.Selection(order=(0, 2, 3))
    assert filters.before(picked, 3) == 2
    assert filters.before(picked, 2) == 0
    assert filters.before(picked, 0) is None
    assert filters.before(picked, 1) == 0


def test_remaining_leaves_out_the_sentence_you_are_on():
    assert filters.remaining(filters.Selection(order=(0, 2, 3)), 2) == 2
    assert filters.remaining(filters.Selection(order=(0, 1)), 1) == 1
    assert filters.remaining(filters.Selection(order=(1,)), 0) == 1


def test_the_pager_says_which_filter_you_are_walking_through():
    assert filters.view("review", remaining=3) == {
        "name": "review", "title": "该复习", "label": "复习下一句",
        "done": "今天该复习的都练完了", "remaining": 3, "query": "?from=review"}
    assert filters.view("fresh", remaining=0)["label"] == "练下一句新的"
