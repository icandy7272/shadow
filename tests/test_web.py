import re

import pytest
from fastapi.testclient import TestClient

from shadow import config, db
from shadow.models import Segment, Word


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_DATA_DIR", str(tmp_path))
    from shadow.web.app import app

    return TestClient(app)


def _seed(tmp_path):
    """一个片段，两句话。"""
    import numpy as np
    import soundfile as sf

    connection = db.connect()
    db.init_db(connection)
    source = config.source_audio_dir() / "1.wav"
    t = np.arange(16000 * 8) / 16000
    sf.write(source, (0.4 * np.sin(2 * np.pi * 200 * t)).astype("float32"), 16000)
    source_id = db.create_source(connection, url="https://x/y", title="T",
                                 duration_sec=8.0)
    db.finish_source(connection, source_id, audio_path=str(source))
    spec = [("Hello", 0.0, 0.4), ("there.", 0.5, 0.4),
            ("It", 1.5, 0.3), ("was", 1.9, 0.1),
            ("a", 2.0, 0.1), ("start.", 2.2, 0.4)]
    words = tuple(Word(text=t_, start=a, end=a + d) for t_, a, d in spec)
    db.insert_segments(connection, source_id,
                       (Segment(idx=0, start=0.0, end=2.6, words=words),))
    segment_id = db.list_segments(connection, source_id)[0]["id"]
    connection.close()
    return segment_id


def test_index_lists_units(client, tmp_path):
    segment_id = _seed(tmp_path)
    body = client.get("/").text
    assert "Hello there." in body
    assert f"/practice/{segment_id}/2" in body


def test_static_urls_carry_a_version_that_follows_the_files(client, tmp_path):
    """改了 js 而浏览器还跑缓存里的旧版，页面看着正常、行为却是上一版的。"""
    import os
    import re

    _seed(tmp_path)
    from shadow.web.app import HERE

    stamp = re.findall(r"app\.js\?v=(\d+)", client.get("/").text)
    assert stamp and stamp[0] != "0"

    target = HERE / "static" / "app.js"
    os.utime(target, (int(stamp[0]) + 100, int(stamp[0]) + 100))
    try:
        again = re.findall(r"app\.js\?v=(\d+)", client.get("/").text)
        assert again[0] != stamp[0]
    finally:
        os.utime(target, (int(stamp[0]), int(stamp[0])))


def test_index_is_helpful_when_empty(client):
    assert "还没有导入素材" in client.get("/").text


def test_practice_page_hides_the_text_behind_locked_steps(client, tmp_path):
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/2").text
    # 第二、三步默认锁住；样式把锁住的内容整个折叠，避免盲听前泄题
    assert body.count('class="step locked"') == 2
    assert "盲听" in body


def test_practice_page_links_to_the_neighbouring_units(client, tmp_path):
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/1").text
    # 第一句没有上一句，只该出现下一句
    assert f'href="/practice/{segment_id}/2"' in body
    assert f'href="/practice/{segment_id}/0"' not in body

    body = client.get(f"/practice/{segment_id}/2").text
    assert f'href="/practice/{segment_id}/1"' in body
    # 只有两句，最后一句不该有下一句
    assert f'href="/practice/{segment_id}/3"' not in body


def _finished_run(segment_id, unit, titles):
    connection = db.connect()
    run_id = db.start_run(connection, segment_id=segment_id, unit_index=unit,
                          unit_text="It was a start.")
    for _ in range(2):
        db.add_attempt(
            connection, run_id=run_id, audio_path="x.wav", asr_text="It was a start.",
            metrics={"accuracy": 1.0, "speech_ratio": 1.1, "pause_ratio": None,
                     "issues": [{"kind": "stretched", "ref_index": 0, "score": 1.0,
                                 "title": t} for t in titles]},
        )
    db.finish_run(connection, run_id)
    connection.close()


def test_last_time_is_shown_inside_the_shadowing_step(client, tmp_path):
    """记录里带着句子原文的片段，提前露出来盲听和默写就废了。"""
    segment_id = _seed(tmp_path)
    _finished_run(segment_id, 2, ["“was” 该降没降"])

    body = client.get(f"/practice/{segment_id}/2").text

    assert "“was” 该降没降" in body
    assert body.index('id="step-record"') < body.index('class="history"')
    # 锁着的时候只说有几处，不说是哪些词
    assert "上次" in body[body.index('id="step-record"'):body.index('class="history"')]
    # 指标不进来：开口前看见分数会让人去够数字
    assert "可懂度" not in body


