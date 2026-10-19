"""Tool-level retry (BR-04): exponential backoff with jitter, transient errors only.

Separate from the model-level re-prompt in loop.py: they fail for different reasons and have
different caps (memory.md).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from incident_agent.errors import TransientToolError
from incident_agent.log import get_logger

log = get_logger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 2.0

    def delay(self, attempt: int, jitter: float) -> float:
        """Delay after failed `attempt` (1-based): base * 2^(attempt-1), plus up to 100% jitter."""
        backoff = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return backoff * (1 + jitter)


DEFAULT_POLICY = RetryPolicy()


@dataclass(frozen=True)
class RetryOutcome(Generic[T]):
    value: T
    attempts: int


def call_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy = DEFAULT_POLICY,
    *,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
    label: str = "tool",
) -> RetryOutcome[T]:
    """Run `fn`; retry TransientToolError up to policy.max_attempts. Anything else propagates
    immediately (a permanent error is attempted exactly once). Re-raises the last transient
    error when attempts run out."""
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return RetryOutcome(fn(), attempt)
        except TransientToolError as exc:
            if attempt == policy.max_attempts:
                log.warning(
                    "%s: transient failure, attempts exhausted (%d): %s", label, attempt, exc
                )
                raise
            wait = policy.delay(attempt, jitter())
            log.info(
                "%s: transient failure (attempt %d), retrying in %.2fs: %s",
                label,
                attempt,
                wait,
                exc,
            )
            sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover
