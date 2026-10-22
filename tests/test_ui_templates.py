"""Navigation and accessible search structure shared by the native page layouts."""
from html.parser import HTMLParser

from tests.test_web import client, _seed, _source_of


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_detail_pages_return_to_their_parent(client, tmp_path):
    segment = _seed(tmp_path)
    routes = {
        f'/sources/{_source_of(segment)}': '/sources',
        '/vocab': '/sources',
        '/talk': '/start',
        '/plan/guide': '/plan',
        '/records/day/2026-10-15?range=month': '/records?range=month',
    }
    for route, parent in routes.items():
        response = client.get(route)
        assert response.status_code == 200, route
        elements = Elements(response.text).elements
        backs = [attrs for tag, attrs in elements if tag == 'a' and 'page-back' in attrs.get('class', '').split()]
        assert len(backs) == 1, route
        assert backs[0]['href'] == parent, route
        headings = [attrs for tag, attrs in elements if tag == 'h1']
        assert len(headings) == 1, route
        assert 'page-title' in headings[0].get('class', '').split(), route


def test_search_uses_decorative_vector_and_named_input(client):
    for route, search_id, label in [('/sources', 'library-search', '搜索素材'), ('/vocab', 'vocab-search', '搜索生词')]:
        response = client.get(route)
        assert response.status_code == 200
        elements = Elements(response.text).elements
        icons = [attrs for tag, attrs in elements if tag == 'svg' and 'search-icon' in attrs.get('class', '').split()]
        assert len(icons) == 1
        assert icons[0]['aria-hidden'] == 'true'
        assert icons[0]['focusable'] == 'false'
        inputs = [attrs for tag, attrs in elements if tag == 'input' and attrs.get('id') == search_id]
        assert inputs[0]['aria-label'] == label
        assert inputs[0]['type'] == 'search'
        assert '⌕' not in response.text


def test_desktop_layer_and_practice_rail_share_existing_controls(client, tmp_path):
    segment = _seed(tmp_path)
    body = client.get(f'/practice/{segment}/1').text
    assert '/static/desktop.css?v=' in body
    assert 'class="practice-rail"' in body
    assert body.count('id="practice-minimize"') == 1
    assert body.count('id="start-record"') == 1
    assert 'aria-label="主导航"' in body
    assert 'href="/start" aria-current="page"' in body
    assert 'data-route="/practice/' in body
    login = client.get('/login').text
    assert 'aria-label="主导航"' not in login


def test_overview_layouts_have_independent_responsive_regions(client):
    assert 'class="today-layout"' in client.get('/today').text
    assert 'class="records-overview"' in client.get('/records').text
    assert 'class="start-layout"' in client.get('/start').text


def test_removed_continuous_play_entry_points_are_gone(client):
    for route in ('/chain', '/chain?scope=week'):
        response = client.get(route, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == '/start'

    start = client.get('/start').text
    assert '/chain' not in start
    assert '整段跟读' not in start