def test_a_fresh_sentence_has_no_last_time_block(client, tmp_path):
    segment_id = _seed(tmp_path)
    assert 'class="history"' not in client.get(f"/practice/{segment_id}/2").text


def _seed_with_a_broken_unit(tmp_path):
    """第 2 句时间戳挤成一团，没法练——练下一句不该把人送进去。"""
    import numpy as np
    import soundfile as sf

    connection = db.connect()
    db.init_db(connection)
    source = config.source_audio_dir() / "9.wav"
    t_ = np.arange(16000 * 8) / 16000
    sf.write(source, (0.4 * np.sin(2 * np.pi * 200 * t_)).astype("float32"), 16000)
    source_id = db.create_source(connection, url="https://x/b", title="B",
                                 duration_sec=8.0)
    db.finish_source(connection, source_id, audio_path=str(source))
    spec = [("One", 0.0, 0.4), ("two.", 0.5, 0.4)]
    # 十四个词挤在 0.28 秒里，且只在最后一个带句号，合成一个不可练的单元
    spec += [(f"w{i}", 1.5 + i * 0.02, 0.02) for i in range(13)]
    spec += [("w13.", 1.76, 0.02)]
    spec += [("Last", 3.0, 0.4), ("one.", 3.5, 0.4)]
    words = tuple(Word(text=x, start=a, end=a + d) for x, a, d in spec)
    db.insert_segments(connection, source_id,
                       (Segment(idx=0, start=0.0, end=4.0, words=words),))
    segment_id = db.list_segments(connection, source_id)[0]["id"]
    connection.close()
    return segment_id


def test_an_unusable_unit_is_a_page_not_raw_json(client, tmp_path):
    segment_id = _seed_with_a_broken_unit(tmp_path)
    response = client.get(f"/practice/{segment_id}/2")

    assert response.status_code == 409
    assert "text/html" in response.headers["content-type"]
    assert "没法练" in response.text
    # 得留个出口，不能让人卡在这里
    assert f"/practice/{segment_id}/3" in response.text


def test_the_pager_skips_over_unusable_units(client, tmp_path):
    segment_id = _seed_with_a_broken_unit(tmp_path)
    body = client.get(f"/practice/{segment_id}/1").text

    assert f'href="/practice/{segment_id}/3"' in body
    assert f'href="/practice/{segment_id}/2"' not in body


def test_the_page_counts_sentences_not_segments(client, tmp_path):
    """练的是句子，片段只是切素材时的实现细节，不该出现在界面上。"""
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/2").text

    assert "第 2 句" in body
    assert "共 2 句" in body
    assert "片段" not in body


def _source_of(segment_id):
    connection = db.connect()
    try:
        return db.get_segment(connection, segment_id)["source_id"]
    finally:
        connection.close()


def _seed_second_segment():
    """在 _seed 那份素材里再加一个片段。"""
    connection = db.connect()
    source_id = next(row["id"] for row in db.list_sources(connection) if row["title"] == "T")
    words = tuple(Word(text=t_, start=a, end=a + 0.4)
                  for t_, a in (("Thank", 3.0), ("you", 3.5), ("all.", 4.0)))
    db.insert_segments(connection, source_id,
                       (Segment(idx=1, start=3.0, end=4.4, words=words),))
    segment_id = db.list_segments(connection, source_id)[-1]["id"]
    connection.close()
    return segment_id


def test_the_pager_walks_across_segment_boundaries(client, tmp_path):
    """句子是连着编号的，走到一段的末尾该接着进下一段，不是没路了。"""
    first = _seed(tmp_path)
    second = _seed_second_segment()

    body = client.get(f"/practice/{first}/2").text
    assert f'href="/practice/{second}/1"' in body

    body = client.get(f"/practice/{second}/1").text
    assert f'href="/practice/{first}/2"' in body


