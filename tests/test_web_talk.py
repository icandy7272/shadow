"""自己开口说：复述和自由说。原来这两步只有一句说明，录在哪、上周那段在哪都得自己想办法。"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from shadow import db
from tests.test_web import _seed, _source_of
from tests.test_web_plan import MONDAY, _practised

SATURDAY = MONDAY + timedelta(days=5)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web import app as web

    monkeypatch.setattr(web, "_today", lambda: MONDAY)
    # 转码和校验要 ffmpeg，这里测的是「录完了往哪存」，不是音频本身
    monkeypatch.setattr(web.media, "convert_upload", _fake_upload)
    monkeypatch.setattr(web.media, "validate_attempt", lambda path: None)
    monkeypatch.setattr(web.media, "probe_duration", lambda path: 120.0)
    return TestClient(web.app)


def _fake_upload(data, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"wav")
    return dest


def _learned(word, sentence, *, on: date):
    """某天把一个词记进了生词本。"""
    connection = db.connect()
    db.add_vocab(connection, word, sentence=sentence)
    stamp = datetime(on.year, on.month, on.day, 12).astimezone().isoformat(timespec="seconds")
    connection.execute("UPDATE vocab_sources SET added_at = ? WHERE word = ?", (stamp, word))
    connection.execute("UPDATE vocab SET first_added = ?, last_added = ? WHERE word = ?",
                       (stamp, stamp, word))
    connection.commit()
    connection.close()


def _record(client, kind, picks=()):
    return client.post("/api/talk", data={"kind": kind, "picks": list(picks)},
                       files={"file": ("talk.webm", b"blob", "audio/webm")})


def test_the_free_talk_page_offers_this_weeks_words(client, tmp_path):
    _seed(tmp_path)
    _learned("traction", "It started to get traction.", on=MONDAY)
    _learned("dwindle", "Savings dwindled away.", on=MONDAY - timedelta(days=3))

    body = client.get("/talk?kind=free_talk").text

    assert "traction" in body
    assert "It started to get traction." in body      # 出自哪句也要给，不然想不起来怎么用
    assert "dwindle" not in body                      # 上周的不算本周学到的


def test_with_an_empty_vocab_book_it_falls_back_to_this_weeks_sentences(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)

    body = client.get("/talk?kind=free_talk").text

    assert "Hello there." in body


def test_retelling_does_not_hand_you_the_material(client, tmp_path):
    """复述是合上材料讲，屏幕上摆着原句就不是复述了。"""
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY)

    body = client.get("/talk?kind=retell").text

    assert "复述" in body
    assert "Hello there." not in body


def test_retelling_covers_todays_new_sentences_with_cues_not_the_text(client, tmp_path):
    """复述只讲今天新练的那几句：新句子是顺着往下练的，连得成一段；复习的散在全文各处。
    页面给几个关键词提醒讲到哪儿了，不给原句——给了就成了照着念。"""
    segment_id = _seed(tmp_path)
    _practised(segment_id, 1, on=MONDAY - timedelta(days=3))    # 以前练过，今天只是复习
    _practised(segment_id, 1, on=MONDAY)
    _practised(segment_id, 2, on=MONDAY)                        # 今天新练的

    body = client.get("/talk?kind=retell").text

    assert "今天新练的 1 句" in body
    assert "第 2 句" in body
    assert '<span class="talk-cue">start</span>' in body
    assert "It was a start." not in body
    assert ">hello<" not in body                                 # 复习的那句不算


def test_a_day_without_new_sentences_retells_the_last_new_ones(client, tmp_path):
    """今天只做了复习，也得有东西可讲：讲上次新练的那几句。"""
    segment_id = _seed(tmp_path)
    _practised(segment_id, 2, on=MONDAY - timedelta(days=2))

    body = client.get("/talk?kind=retell").text

    assert "上次新练的" in body
    assert "09-12" in body
    assert '<span class="talk-cue">start</span>' in body


def test_retelling_before_any_practice_says_where_to_start(client, tmp_path):
    _seed(tmp_path)

    body = client.get("/talk?kind=retell").text

    assert "还没新练过句子" in body
    assert 'class="talk-cue"' not in body


def test_free_talk_has_no_retell_cues(client, tmp_path):
    segment_id = _seed(tmp_path)
    _practised(segment_id, 2, on=MONDAY)

    assert 'class="talk-cue"' not in client.get("/talk?kind=free_talk").text


def test_today_is_saturdays_free_talk_and_a_weekdays_retell(client, tmp_path, monkeypatch):
    from shadow.web import app as web

    _seed(tmp_path)
    assert "复述" in client.get("/talk").text

    monkeypatch.setattr(web, "_today", lambda: SATURDAY)
    assert "自由说" in client.get("/talk").text


def test_a_recording_can_be_played_back_and_says_what_it_used(client, tmp_path):
    _seed(tmp_path)

    saved = _record(client, "free_talk", picks=["traction", "dwindle"]).json()["talk"]

    body = client.get("/talk?kind=free_talk").text
    assert saved["url"] in body
    assert "用了 traction · dwindle" in body
    assert "今天" in body
    audio = client.get(saved["url"])
    assert audio.status_code == 200


def test_each_kind_keeps_its_own_recordings(client, tmp_path):
    _seed(tmp_path)
    _record(client, "retell")

    assert "talk-take" not in client.get("/talk?kind=free_talk").text
    assert "talk-take" in client.get("/talk?kind=retell").text


def test_recording_ticks_that_step_off_the_plan(client, tmp_path):
    """录过就是做过了，不用再回首页勾一次。"""
    segment_id = _seed(tmp_path)
    assert 'class="plan-check" data-step="retell"' in client.get(f"/sources/{_source_of(segment_id)}").text

    _record(client, "retell")

    body = client.get(f"/sources/{_source_of(segment_id)}").text
    assert 'class="plan-check" data-step="retell" checked' in body


def test_last_weeks_talk_is_labelled_so_you_can_compare(client, tmp_path):
    _seed(tmp_path)
    _record(client, "free_talk")
    connection = db.connect()
    connection.execute("UPDATE talks SET day = ?", ((MONDAY - timedelta(days=4)).isoformat(),))
    connection.commit()
    connection.close()

    assert "上周" in client.get("/talk?kind=free_talk").text


def test_a_recording_can_be_deleted(client, tmp_path):
    _seed(tmp_path)
    _record(client, "free_talk")
    talk = db.list_talks(db.connect(), kind="free_talk")[0]

    assert client.delete(f"/api/talk/{talk['id']}").status_code == 200

    assert "talk-take" not in client.get("/talk?kind=free_talk").text
    assert client.delete(f"/api/talk/{talk['id']}").status_code == 404


def test_an_unknown_kind_is_refused(client, tmp_path):
    _seed(tmp_path)

    assert _record(client, "singing").status_code == 400


def test_the_plan_card_links_to_the_talk_page(client, tmp_path, monkeypatch):
    from shadow.web import app as web

    segment_id = _seed(tmp_path)
    assert 'href="/talk"' in client.get(f"/sources/{_source_of(segment_id)}").text

    monkeypatch.setattr(web, "_today", lambda: SATURDAY)
    assert 'href="/talk"' in client.get(f"/sources/{_source_of(segment_id)}").text
