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


def test_agent_plan_endpoint(monkeypatch):
    from app import main as m
    monkeypatch.setattr(m, "kimi_reason_with_search", lambda prompt: {"model":"kimi-k2.6:cloud","response":"ok","web_results":[]})
    r = client.post("/api/agent/plan", json={"ai_prompt":"test"})
    assert r.status_code == 200
    assert r.json()["model"] == "kimi-k2.6:cloud"
