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
    assert links["chain"] is None
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


@pytest.mark.parametrize("last_day, issues, rating, due", [
    (TODAY - timedelta(days=1), 0, 4, True),       # 昨天练过
    (TODAY - timedelta(days=7), 2, 4, True),       # 上次还有问题没解决
    (TODAY - timedelta(days=7), 0, 2, True),       # 盲听没听懂
    (TODAY - timedelta(days=7), 0, 4, False),      # 早就练好了
    (TODAY - timedelta(days=7), 0, None, False),
    (TODAY, 3, 1, False),                          # 今天才练，明天再复习
    (None, 0, None, False),                        # 没练过
])
def test_what_counts_as_due_for_review(last_day, issues, rating, due):
    assert plan.needs_review(last_day, TODAY, issues=issues, rating=rating) is due


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

    db.set_plan_check(conn, "2026-09-14", "new", False)
    db.set_plan_check(conn, "2026-09-14", "chain", False)  # 没勾过的取消也不报错

    assert db.plan_checks(conn, "2026-09-14") == {"review"}
    assert db.plan_checks(conn, "2026-09-15") == {"review"}
    assert db.plan_checks(conn, "2026-09-16") == set()