def test_another_source_is_not_mixed_in(client, tmp_path):
    """新导入一份素材，它的句子不该接在上一份后面。"""
    first = _seed(tmp_path)
    other = _seed_other_source(tmp_path)

    body = client.get(f"/practice/{first}/2").text
    assert f"/practice/{other}/1" not in body
    assert "共 2 句" in body

    page = client.get(f"/sources/{_source_of(other)}").text
    assert f"/practice/{other}/1" in page
    assert f"/practice/{first}/1" not in page


def test_the_practice_page_links_back_to_its_source(client, tmp_path):
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/1").text
    assert f'href="/sources/{_source_of(segment_id)}"' in body


def test_home_goes_to_the_source_you_opened_last(client, tmp_path):
    first = _seed(tmp_path)
    _seed_other_source(tmp_path)
    client.get(f"/sources/{_source_of(first)}")

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/sources/{_source_of(first)}"


def test_home_without_sources_goes_to_the_library(client):
    response = client.get("/", follow_redirects=False)
    assert response.headers["location"] == "/sources"


def test_the_index_lists_a_running_sentence_number(client, tmp_path):
    _seed(tmp_path)
    body = client.get("/").text

    assert "<th>片段</th>" not in body
    assert ">1</td>" in body


def test_a_run_records_which_sentence_was_practised(client, tmp_path):
    """切分规则一变，序号就失去意义——必须存下练的是哪句话。"""
    segment_id = _seed(tmp_path)
    client.post("/api/rating", data={"segment": segment_id, "unit": 2, "rating": 4})

    connection = db.connect()
    row = db.list_runs(connection, segment_id=segment_id)[0]
    connection.close()
    assert row["unit_text"] == "It was a start."


def test_the_page_says_so_when_recording_is_impossible(client, tmp_path):
    """局域网 HTTP 下浏览器根本不给麦克风权限，点了只会静默失败。"""
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/2").text

    assert 'id="no-mic"' in body
    assert "跟读请用电脑" in body


def test_the_list_carries_what_the_filters_need(client, tmp_path):
    """盲听自评一直存着却没人用过。它正好回答：哪些句子是真没听懂的。"""
    segment_id = _seed(tmp_path)
    client.post("/api/rating", data={"segment": segment_id, "unit": 2, "rating": 2})
    _finished_run(segment_id, 2, ["“was” 该降没降"])

    body = client.get("/").text

    assert 'data-filter="issues"' in body
    assert 'data-filter="unheard"' in body
    assert 'data-rating="2"' in body
    assert 'data-issues="1"' in body


def test_unknown_unit_is_a_404(client, tmp_path):
    segment_id = _seed(tmp_path)
    assert client.get(f"/practice/{segment_id}/99").status_code == 404


