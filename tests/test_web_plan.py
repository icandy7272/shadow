"""首页的日课卡片、勾选接口、「该复习」筛选、完整日课页。"""

import re
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shadow import db
from tests.test_web import _seed, _source_of

MONDAY = date(2026, 9, 14)
TEXTS = {1: "Hello there.", 2: "It was a start."}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web import app as web

    monkeypatch.setattr(web, "_today", lambda: MONDAY)
    return TestClient(web.app)


def _home(client, segment_id):
    return client.get(f"/sources/{_source_of(segment_id)}").text


def _practised(segment_id, unit, *, on, titles=(), rating=4):
    """某一天练过这句：自评几分、录音里反复出现哪些问题。"""
    connection = db.connect()
    run_id = db.start_run(connection, segment_id=segment_id, unit_index=unit,
                          unit_text=TEXTS[unit])
    db.set_blind_rating(connection, run_id, rating)
    for _ in range(2):
        db.add_attempt(connection, run_id=run_id, audio_path="x.wav", asr_text=TEXTS[unit],
                       metrics={"accuracy": 1.0, "speech_ratio": 1.0, "pause_ratio": None,
                                "issues": [{"kind": "stretched", "ref_index": 0,
                                            "score": 1.0, "title": t} for t in titles]})
    db.finish_run(connection, run_id)
    stamp = datetime(on.year, on.month, on.day, 12).astimezone().isoformat(timespec="seconds")
    connection.execute("UPDATE practice_runs SET started_at = ?, finished_at = ? WHERE id = ?",
                       (stamp, stamp, run_id))
    connection.commit()
    connection.close()


def test_the_home_page_shows_todays_plan(client, tmp_path):
    segment_id = _seed(tmp_path)

    body = _home(client, segment_id)

    assert 'id="plan"' in body
    assert "今天的日课 · 周一 · 30 分钟" in body
    assert body.count('class="plan-check"') == 5
    assert f'<a class="plan-link" href="/practice/{segment_id}/1"' in body
    assert 'href="/plan"' in body


def test_saturday_shows_the_weekly_review(client, tmp_path, monkeypatch):
    from shadow.web import app as web

    monkeypatch.setattr(web, "_today", lambda: MONDAY + timedelta(days=5))

    body = _home(client, _seed(tmp_path))

    assert "今天的日课 · 周六 · 回顾" in body
    assert body.count('class="plan-check"') == 4


def test_a_ticked_step_is_remembered_for_the_day(client, tmp_path):
    segment_id = _seed(tmp_path)

    response = client.post("/api/plan", json={"step": "chain", "done": True})

    assert response.json() == {"step": "chain", "done": True, "all_done": False}
    assert 'data-step="chain" checked' in _home(client, segment_id)
    connection = db.connect()
    assert db.plan_checks(connection, MONDAY.isoformat()) == {"chain"}
    connection.close()

    client.post("/api/plan", json={"step": "chain", "done": False})
    assert 'data-step="chain" checked' not in _home(client, segment_id)


def test_ticking_every_step_finishes_the_day(client, tmp_path):
    segment_id = _seed(tmp_path)
    for step in ("review", "new", "chain", "retell"):
        client.post("/api/plan", json={"step": step, "done": True})

    last = client.post("/api/plan", json={"step": "extensive", "done": True}).json()

    assert last["all_done"] is True
    assert "做完了" in _home(client, segment_id)


def test_a_step_that_is_not_on_today_is_rejected(client):
    assert client.post("/api/plan", json={"step": "free_talk", "done": True}).status_code == 400
    assert client.post("/api/plan", json={"step": "review"}).status_code == 400


def test_review_picks_yesterdays_sentences_and_unfinished_ones(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY - timedelta(days=1))
    _practised(segment_id, 2, on=MONDAY - timedelta(days=5), titles=["“was” 该降没降"])

    body = _home(client, segment_id)

    assert body.count('data-review="1"') == 2
    assert 'data-filter="review"' in body
    assert "筛出该复习的 2 句" in body


def test_a_sentence_practised_today_is_not_due_yet(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY, titles=["“there” 没沉下去"], rating=1)

    body = _home(client, segment_id)

    assert 'data-review="1"' not in body
    assert "没有要复习的" in body


def test_the_full_plan_page_is_up_to_date(client):
    body = client.get("/plan").text

    assert "影子跟读日课" in body
    assert "默写" in body
    assert "填空" not in body


def test_every_row_has_as_many_cells_as_the_header(client, tmp_path):
    """删「空」那一列时表头删了、行里漏删，手机上按列序号隐藏的列跟着错位。"""
    body = _home(client, _seed(tmp_path))

    head = re.search(r"<thead>(.*?)</thead>", body, re.S).group(1)
    row = re.search(r"<tbody>\s*<tr.*?>(.*?)</tr>", body, re.S).group(1)

    assert head.count("<th>") == row.count("<td")
