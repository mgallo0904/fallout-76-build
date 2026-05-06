"""LLM-based build candidate generation.

Retains only candidate-build generation logic. Shared Ollama infrastructure
lives in ollama_client.py.
"""
from __future__ import annotations

from pydantic import ValidationError

from app.models import BuildCandidate
from app.services.ollama_client import (
    BrainError,
    chat_raw,
    extract_json_object,
    get_brain_config,
)

# Re-export so existing test imports continue to work.
_extract_json_object = extract_json_object


def _parse_chat_response(response: dict) -> dict:
    """Extract JSON content from an Ollama chat response dict."""
    message = response.get('message', {})
    content = message.get('content') if isinstance(message, dict) else None
    if not content:
        content = response.get('response')
    if not isinstance(content, str) or not content.strip():
        raise BrainError('Ollama chat returned no message content')
    return extract_json_object(content)


def _chat_for_candidate(messages: list[dict[str, str]], cfg=None):
    """Return the raw Ollama chat response dict."""
    if cfg is None:
        cfg = get_brain_config(require_api_key=False)
    return chat_raw(messages, cfg)


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
    cfg = get_brain_config(require_api_key=False)
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
