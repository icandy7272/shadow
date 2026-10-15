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
        '/chain': '/start',
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
