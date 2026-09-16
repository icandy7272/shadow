"""生词本：页面、手动加入、记住了；删素材后原句还在。"""

import pytest
from fastapi.testclient import TestClient

from shadow import dictionary
from tests.test_web import _seed, _source_of


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web.app import app

    return TestClient(app)


def test_every_page_links_to_the_vocab_book(client, tmp_path):
    segment_id = _seed(tmp_path)
    for url in ("/sources", "/vocab", f"/sources/{_source_of(segment_id)}",
                f"/practice/{segment_id}/1"):
        assert 'href="/vocab"' in client.get(url).text
    assert "/static/vocab.js" in client.get("/vocab").text


def test_an_empty_vocab_book_says_how_words_get_in(client):
    body = client.get("/vocab").text
    assert "生词本还是空的" in body


def test_adding_a_word_twice_counts_and_links_back_to_the_sentence(client, tmp_path):
    segment_id = _seed(tmp_path)
    for _ in range(2):
        response = client.post("/api/vocab", json={
            "word": "start.", "sentence": "It was a start.",
            "segment": segment_id, "unit": 2})
    assert response.json() == {"word": "start", "times": 2}

    body = client.get("/vocab").text

    assert 'data-word="start"' in body
    assert "记过 2 次" in body
    assert f'<a href="/practice/{segment_id}/2">It was a start.<span class="go">去练这句' in body
    # 没装词典：词和原句照记，提示怎么装
    assert "uv run shadow dict install" in body


def test_adding_nothing_is_rejected(client):
    assert client.post("/api/vocab", json={"word": " — "}).status_code == 400
    assert client.post("/api/vocab", json={"word": "start", "segment": "x"}).status_code == 400


def test_a_word_you_remember_leaves_the_book(client):
    client.post("/api/vocab", json={"word": "start", "sentence": "It was a start."})

    assert client.delete("/api/vocab/start").json() == {"removed": True}
    assert client.delete("/api/vocab/start").status_code == 404
    assert "生词本还是空的" in client.get("/vocab").text


def test_the_sentence_stays_after_its_source_is_deleted(client, tmp_path):
    """删素材是彻底删，可生词是自己的：原句留下，只是不能再点回去练。"""
    segment_id = _seed(tmp_path)
    client.post("/api/vocab", json={"word": "start", "sentence": "It was a start.",
                                    "segment": segment_id, "unit": 2})
    assert client.delete(f"/api/sources/{_source_of(segment_id)}").status_code == 200

    body = client.get("/vocab").text

    assert "It was a start." in body
    assert f'href="/practice/{segment_id}/2"' not in body


def test_the_book_explains_each_word_once_the_dictionary_is_installed(client):
    from tests.test_dictionary import _fetch

    dictionary.install(fetch=_fetch)
    client.post("/api/vocab", json={"word": "graduated", "sentence": "I never graduated."})

    body = client.get("/vocab").text

    assert "a. 毕业了的" in body
    assert "原形 graduate：n. 毕业生；v. 毕业" in body
    assert "shadow dict install" not in body


def test_the_vocab_book_can_be_sorted_by_how_often_a_word_came_up(client):
    """词多了以后，固定按最近加入就不好找了。"""
    client.post("/api/vocab", json={"word": "adoption", "sentence": "She refused."})
    client.post("/api/vocab", json={"word": "adoption", "sentence": "Final papers."})
    client.post("/api/vocab", json={"word": "commencement", "sentence": "I'm honored."})

    recent = client.get("/vocab").text
    assert recent.index('data-word="commencement"') < recent.index('data-word="adoption"')

    often = client.get("/vocab?sort=times").text
    assert often.index('data-word="adoption"') < often.index('data-word="commencement"')

    # 两种排法都在页面上，当前用的那种标出来
    assert 'href="/vocab?sort=times"' in recent
    assert 'class="chosen">最近' in recent
    assert 'class="chosen">次数' in often
    # 认不出的排法当作默认，不报错
    assert client.get("/vocab?sort=nonsense").status_code == 200
