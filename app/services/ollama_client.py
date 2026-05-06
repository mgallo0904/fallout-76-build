"""Shared Ollama API client infrastructure.

Provides configuration parsing, HTTP POST logic, JSON object extraction,
and Ollama chat JSON request handling used by both brain.py and llm_builder.py.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_MODEL = 'kimi-k2.6:cloud'
DEFAULT_WEB_SEARCH_URL = 'https://ollama.com/api/web_search'


class BrainError(RuntimeError):
    """Raised when the optional Ollama brain cannot complete a request."""


# ---- Environment helpers ----

def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


# ---- Configuration ----

@dataclass(frozen=True)
class BrainConfig:
    model: str
    base_url: str
    api_key: str
    web_search_enabled: bool
    web_search_url: str
    timeout_seconds: float
    max_search_results: int

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


def get_brain_config(*, require_api_key: bool = True) -> BrainConfig:
    """Build the Ollama configuration from environment variables.

    When *require_api_key* is True (the default, used by brain.py), a missing
    OLLAMA_API_KEY raises BrainError.  When False (used by llm_builder.py),
    the key defaults to an empty string so that local Ollama instances work
    without an explicit key.
    """
    api_key = os.getenv('OLLAMA_API_KEY') or ''
    if require_api_key and not api_key:
        raise BrainError('OLLAMA_API_KEY is required for mandatory brain mode')
    default_base_url = 'https://ollama.com'
    base_url = os.getenv('OLLAMA_BASE_URL') or os.getenv('OLLAMA_HOST') or default_base_url
    return BrainConfig(
        model=os.getenv('OLLAMA_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        base_url=base_url.rstrip('/'),
        api_key=api_key,
        web_search_enabled=env_bool('OLLAMA_WEB_SEARCH', True),
        web_search_url=os.getenv('OLLAMA_WEB_SEARCH_URL', DEFAULT_WEB_SEARCH_URL).rstrip('/'),
        timeout_seconds=env_float('OLLAMA_TIMEOUT_SECONDS', 120.0, 1.0, 600.0),
        max_search_results=env_int('OLLAMA_MAX_SEARCH_RESULTS', 5, 1, 10),
    )


# ---- HTTP ----

def api_url(base_url: str, path: str) -> str:
    root = base_url.rstrip('/')
    if root.endswith('/api'):
        return f'{root}{path}'
    return f'{root}/api{path}'


def post_json(url: str, payload: dict[str, Any], api_key: str | None, timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload, default=str).encode('utf-8')
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:500]
        raise BrainError(f'Ollama HTTP {exc.code}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise BrainError(f'Ollama connection failed: {exc.reason}') from exc
    except TimeoutError as exc:
        raise BrainError('Ollama request timed out') from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrainError(f'Ollama returned invalid JSON: {exc}') from exc


# ---- JSON extraction ----

def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith('```'):
        lines = [line for line in stripped.splitlines() if not line.strip().startswith('```')]
        stripped = '\n'.join(lines).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find('{')
        end = stripped.rfind('}')
        if start < 0 or end <= start:
            raise BrainError('Ollama response did not contain a JSON object')
        try:
            parsed = json.loads(stripped[start:end + 1])
        except json.JSONDecodeError as exc:
            raise BrainError(f'Ollama response JSON could not be parsed: {exc}') from exc

    if not isinstance(parsed, dict):
        raise BrainError('Ollama response JSON must be an object')
    return parsed


# ---- Chat helpers ----

def chat_json(messages: list[dict[str, str]], cfg: BrainConfig) -> dict[str, Any]:
    """Send a chat request to Ollama and return parsed JSON from the response content."""
    response = post_json(
        api_url(cfg.base_url, '/chat'),
        {
            'model': cfg.model,
            'messages': messages,
            'stream': False,
            'format': 'json',
        },
        cfg.api_key,
        cfg.timeout_seconds,
    )
    message = response.get('message', {})
    content = message.get('content') if isinstance(message, dict) else None
    if not content:
        content = response.get('response')
    if not isinstance(content, str) or not content.strip():
        raise BrainError('Ollama chat returned no message content')
    return extract_json_object(content)


def chat_raw(messages: list[dict[str, str]], cfg: BrainConfig) -> dict[str, Any]:
    """Send a chat request to Ollama and return the raw response dict (before JSON extraction)."""
    return post_json(
        api_url(cfg.base_url, '/chat'),
        {
            'model': cfg.model,
            'messages': messages,
            'stream': False,
            'format': 'json',
        },
        cfg.api_key,
        cfg.timeout_seconds,
    )
