import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from wmm.app import app

ARTICLE = """<html><head><title>Testing The Service Endpoint</title></head><body>
<nav><a href=/>Home</a><a href=/x>Other</a></nav>
<main class=article><h1>Testing The Service Endpoint</h1>
<p>""" + ('A sufficiently long paragraph of prose that should survive extraction. ' * 8) + """</p>
<p>""" + ('A second paragraph with more prose so the validation gate is satisfied. ' * 8) + """</p>
</main><footer>Copyright. All rights reserved.</footer></body></html>"""


def client(tmp_path, monkeypatch):
    from wmm import config
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    import wmm.app as appmod
    appmod._store = None
    return TestClient(app)


def test_health_and_extract(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.get('/health').json()['ok'] is True

    r = c.post('/extract', json={'html': ARTICLE, 'url': 'https://example.com/t'})
    assert r.status_code == 200
    body = r.json()
    assert body['validated'] is True
    assert body['tier'] in ('generic', 'rule')
    assert 'sufficiently long paragraph' in body['markdown']

    s = c.get('/stats').json()
    assert s['episodes'] == 1


def test_extract_requires_input(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post('/extract', json={}).status_code == 400
    assert c.post('/extract', json={'html': ARTICLE, 'profile': 'bogus'}).status_code == 400


def test_rule_endpoints(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post('/rules', json={'signature': 'abc', 'include_xpaths': ['//article'],
                              'activate': True})
    assert r.status_code == 200
    rid = r.json()['_id']
    assert c.get('/rules?status=active').json()['rules']
    assert c.post(f'/rules/{rid}/status', json={'status': 'retired'}).json()['status'] == 'retired'
    assert c.post(f'/rules/{rid}/status', json={'status': 'nonsense'}).status_code == 404


def test_extract_rejects_unfetchable_url(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post('/extract', json={'url': 'ftp://example.com/x'})
    assert r.status_code == 422
