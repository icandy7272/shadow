"""从筛选点进去练：下一句在同一个筛选里找，不按原文顺序。"""

from datetime import date, datetime, timedelta

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from shadow import config, db, plan
from shadow.models import Segment, Word
from tests.test_web import _source_of

MONDAY = date(2026, 9, 14)
YESTERDAY = MONDAY - timedelta(days=1)
LAST_WEEK = MONDAY - timedelta(days=7)
TEXTS = ["One two.", "Three four.", "Five six.", "Seven eight.", "Nine ten."]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web import app as web

    monkeypatch.setattr(web, "_today", lambda: MONDAY)
    return TestClient(web.app)


@pytest.fixture()
def seg(client):
    """一段五句，按先后是第 1 到第 5 句。"""
    connection = db.connect()
    db.init_db(connection)
    audio = config.source_audio_dir() / "q.wav"
    t = np.arange(16000 * 12) / 16000
    sf.write(audio, (0.4 * np.sin(2 * np.pi * 200 * t)).astype("float32"), 16000)
    source_id = db.create_source(connection, url="https://x/q", title="Q", duration_sec=12.0)
    db.finish_source(connection, source_id, audio_path=str(audio))
    words, start = [], 0.2
    for sentence in TEXTS:
        for token in sentence.split():
            words.append(Word(text=token, start=start, end=start + 0.4))
            start += 0.5
        start += 0.8
    db.insert_segments(connection, source_id,
                       (Segment(idx=0, start=0.0, end=start, words=tuple(words)),))
    segment_id = db.list_segments(connection, source_id)[0]["id"]
    connection.close()
    return segment_id


def _practised(segment_id, unit, *, on, titles=(), rating=4):
    """某一天练过第 unit 句：自评几分、录音里反复出现哪些问题。"""
    connection = db.connect()
    text = TEXTS[unit - 1]
    run_id = db.start_run(connection, segment_id=segment_id, unit_index=unit, unit_text=text)
    db.set_blind_rating(connection, run_id, rating)
    for _ in range(2):
        db.add_attempt(connection, run_id=run_id, audio_path="x.wav", asr_text=text,
                       metrics={"accuracy": 1.0, "speech_ratio": 1.0, "pause_ratio": None,
                                "issues": [{"kind": "stretched", "ref_index": 0,
                                            "score": 1.0, "title": t} for t in titles]})
    db.finish_run(connection, run_id)
    stamp = datetime(on.year, on.month, on.day, 12).astimezone().isoformat(timespec="seconds")
    connection.execute("UPDATE practice_runs SET started_at = ?, finished_at = ? WHERE id = ?",
                       (stamp, stamp, run_id))
    connection.commit()
    connection.close()


def _page(client, segment_id, unit, query=""):
    return client.get(f"/practice/{segment_id}/{unit}{query}").text


def test_review_goes_to_the_next_sentence_that_is_due(client, seg):
    """挑着练过的话，原文的下一句可能根本不用复习，甚至没练过——点进去就先看到了原文。"""
    _practised(seg, 1, on=YESTERDAY)
    for _ in range(len(plan.INTERVALS)):         # 练对这么多次，间隔推到 30 天
        _practised(seg, 2, on=LAST_WEEK)         # 早就练熟了，这个月都不用复习
    _practised(seg, 4, on=YESTERDAY)             # 第 3 句没练过

    body = _page(client, seg, 1, "?from=review")

    assert f'href="/practice/{seg}/4?from=review"' in body
    assert "复习下一句（第 4 句 · 还剩 1 句）" in body
    assert f'href="/practice/{seg}/2' not in body
    assert f'href="/practice/{seg}/3' not in body
    assert f'<a href="/practice/{seg}/1">改回原文顺序</a>' in body


def test_review_comes_back_round_to_the_ones_before(client, seg):
    _practised(seg, 1, on=YESTERDAY)
    _practised(seg, 4, on=YESTERDAY)

    body = _page(client, seg, 4, "?from=review")

    assert f'class="next" href="/practice/{seg}/1?from=review"' in body


def test_the_last_one_due_leads_back_to_the_list(client, seg):
    _practised(seg, 2, on=YESTERDAY)

    body = _page(client, seg, 2, "?from=review")

    assert "今天该复习的都练完了" in body
    assert f'class="next" href="/sources/{_source_of(seg)}"' in body
    assert 'class="next" href="/practice/' not in body


def test_fresh_goes_to_the_next_sentence_not_yet_practised(client, seg):
    _practised(seg, 2, on=MONDAY)

    assert f'href="/practice/{seg}/3?from=fresh"' in _page(client, seg, 1, "?from=fresh")


def test_issues_and_unheard_follow_the_list_rules(client, seg):
    _practised(seg, 3, on=LAST_WEEK, titles=["“five” 拖长了"])
    _practised(seg, 5, on=LAST_WEEK, rating=2)

    assert f'href="/practice/{seg}/3?from=issues"' in _page(client, seg, 1, "?from=issues")
    assert f'href="/practice/{seg}/5?from=unheard"' in _page(client, seg, 1, "?from=unheard")


def test_without_a_filter_the_pager_follows_the_text(client, seg):
    _practised(seg, 1, on=YESTERDAY)

    for query in ("", "?from=all", "?from=nonsense"):
        body = _page(client, seg, 1, query)
        assert f'class="next" href="/practice/{seg}/2"' in body
        assert "?from=" not in body
        assert "改回原文顺序" not in body


def test_skipping_an_unusable_sentence_stays_in_the_filter(client, tmp_path):
    from tests.test_web import _seed_with_a_broken_unit

    broken = _seed_with_a_broken_unit(tmp_path)

    body = client.get(f"/practice/{broken}/2?from=fresh").text

    assert f'class="next" href="/practice/{broken}/3?from=fresh"' in body
