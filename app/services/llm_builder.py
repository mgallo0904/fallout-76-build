from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.models import BuildCandidate


DEFAULT_MODEL = 'kimi-k2.6:cloud'


class BrainError(RuntimeError):
    """Raised when the optional Ollama brain cannot complete a request."""


@dataclass(frozen=True)
class _BrainConfig:
    model: str
    base_url: str
    api_key: str
    timeout_seconds: float

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _get_brain_config() -> _BrainConfig:
    api_key = os.getenv('OLLAMA_API_KEY') or ''
    default_base_url = 'https://ollama.com'
    base_url = os.getenv('OLLAMA_BASE_URL') or os.getenv('OLLAMA_HOST') or default_base_url
    return _BrainConfig(
        model=os.getenv('OLLAMA_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        base_url=base_url.rstrip('/'),
        api_key=api_key,
        timeout_seconds=_env_float('OLLAMA_TIMEOUT_SECONDS', 120.0, 1.0, 300.0),
    )


def _api_url(base_url: str, path: str) -> str:
    root = base_url.rstrip('/')
    if root.endswith('/api'):
        return f'{root}{path}'
    return f'{root}/api{path}'


def _post_json(url: str, payload: dict[str, Any], api_key: str | None, timeout_seconds: float) -> dict[str, Any]:
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


def _extract_json_object(text: str) -> dict[str, Any]:
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


def _chat_for_candidate(messages: list[dict[str, str]], cfg: _BrainConfig) -> dict[str, Any]:
    """Return the raw Ollama chat response dict."""
    return _post_json(
        _api_url(cfg.base_url, '/chat'),
        {
            'model': cfg.model,
            'messages': messages,
            'stream': False,
            'format': 'json',
        },
        cfg.api_key,
        cfg.timeout_seconds,
    )


def _parse_chat_response(response: dict[str, Any]) -> dict[str, Any]:
    """Extract JSON content from an Ollama chat response dict."""
    message = response.get('message', {})
    content = message.get('content') if isinstance(message, dict) else None
    if not content:
        content = response.get('response')
    if not isinstance(content, str) or not content.strip():
        raise BrainError('Ollama chat returned no message content')
    return _extract_json_object(content)


def generate_llm_candidate(
    messages: list[dict[str, str]],
    *,
    max_retries: int = 1,
) -> BuildCandidate:
    """
    Call Ollama API with the constructed prompt and parse the JSON response
    into a BuildCandidate. If parsing fails, retry once. If retry fails,
    return an empty BuildCandidate so the deterministic baseline is kept.
    """
    cfg = _get_brain_config()
    last_error: Exception | None = None

    for attempt in range(max(0, max_retries) + 1):
        try:
            response = _chat_for_candidate(messages, cfg)
            raw = _parse_chat_response(response)
            return BuildCandidate.model_validate(raw)
        except (BrainError, ValidationError, Exception) as exc:
            last_error = exc
            if attempt < max_retries:
                continue

    # All retries exhausted: return empty candidate so deterministic baseline is kept
    return BuildCandidate()