def test_audio_is_cut_on_demand(client, tmp_path):
    segment_id = _seed(tmp_path)
    response = client.get(f"/audio/{segment_id}/2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert (config.segment_audio_dir() / f"{segment_id}-u2.wav").exists()


def test_reference_words_are_rebased_onto_the_cut_audio(client, tmp_path):
    """词的时间戳是整段素材里的绝对秒数，裁出来的单元音频只有一两秒。

    不平移的话，按绝对秒数去这段音频里取音高会一帧都取不到，
    图 2 的原声轮廓会整条变平——比对的基准整个失效。
    """
    import soundfile as sf

    from shadow.web import app as web

    segment_id = _seed(tmp_path)
    connection = db.connect()
    path, words = web._unit_reference(connection, segment_id, 2)
    connection.close()

    # 单元 2 在素材里从 1.5 秒开始，裁剪时前面留了 0.1 秒余量
    assert words[0].start == pytest.approx(0.1, abs=0.01)
    assert words[-1].end < sf.info(path).duration + 0.01


def test_rating_is_stored(client, tmp_path):
    segment_id = _seed(tmp_path)
    response = client.post("/api/rating",
                           data={"segment": segment_id, "unit": 2, "rating": 4})
    assert response.status_code == 200
    connection = db.connect()
    assert db.list_runs(connection, segment_id=segment_id)[0]["blind_rating"] == 4
    connection.close()


def test_rating_rejects_out_of_range(client, tmp_path):
    segment_id = _seed(tmp_path)
    assert client.post("/api/rating",
                       data={"segment": segment_id, "unit": 2, "rating": 9}
                       ).status_code == 400


def test_the_old_gapfill_endpoint_is_gone(client, tmp_path):
    segment_id = _seed(tmp_path)
    response = client.post("/api/gapfill", json={"segment": segment_id, "unit": 2,
                                                 "answers": []})
    assert response.status_code == 404


def test_index_hides_the_text_of_unpractised_units(client, tmp_path):
    """列表页把原文都列出来，等于还没开始练就把整篇读了一遍。

    原文仍在 data 属性里（勾选「全部显示」时要用），但不能被渲染出来——
    目的是避免不小心读到，不是防偷看。
    """
    segment_id = _seed(tmp_path)
    body = client.get("/").text
    assert ">4 个词</span>" in body                     # 只说几个词，不露原文
    assert body.count("It was a start.") == 1          # 只此一处
    assert 'data-text="It was a start."' in body       # 而且是在属性里


def test_index_shows_the_text_once_practised(client, tmp_path):
    segment_id = _seed(tmp_path)
    client.post("/api/rating", data={"segment": segment_id, "unit": 2, "rating": 3})
    body = client.get("/").text
    assert "It was a start." in body


def test_index_links_straight_to_the_next_unpractised_unit(client, tmp_path):
    segment_id = _seed(tmp_path)
    assert f'class="cta" href="/practice/{segment_id}/1"' in client.get("/").text
    client.post("/api/rating", data={"segment": segment_id, "unit": 1, "rating": 3})
    assert f'class="cta" href="/practice/{segment_id}/2"' in client.get("/").text


def test_no_next_link_when_everything_is_practised(client, tmp_path):
    segment_id = _seed(tmp_path)
    for unit in (1, 2):
        client.post("/api/rating",
                    data={"segment": segment_id, "unit": unit, "rating": 3})
    assert "开始下一句" not in client.get("/").text


def test_practice_page_offers_repeat_playback(client, tmp_path):
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/2").text
    assert 'class="times" value="10"' in body      # 盲听默认连播 10 遍
    # 放着的时候播放按钮自己变成「停」，不另起一个按钮——按钮位置不该跳
    assert body.count('class="play"') == 2
    assert 'class="stop"' not in body


def _wav_bytes(seconds=2.0):
    import io

    import numpy as np
    import soundfile as sf

    t = np.arange(int(seconds * 16000)) / 16000
    buffer = io.BytesIO()
    sf.write(buffer, (0.4 * np.sin(2 * np.pi * 200 * t)).astype("float32"),
             16000, format="WAV")
    return buffer.getvalue()


def _stream(response):
    """NDJSON：前面每行一步进度，最后一行是 result 或 error。"""
    import json

    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_takes_endpoint_runs_the_whole_review(client, tmp_path, monkeypatch):
    from shadow import review
    from shadow.models import Word

    segment_id = _seed(tmp_path)
    fake = lambda path: tuple(                                    # noqa: E731
        Word(text=t, start=a, end=a + d)
        for t, a, d in (("It", 0.0, 0.3), ("was", 0.4, 0.1),
                        ("a", 0.5, 0.1), ("start.", 0.7, 0.4))
    )
    monkeypatch.setattr(review, "transcribe_words", fake)

    response = client.post(
        "/api/takes",
        data={"segment": segment_id, "unit": 2},
        files=[("files", ("a.wav", _wav_bytes(), "audio/wav")),
               ("files", ("b.wav", _wav_bytes(), "audio/wav"))],
    )
    assert response.status_code == 200, response.text
    data = _stream(response)[-1]["result"]
    assert data["count"] == 2
    assert data["accuracy"] == 100
    # 每一遍都出图，让人自己挑着看
    assert len(data["view"]["takes"]) == 2
    assert 0 <= data["view"]["chosen"] < 2
    one = data["view"]["takes"][0]
    # 反馈是几何数据，不是图片——图片里的字太小
    assert [b["text"] for b in one["rhythm"]["ref"]] == ["It", "was", "a", "start"]
    assert [s["text"] for s in one["pitch"]] == ["It", "was", "a", "start"]
    assert len(one["pitch"][0]["refTrace"]) > 2
    # 播放时要把当前时刻映射到是哪一格，所以每格带上各自音频里的秒数
    first = one["pitch"][0]
    assert first["refAt"][0] < first["refAt"][1]
    assert first["usrAt"][0] < first["usrAt"][1]
    # 每一遍指向自己那条录音
    assert one["audio"]["ref"] == f"/audio/{segment_id}/2"
    usr = {take["audio"]["usr"] for take in data["view"]["takes"]}
    assert len(usr) == 2
    assert all(client.get(url).status_code == 200 for url in usr)
    assert one["audio"]["refOffset"] == pytest.approx(0.1, abs=0.01)

    connection = db.connect()
    row = db.list_runs(connection, segment_id=segment_id)[0]
    assert len(db.run_metrics(connection, row["id"])) == 2
    connection.close()


def test_takes_endpoint_streams_progress_before_the_result(client, tmp_path,
                                                           monkeypatch):
    from shadow import review
    from shadow.models import Word

    segment_id = _seed(tmp_path)
    monkeypatch.setattr(review, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d)
        for t, a, d in (("It", 0.0, 0.3), ("was", 0.4, 0.1),
                        ("a", 0.5, 0.1), ("start.", 0.7, 0.4))
    ))

    response = client.post(
        "/api/takes",
        data={"segment": segment_id, "unit": 2},
        files=[("files", ("a.wav", _wav_bytes(), "audio/wav")),
               ("files", ("b.wav", _wav_bytes(), "audio/wav"))],
    )
    lines = _stream(response)
    progress = lines[:-1]

    # 原声一步，两遍录音两步
    assert [p["done"] for p in progress] == [0, 1, 2]
    assert {p["total"] for p in progress} == {3}
    assert progress[0]["label"] == "转写原声"
    assert progress[1]["label"] == "转写第 1/2 遍"
    assert progress[-1]["label"] == "转写第 2/2 遍"
    assert "result" in lines[-1]


