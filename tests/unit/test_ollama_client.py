import json

import httpx
import pytest

from incident_agent.config import ConfigError
from incident_agent.llm.base import ModelError
from incident_agent.llm.ollama import OllamaChatModel


def _transport(handler):
    return httpx.MockTransport(handler)


def test_rejects_non_local_endpoint():
    with pytest.raises(ConfigError):
        OllamaChatModel("m", "https://api.anthropic.com")


def test_parses_tool_calls_and_normalises_dict_arguments():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "search_logs"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {
                                        "name": "search_logs",
                                        "arguments": {"pattern": "ERROR"},
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    model = OllamaChatModel("m", transport=_transport(handler))
    tools = [{"type": "function", "function": {"name": "search_logs", "parameters": {}}}]
    msg = model.chat([{"role": "user", "content": "hi"}], tools)
    call = msg["tool_calls"][0]
    assert call["function"]["name"] == "search_logs"
    assert json.loads(call["function"]["arguments"]) == {"pattern": "ERROR"}


def test_retries_once_then_raises_clear_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("connection refused")

    model = OllamaChatModel("m", transport=_transport(handler))
    with pytest.raises(ModelError, match="ollama serve"):
        model.chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 2
