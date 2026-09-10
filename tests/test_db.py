import pytest

from shadow import db
from shadow.models import Segment, Word


@pytest.fixture()
def conn(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    connection = db.connect()
    db.init_db(connection)
    yield connection
    connection.close()


def test_create_and_read_source(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=120.0)
    row = db.get_source(conn, source_id)
    assert row["title"] == "T"
    assert row["status"] == db.STATUS_PENDING
    assert row["error"] is None


def test_status_transitions_and_failure(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=1.0)
    db.set_source_status(conn, source_id, db.STATUS_TRANSCRIBING)
    assert db.get_source(conn, source_id)["status"] == db.STATUS_TRANSCRIBING
    db.fail_source(conn, source_id, "boom")
    row = db.get_source(conn, source_id)
    assert row["status"] == db.STATUS_FAILED
    assert row["error"] == "boom"


def test_insert_and_list_segments(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=60.0)
    segments = (
        Segment(idx=0, start=0.0, end=1.0, words=(Word("hi", 0.0, 1.0, is_blank=True),)),
    )
    db.insert_segments(conn, source_id, segments)
    listed = db.list_segments(conn, source_id)
    assert len(listed) == 1
    assert listed[0]["text"] == "hi"
    stored = db.get_segment(conn, listed[0]["id"])
    assert stored["words"][0].is_blank is True


def test_reset_stale_sources_marks_non_terminal_as_failed(conn):
    stuck = db.create_source(conn, url="https://x/1", title="A", duration_sec=1.0)
    db.set_source_status(conn, stuck, db.STATUS_DOWNLOADING)
    done = db.create_source(conn, url="https://x/2", title="B", duration_sec=1.0)
    db.finish_source(conn, done, audio_path="/tmp/a.wav")

    db.reset_stale_sources(conn)

    assert db.get_source(conn, stuck)["status"] == db.STATUS_FAILED
    assert db.get_source(conn, done)["status"] == db.STATUS_READY


def test_migration_adds_columns_to_an_existing_database(monkeypatch, tmp_path):
    """老库是 M1 建的，没有 unit_index / metrics_json 两列。"""
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    old = db.connect()
    old.executescript(db.SCHEMA)      # 只建表，不跑迁移
    old.commit()
    cols = {r["name"] for r in old.execute("PRAGMA table_info(practice_runs)")}
    assert "unit_index" not in cols
    db.init_db(old)                   # 迁移应就地补列
    cols = {r["name"] for r in old.execute("PRAGMA table_info(practice_runs)")}
    assert "unit_index" in cols
    assert "metrics_json" in {r["name"] for r in old.execute("PRAGMA table_info(attempts)")}
    db.init_db(old)                   # 再跑一次不应报错
    old.close()


def test_practice_run_records_takes_and_metrics(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=60.0)
    db.insert_segments(conn, source_id, (
        Segment(idx=0, start=0.0, end=1.0, words=(Word("hi", 0.0, 1.0),)),
    ))
    segment_id = db.list_segments(conn, source_id)[0]["id"]

    run_id = db.start_run(conn, segment_id=segment_id, unit_index=1)
    assert db.list_runs(conn) == []          # 未完成的不计入
    db.add_attempt(conn, run_id=run_id, audio_path="/tmp/a.wav", asr_text="hi",
                   metrics={"accuracy": 1.0, "speech_ratio": 1.1})
    db.add_attempt(conn, run_id=run_id, audio_path="/tmp/b.wav", asr_text="hi",
                   metrics={"accuracy": 0.9, "speech_ratio": 1.2})
    db.finish_run(conn, run_id)

    runs = db.list_runs(conn, segment_id=segment_id, unit_index=1)
    assert len(runs) == 1
    metrics = db.run_metrics(conn, run_id)
    assert [m["speech_ratio"] for m in metrics] == [1.1, 1.2]


def test_list_runs_filters_by_unit(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=60.0)
    db.insert_segments(conn, source_id, (
        Segment(idx=0, start=0.0, end=1.0, words=(Word("hi", 0.0, 1.0),)),
    ))
    segment_id = db.list_segments(conn, source_id)[0]["id"]
    for unit in (1, 2):
        run_id = db.start_run(conn, segment_id=segment_id, unit_index=unit)
        db.finish_run(conn, run_id)
    assert len(db.list_runs(conn, segment_id=segment_id)) == 2
    assert len(db.list_runs(conn, segment_id=segment_id, unit_index=2)) == 1


def test_empty_run_is_discarded(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=60.0)
    db.insert_segments(conn, source_id, (
        Segment(idx=0, start=0.0, end=1.0, words=(Word("hi", 0.0, 1.0),)),
    ))
    segment_id = db.list_segments(conn, source_id)[0]["id"]
    run_id = db.start_run(conn, segment_id=segment_id, unit_index=1)
    db.finish_run(conn, run_id)
    assert db.discard_if_empty(conn, run_id) is True
    assert db.list_runs(conn) == []


def test_run_with_any_data_is_kept(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=60.0)
    db.insert_segments(conn, source_id, (
        Segment(idx=0, start=0.0, end=1.0, words=(Word("hi", 0.0, 1.0),)),
    ))
    segment_id = db.list_segments(conn, source_id)[0]["id"]
    for setter in (lambda r: db.set_blind_rating(conn, r, 3),
                   lambda r: db.set_gapfill(conn, r, 1, 2)):
        run_id = db.start_run(conn, segment_id=segment_id, unit_index=1)
        setter(run_id)
        db.finish_run(conn, run_id)
        assert db.discard_if_empty(conn, run_id) is False
    assert len(db.list_runs(conn)) == 2
