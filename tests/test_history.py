"""上一次练这句留下的东西。给「跟读」那一步用，不能提前给到盲听。"""

from shadow import db, history


def _run(conn, *, segment_id, unit, issues_per_take, finished=True):
    run_id = db.start_run(conn, segment_id=segment_id, unit_index=unit,
                          unit_text="It was a start.")
    for titles in issues_per_take:
        db.add_attempt(
            conn, run_id=run_id, audio_path="x.wav", asr_text="It was a start.",
            metrics={"accuracy": 1.0, "speech_ratio": 1.1, "pause_ratio": None,
                     "issues": [{"kind": "stretched", "ref_index": 0,
                                 "score": 1.0, "title": t} for t in titles]},
        )
    if finished:
        db.finish_run(conn, run_id)
    return run_id


def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    conn = db.connect()
    db.init_db(conn)
    source = db.create_source(conn, url="https://x/y", title="T", duration_sec=8.0)
    db.finish_source(conn, source, audio_path="a.wav")
    from shadow.models import Segment, Word
    words = (Word(text="It", start=0.0, end=0.3),)
    db.insert_segments(conn, source, (Segment(idx=0, start=0.0, end=1.0, words=words),))
    return conn, db.list_segments(conn, source)[0]["id"]


def test_nothing_to_show_for_a_sentence_never_practised(tmp_path, monkeypatch):
    conn, segment_id = _db(tmp_path, monkeypatch)
    assert history.last_practice(conn, segment_id, 1) is None


def test_only_problems_that_came_back_are_kept(tmp_path, monkeypatch):
    """三遍里犯两次才算数。偶尔一次的不该带到下次练习去。"""
    conn, segment_id = _db(tmp_path, monkeypatch)
    _run(conn, segment_id=segment_id, unit=1, issues_per_take=[
        ["“It” 拖长了", "“was” 该降没降"],
        ["“It” 拖长了"],
        ["“It” 拖长了", "“a” 音高偏高"],
    ])

    last = history.last_practice(conn, segment_id, 1)

    assert last.times == 1
    assert last.issues == ("“It” 拖长了",)


def test_it_reports_the_latest_run_and_counts_them_all(tmp_path, monkeypatch):
    conn, segment_id = _db(tmp_path, monkeypatch)
    _run(conn, segment_id=segment_id, unit=1, issues_per_take=[["旧问题"], ["旧问题"]])
    _run(conn, segment_id=segment_id, unit=1, issues_per_take=[["新问题"], ["新问题"]])

    last = history.last_practice(conn, segment_id, 1)

    assert last.times == 2
    assert last.issues == ("新问题",)
    assert len(last.when) == 10          # YYYY-MM-DD


def test_runs_without_a_recording_do_not_count(tmp_path, monkeypatch):
    """只做了盲听、没录音的一轮，没有可带走的东西。"""
    conn, segment_id = _db(tmp_path, monkeypatch)
    _run(conn, segment_id=segment_id, unit=1, issues_per_take=[])

    assert history.last_practice(conn, segment_id, 1) is None


def test_a_clean_run_is_remembered_as_clean(tmp_path, monkeypatch):
    conn, segment_id = _db(tmp_path, monkeypatch)
    _run(conn, segment_id=segment_id, unit=1, issues_per_take=[[], [], []])

    last = history.last_practice(conn, segment_id, 1)

    assert last is not None
    assert last.issues == ()
