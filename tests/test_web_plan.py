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


def _rows(body):
    """列表上每一句：第几句 → （该不该复习、在复习队列里排第几）。"""
    found = re.findall(
        r'data-review="(\d)"\s+data-review-rank="(\d+)">\s*<td class="num">(\d+)<', body)
    return {int(number): (due == "1", int(rank)) for due, rank, number in found}


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
    # 五步都是复选框：系统看得出来的先替你勾上，也能点掉
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
    assert db.plan_checks(connection, MONDAY.isoformat()) == {"chain": True}
    connection.close()

    client.post("/api/plan", json={"step": "chain", "done": False})
    assert 'data-step="chain" checked' not in _home(client, segment_id)


def test_ticking_every_step_finishes_the_day(client, tmp_path):
    segment_id = _seed(tmp_path)
    for step in ("review", "new", "chain", "retell"):
        client.post("/api/plan", json={"step": step, "done": True})

    last = client.post("/api/plan", json={"step": "extensive", "done": True}).json()

    assert last["all_done"] is True
    assert 'class="plan-done">做完了' in _home(client, segment_id)


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


def test_a_sentence_practised_well_is_not_due_again_the_next_day(client, tmp_path):
    """练对一次就往后推一级：昨天练的第二句这次轮不到，隔了三天的第一句才到期。"""
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY - timedelta(days=6))
    _practised(segment_id, 1, on=MONDAY - timedelta(days=3))   # 两次都听懂了 → 3 天后
    _practised(segment_id, 2, on=MONDAY - timedelta(days=1))
    _practised(segment_id, 2, on=MONDAY - timedelta(days=1))

    body = _home(client, segment_id)

    assert "筛出该复习的 1 句" in body
    assert _rows(body) == {1: (True, 1), 2: (False, 0)}


def test_the_most_urgent_sentence_is_first_in_the_queue(client, tmp_path):
    """老问题没解决的排在单纯到期的前面，复习页的「下一句」也按这个顺序走。"""
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY - timedelta(days=1))
    _practised(segment_id, 2, on=MONDAY - timedelta(days=1), titles=["“was” 该降没降"])

    body = _home(client, segment_id)

    assert _rows(body) == {1: (True, 2), 2: (True, 1)}
    onwards = client.get(f"/practice/{segment_id}/2?from=review").text
    assert f'href="/practice/{segment_id}/1?from=review"' in onwards


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


def _practised_text(segment_id, unit, text, *, on, rating=4):
    """和 _practised 一样，只是句子文本由调用方给（第二个片段里的句子）。"""
    connection = db.connect()
    run_id = db.start_run(connection, segment_id=segment_id, unit_index=unit, unit_text=text)
    db.set_blind_rating(connection, run_id, rating)
    db.add_attempt(connection, run_id=run_id, audio_path="x.wav", asr_text=text,
                   metrics={"accuracy": 1.0, "speech_ratio": 1.0,
                            "pause_ratio": None, "issues": []})
    db.finish_run(connection, run_id)
    stamp = datetime(on.year, on.month, on.day, 12).astimezone().isoformat(timespec="seconds")
    connection.execute("UPDATE practice_runs SET started_at = ?, finished_at = ? WHERE id = ?",
                       (stamp, stamp, run_id))
    connection.commit()
    connection.close()


def test_a_step_the_app_can_measure_ticks_itself(client, tmp_path):
    """卡片上已经写着今天有没有到期的，勾还得自己再点一次——同一件事确认两遍。"""
    segment_id = _seed(tmp_path)                 # 都没练过，没有到期的

    body = _home(client, segment_id)

    assert 'class="plan-check" data-step="review" checked' in body
    assert 'class="plan-check" data-step="chain" id' in body   # 测不出来的还空着，自己勾


def test_you_can_untick_what_the_app_ticked_for_you(client, tmp_path):
    """替你勾上的和自己勾的长得一样，就得一样能点掉——不然同一个方框两种脾气。"""
    segment_id = _seed(tmp_path)
    assert 'class="plan-check" data-step="review" checked' in _home(client, segment_id)

    assert client.post("/api/plan", json={"step": "review", "done": False}).status_code == 200

    body = _home(client, segment_id)
    assert 'class="plan-check" data-step="review" id' in body   # 还在，只是没勾上
    assert 'class="plan-check" data-step="review" checked' not in body

    client.post("/api/plan", json={"step": "review", "done": True})
    assert 'class="plan-check" data-step="review" checked' in _home(client, segment_id)


def test_the_review_step_stays_open_while_sentences_are_due(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY - timedelta(days=1))

    body = _home(client, segment_id)

    assert 'class="plan-check" data-step="review" id' in body


def test_the_new_sentence_step_ticks_itself_once_you_have_done_enough(client, tmp_path):
    from shadow import plan
    from tests.test_web import _seed_second_segment

    segment_id = _seed(tmp_path)
    second = _seed_second_segment()
    _practised(segment_id, 1, on=MONDAY)
    _practised(segment_id, 2, on=MONDAY)

    assert plan.NEW_SENTENCES == 3
    assert 'class="plan-check" data-step="new" checked' not in _home(client, segment_id)

    _practised_text(second, 1, "Thank you all.", on=MONDAY)

    assert 'class="plan-check" data-step="new" checked' in _home(client, segment_id)


def test_the_day_is_done_when_what_is_left_is_ticked(client, tmp_path):
    from tests.test_web import _seed_second_segment

    segment_id = _seed(tmp_path)                 # 没有到期的：复习那一步自动划掉
    second = _seed_second_segment()
    for step in ("chain", "retell", "extensive"):
        client.post("/api/plan", json={"step": step, "done": True})

    assert 'class="plan-done">做完了' not in _home(client, segment_id)   # 新句子还没练够

    _practised(segment_id, 1, on=MONDAY)
    _practised(segment_id, 2, on=MONDAY)
    _practised_text(second, 1, "Thank you all.", on=MONDAY)

    assert "做完了" in _home(client, segment_id)
