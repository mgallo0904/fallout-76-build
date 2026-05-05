import pytest


@pytest.fixture(autouse=True)
def disable_external_brain(monkeypatch):
    monkeypatch.setenv('USE_OLLAMA_BRAIN', '0')
    monkeypatch.setenv('OLLAMA_WEB_SEARCH', '0')
