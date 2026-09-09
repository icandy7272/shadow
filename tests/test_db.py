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