def test_takes_endpoint_reports_unusable_recordings_in_the_stream(client, tmp_path,
                                                                  monkeypatch):
    from shadow import review
    from shadow.models import Word

    segment_id = _seed(tmp_path)
    # 时间戳整体晚 5 秒，对不上实际发声，每一遍都会被剔除
    monkeypatch.setattr(review, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d)
        for t, a, d in (("It", 5.0, 0.3), ("was", 5.4, 0.1),
                        ("a", 5.5, 0.1), ("start.", 5.7, 0.4))
    ))

    response = client.post(
        "/api/takes",
        data={"segment": segment_id, "unit": 2},
        files=[("files", ("a.wav", _wav_bytes(), "audio/wav"))],
    )

    assert response.status_code == 200
    assert "时间戳" in _stream(response)[-1]["error"]


def test_practice_page_has_a_progress_bar(client, tmp_path):
    segment_id = _seed(tmp_path)
    assert 'id="rec-progress"' in client.get(f"/practice/{segment_id}/2").text


def test_the_recorder_is_told_how_long_the_sentence_is(client, tmp_path):
    """自动停拿原声的两个时长当下限：真出声的时长（词时长之和）和整段时长。

    少了它们，头几遍还没顺下来、句中卡两秒的，会被当成说完而截断。
    """
    segment_id = _seed(tmp_path)

    body = client.get(f"/practice/{segment_id}/2").text

    assert re.search(r'id="practice"[^>]*data-seconds="\d+(\.\d+)?"', body, re.S)
    assert re.search(r'data-spoken="\d+(\.\d+)?"', body)
    assert 'id="stop-take"' in body      # 手动那条路留着


def test_take_audio_is_served_and_stays_inside_its_folder(client, tmp_path):
    _seed(tmp_path)
    name = "1-u1-0101-000000-1.wav"
    (config.attempt_audio_dir() / name).write_bytes(_wav_bytes())

    ok = client.get(f"/take/{name}")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "audio/wav"
    assert client.get("/take/..%2F..%2Fshadow.db").status_code == 404


def _silent_wav_bytes(seconds=2.0):
    import io

    import numpy as np
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(int(seconds * 16000), dtype="float32"), 16000,
             format="WAV")
    return buffer.getvalue()


