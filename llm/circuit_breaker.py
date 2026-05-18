"""Per-provider circuit breaker for LLM calls.

Why this exists
---------------
Without a breaker, when Groq has a regional outage every chat request
spends ~15s exhausting the tenacity retries (3 attempts × exponential
backoff) before we even try Gemini. With dozens of concurrent users
that's enough latency to chew through Cloud Run's request budget and
make the whole app feel hung.

A circuit breaker fast-fails calls to a provider that has recently been
seen to fail repeatedly, so the fallback path is hit immediately. After
a cool-down window the breaker enters a "half-open" state and lets one
trial request through; on success it closes again, on failure the
cool-down resets.

This is deliberately a tiny implementation — no external library,
process-local state. Across multiple Cloud Run instances each replica
has its own view, which is acceptable: failures correlate, so each
replica will trip its own breaker around the same time.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: float = 0.0
    state: str = "closed"  # "closed" | "open" | "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the breaker is open."""


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        # Three consecutive failures trip the breaker. The default
        # cool-down (60s) is long enough to ride out a typical provider
        # blip but short enough that a recovered provider re-enters
        # rotation quickly.
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, _BreakerState] = {}
        self._lock = threading.Lock()

    def _get(self, name: str) -> _BreakerState:
        state = self._states.get(name)
        if state is None:
            state = _BreakerState()
            self._states[name] = state
        return state

    def allow(self, name: str) -> bool:
        """Return True if the caller may proceed; False if breaker is open."""
        with self._lock:
            state = self._get(name)
            if state.state == "closed":
                return True
            if state.state == "open":
                if (time.monotonic() - state.opened_at) >= self.cooldown_seconds:
                    # Cool-down elapsed — let one trial through.
                    state.state = "half_open"
                    logger.info("Circuit breaker for %s entering half-open state", name)
                    return True
                return False
            # half_open: only one trial at a time; subsequent callers
            # must wait until success/failure resolves the state.
            return True

    def record_success(self, name: str) -> None:
        with self._lock:
            state = self._get(name)
            if state.state != "closed":
                logger.info("Circuit breaker for %s closed after success", name)
            state.failures = 0
            state.opened_at = 0.0
            state.state = "closed"

    def record_failure(self, name: str) -> None:
        with self._lock:
            state = self._get(name)
            state.failures += 1
            if state.state == "half_open" or state.failures >= self.failure_threshold:
                state.state = "open"
                state.opened_at = time.monotonic()
                logger.warning(
                    "Circuit breaker for %s OPEN for %.0fs (failures=%d)",
                    name,
                    self.cooldown_seconds,
                    state.failures,
                )


# Shared module-level breaker. One instance keeps the same view across
# every caller in the process; importing it doesn't reset its state.
llm_breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)


def call_with_breaker(name: str, fn, *args, **kwargs):
    """Run ``fn(*args, **kwargs)`` guarded by the named breaker.

    Raises ``CircuitOpenError`` immediately if the breaker is open.
    Records success / failure based on whether ``fn`` raises.
    """
    if not llm_breaker.allow(name):
        raise CircuitOpenError(f"Circuit open for provider {name!r}")
    try:
        result = fn(*args, **kwargs)
    except Exception:
        llm_breaker.record_failure(name)
        raise
    llm_breaker.record_success(name)
    return result
