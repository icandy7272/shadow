"""连着放：今天练过的（串起来）和本周练过的（周六的整段跟读）。原来只有一句说明，没有入口。"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.test_web import _seed
from tests.test_web_plan import MONDAY, _practised


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web import app as web

    monkeypatch.setattr(web, "_today", lambda: MONDAY)
    return TestClient(web.app)


def test_the_chain_page_lists_what_you_practised_today(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)                        # 今天练的
    _practised(segment_id, 2, on=MONDAY - timedelta(days=1))    # 昨天练的，不算

    body = client.get("/chain").text

    assert "Hello there." in body
    assert "It was a start." not in body
    assert f'data-src="/audio/{segment_id}/1"' in body
    assert "/static/chain.js" in body


def test_the_chain_page_says_so_when_you_have_not_practised_today(client, tmp_path):
    _seed(tmp_path)

    body = client.get("/chain").text

    assert "今天还没练过句子" in body


def test_the_plan_card_links_to_the_chain_page(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)

    body = client.get("/").text

    assert 'href="/chain"' in body


SATURDAY = MONDAY + timedelta(days=5)


def test_the_whole_read_through_takes_the_whole_week(client, tmp_path, monkeypatch):
    """周六的「整段跟读」跟的是本周练过的，不只是今天这几句。"""
    from shadow.web import app as web

    monkeypatch.setattr(web, "_today", lambda: SATURDAY)
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)                        # 本周一练的
    _practised(segment_id, 2, on=MONDAY - timedelta(days=3))    # 上周练的，不算

    body = client.get("/chain?scope=week").text

    assert "整段跟读" in body
    assert "Hello there." in body
    assert "It was a start." not in body
    assert 'data-rounds="1"' in body        # 从头到尾一遍，不中断


def test_the_saturday_plan_card_links_to_the_whole_read_through(client, tmp_path, monkeypatch):
    from shadow.web import app as web

    monkeypatch.setattr(web, "_today", lambda: SATURDAY)
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)

    body = client.get("/").text

    assert 'href="/chain?scope=week"' in body
    assert "本周练过的 1 句" in body


def test_playing_it_through_ticks_the_step_only_when_it_is_todays(client, tmp_path, monkeypatch):
    """跟完了页面自己去勾；周六没有「串起来」这一步，那就别勾。"""
    from shadow.web import app as web

    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)

    assert 'data-step="chain"' in client.get("/chain").text

    monkeypatch.setattr(web, "_today", lambda: SATURDAY)
    _practised(segment_id, 2, on=SATURDAY)
    assert 'data-step=""' in client.get("/chain").text
    assert 'data-step="whole"' in client.get("/chain?scope=week").text
