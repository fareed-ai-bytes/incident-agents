"""Runtime settings, read from the environment (and an optional local .env file).

Every endpoint must be local (rules.md): `Settings` refuses a non-localhost Ollama URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlparse

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Module run as the stdio MCP server. Kept here (not in mcp_client/) so the client
# never names the server package (verification.md S12).
MCP_SERVER_MODULE = "incident_agent.mcp_server"


class ConfigError(ValueError):
    """Raised when settings are invalid (a setup error, not an incident)."""


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines from `path` into os.environ without overriding existing vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def ensure_local_url(url: str) -> str:
    """Return `url` unchanged if it points at localhost, else raise ConfigError."""
    host = urlparse(url).hostname
    if host not in LOCAL_HOSTS:
        raise ConfigError(
            f"Model endpoint must be localhost, got {url!r} (rules.md: no hosted LLMs)"
        )
    return url


@dataclass(frozen=True)
class Settings:
    model_provider: str = "ollama"
    model_name: str = "qwen2.5:7b-instruct"
    ollama_base_url: str = "http://localhost:11434"
    checkpoint_db: Path = Path("var/checkpoints.sqlite")
    audit_db: Path = Path("var/audit.sqlite")
    warehouse_db: Path = Path("var/warehouse.duckdb")
    max_iterations: int = 6
    max_reprompts: int = 2
    max_tool_attempts: int = 3
    max_verify_attempts: int = 2
    confidence_threshold: float = 0.6
    log_page_size: int = 200
    observation_window: int = 3
    approval_ttl_hours: float = 24.0
    retry_base_delay: float = 0.2
    log_level: str = "INFO"
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ensure_local_url(self.ollama_base_url)
        if self.model_provider not in {"ollama", "heuristic"}:
            raise ConfigError(
                f"MODEL_PROVIDER must be 'ollama' or 'heuristic', got {self.model_provider!r}"
            )

    @classmethod
    def from_env(cls, dotenv: bool = True) -> Settings:
        if dotenv:
            load_dotenv()
        env = os.environ
        defaults = cls()
        return cls(
            model_provider=env.get("MODEL_PROVIDER", defaults.model_provider),
            model_name=env.get("MODEL_NAME", defaults.model_name),
            ollama_base_url=env.get("OLLAMA_BASE_URL", defaults.ollama_base_url),
            checkpoint_db=Path(env.get("CHECKPOINT_DB", str(defaults.checkpoint_db))),
            audit_db=Path(env.get("AUDIT_DB", str(defaults.audit_db))),
            warehouse_db=Path(env.get("WAREHOUSE_DB", str(defaults.warehouse_db))),
            max_iterations=int(env.get("MAX_ITERATIONS", defaults.max_iterations)),
            confidence_threshold=float(
                env.get("CONFIDENCE_THRESHOLD", defaults.confidence_threshold)
            ),
            log_page_size=int(env.get("LOG_PAGE_SIZE", defaults.log_page_size)),
            approval_ttl_hours=float(env.get("APPROVAL_TTL_HOURS", defaults.approval_ttl_hours)),
            retry_base_delay=float(env.get("RETRY_BASE_DELAY", defaults.retry_base_delay)),
            log_level=env.get("LOG_LEVEL", defaults.log_level),
        )

    def with_paths(self, root: Path) -> Settings:
        """Copy of these settings with every DB file placed under `root` (used by tests)."""
        return replace(
            self,
            checkpoint_db=root / "checkpoints.sqlite",
            audit_db=root / "audit.sqlite",
            warehouse_db=root / "warehouse.duckdb",
        )

    def as_env(self) -> dict[str, str]:
        """Environment variables that reproduce these settings in a child process (MCP server)."""
        return {
            "MODEL_PROVIDER": self.model_provider,
            "MODEL_NAME": self.model_name,
            "OLLAMA_BASE_URL": self.ollama_base_url,
            "CHECKPOINT_DB": str(self.checkpoint_db),
            "AUDIT_DB": str(self.audit_db),
            "WAREHOUSE_DB": str(self.warehouse_db),
            "MAX_ITERATIONS": str(self.max_iterations),
            "CONFIDENCE_THRESHOLD": str(self.confidence_threshold),
            "LOG_PAGE_SIZE": str(self.log_page_size),
            "APPROVAL_TTL_HOURS": str(self.approval_ttl_hours),
            "RETRY_BASE_DELAY": str(self.retry_base_delay),
            "LOG_LEVEL": self.log_level,
        }
