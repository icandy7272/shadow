import pytest

from shadow import db
from shadow.ingest import pipeline
from shadow.ingest.downloader import DownloadError
from shadow.models import Word


@pytest.fixture()
def conn(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    connection = db.connect()
    db.init_db(connection)
    yield connection
    connection.close()


def fake_words():
    """160 词，第 79 词后有停顿 -> 应切成 2 段。

    实词 market（2 音节）0.7s、功能词 the（1 音节）0.1s，每对仍占 0.8s。
    这样 the 的弱读比值 = 0.1 / (1 x 32.0/120) = 0.375，低于 0.6 的严格阈值，
    会被 select_blanks 选中。若两者时长相同，1 音节的 the 反而显得「偏慢」
    （比值 1.5），一个空都挖不出来。
    """
    words, t = [], 0.0
    for i in range(160):
        text, duration = ("the", 0.1) if i % 2 else ("market", 0.7)
        words.append(Word(text=text, start=t, end=t + duration))
        t += duration + (0.5 if i == 79 else 0.0)
    return tuple(words)


@pytest.fixture()
def stub_externals(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "probe", lambda url: ("Talk", 100.0))
    monkeypatch.setattr(
        pipeline, "download_audio",
        lambda url, dest, workdir: (dest.write_bytes(b"RIFF"), dest)[1],
    )
    monkeypatch.setattr(pipeline, "transcribe_words", lambda path: fake_words())


def test_import_creates_ready_source_with_segments(conn, stub_externals):
    source_id = pipeline.import_source("https://x/y", conn=conn)
    row = db.get_source(conn, source_id)
    assert row["status"] == db.STATUS_READY
    assert row["audio_path"].endswith(f"{source_id}.wav")
    assert len(db.list_segments(conn, source_id)) == 2


def test_import_marks_blanks_on_segments(conn, stub_externals):
    source_id = pipeline.import_source("https://x/y", conn=conn)
    first = db.get_segment(conn, db.list_segments(conn, source_id)[0]["id"])
    assert any(word.is_blank for word in first["words"])


def test_import_rejects_overlong_source(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "probe", lambda url: ("Long", 3601.0))
    with pytest.raises(pipeline.ImportError_, match="60"):
        pipeline.import_source("https://x/y", conn=conn)
    assert db.list_sources(conn) == []


def test_import_records_failure_and_reraises(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "probe", lambda url: ("Talk", 100.0))

    def boom(url, dest, workdir):
        raise DownloadError("ERROR: Video unavailable")

    monkeypatch.setattr(pipeline, "download_audio", boom)

    with pytest.raises(DownloadError):
        pipeline.import_source("https://x/y", conn=conn)

    row = db.list_sources(conn)[0]
    assert row["status"] == db.STATUS_FAILED
    assert "Video unavailable" in row["error"]


def test_import_rejects_bad_url_before_touching_db(conn):
    with pytest.raises(Exception):
        pipeline.import_source("file:///etc/passwd", conn=conn)
    assert db.list_sources(conn) == []
