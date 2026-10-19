"""IncidentRunner: the graph plus durable SQLite checkpoints (S31).

One thread_id per incident (thread_id == incident_id). Every node transition is
checkpointed, so a new process can resume an incident where the old one stopped.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import StateSnapshot

from incident_agent.config import Settings
from incident_agent.graph.builder import build_graph
from incident_agent.graph.runtime import Runtime, utcnow
from incident_agent.graph.state import IncidentState, initial_state
from incident_agent.llm import build_model
from incident_agent.llm.base import ChatModel
from incident_agent.log import get_logger
from incident_agent.mcp_client import ToolClient
from incident_agent.mocks.injector import inject
from incident_agent.models import Alert, ApprovalDecision
from incident_agent.policy.approvals import ApprovalStore

log = get_logger(__name__)


class IncidentExistsError(ValueError):
    """Refuse to reuse a thread_id: two incidents must never share one."""


class IncidentNotFoundError(LookupError):
    pass


def thread_config(incident_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {"thread_id": incident_id}
    if checkpoint_id:
        cfg["checkpoint_id"] = checkpoint_id
    return {"configurable": cfg}


class IncidentRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        model: ChatModel | None = None,
        tools: ToolClient | None = None,
        clock: Callable[[], datetime] = utcnow,
        health_check: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.settings = settings
        self._owns_tools = tools is None
        self.tools = tools or ToolClient.from_settings(settings)
        self.model = model or build_model(settings)
        settings.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(settings.checkpoint_db, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._conn)
        self.checkpointer.setup()
        self.runtime = Runtime(
            settings=settings,
            model=self.model,
            tools=self.tools,
            clock=clock,
            health_check=health_check,
        )
        self.store = ApprovalStore(settings.audit_db)
        self.graph = build_graph(
            self.runtime, self.checkpointer, on_approval_request=self.store.add_pending
        )

    # -- lifecycle ---------------------------------------------------------------------------

    def __enter__(self) -> IncidentRunner:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()
        if self._owns_tools:
            self.tools.close()

    # -- running -----------------------------------------------------------------------------

    def exists(self, incident_id: str) -> bool:
        return self.checkpointer.get_tuple(thread_config(incident_id)) is not None

    def start(self, scenario_id: str) -> str:
        incident_id, alert = inject(scenario_id)
        self.start_alert(incident_id, scenario_id, alert)
        return incident_id

    def start_alert(self, incident_id: str, scenario_id: str, alert: Alert) -> IncidentState:
        if self.exists(incident_id):
            raise IncidentExistsError(f"incident {incident_id} already has a thread")
        log.info("starting %s (%s)", incident_id, scenario_id)
        return self.graph.invoke(
            initial_state(incident_id, scenario_id, alert), thread_config(incident_id)
        )

    def resume(self, incident_id: str) -> IncidentState:
        """Continue from the last checkpoint; completed nodes are not re-run."""
        self._require(incident_id)
        return self.graph.invoke(None, thread_config(incident_id))

    # -- inspection --------------------------------------------------------------------------

    def snapshot(self, incident_id: str) -> StateSnapshot:
        self._require(incident_id)
        return self.graph.get_state(thread_config(incident_id))

    def history(self, incident_id: str) -> Iterator[StateSnapshot]:
        self._require(incident_id)
        return self.graph.get_state_history(thread_config(incident_id))

    def incident_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        ).fetchall()
        return [r[0] for r in rows]

    def _require(self, incident_id: str) -> None:
        if not self.exists(incident_id):
            raise IncidentNotFoundError(
                f"no incident {incident_id!r} in {self.settings.checkpoint_db}"
            )

    # -- approvals -----------------------------------------------------------------------

    def record_decisions(self, incident_id: str, decisions: list[ApprovalDecision]) -> None:
        """Write approval decisions into the halted thread's state (checkpointed)."""
        self._require(incident_id)
        self.graph.update_state(thread_config(incident_id), {"approvals": decisions})
        self.store.record(decisions)

    def pending_incidents(self) -> list[str]:
        """Incidents halted at the approval gate, oldest request first (from the durable store,
        cross-checked against each incident's checkpointed state)."""
        out = []
        for _, incident_id in self.store.pending_incidents():
            if self.exists(incident_id) and tuple(
                self.graph.get_state(thread_config(incident_id)).next
            ) == ("execute",):
                out.append(incident_id)
        return out
