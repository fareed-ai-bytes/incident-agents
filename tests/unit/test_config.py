import pytest

from incident_agent.config import ConfigError, Settings, ensure_local_url


def test_package_imports():
    import incident_agent

    assert incident_agent.__version__


def test_local_urls_accepted():
    for url in ("http://localhost:11434", "http://127.0.0.1:11434/v1"):
        assert ensure_local_url(url) == url


def test_hosted_model_url_rejected():
    with pytest.raises(ConfigError):
        Settings(ollama_base_url="https://api.openai.com")


def test_unknown_provider_rejected():
    with pytest.raises(ConfigError):
        Settings(model_provider="openai")


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("MAX_ITERATIONS", "4")
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.7")
    s = Settings.from_env(dotenv=False)
    assert s.max_iterations == 4
    assert s.confidence_threshold == 0.7
