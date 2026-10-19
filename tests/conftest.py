"""Shared fixtures. Every test gets its own temp DB directory; nothing touches ./var."""

from __future__ import annotations

from pathlib import Path

import pytest

from incident_agent.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated settings: offline heuristic model, temp DBs, no retry sleeps."""
    return Settings(model_provider="heuristic", retry_base_delay=0.0).with_paths(tmp_path)
