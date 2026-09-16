"""串起来：今天练过的几句连着跟一遍。日课里那一步原来只有一句说明，没有入口。"""

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
