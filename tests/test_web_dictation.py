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
    assert 'id="skip-drill"' in body
    assert "跳过默写" in body
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


def _runs(segment_id):
    from shadow import db
    connection = db.connect()
    rows = connection.execute(
        "SELECT id, unit_index, blind_rating, gapfill_total FROM practice_runs"
        " WHERE segment_id = ? ORDER BY id", (segment_id,)).fetchall()
    connection.close()
    return [tuple(row) for row in rows]


def test_one_round_is_one_row(client, tmp_path):
    """打分和默写是同一轮：页面把打分拿到的编号带回来，就写进同一行。
    原来每一步各开一行，「练过 N 次」被放大成三倍。"""
    segment_id = _seed(tmp_path)
    run_id = client.post("/api/rating", data={"segment": segment_id, "unit": 2,
                                               "rating": 4}).json()["run_id"]

    graded = client.post("/api/dictation", json={"segment": segment_id, "unit": 2,
                                                  "text": "It was a start.",
                                                  "run_id": run_id}).json()

    assert graded["run_id"] == run_id
    assert _runs(segment_id) == [(run_id, 2, 4, 4)]


def test_a_round_of_another_sentence_is_not_written_into(client, tmp_path):
    """编号是页面传来的，不能信：别的句子那一轮不能被写进去。"""
    segment_id = _seed(tmp_path)
    other = client.post("/api/rating", data={"segment": segment_id, "unit": 1,
                                             "rating": 4}).json()["run_id"]

    graded = client.post("/api/dictation", json={"segment": segment_id, "unit": 2,
                                                  "text": "It was a start.",
                                                  "run_id": other}).json()

    assert graded["run_id"] != other
    assert _runs(segment_id) == [(other, 1, 4, None), (graded["run_id"], 2, None, 4)]


def test_a_malformed_round_number_starts_a_fresh_round(client, tmp_path):
    segment_id = _seed(tmp_path)
    graded = client.post("/api/dictation", json={"segment": segment_id, "unit": 2,
                                                  "text": "It was a start.",
                                                  "run_id": "12; DROP"}).json()
    assert isinstance(graded["run_id"], int)


def test_dictation_auto_skip_uses_cumulative_perfect_runs(client, tmp_path):
    segment_id = _seed(tmp_path)
    page = lambda: client.get(f"/practice/{segment_id}/2").text
    assert 'data-auto-skip="false"' in page()
    _post(client, segment_id, "It was a start.")
    assert 'data-auto-skip="false"' in page()
    _post(client, segment_id, "It was start.")
    _post(client, segment_id, "It was a start.")
    assert 'data-auto-skip="true"' in page()
    assert "已全对 2 次，自动跳过" in page()
    assert 'data-auto-skip="false"' in client.get(f"/practice/{segment_id}/1").text


def test_extra_words_and_resubmitting_same_run_do_not_count_twice(client, tmp_path):
    segment_id = _seed(tmp_path)
    first = _post(client, segment_id, "It was a start.").json()
    _post(client, segment_id, "It was a start.", run_id=first["run_id"])
    _post(client, segment_id, "It was a start extra.")
    assert 'data-auto-skip="false"' in client.get(f"/practice/{segment_id}/2").text
