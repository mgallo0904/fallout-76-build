from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_generate_and_get_build():
    generated = client.post('/api/build/generate', json={})
    assert generated.status_code == 200
    payload = generated.json()
    assert payload['build']['build_name'] == 'Power Armor Heavy Energy Gunner'
    build_id = payload['build']['id']

    fetched = client.get(f'/api/build/{build_id}')
    assert fetched.status_code == 200
    assert fetched.json()['id'] == build_id


def test_sources_and_update_endpoints():
    assert client.get('/api/sources').status_code == 200
    resp = client.post('/api/research/update')
    assert resp.status_code == 200
    assert 'checked' in resp.json()


def test_import_sources_rejects_invalid_payload_type():
    resp = client.post(
        '/api/admin/import/sources',
        files={'file': ('sources.json', '{"bad": true}', 'application/json')},
    )
    assert resp.status_code == 400
    assert 'Payload must be a JSON list' in resp.text


def test_brain_status_endpoint_hides_api_key(monkeypatch):
    monkeypatch.setenv('OLLAMA_API_KEY', 'secret-value')
    monkeypatch.setenv('USE_OLLAMA_BRAIN', '1')

    resp = client.get('/api/brain/status')

    assert resp.status_code == 200
    assert resp.json()['has_api_key'] is True
    assert 'secret-value' not in resp.text
