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
    """一个片段，两句话，第二句有两个挖空位。"""
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
    words = tuple(
        Word(text=t_, start=a, end=a + d, is_blank=t_ in {"was", "a"})
        for t_, a, d in spec
    )
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
    """记录里带着句子原文的片段，提前露出来盲听和填空就废了。"""
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


def test_the_pager_walks_across_segment_boundaries(client, tmp_path):
    """句子是连着编号的，走到一段的末尾该接着进下一段，不是没路了。"""
    first = _seed(tmp_path)
    second = _seed_without_blanks(tmp_path)

    body = client.get(f"/practice/{first}/2").text
    assert f'href="/practice/{second}/1"' in body

    body = client.get(f"/practice/{second}/1").text
    assert f'href="/practice/{first}/2"' in body


def test_the_index_lists_a_running_sentence_number(client, tmp_path):
    _seed(tmp_path)
    body = client.get("/").text

    assert "<th>片段</th>" not in body
    assert ">1</td>" in body


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


def test_gapfill_separates_heard_from_guessed(client, tmp_path):
    segment_id = _seed(tmp_path)
    payload = {
        "segment": segment_id, "unit": 2, "replays": 2,
        "answers": [
            {"index": 1, "guess": "was", "guessed": False},
            {"index": 2, "guess": "a", "guessed": True},
        ],
    }
    data = client.post("/api/gapfill", json=payload).json()
    assert (data["correct"], data["total"], data["heard"]) == (2, 2, 1)
    assert data["items"][1]["heard"] is False

    connection = db.connect()
    row = db.list_runs(connection, segment_id=segment_id)[0]
    assert (row["gapfill_correct"], row["gapfill_heard"], row["gapfill_replays"]) == (2, 1, 2)
    connection.close()


def test_gapfill_reports_the_swallowed_duration_on_a_miss(client, tmp_path):
    segment_id = _seed(tmp_path)
    payload = {"segment": segment_id, "unit": 2, "replays": 0,
               "answers": [{"index": 1, "guess": "were", "guessed": False}]}
    data = client.post("/api/gapfill", json=payload).json()
    assert data["items"][0]["correct"] is False
    assert data["items"][0]["ms"] == 100


def test_index_hides_the_text_of_unpractised_units(client, tmp_path):
    """列表页把原文都列出来，等于还没开始练就把整篇读了一遍。

    原文仍在 data 属性里（勾选「全部显示」时要用），但不能被渲染出来——
    目的是避免不小心读到，不是防偷看。
    """
    segment_id = _seed(tmp_path)
    body = client.get("/").text
    assert "未练过" in body
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
    assert body.count('button class="stop"') == 2  # 每个播放控件都能中途停


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


def _seed_without_blanks(tmp_path):
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


def test_step_two_is_omitted_when_there_is_nothing_to_fill(client, tmp_path):
    """没有挖空位时那一步无事可做，不该还要点一次「对答案」才解锁。"""
    segment_id = _seed_without_blanks(tmp_path)
    body = client.get(f"/practice/{segment_id}/1").text
    assert 'id="step-drill"' not in body
    assert "对答案" not in body
    assert 'id="step-record"' in body
    assert '<span class="n">2</span> 跟读' in body      # 跟读顺位变成第 2 步


def test_step_two_is_present_when_there_are_blanks(client, tmp_path):
    segment_id = _seed(tmp_path)
    body = client.get(f"/practice/{segment_id}/2").text
    assert 'id="step-drill"' in body
    assert '<span class="n">3</span> 跟读' in body