def test_one_bad_take_does_not_throw_away_the_good_ones(client, tmp_path,
                                                        monkeypatch):
    """录坏一遍就整批作废，等于逼人从头再录三遍。坏的那遍剔掉就行。"""
    from shadow import review
    from shadow.models import Word

    segment_id = _seed(tmp_path)
    monkeypatch.setattr(review, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d)
        for t, a, d in (("It", 0.0, 0.3), ("was", 0.4, 0.1),
                        ("a", 0.5, 0.1), ("start.", 0.7, 0.4))
    ))

    response = client.post(
        "/api/takes",
        data={"segment": segment_id, "unit": 2},
        files=[("files", ("a.wav", _wav_bytes(), "audio/wav")),
               ("files", ("mute.wav", _silent_wav_bytes(), "audio/wav")),
               ("files", ("c.wav", _wav_bytes(), "audio/wav"))],
    )

    assert response.status_code == 200, response.text
    data = _stream(response)[-1]["result"]
    assert data["count"] == 2
    assert [r["index"] for r in data["rejected"]] == [2]
    assert "静音" in data["rejected"][0]["reason"]


def test_the_text_is_behind_a_button_in_the_shadowing_step(client, tmp_path):
    """跟读时屏幕上有字，人就会去读它而不是模仿声音。想看得自己点。"""
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/2").text

    assert 'id="peek"' in body
    tag = body[body.index('id="peek-text"'):]
    assert "hidden" in tag[:tag.index(">")]
    assert body.index('id="step-record"') < body.index('id="peek"')


def test_whether_the_text_was_seen_is_recorded(client, tmp_path, monkeypatch):
    """看不看原文对音高节奏影响多大，只能靠数据回答。"""
    from shadow import review
    from shadow.models import Word

    segment_id = _seed(tmp_path)
    monkeypatch.setattr(review, "transcribe_words", lambda path: tuple(
        Word(text=t, start=a, end=a + d)
        for t, a, d in (("It", 0.0, 0.3), ("was", 0.4, 0.1),
                        ("a", 0.5, 0.1), ("start.", 0.7, 0.4))
    ))

    response = client.post(
        "/api/takes",
        data={"segment": segment_id, "unit": 2, "saw_text": 1},
        files=[("files", ("a.wav", _wav_bytes(), "audio/wav"))],
    )
    run_id = _stream(response)[-1]["result"]["run_id"]

    connection = db.connect()
    row = connection.execute(
        "SELECT saw_text FROM practice_runs WHERE id = ?", (run_id,)
    ).fetchone()
    connection.close()
    assert row["saw_text"] == 1


def test_takes_rejects_a_silent_recording(client, tmp_path):
    import io

    import numpy as np
    import soundfile as sf

    segment_id = _seed(tmp_path)
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(32000, dtype="float32"), 16000, format="WAV")
    response = client.post(
        "/api/takes",
        data={"segment": segment_id, "unit": 2},
        files=[("files", ("silent.wav", buffer.getvalue(), "audio/wav"))],
    )
    assert response.status_code == 400
    assert "静音" in response.json()["detail"]


def test_practice_page_has_the_recording_controls(client, tmp_path):
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/2").text
    # 最短时长由服务端下发，页面不另写一份，免得两边卡的线不一样
    assert f'data-min-take="{config.MIN_ATTEMPT_SEC}"' in body
    assert 'id="start-record"' in body
    assert 'id="stop-take"' in body
    assert 'id="prelisten"' in body
    # 说错了、卡壳了要能当场作废：一遍念砸的录音会把三遍的中位数带偏
    assert 'id="redo-take"' in body


def _seed_other_source(tmp_path):
    import numpy as np
    import soundfile as sf

    connection = db.connect()
    db.init_db(connection)
    source = config.source_audio_dir() / "2.wav"
    t = np.arange(16000 * 4) / 16000
    sf.write(source, (0.4 * np.sin(2 * np.pi * 200 * t)).astype("float32"), 16000)
    source_id = db.create_source(connection, url="https://x/z", title="Z",
                                 duration_sec=4.0)
    db.finish_source(connection, source_id, audio_path=str(source))
    words = tuple(
        Word(text=t_, start=a, end=a + 0.4)
        for t_, a in (("Thank", 0.0), ("you", 0.5), ("all.", 1.0))
    )
    db.insert_segments(connection, source_id,
                       (Segment(idx=0, start=0.0, end=1.4, words=words),))
    segment_id = db.list_segments(connection, source_id)[0]["id"]
    connection.close()
    return segment_id


