"""每日练习格子。鼓励的是「今天练了没有」，不是总量。"""

from datetime import datetime, timedelta, timezone

import pytest

from shadow import db, progress


def _seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    conn = db.connect()
    db.init_db(conn)
    source = db.create_source(conn, url="https://x/y", title="T", duration_sec=8.0)
    db.finish_source(conn, source, audio_path="a.wav")
    from shadow.models import Segment, Word
    words = (Word(text="It", start=0.0, end=0.3),)
    db.insert_segments(conn, source, (Segment(idx=0, start=0.0, end=1.0, words=words),))
    return conn, db.list_segments(conn, source)[0]["id"]


def _round(conn, segment_id, unit, days_ago):
    """直接写库：start_run 只会记当下，测不了过去的日子。"""
    stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(
        timespec="seconds")
    cursor = conn.execute(
        "INSERT INTO practice_runs (segment_id, unit_index, unit_text, started_at,"
        " finished_at) VALUES (?, ?, ?, ?, ?)",
        (segment_id, unit, f"句子 {unit}", stamp, stamp),
    )
    run_id = int(cursor.lastrowid)
    db.add_attempt(conn, run_id=run_id, audio_path="x.wav", asr_text="It",
                   metrics={"accuracy": 1.0, "speech_ratio": 1.0,
                            "pause_ratio": None, "issues": []})
    conn.commit()
    return run_id


def test_an_empty_history_still_fills_the_grid(tmp_path, monkeypatch):
    conn, _ = _seeded(tmp_path, monkeypatch)

    calendar = progress.calendar(conn, weeks=4)

    assert len(calendar.days) % 7 == 0
    assert calendar.today == 0
    assert calendar.streak == 0
    assert all(day.sentences == 0 for day in calendar.days)


def test_counts_distinct_sentences_and_rounds_per_day(tmp_path, monkeypatch):
    conn, segment_id = _seeded(tmp_path, monkeypatch)
    _round(conn, segment_id, 1, 0)
    _round(conn, segment_id, 1, 0)          # 同一句练两轮
    _round(conn, segment_id, 2, 0)

    calendar = progress.calendar(conn, weeks=4)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d")
    today = next(d for d in calendar.days if d.date == stamp)

    assert today.sentences == 2
    assert today.rounds == 3
    assert calendar.today == 2


def test_streak_counts_back_from_today(tmp_path, monkeypatch):
    conn, segment_id = _seeded(tmp_path, monkeypatch)
    for ago in (0, 1, 2, 5):
        _round(conn, segment_id, 1, ago)

    assert progress.calendar(conn, weeks=4).streak == 3


def test_a_gap_today_does_not_break_yesterdays_streak(tmp_path, monkeypatch):
    """今天还没练不等于断了。早上一打开就显示 0，会劝退。"""
    conn, segment_id = _seeded(tmp_path, monkeypatch)
    for ago in (1, 2):
        _round(conn, segment_id, 1, ago)

    calendar = progress.calendar(conn, weeks=4)

    assert calendar.today == 0
    assert calendar.streak == 2


def test_runs_with_no_recording_do_not_count(tmp_path, monkeypatch):
    conn, segment_id = _seeded(tmp_path, monkeypatch)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO practice_runs (segment_id, unit_index, unit_text, started_at,"
        " finished_at) VALUES (?, ?, ?, ?, ?)",
        (segment_id, 1, "句子 1", stamp, stamp),
    )
    conn.commit()

    assert progress.calendar(conn, weeks=4).today == 0


def test_level_scales_with_the_busiest_day(tmp_path, monkeypatch):
    conn, segment_id = _seeded(tmp_path, monkeypatch)
    for unit in range(1, 5):
        _round(conn, segment_id, unit, 0)
    _round(conn, segment_id, 1, 1)

    calendar = progress.calendar(conn, weeks=4)
    levels = {day.date: day.level for day in calendar.days if day.sentences}

    assert max(levels.values()) == 4
    assert min(levels.values()) == 1
    assert all(day.level == 0 for day in calendar.days if not day.sentences)


def test_week_total_covers_the_last_seven_days(tmp_path, monkeypatch):
    conn, segment_id = _seeded(tmp_path, monkeypatch)
    _round(conn, segment_id, 1, 0)
    _round(conn, segment_id, 2, 3)
    _round(conn, segment_id, 3, 9)          # 超出一周

    assert progress.calendar(conn, weeks=4).week == 2


@pytest.mark.parametrize("weeks", [1, 8, 26])
def test_the_grid_covers_whole_weeks_and_reaches_today(tmp_path, monkeypatch, weeks):
    conn, _ = _seeded(tmp_path, monkeypatch)
    calendar = progress.calendar(conn, weeks=weeks)
    today = datetime.now().astimezone().strftime("%Y-%m-%d")

    assert len(calendar.days) % 7 == 0
    here = [d for d in calendar.days if d.date == today]
    assert here and not here[0].future
    # 本周还没到的日子只占位，不该被当成「没练」
    assert all(d.future for d in calendar.days if d.date > today)


def test_deleting_a_source_keeps_the_grid_and_streak(tmp_path, monkeypatch):
    """删素材是彻底删，但每天练了几句、连续几天得留下来。"""
    conn, segment_id = _seeded(tmp_path, monkeypatch)
    for unit, days_ago in ((1, 0), (1, 0), (2, 1), (3, 2)):
        _round(conn, segment_id, unit=unit, days_ago=days_ago)
    source_id = db.get_segment(conn, segment_id)["source_id"]
    before = progress.calendar(conn, weeks=4)

    db.delete_source(conn, source_id, archive=progress.archive_rows(conn, source_id))

    after = progress.calendar(conn, weeks=4)
    assert after == before
    assert (after.today, after.streak) == (1, 3)
