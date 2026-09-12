"""素材库：当前练哪份、每份的概况、彻底删除。"""

import pytest

from shadow import config, db, library, progress
from shadow.models import Segment, Word


@pytest.fixture()
def conn(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path / "data"))
    connection = db.connect()
    db.init_db(connection)
    yield connection
    connection.close()


def _ready(conn, title, *, practised=False):
    """一份能练的素材：两句话，原音和第 1 句的缓存都真写到磁盘上。"""
    source_id = db.create_source(conn, url=f"https://x/{title}", title=title,
                                 duration_sec=120.0)
    audio = config.source_audio_dir() / f"{source_id}.wav"
    audio.write_bytes(b"RIFF")
    db.finish_source(conn, source_id, audio_path=str(audio))
    words = (Word("One", 0.0, 0.4), Word("two.", 0.5, 0.9),
             Word("Three", 1.0, 1.4), Word("four.", 1.5, 1.9))
    db.insert_segments(conn, source_id, (Segment(idx=0, start=0.0, end=2.0, words=words),))
    segment_id = db.list_segments(conn, source_id)[0]["id"]
    (config.segment_audio_dir() / f"{segment_id}-u1.wav").write_bytes(b"RIFF")
    if practised:
        run_id = db.start_run(conn, segment_id=segment_id, unit_index=1, unit_text="One two.")
        take = config.attempt_audio_dir() / f"{segment_id}-u1-take-1.wav"
        take.write_bytes(b"RIFF")
        db.add_attempt(conn, run_id=run_id, audio_path=str(take), asr_text="One two.",
                       metrics={"issues": []})
        db.finish_run(conn, run_id)
    return source_id


def test_current_is_the_one_you_opened_last(conn):
    first = _ready(conn, "A")
    _ready(conn, "B")
    library.select(conn, first)
    assert library.current(conn) == first


def test_without_a_choice_current_is_the_last_practised_then_the_newest(conn):
    practised = _ready(conn, "A", practised=True)
    newest = _ready(conn, "B")
    assert library.current(conn) == practised
    db.delete_source(conn, practised)
    assert library.current(conn) == newest


def test_a_source_still_importing_is_never_current(conn):
    ready = _ready(conn, "A")
    busy = db.create_source(conn, url="https://x/b", title="B", duration_sec=0.0)
    library.select(conn, busy)
    assert library.current(conn) == ready


def test_nothing_ready_means_no_current(conn):
    assert library.current(conn) is None


def test_cards_show_progress_and_import_steps(conn):
    source_id = _ready(conn, "A", practised=True)
    busy = db.create_source(conn, url="https://x/b", title="https://x/b", duration_sec=0.0)
    db.set_source_status(conn, busy, db.STATUS_TRANSCRIBING)

    cards = library.cards(conn)
    by_id = {card.id: card for card in cards}

    ready = by_id[source_id]
    assert (ready.sentences, ready.practised, ready.rounds, ready.takes) == (2, 1, 1, 1)
    assert ready.minutes == pytest.approx(2.0)
    assert ready.step is None and ready.last_practised is not None
    assert by_id[busy].step == "转写"
    assert cards[0].id == busy          # 新导入的在前


def test_remove_deletes_rows_and_files_but_keeps_the_streak(conn):
    doomed = _ready(conn, "A", practised=True)
    kept = _ready(conn, "B")
    library.select(conn, doomed)
    before = progress.calendar(conn, weeks=2)

    after = library.remove(conn, doomed)

    assert after == kept
    assert db.get_source(conn, doomed) is None
    assert list(config.attempt_audio_dir().iterdir()) == []
    assert not (config.source_audio_dir() / f"{doomed}.wav").exists()
    kept_segment = db.list_segments(conn, kept)[0]["id"]
    assert [p.name for p in config.segment_audio_dir().iterdir()] == [f"{kept_segment}-u1.wav"]
    assert progress.calendar(conn, weeks=2) == before


def test_remove_refuses_while_importing(conn):
    busy = db.create_source(conn, url="https://x/b", title="B", duration_sec=0.0)
    with pytest.raises(library.LibraryError, match="导入"):
        library.remove(conn, busy)


def test_remove_never_touches_files_outside_the_data_folder(conn, tmp_path_factory):
    """库里记的路径不能拿来随便删。"""
    outside = tmp_path_factory.mktemp("elsewhere") / "keep.wav"
    outside.write_bytes(b"RIFF")
    source_id = db.create_source(conn, url="https://x/y", title="T", duration_sec=1.0)
    db.finish_source(conn, source_id, audio_path=str(outside))

    library.remove(conn, source_id)

    assert outside.exists()
