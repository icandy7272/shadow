"""网页导入：记录马上建好，下载转写交给后台。"""

import pytest

from shadow import db
from shadow.ingest.downloader import DownloadError
from shadow.web import importer


@pytest.fixture(autouse=True)
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    connection = db.connect()
    db.init_db(connection)
    connection.close()


def _rows():
    connection = db.connect()
    try:
        return [dict(row) for row in db.list_sources(connection)]
    finally:
        connection.close()


def test_start_creates_the_record_and_hands_it_to_the_background():
    launched = []
    source_id = importer.start("https://x/y", launch=launched.append)
    assert launched == [source_id]
    assert _rows()[0]["status"] == db.STATUS_PENDING


def test_only_one_import_at_a_time():
    importer.start("https://x/a", launch=lambda source_id: None)
    with pytest.raises(importer.Busy):
        importer.start("https://x/b", launch=lambda source_id: None)
    assert len(_rows()) == 1


def test_a_bad_link_creates_nothing():
    with pytest.raises(DownloadError):
        importer.start("not a link", launch=lambda source_id: None)
    assert _rows() == []


def test_retry_replaces_the_failed_record():
    connection = db.connect()
    failed = db.create_source(connection, url="https://x/y", title="T", duration_sec=0.0)
    db.fail_source(connection, failed, "ERROR: Video unavailable")
    connection.close()
    launched = []

    fresh = importer.retry(failed, launch=launched.append)

    assert [row["id"] for row in _rows()] == [fresh]
    assert launched == [fresh]


def test_only_a_failed_import_can_be_retried():
    connection = db.connect()
    ready = db.create_source(connection, url="https://x/y", title="T", duration_sec=1.0)
    db.finish_source(connection, ready, audio_path="a.wav")
    connection.close()
    with pytest.raises(importer.NotRetryable):
        importer.retry(ready, launch=lambda source_id: None)


def test_the_background_run_never_raises(monkeypatch):
    """线程里的异常没人接；错误已经由 run_import 记进库里。"""
    def boom(source_id, conn):
        raise RuntimeError("ERROR: Video unavailable")

    monkeypatch.setattr(importer.pipeline, "run_import", boom)
    importer._run(1)
