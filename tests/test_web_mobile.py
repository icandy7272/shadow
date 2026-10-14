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
