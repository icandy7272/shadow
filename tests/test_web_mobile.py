from datetime import datetime, timedelta
from tests.test_web import client, _seed, _source_of
from shadow import db, plan


def test_today_uses_current_source_and_real_week(client, tmp_path):
    segment = _seed(tmp_path)
    page = client.get('/today')
    assert page.status_code == 200
    assert f'href="/practice/{segment}/1"' in page.text
    assert f'href="/sources/{_source_of(segment)}"' in page.text
    assert page.text.count('class="week-day') == 7
    assert datetime.now().astimezone().date().isoformat() in page.text
    for step in plan.steps_for(datetime.now().astimezone().weekday()):
        assert f'id="plan-{step.key}"' in page.text


def test_today_empty_still_shows_plan_and_import_action(client):
    page = client.get('/today')
    assert page.status_code == 200
    assert '还没有导入素材' in page.text
    assert 'id="plan"' in page.text


def test_records_combines_real_talk_history_and_calendar(client):
    client.get('/sources')
    connection = db.connect()
    day = datetime.now().astimezone().date().isoformat()
    db.add_talk(connection, day=day, kind='retell', audio_path='/tmp/retell.webm', seconds=42)
    db.add_talk(connection, day=day, kind='free_talk', audio_path='/tmp/free.webm', seconds=120, picks=['a fresh start'])
    connection.execute('INSERT INTO practice_archive (day, sentence, rounds) VALUES (?, ?, ?)', (day, 'An archived sentence.', 3))
    connection.commit()
    connection.close()
    page = client.get('/records')
    assert page.status_code == 200
    assert '/talk/audio/retell.webm' in page.text
    assert '/talk/audio/free.webm' in page.text
    assert 'a fresh start' in page.text
    assert '练习日历' in page.text
    assert f'{day}：1 句 / 3 轮' in page.text


def test_records_range_filters_real_archive_and_talks(client):
    client.get('/sources')
    connection = db.connect()
    today = datetime.now().astimezone().date()
    old = today - timedelta(days=40)
    for day in (today, old):
        db.add_talk(connection, day=day.isoformat(), kind='retell', audio_path=f'/tmp/{day}.webm', seconds=42)
        connection.execute('INSERT INTO practice_archive (day, sentence, rounds) VALUES (?, ?, ?)', (day.isoformat(), str(day), 3))
    connection.commit()
    connection.close()
    for selected in ('week', 'month'):
        recent = client.get(f'/records?range={selected}').text
        assert f'/talk/audio/{today}.webm' in recent
        assert f'/talk/audio/{old}.webm' not in recent
        assert 'data-sentences="1" data-rounds="3" data-talks="1"' in recent
        assert f'href="/records?range={selected}" aria-current="page"' in recent
    assert 'href="/records?range=week" aria-current="page"' in client.get('/records?range=invalid').text
    entire = client.get('/records?range=all').text
    assert f'/talk/audio/{old}.webm' in entire
    assert 'data-sentences="2" data-rounds="6" data-talks="2"' in entire


def test_native_start_and_five_slot_navigation(client, tmp_path):
    segment = _seed(tmp_path)
    page = client.get('/start')
    assert page.status_code == 200
    assert f'href="/practice/{segment}/1"' in page.text
    for href in ('/today', '/plan', '/start', '/records', '/sources'):
        assert f'href="{href}"' in page.text
    assert 'data-session-start' in page.text
    assert 'session.js' in page.text


def test_native_settings_and_practice_session_controls(client, tmp_path):
    segment = _seed(tmp_path)
    assert client.get('/settings').status_code == 200
    page = client.get(f'/practice/{segment}/1').text
    assert 'id="practice-minimize"' in page
    assert 'id="practice-finish"' in page
    assert 'id="session-finish"' in page


def test_record_day_and_plan_overview(client, tmp_path):
    _seed(tmp_path)
    day = datetime.now().astimezone().date().isoformat()
    assert f'/records/day/{day}' in client.get('/today').text
    page = client.get(f'/records/day/{day}')
    assert page.status_code == 200
    assert '这天还没有练习记录' in page.text
    assert client.get('/records/day/2026-02-30').status_code == 422
    assert client.get('/records/run/999999').status_code == 404
    assert 'id="plan"' in client.get('/plan').text
    assert '影子跟读日课' in client.get('/plan/guide').text


