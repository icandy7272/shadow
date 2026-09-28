"""「这句不用再练」和每一步之前做过几次。

太短的（Thank you.）、早就熟了的句子，每次复习都要完整来一遍，太耗时间。
标成不再练以后，复习、「下一句」都跳过它；标错了能恢复。
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from shadow import db
from tests.test_web import _seed, _seed_second_segment, _source_of
from tests.test_web_plan import MONDAY, _home, _practised


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web import app as web

    monkeypatch.setattr(web, "_today", lambda: MONDAY)
    return TestClient(web.app)


def _retire(client, segment_id, unit, retired=True):
    return client.post("/api/retire", json={"segment": segment_id, "unit": unit,
                                            "retired": retired})


def _section(body, step):
    start = body.index(f'id="step-{step}"')
    return body[start:body.index("</h2>", start)]


def test_a_sentence_marked_done_leaves_the_review(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY - timedelta(days=1))
    assert "开始复习（1 句）" in _home(client, segment_id)

    assert _retire(client, segment_id, 1).json() == {"retired": True}

    body = _home(client, segment_id)
    assert "开始复习" not in body
    assert 'data-retired="1"' in body
    assert '<span class="unit-tag">不再练</span>' in body


def test_skipping_a_new_sentence_moves_the_next_one_up(client, tmp_path):
    """没练过也能跳：「Thank you.」这种不用练。"""
    segment_id = _seed(tmp_path)
    assert f'class="cta" href="/practice/{segment_id}/1"' in _home(client, segment_id)

    _retire(client, segment_id, 1)

    assert f'class="cta" href="/practice/{segment_id}/2"' in _home(client, segment_id)


def test_the_next_sentence_link_steps_over_it(client, tmp_path):
    first = _seed(tmp_path)
    second = _seed_second_segment()

    _retire(client, first, 2)

    body = client.get(f"/practice/{first}/1").text
    assert f'class="next" href="/practice/{second}/1"' in body


def test_it_can_be_brought_back(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY - timedelta(days=1))
    page = client.get(f"/practice/{segment_id}/1").text
    assert 'id="retire"' in page and "已标为不再练" not in page

    _retire(client, segment_id, 1)
    page = client.get(f"/practice/{segment_id}/1").text
    assert "已标为不再练" in page
    assert 'id="unretire"' in page

    assert _retire(client, segment_id, 1, retired=False).json() == {"retired": False}
    assert "开始复习（1 句）" in _home(client, segment_id)


def test_bad_requests_are_refused(client, tmp_path):
    segment_id = _seed(tmp_path)
    assert _retire(client, segment_id, 99).status_code == 404
    assert client.post("/api/retire", json={"segment": segment_id, "unit": 1}).status_code == 400


def test_each_step_says_how_many_times_you_did_it_before(client, tmp_path):
    """练到第几次了，页面上原来只在跟读那一步的「上次」里写了一句。"""
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY - timedelta(days=3))
    run_id = _practised(segment_id, 1, on=MONDAY - timedelta(days=1))
    connection = db.connect()
    db.set_dictation(connection, run_id, correct=2, total=2, unknown=0, replays=0)
    connection.close()

    body = client.get(f"/practice/{segment_id}/1").text
    assert "之前 2 次" in _section(body, "listen")
    assert "之前 1 次" in _section(body, "drill")
    assert "之前 2 次" in _section(body, "record")

    fresh = client.get(f"/practice/{segment_id}/2").text
    for step in ("listen", "drill", "record"):
        assert "第一次" in _section(fresh, step)


def test_deleting_the_source_forgets_its_marks(client, tmp_path):
    segment_id = _seed(tmp_path)
    _retire(client, segment_id, 1)
    source_id = _source_of(segment_id)

    assert client.delete(f"/api/sources/{source_id}").status_code == 200

    connection = db.connect()
    assert db.retired_texts(connection, source_id) == set()
    connection.close()
