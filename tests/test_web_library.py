"""素材库页面和接口：导入、看进度、重试、删除；每个页面都有入口。"""

import pytest
from fastapi.testclient import TestClient

from shadow import db
from tests.test_web import _seed, _source_of


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web.app import app

    return TestClient(app)


def test_every_page_links_to_the_library(client, tmp_path):
    segment_id = _seed(tmp_path)
    for url in ("/sources", f"/sources/{_source_of(segment_id)}",
                f"/practice/{segment_id}/1"):
        assert 'href="/sources"' in client.get(url).text


def test_the_library_is_where_you_start_when_empty(client):
    body = client.get("/").text
    assert "还没有导入素材" in body
    assert 'id="import-form"' in body


def test_the_library_page_loads_its_script(client):
    """实际遇到的：模板里漏了脚本，点「导入」变成表单原样提交，页面一刷新什么都没发生。"""
    assert "/static/library.js" in client.get("/sources").text


def test_the_library_shows_every_state(client, tmp_path):
    _seed(tmp_path)
    connection = db.connect()
    busy = db.create_source(connection, url="https://x/b", title="https://x/b",
                            duration_sec=0.0)
    db.set_source_status(connection, busy, db.STATUS_DOWNLOADING)
    failed = db.create_source(connection, url="https://x/c", title="https://x/c",
                              duration_sec=0.0)
    db.fail_source(connection, failed, "ERROR: Video unavailable")
    connection.close()

    body = client.get("/sources").text

    assert "练过 0 / 2 句" in body
    assert "正在导入" in body and "下载" in body
    assert "ERROR: Video unavailable" in body
    assert 'data-action="retry"' in body
    assert client.get("/api/sources").json()["sources"][0]["id"] == failed


def test_import_api(client, monkeypatch):
    from shadow.web import importer

    launched = []
    monkeypatch.setattr(importer, "_in_background", launched.append)

    assert client.post("/api/sources", data={"url": "not a link"}).status_code == 400
    response = client.post("/api/sources", data={"url": "https://x/y"})
    assert response.status_code == 201
    assert launched == [response.json()["id"]]
    # 上一份还在导入
    assert client.post("/api/sources", data={"url": "https://x/z"}).status_code == 409


def test_retry_api(client, monkeypatch):
    from shadow.web import importer

    monkeypatch.setattr(importer, "_in_background", lambda source_id: None)
    connection = db.connect()
    db.init_db(connection)
    failed = db.create_source(connection, url="https://x/y", title="T", duration_sec=0.0)
    db.fail_source(connection, failed, "boom")
    connection.close()

    response = client.post(f"/api/sources/{failed}/retry")
    assert response.status_code == 201
    # 新的那条还在导入，不是失败，不能再重试
    assert client.post(f"/api/sources/{response.json()['id']}/retry").status_code == 409


def test_delete_api(client, tmp_path):
    segment_id = _seed(tmp_path)
    source_id = _source_of(segment_id)
    connection = db.connect()
    busy = db.create_source(connection, url="https://x/b", title="B", duration_sec=0.0)
    db.set_source_status(connection, busy, db.STATUS_PROBING)
    connection.close()

    assert client.delete(f"/api/sources/{busy}").status_code == 409
    response = client.delete(f"/api/sources/{source_id}")
    assert response.status_code == 200
    assert response.json() == {"next": "/sources"}
    assert client.delete(f"/api/sources/{source_id}").status_code == 404


def test_starting_the_service_marks_interrupted_imports(tmp_path, monkeypatch):
    """导入跑在服务的线程里，服务一重启线程就没了。"""
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web.app import app

    connection = db.connect()
    db.init_db(connection)
    stuck = db.create_source(connection, url="https://x/y", title="T", duration_sec=0.0)
    db.set_source_status(connection, stuck, db.STATUS_TRANSCRIBING)
    connection.close()

    with TestClient(app):
        pass

    connection = db.connect()
    assert db.get_source(connection, stuck)["status"] == db.STATUS_FAILED
    connection.close()