def test_records_keep_blind_runs_and_every_attempt(client, tmp_path):
    segment = _seed(tmp_path)
    connection = db.connect()
    run_ids = []
    for index in range(8):
        run = db.start_run(connection, segment_id=segment, unit_index=1, unit_text=f'Recorded sentence {index}')
        db.set_blind_rating(connection, run, 3)
        db.finish_run(connection, run)
        run_ids.append(run)
    for index in range(2):
        audio = tmp_path / f'actual-{index}.wav'
        audio.write_bytes(b'audio')
        db.add_attempt(connection, run_id=run_ids[-1], audio_path=str(audio), asr_text=f'Actual take {index}', metrics={'accuracy': 0.8, 'speech_ratio': 1.2, 'pause_ratio': None, 'issues': [{'title': '这里停顿过长'}]})
    connection.close()
    recent = client.get('/records?range=all').text
    assert recent.count('href="/records/run/') == 6
    assert '/records?range=all&history=all' in recent
    assert client.get('/records?range=all&history=all').text.count('href="/records/run/') == 8
    detail = client.get(f'/records/run/{run_ids[-1]}?range=all').text
    assert 'Recorded sentence 7' in detail
    assert 'Actual take 0' in detail and 'Actual take 1' in detail
    assert '/take/actual-0.wav' in detail and '/take/actual-1.wav' in detail
    assert '识别准确率：80%' in detail
    assert '发声时长相对原音：1.2 倍' in detail
    assert '这里停顿过长' in detail
    assert '<pre>' not in detail
    assert '停顿时长相对原音：' not in detail
    assert '?range=all' in detail
    blind = client.get(f'/records/run/{run_ids[0]}').text
    assert '盲听自评：3' in blind
    assert '这轮没有跟读录音' in blind


def test_records_talks_are_bounded_and_not_duplicated(client):
    client.get('/sources')
    connection = db.connect()
    day = datetime.now().astimezone().date().isoformat()
    for index in range(9):
        db.add_talk(connection, day=day, kind='retell', audio_path=f'/tmp/bounded-{index}.webm', seconds=42)
    connection.close()
    recent = client.get('/records?range=all').text
    assert recent.count('<audio ') == 6
    assert 'data-talks="9"' in recent
    full = client.get('/records?range=all&history=all').text
    assert full.count('<audio ') == 9
    assert '/talk/audio/bounded-0.webm' in full


def test_empty_plan_keeps_real_today_status(client):
    page = client.get('/plan')
    assert page.status_code == 200
    assert '今天还没练' in page.text
    assert 'href="/plan/guide"' in page.text


def test_today_week_navigation_preserves_today_task_and_real_archive(client):
    client.get('/sources')
    connection = db.connect()
    past = datetime.now().astimezone().date() - timedelta(days=7)
    connection.execute('INSERT INTO practice_archive (day, sentence, rounds) VALUES (?, ?, ?)', (past.isoformat(), 'Earlier sentence.', 2))
    connection.commit()
    connection.close()
    page = client.get('/today?week=-1')
    assert page.status_code == 200
    assert f'href="/records/day/{past.isoformat()}"' in page.text
    assert f'{past.isoformat()} · 1 句 · 2 轮' in page.text
    assert 'href="/today?week=-2"' in page.text
    assert 'href="/today?week=0"' in page.text
    assert 'href="/records" class="streak-card"' in page.text
    assert datetime.now().astimezone().date().isoformat() in page.text
    assert client.get('/today?week=1000').status_code == 422


def test_mobile_settings_include_optional_awake_and_touch_controls(client):
    page = client.get('/settings').text
    assert 'id="keep-screen-awake"' in page
    assert 'mobile-controls.js' in page


def test_home_screen_manifest_loads_with_credentials_and_covers_all_tabs(client):
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlsplit

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.manifests = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'link' and attrs.get('rel') == 'manifest':
                self.manifests.append(attrs)

    for page in ('/today', '/plan', '/start', '/records', '/sources', '/login'):
        parser = Links()
        parser.feed(client.get(page).text)
        assert len(parser.manifests) == 1
        link = parser.manifests[0]
        assert link.get('crossorigin') == 'use-credentials'
        response = client.get(link['href'])
        assert response.status_code == 200
        manifest = response.json()
        assert manifest['display'] == 'standalone'
        manifest_url = str(response.url)
        scope = urlsplit(urljoin(manifest_url, manifest['scope']))
        assert scope.path == '/'
        assert urlsplit(urljoin(manifest_url, manifest['start_url'])).path.startswith(scope.path)
        assert page.startswith(scope.path)
