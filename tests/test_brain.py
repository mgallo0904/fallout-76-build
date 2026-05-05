from app.services.brain import DEFAULT_MODEL, api_url, brain_status, extract_json_object


def test_extract_json_object_from_fenced_response():
    parsed = extract_json_object('```json\n{"ok": true, "items": [1]}\n```')
    assert parsed == {'ok': True, 'items': [1]}


def test_default_brain_config_hides_key_and_uses_kimi(monkeypatch):
    monkeypatch.setenv('OLLAMA_API_KEY', 'secret-value')
    monkeypatch.setenv('USE_OLLAMA_BRAIN', '1')
    status = brain_status()

    assert status['enabled'] is True
    assert status['model'] == DEFAULT_MODEL
    assert status['has_api_key'] is True
    assert 'secret-value' not in str(status)


def test_api_url_normalizes_hosts():
    assert api_url('https://ollama.com', '/chat') == 'https://ollama.com/api/chat'
    assert api_url('https://ollama.com/api', '/chat') == 'https://ollama.com/api/chat'
