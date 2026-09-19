"""日课：每天该做哪几步、哪些句子该复习、勾选按天存。"""

from datetime import date, timedelta

import pytest

from shadow import db, plan

TODAY = date(2026, 9, 14)      # 周一


def _keys(weekday):
    return [step.key for step in plan.steps_for(weekday)]


def test_weekdays_follow_the_30_minute_routine():
    for weekday in range(5):
        assert _keys(weekday) == ["review", "new", "chain", "retell", "extensive"]
    assert plan.heading(0) == "周一 · 30 分钟"
    assert plan.heading(4) == "周五 · 30 分钟"


def test_saturday_is_for_looking_back():
    assert _keys(5) == ["redo", "whole", "free_talk", "extensive"]
    assert plan.heading(5) == "周六 · 回顾"


def test_sunday_only_keeps_the_streak():
    assert _keys(6) == ["review", "extensive"]
    assert plan.heading(6) == "周日 · 轻松一天"


def test_links_point_at_review_and_the_next_sentence():
    links = {step.key: step.link for step in plan.steps_for(0)}
    assert links["review"] == plan.REVIEW
    assert links["new"] == plan.NEXT
    assert links["chain"] == plan.CHAIN      # 串起来也有了入口
    assert {step.key: step.link for step in plan.steps_for(5)}["redo"] == plan.REVIEW


def test_a_step_only_counts_on_the_days_it_belongs_to():
    assert plan.is_step(0, "chain")
    assert plan.is_step(5, "free_talk")
    assert not plan.is_step(6, "chain")
    assert not plan.is_step(0, "free_talk")
    assert not plan.is_step(0, "nonsense")


def test_nothing_still_says_fill_in_the_blanks():
    """填空早就改成默写了，日课里不能还是老说法。"""
    text = " ".join(step.title + step.detail
                    for weekday in range(7) for step in plan.steps_for(weekday))
    assert "填空" not in text
    assert "默写" in text


@pytest.mark.parametrize("rating, issues, result", [
    (5, 0, plan.ONWARD),        # 听懂了，问题也清了
    (4, 0, plan.ONWARD),
    (3, 0, plan.HOLD),          # 磕磕绊绊：不推进也不倒退
    (None, 0, plan.HOLD),       # 跳过盲听：不知道不等于练好了
    (2, 0, plan.AGAIN),         # 没听懂
    (5, 1, plan.AGAIN),         # 听懂了，但上次的问题还挂着
])
def test_one_round_pushes_the_interval_out_holds_it_or_sends_it_back(
        rating, issues, result):
    assert plan.result_of(rating=rating, issues=issues) == result


def test_the_interval_ladder_climbs_one_step_at_a_time():
    level = -1                                     # 没练过
    for expected in range(len(plan.INTERVALS)):
        level = plan.next_level(level, plan.ONWARD)
        assert level == expected
    assert plan.next_level(level, plan.ONWARD) == level       # 到顶就不再往后推

    assert plan.next_level(3, plan.HOLD) == 3
    assert plan.next_level(-1, plan.HOLD) == 0     # 第一次练完，明天再来
    assert plan.next_level(4, plan.AGAIN) == 0     # 打回 1 天


def test_the_first_round_comes_back_tomorrow_and_a_good_one_waits_longer():
    assert plan.due_day(TODAY, 0) == TODAY + timedelta(days=1)
    assert plan.due_day(TODAY, 2) == TODAY + timedelta(days=7)
    assert plan.due_day(TODAY, -1) == TODAY + timedelta(days=1)


@pytest.mark.parametrize("due, is_due", [
    (TODAY - timedelta(days=3), True),             # 逾期了
    (TODAY, True),
    (TODAY + timedelta(days=1), False),            # 还没到
    (None, False),                                 # 没练过
])
def test_only_sentences_that_came_due_get_reviewed(due, is_due):
    assert plan.is_due(due, TODAY) is is_due


def test_the_worst_sentences_come_first():
    def key(*, issues=0, rating=4, overdue=0):
        return plan.urgency(due=TODAY - timedelta(days=overdue), today=TODAY,
                            issues=issues, rating=rating)

    assert key(issues=1) < key(rating=1) < key()           # 老问题 > 没听懂 > 单纯到期
    assert key(overdue=5) < key(overdue=1)                 # 同一档里逾期久的在前
    assert key(issues=1, overdue=0) < key(rating=1, overdue=9)


@pytest.fixture()
def conn(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    connection = db.connect()
    db.init_db(connection)
    yield connection
    connection.close()


def test_ticks_are_kept_per_day(conn):
    db.set_plan_check(conn, "2026-09-14", "review", True)
    db.set_plan_check(conn, "2026-09-14", "new", True)
    db.set_plan_check(conn, "2026-09-14", "new", True)     # 重复勾选不报错
    db.set_plan_check(conn, "2026-09-15", "review", True)

    # 点掉记成「今天没做」，不是「没勾过」：系统自己看得出来的那几步要靠它压住自动勾
    db.set_plan_check(conn, "2026-09-14", "new", False)
    db.set_plan_check(conn, "2026-09-14", "chain", False)  # 没勾过的也能点掉

    assert db.plan_checks(conn, "2026-09-14") == {"review": True, "new": False, "chain": False}
    assert db.plan_checks(conn, "2026-09-15") == {"review": True}
    assert db.plan_checks(conn, "2026-09-16") == {}
