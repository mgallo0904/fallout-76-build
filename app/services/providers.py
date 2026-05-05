from __future__ import annotations
import os
import requests
from typing import Any

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "kimi-k2.6:cloud")


def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Lightweight web search using DuckDuckGo instant answer + html endpoint fallback."""
    results: list[dict[str, Any]] = []
    instant = requests.get(
        "https://api.duckduckgo.com/",
        params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        timeout=15,
    )
    instant.raise_for_status()
    payload = instant.json()
    related = payload.get("RelatedTopics", [])
    for item in related:
        if isinstance(item, dict) and item.get("Text") and item.get("FirstURL"):
            results.append({"title": item["Text"], "url": item["FirstURL"]})
            if len(results) >= max_results:
                break
    return results


def ollama_chat(messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={"model": model or OLLAMA_MODEL, "messages": messages, "stream": False},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def kimi_reason_with_search(user_prompt: str) -> dict[str, Any]:
    web = web_search(user_prompt, max_results=5)
    web_context = "\n".join([f"- {x['title']} ({x['url']})" for x in web])
    system = (
        "You are a Fallout 76 build logic assistant. Use provided web findings as evidence, "
        "avoid hallucination, and mark uncertain claims explicitly."
    )
    user = f"User request: {user_prompt}\n\nWeb findings:\n{web_context}\n\nReturn concise structured guidance."
    ai = ollama_chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    return {"model": model_name(ai), "response": ai.get("message", {}).get("content", ""), "web_results": web}


def model_name(payload: dict[str, Any]) -> str:
    return str(payload.get("model") or OLLAMA_MODEL)
