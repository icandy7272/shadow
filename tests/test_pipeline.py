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
    """160 词，第 79 词后有停顿 -> 应切成 2 段。"""
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


def test_import_rejects_overlong_source(conn, monkeypatch):
    monkeypatch.setattr(pipeline, "probe", lambda url: ("Long", 3601.0))
    with pytest.raises(pipeline.ImportError_, match="60"):
        pipeline.import_source("https://x/y", conn=conn)
    # 记录留着、标成失败：素材库里要能看到为什么没导进来
    row = db.list_sources(conn)[0]
    assert row["status"] == db.STATUS_FAILED
    assert "60" in row["error"]


def test_begin_import_returns_at_once_with_the_link_as_title(conn, monkeypatch):
    """网页导入要让卡片马上出现，查标题要联网，不能卡在这一步。"""
    monkeypatch.setattr(pipeline, "probe", lambda url: pytest.fail("这一步不该联网"))
    source_id = pipeline.begin_import("https://x/y", conn=conn)
    row = db.get_source(conn, source_id)
    assert (row["status"], row["title"]) == (db.STATUS_PENDING, "https://x/y")


def test_begin_import_rejects_a_non_http_link(conn):
    with pytest.raises(DownloadError):
        pipeline.begin_import("ftp://x/y", conn=conn)
    assert db.list_sources(conn) == []


def test_run_import_walks_through_every_status(conn, stub_externals, monkeypatch):
    seen = []
    real = db.set_source_status
    monkeypatch.setattr(pipeline.db, "set_source_status",
                        lambda c, i, s: (seen.append(s), real(c, i, s)))
    source_id = pipeline.begin_import("https://x/y", conn=conn)

    pipeline.run_import(source_id, conn=conn)

    assert seen == [db.STATUS_PROBING, db.STATUS_DOWNLOADING,
                    db.STATUS_TRANSCRIBING, db.STATUS_SEGMENTING]
    row = db.get_source(conn, source_id)
    assert (row["status"], row["title"], row["duration_sec"]) == (db.STATUS_READY, "Talk", 100.0)


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
