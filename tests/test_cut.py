"""切句子音频：边界不能卡在「片段」上。

片段的起止就是它第一个词的开头、最后一个词的结尾——词尾的余音、词头的爆破音
都在这条线外面。卡在这条线上，每一段的最后一句都会被切掉词尾：实测 210 句里
有 25 句尾巴少了 0.14–0.35 秒，4 句开头少了 0.05–0.27 秒。
"""

from pathlib import Path

import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from shadow import config, db, media
from tests.test_web import _seed, _seed_second_segment


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web.app import app

    return TestClient(app)


def _cut(segment_id, unit):
    """网页上放的那段句子音频：时长，以及平移到切点为 0 之后的词。"""
    from shadow.web import app as web

    connection = db.connect()
    try:
        path, words = web._unit_reference(connection, segment_id, unit)
        return sf.info(path).duration, words
    finally:
        connection.close()


def test_segment_edges_come_from_the_neighbouring_segments(client, tmp_path):
    first = _seed(tmp_path)                  # 0.0–2.6 秒
    second = _seed_second_segment()          # 3.0–4.4 秒

    connection = db.connect()
    try:
        assert db.segment_edges(connection, first) == (0.0, 3.0)
        assert db.segment_edges(connection, second) == (2.6, float("inf"))
    finally:
        connection.close()


def test_the_last_sentence_of_a_segment_keeps_its_tail(client, tmp_path):
    first = _seed(tmp_path)                  # 第 1 段最后一个词 2.2–2.6 秒
    _seed_second_segment()                   # 第 2 段 3.0 秒才开始

    duration, words = _cut(first, 2)

    tail = duration - words[-1].end
    assert tail >= config.UNIT_PAD_SEC - 0.01
    assert tail <= 3.0 - 2.6 + 0.01          # 但不能伸进下一段


def test_the_first_sentence_of_a_segment_keeps_its_head(client, tmp_path):
    _seed(tmp_path)                          # 第 1 段 2.6 秒结束
    second = _seed_second_segment()          # 第 2 段第一个词 3.0 秒开始

    _, words = _cut(second, 1)

    assert words[0].start >= config.UNIT_PAD_SEC - 0.01
    assert words[0].start <= 3.0 - 2.6 + 0.01


def test_a_cut_made_with_the_old_bounds_is_redone(client, tmp_path):
    """修之前切好的句子音频还在缓存里，不重切的话照样听到被切掉的词尾。"""
    first = _seed(tmp_path)
    _seed_second_segment()
    connection = db.connect()
    audio = db.get_source(connection, db.get_segment(connection, first)["source_id"])["audio_path"]
    connection.close()
    stale = config.segment_audio_dir() / f"{first}-u2.wav"
    media.cut_segment(Path(audio), stale, start=1.4, end=2.6)     # 旧切法：卡在片段结尾

    duration, words = _cut(first, 2)

    assert duration - words[-1].end >= config.UNIT_PAD_SEC - 0.01
