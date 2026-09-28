"""快捷键写在按钮上。原来是一行文字说明，得对着文字找按钮，记不住。"""

import re

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


def _keys_on(body, element_id):
    """某个按钮上挂着哪些键。"""
    button = re.search(rf'<button[^>]*id="{element_id}"[^>]*>(.*?)</button>', body, re.S)
    assert button, element_id
    return re.findall(r'<kbd class="key[^"]*" aria-hidden="true">([^<]+)</kbd>', button.group(1))


def test_every_step_on_the_practice_page_shows_its_key_on_the_button(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)

    body = client.get(f"/practice/{segment_id}/1").text

    assert _keys_on(body, "submit-drill") == ["回车"]
    assert _keys_on(body, "start-record") == ["R"]
    assert _keys_on(body, "stop-take") == ["空格"]
    assert _keys_on(body, "redo-take") == ["Esc"]
    assert _keys_on(body, "peek") == ["T"]
    assert _keys_on(body, "retire") == ["K"]
    # 两个播放键：盲听的放/停，默写的重听（框里按 Esc）
    plays = re.findall(r'<button class="play"[^>]*>(.*?)</button>', body, re.S)
    assert ['<kbd class="key key-space" aria-hidden="true">空格</kbd>' in p for p in plays] == [True, True]
    assert 'aria-hidden="true">Esc</kbd>' in plays[1]
    # 打分的 1–5、翻页的 ← →：字本身就是键，电脑上画成键帽，手机上照常显示
    for score in "12345":
        assert (f'<button data-rating="{score}"><kbd class="key-inline" aria-hidden="true">'
                f'{score}</kbd>') in body
    assert '<kbd class="key-inline" aria-hidden="true">→</kbd>' in body
    # 文字版的快捷键说明不要了
    assert "快捷键：" not in body


def test_the_other_pages_put_space_on_their_button(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)

    chain = client.get("/chain").text
    talk = client.get("/talk?kind=retell").text

    assert _keys_on(chain, "chain-play") == ["空格"]
    assert _keys_on(talk, "talk-start") == ["空格"]
    assert _keys_on(talk, "talk-stop") == ["空格"]
    assert "快捷键：" not in chain + talk
