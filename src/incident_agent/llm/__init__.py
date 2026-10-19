"""Local chat models: Ollama (real) and a deterministic heuristic model (offline / CI)."""

from __future__ import annotations

from incident_agent.config import Settings
from incident_agent.llm.base import ChatMessage, ChatModel, ModelError, ToolCall, ToolSchema

__all__ = ["ChatMessage", "ChatModel", "ModelError", "ToolCall", "ToolSchema", "build_model"]


def build_model(settings: Settings) -> ChatModel:
    """Model for `settings.model_provider`. Only localhost endpoints are ever built."""
    if settings.model_provider == "heuristic":
        from incident_agent.llm.heuristic import HeuristicModel

        return HeuristicModel()
    from incident_agent.llm.ollama import OllamaChatModel

    return OllamaChatModel(settings.model_name, settings.ollama_base_url)
