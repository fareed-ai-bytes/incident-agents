"""Ollama client over its OpenAI-compatible HTTP API, using plain httpx (no SDK)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from incident_agent.config import ensure_local_url
from incident_agent.llm.base import ChatMessage, ModelError, ToolSchema
from incident_agent.log import get_logger

log = get_logger(__name__)


class OllamaChatModel:
    """Calls `{base_url}/v1/chat/completions`. Retries once, then raises ModelError."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        *,
        temperature: float = 0.0,
        timeout: float = 120.0,
        connect_timeout: float = 3.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = model
        self.base_url = ensure_local_url(base_url).rstrip("/")
        self.temperature = temperature
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
        )

    def chat(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
        *,
        purpose: str = "",
    ) -> ChatMessage:
        payload: dict[str, Any] = {
            "model": self.name,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        last_error: Exception | None = None
        for attempt in (1, 2):  # architecture.md: retry once, then fail clearly
            try:
                resp = self._client.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
                return _to_message(resp.json())
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last_error = exc
                log.warning("ollama call failed (%s, attempt %d): %s", purpose, attempt, exc)
        raise ModelError(
            f"Ollama at {self.base_url} failed for model {self.name!r}: {last_error}. "
            "Is `ollama serve` running and the model pulled?"
        ) from last_error

    def list_models(self) -> list[str]:
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelError(f"Ollama at {self.base_url} is unreachable: {exc}") from exc
        return [m["name"] for m in resp.json().get("models", [])]


def _to_message(body: dict[str, Any]) -> ChatMessage:
    raw = body["choices"][0]["message"]
    msg: ChatMessage = {"role": "assistant", "content": raw.get("content") or ""}
    calls = raw.get("tool_calls") or []
    if calls:
        msg["tool_calls"] = [
            {
                "id": c.get("id") or f"call_{i}",
                "type": "function",
                "function": {
                    "name": c["function"]["name"],
                    # Ollama sometimes returns a dict here; normalise to a JSON string.
                    "arguments": c["function"]["arguments"]
                    if isinstance(c["function"]["arguments"], str)
                    else json.dumps(c["function"]["arguments"]),
                },
            }
            for i, c in enumerate(calls)
        ]
    return msg
