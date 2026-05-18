"""Cumulative spend tracker for the AI Credits provider.

Enforces a hard INR cap (default ₹5) so a misconfigured loop or runaway
prompt cannot drain the wallet. State is persisted to a JSON file so the
counter survives restarts. All access is thread-safe.

Pricing is approximate — `aicredits.in` may not return cost in the
response, so we estimate from token usage using configurable per-1k
rates from `AppSettings`. If a real `cost`/`total_cost` field appears in
the upstream response, that value is preferred.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.config import get_settings


_LOCK = threading.Lock()
_STATE_PATH = (
    Path(os.path.dirname(os.path.dirname(__file__))) / "workspace" / "aicredits_spend.json"
)


def _load() -> dict[str, Any]:
    if not _STATE_PATH.exists():
        return {"total_inr": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    try:
        with _STATE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {"total_inr": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    return {
        "total_inr": float(data.get("total_inr", 0.0)),
        "prompt_tokens": int(data.get("prompt_tokens", 0)),
        "completion_tokens": int(data.get("completion_tokens", 0)),
        "calls": int(data.get("calls", 0)),
    }


def _save(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, _STATE_PATH)


def get_spend() -> dict[str, Any]:
    """Return the current spend snapshot."""
    with _LOCK:
        return _load()


def get_remaining_inr() -> float:
    settings = get_settings()
    state = get_spend()
    return max(0.0, settings.aicredits_inr_limit - state["total_inr"])


def assert_within_limit() -> None:
    """Raise RuntimeError if the cumulative spend already met the cap."""
    settings = get_settings()
    state = get_spend()
    if state["total_inr"] >= settings.aicredits_inr_limit:
        raise RuntimeError(
            f"AI Credits limit reached: ₹{state['total_inr']:.4f} of "
            f"₹{settings.aicredits_inr_limit:.2f} consumed. Reset the "
            f"counter at {_STATE_PATH} to continue."
        )


def _estimate_inr(prompt_tokens: int, completion_tokens: int) -> float:
    settings = get_settings()
    return (
        (prompt_tokens / 1000.0) * settings.aicredits_inr_per_1k_input_tokens
        + (completion_tokens / 1000.0) * settings.aicredits_inr_per_1k_output_tokens
    )


def record_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Increment the spend counter from an upstream usage block.

    Accepts the raw `usage` dict that OpenAI-compatible providers return.
    If a `cost`/`total_cost`/`cost_inr` field is present we trust it
    verbatim; otherwise we estimate from tokens.

    Returns the updated state snapshot.
    """
    if not usage:
        return get_spend()

    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)

    explicit_cost = (
        usage.get("cost_inr")
        or usage.get("total_cost_inr")
        or usage.get("total_cost")
        or usage.get("cost")
    )
    inr = (
        float(explicit_cost)
        if explicit_cost is not None
        else _estimate_inr(prompt_tokens, completion_tokens)
    )

    with _LOCK:
        state = _load()
        state["total_inr"] = round(state["total_inr"] + inr, 6)
        state["prompt_tokens"] += prompt_tokens
        state["completion_tokens"] += completion_tokens
        state["calls"] += 1
        _save(state)
        return state


def reset() -> None:
    """Reset the counter (admin-only; used by tests / manual override)."""
    with _LOCK:
        _save({"total_inr": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
