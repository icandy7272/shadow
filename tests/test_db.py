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


def _source_with_practice(conn, *, title, text="It was."):
    source_id = db.create_source(conn, url=f"https://x/{title}", title=title,
                                 duration_sec=8.0)
    db.finish_source(conn, source_id, audio_path=f"/tmp/{title}.wav")
    db.insert_segments(conn, source_id, (Segment(
        idx=0, start=0.0, end=1.0,
        words=(Word("It", 0.0, 0.5), Word("was.", 0.5, 1.0))),))
    segment_id = db.list_segments(conn, source_id)[0]["id"]
    run_id = db.start_run(conn, segment_id=segment_id, unit_index=1, unit_text=text)
    db.add_attempt(conn, run_id=run_id, audio_path=f"/tmp/{title}-take.wav",
                   asr_text=text, metrics={"issues": []})
    db.finish_run(conn, run_id)
    return source_id, segment_id


def test_settings_round_trip(conn):
    assert db.get_setting(conn, "current_source") is None
    db.set_setting(conn, "current_source", "3")
    db.set_setting(conn, "current_source", "4")
    assert db.get_setting(conn, "current_source") == "4"
    db.set_setting(conn, "current_source", None)
    assert db.get_setting(conn, "current_source") is None


def test_importing_source_is_the_one_not_finished(conn):
    ready = db.create_source(conn, url="https://x/a", title="A", duration_sec=1.0)
    db.finish_source(conn, ready, audio_path="a.wav")
    assert db.importing_source(conn) is None
    busy = db.create_source(conn, url="https://x/b", title="B", duration_sec=0.0)
    db.set_source_status(conn, busy, db.STATUS_PROBING)
    assert db.importing_source(conn)["id"] == busy


def test_source_meta_is_filled_in_after_probing(conn):
    source_id = db.create_source(conn, url="https://x/y", title="https://x/y",
                                 duration_sec=0.0)
    db.update_source_meta(conn, source_id, title="Talk", duration_sec=90.0)
    row = db.get_source(conn, source_id)
    assert (row["title"], row["duration_sec"]) == ("Talk", 90.0)


def test_source_runs_and_takes_only_cover_that_source(conn):
    first, _ = _source_with_practice(conn, title="A")
    _source_with_practice(conn, title="B")
    assert len(db.source_runs(conn, first)) == 1
    assert db.count_takes(conn, first) == 1


def test_delete_source_leaves_nothing_behind(conn):
    """外键没有级联：素材下面的片段、练习记录、每遍录音都得一起删干净。"""
    doomed, doomed_segment = _source_with_practice(conn, title="A")
    kept, _ = _source_with_practice(conn, title="B")

    removed = db.delete_source(conn, doomed, archive=[("2026-09-10", "It was.", 1)])

    assert db.get_source(conn, doomed) is None
    assert db.list_segments(conn, doomed) == []
    assert db.source_runs(conn, doomed) == []
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    assert set(removed.audio_paths) == {"/tmp/A.wav", "/tmp/A-take.wav"}
    assert removed.segment_ids == (doomed_segment,)
    assert len(db.source_runs(conn, kept)) == 1
    assert [tuple(row) for row in db.list_archive(conn)] == [("2026-09-10", "It was.", 1)]


def test_set_dictation_records_unknown_words(conn):
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=1.0)
    db.insert_segments(conn, source_id, (
        Segment(idx=0, start=0.0, end=1.0, words=(Word("hi", 0.0, 1.0),)),
    ))
    segment_id = db.list_segments(conn, source_id)[0]["id"]
    run_id = db.start_run(conn, segment_id=segment_id, unit_index=1)

    db.set_dictation(conn, run_id, correct=2, total=4, unknown=1, replays=3)
    db.finish_run(conn, run_id)

    row = db.list_runs(conn)[0]
    assert (row["gapfill_correct"], row["gapfill_total"],
            row["gapfill_unknown"], row["gapfill_replays"]) == (2, 4, 1, 3)


def test_vocab_counts_times_and_keeps_every_sentence_once(conn):
    assert db.add_vocab(conn, "adoption", sentence="She refused.",
                        segment_id=3, unit_index=11) == 1
    assert db.add_vocab(conn, "adoption", sentence="She refused.",
                        segment_id=3, unit_index=11) == 2
    assert db.add_vocab(conn, "adoption", sentence="Final adoption papers.") == 3

    [item] = db.list_vocab(conn)

    assert (item["word"], item["times"]) == ("adoption", 3)
    assert [s["sentence"] for s in item["sources"]] == ["She refused.", "Final adoption papers."]
    assert item["sources"][0]["segment_id"] == 3
    assert db.vocab_words(conn) == {"adoption"}


def test_newest_vocab_comes_first(conn):
    db.add_vocab(conn, "older", sentence="A.")
    conn.execute("UPDATE vocab SET last_added = '2026-01-01T00:00:00+00:00' WHERE word = 'older'")
    db.add_vocab(conn, "newer", sentence="B.")
    assert [item["word"] for item in db.list_vocab(conn)] == ["newer", "older"]


def test_remove_vocab_takes_its_sentences_too(conn):
    db.add_vocab(conn, "adoption", sentence="She refused.")
    assert db.remove_vocab(conn, "adoption") is True
    assert db.list_vocab(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM vocab_sources").fetchone()[0] == 0
    assert db.remove_vocab(conn, "adoption") is False


def test_vocab_outlives_a_deleted_source(conn):
    """删素材是彻底删，但生词本是自己的，要留下。"""
    source_id, segment_id = _source_with_practice(conn, title="A")
    db.add_vocab(conn, "was", sentence="It was.", segment_id=segment_id, unit_index=1)

    db.delete_source(conn, source_id)

    assert [item["word"] for item in db.list_vocab(conn)] == ["was"]