def test_health_says_the_service_is_up(client):
    """页面靠它判断服务还在不在，顺带看自己加载的脚本是不是最新的。"""
    from shadow.web.app import _asset_version

    response = client.get("/api/health")

    assert response.json() == {"ok": True, "assets": _asset_version()}
    # 缓存住的「在线」比没有指示灯更糟
    assert response.headers["cache-control"] == "no-store"


def test_every_page_carries_the_service_light(client, tmp_path):
    """服务从终端里开，关掉终端就停了；页面还开着却什么都存不进去，人是不知道的。"""
    segment_id = _seed_with_a_broken_unit(tmp_path)

    for url, status in (("/", 200), (f"/practice/{segment_id}/1", 200),
                        (f"/practice/{segment_id}/2", 409)):
        response = client.get(url)
        assert response.status_code == status
        assert 'id="service"' in response.text
        assert 'id="service-banner"' in response.text
        assert "/static/service.js" in response.text


def test_the_light_carries_the_command_that_brings_the_service_back(client):
    """断了的时候光说「断了」没用，得告诉人怎么恢复。"""
    body = client.get("/").text
    assert "uv run shadow serve" in body


def _seed_with_a_phantom_sentence(tmp_path):
    """第 2 句是转写凭空编的：词速正常，可那几秒的音频里没人说话。"""
    import numpy as np
    import soundfile as sf

    connection = db.connect()
    db.init_db(connection)
    source = config.source_audio_dir() / "7.wav"
    sr = 16000
    t_ = np.arange(sr * 6) / sr
    voice = (0.4 * np.sin(2 * np.pi * 200 * t_)).astype("float32")
    voice[int(1.2 * sr):int(3.8 * sr)] = 0.0      # 中间一段停顿，什么声音都没有
    sf.write(source, voice, sr)
    source_id = db.create_source(connection, url="https://x/p", title="P",
                                 duration_sec=6.0)
    db.finish_source(connection, source_id, audio_path=str(source))
    spec = [("One", 0.1, 0.3), ("two.", 0.5, 0.4),
            ("You", 1.6, 0.2), ("know,", 2.0, 0.3), ("I'm", 2.5, 0.2), ("fine.", 2.9, 0.4),
            ("Last", 4.1, 0.3), ("one.", 4.5, 0.4)]
    words = tuple(Word(text=x, start=a, end=a + d) for x, a, d in spec)
    db.insert_segments(connection, source_id,
                       (Segment(idx=0, start=0.0, end=6.0, words=words),))
    segment_id = db.list_segments(connection, source_id)[0]["id"]
    connection.close()
    return segment_id


def test_a_sentence_the_audio_does_not_contain_is_not_offered(client, tmp_path):
    """转写偶尔凭空编一句。强制对齐把它摊到停顿上，词速正常，老的检查拦不住，
    切出来却是静音——盲听时一点声音都没有。练不了的句子不该占着列表、句数和编号。"""
    segment_id = _seed_with_a_phantom_sentence(tmp_path)

    # 直接打开（旧链接、生词本里的出处）还是给个说明和出口
    response = client.get(f"/practice/{segment_id}/2")
    assert response.status_code == 409
    assert "找不到声音" in response.text
    assert f"/practice/{segment_id}/3" in response.text
    assert "第 None" not in response.text

    # 翻页跳过它，后面的句子接着编号
    assert f'href="/practice/{segment_id}/2"' not in client.get(
        f"/practice/{segment_id}/1").text
    assert "第 2 句 / 共 2 句" in client.get(f"/practice/{segment_id}/3").text

    # 列表里干脆不列，也不算进句数
    index = client.get("/").text
    assert "音频里没有这句" not in index
    assert f'href="/practice/{segment_id}/2"' not in index
    assert "练过 0 / 2 句" in index
    assert "练过 0 / 2 句" in client.get("/sources").text


def test_a_failed_submit_can_be_sent_again(client, tmp_path):
    """服务断掉那一刻最亏的是刚录的几遍。录音还在页面里，恢复后重新提交就行。"""
    segment_id = _seed(tmp_path)
    assert 'id="resubmit"' in client.get(f"/practice/{segment_id}/2").text
