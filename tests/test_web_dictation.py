"""练习页第二步：一整句写在一个框里，按对齐判分。"""

import pytest
from fastapi.testclient import TestClient

from shadow import db
from tests.test_web import _seed, _seed_other_source


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web.app import app

    return TestClient(app)


def _post(client, segment_id, text, **extra):
    return client.post("/api/dictation",
                       json={"segment": segment_id, "unit": 2, "text": text, **extra})


def test_the_dictation_step_is_one_box_with_a_word_count(client, tmp_path):
    segment_id = _seed_other_source(tmp_path)          # 「Thank you all.」三个词

    body = client.get(f"/practice/{segment_id}/1").text

    assert 'id="dictation-text"' in body
    assert "已写 0/3 个词" in body
    assert 'id="dictation-unknown"' in body
    assert 'class="box"' not in body
    # 对答案之前，默写这一步里不能有原文
    assert "Thank" not in body.split('id="step-record"')[0]
    assert '<span class="n">3</span> 跟读' in body


def test_what_you_typed_is_lined_up_with_the_sentence(client, tmp_path):
    segment_id = _seed(tmp_path)                       # 第 2 句「It was a start.」

    data = _post(client, segment_id, "it is ? start", replays=2).json()

    assert (data["correct"], data["wrong"], data["missing"], data["unknown"],
            data["total"]) == (2, 1, 0, 1, 4)
    assert [item["status"] for item in data["items"]] == ["ok", "wrong", "unknown", "ok"]
    assert data["items"][1]["guess"] == "is"
    assert data["items"][3]["answer"] == "start"
    assert [item["in_vocab"] for item in data["items"]] == [False, False, True, False]
    assert [(t["lead"] + t["core"] + t["trail"], t["status"]) for t in data["line"]] == [
        ("It", "ok"), ("was", "wrong"), ("a", "unknown"), ("start.", "ok")]
    assert data["extras"] == []
    assert data["sentence"] == "It was a start."
    assert data["dictionary"] is False                  # 没装词典照样判分

    connection = db.connect()
    row = db.list_runs(connection, segment_id=segment_id)[0]
    assert (row["gapfill_correct"], row["gapfill_total"],
            row["gapfill_unknown"], row["gapfill_replays"]) == (2, 4, 1, 2)
    assert [item["word"] for item in db.list_vocab(connection)] == ["a"]
    connection.close()


def test_a_missed_word_only_costs_that_word(client, tmp_path):
    segment_id = _seed(tmp_path)

    data = _post(client, segment_id, "It was start.").json()

    assert [item["status"] for item in data["items"]] == ["ok", "ok", "missing", "ok"]
    assert (data["correct"], data["wrong"], data["missing"]) == (3, 0, 1)


def test_extra_words_come_back_on_their_own(client, tmp_path):
    segment_id = _seed(tmp_path)

    data = _post(client, segment_id, "it was was a start").json()

    assert data["correct"] == 4
    assert data["extras"] == ["was"]


def test_only_the_words_you_did_not_get_are_explained(client, tmp_path):
    from shadow import dictionary

    def fetch(url, dest, report=None):
        dest.write_text(
            "word,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,"
            "exchange,detail,audio\n"
            "it,ɪt,,pron. 它,,,,,,,,,\n"
            "was,wɒz,,v. 是（be 的过去式）,,,,,,,0:be/1:p,,\n"
            "be,biː,,v. 是\\nv. 存在,,,,,,,,,\n", encoding="utf-8")

    dictionary.install(fetch=fetch)
    segment_id = _seed(tmp_path)

    data = _post(client, segment_id, "it is a start").json()

    assert data["dictionary"] is True
    assert data["items"][0]["entry"] is None           # 写对的不用解释
    assert data["items"][1]["entry"] == {
        "word": "was", "phonetic": "wɒz", "meanings": ["v. 是（be 的过去式）"],
        "lemma": {"word": "be", "meanings": ["v. 是", "v. 存在"]}}


SEGMENT = "<seeded segment>"


@pytest.mark.parametrize("payload", [
    {"unit": 2, "text": "it was"},                             # 没说是哪一句
    {"segment": "x", "unit": 2, "text": "it was"},
    {"segment": SEGMENT, "unit": 2, "text": 5},
    {"segment": SEGMENT, "unit": 2},                           # 没交写的内容
    {"segment": SEGMENT, "unit": 2, "text": "word " * 500},    # 太长
])
def test_a_malformed_submission_is_rejected(client, tmp_path, payload):
    segment_id = _seed(tmp_path)
    body = {key: segment_id if value == SEGMENT else value for key, value in payload.items()}

    assert client.post("/api/dictation", json=body).status_code == 400
