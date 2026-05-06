import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_brain(monkeypatch):
    """Mock brain enhancement so tests don't require live Ollama calls."""
    monkeypatch.setenv('OLLAMA_API_KEY', 'test-key')
    monkeypatch.setenv('OLLAMA_WEB_SEARCH', '0')

    def _noop_enhance(user, build, validation_issues, **_kwargs):
        build.brain_confirmed = True
        build.logic_engine = 'ollama:kimi-k2.6:cloud'
        return {
            'enabled': True,
            'model': 'kimi-k2.6:cloud',
            'web_search_enabled': False,
            'search_results': 0,
            'notes': ['Mock brain confirmation.'],
        }

    with patch('app.services.engine.enhance_build_with_brain', _noop_enhance):
        with patch('app.services.brain.enhance_build_with_brain', _noop_enhance):
            yield
