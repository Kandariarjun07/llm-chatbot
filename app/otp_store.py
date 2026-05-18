"""Persistent OTP store with Redis backend and in-memory fallback.

The original implementation kept OTPs in a module-level dict in
``api/auth_routes.py``. That works fine for a single-process dev box,
but on Cloud Run / any multi-worker deployment it has two problems:

1. **OTPs evaporate on restart.** A user who requests an OTP, then we
   redeploy 30 seconds later, sees "OTP expired" forever.
2. **OTPs are not shared across replicas.** Two Cloud Run instances
   each have their own dict; the user might hit a different replica
   on verify than on send.

This module fixes both by using Redis when ``REDIS_HOST`` is set, with
TTL handled by Redis itself, and falling back to the same in-process
dict otherwise. Failed-attempt counts use ``HINCRBY`` so they stay
atomic across replicas.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.rate_limits import _redis_client

logger = logging.getLogger(__name__)


_MEMORY: dict[str, dict[str, Any]] = {}
_MEMORY_LOCK = threading.Lock()


def _key(email: str) -> str:
    # Redis key namespace — keep distinct from rate-limit keys.
    return f"otp:{email}"


def _cleanup_memory(now: float) -> None:
    """Drop expired entries from the in-memory fallback opportunistically."""
    if not _MEMORY:
        return
    stale = [k for k, v in _MEMORY.items() if v.get("expires_at", 0.0) <= now]
    for k in stale:
        _MEMORY.pop(k, None)


def set_otp(email: str, otp: str, ttl_seconds: int) -> None:
    """Store an OTP for ``email`` with a hard expiry of ``ttl_seconds``."""
    client = _redis_client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.hset(_key(email), mapping={"otp": otp, "attempts": 0})
            pipe.expire(_key(email), ttl_seconds)
            pipe.execute()
            return
        except Exception as exc:
            logger.warning("Redis set_otp failed for %s: %s; using memory store", email, exc)

    now = time.time()
    with _MEMORY_LOCK:
        _cleanup_memory(now)
        _MEMORY[_key(email)] = {
            "otp": otp,
            "attempts": 0,
            "expires_at": now + ttl_seconds,
        }


def get_otp(email: str) -> dict[str, Any] | None:
    """Return ``{"otp": str, "attempts": int}`` if still valid, else None."""
    client = _redis_client()
    if client is not None:
        try:
            data = client.hgetall(_key(email))
            if not data:
                return None
            return {
                "otp": data.get("otp", ""),
                "attempts": int(data.get("attempts", 0) or 0),
            }
        except Exception as exc:
            logger.warning("Redis get_otp failed for %s: %s; using memory store", email, exc)

    now = time.time()
    with _MEMORY_LOCK:
        entry = _MEMORY.get(_key(email))
        if not entry:
            return None
        if entry.get("expires_at", 0.0) <= now:
            _MEMORY.pop(_key(email), None)
            return None
        return {"otp": entry["otp"], "attempts": int(entry["attempts"])}


def increment_attempts(email: str) -> int:
    """Atomically bump the failed-attempt counter, returning the new value."""
    client = _redis_client()
    if client is not None:
        try:
            return int(client.hincrby(_key(email), "attempts", 1))
        except Exception as exc:
            logger.warning("Redis increment_attempts failed for %s: %s", email, exc)

    with _MEMORY_LOCK:
        entry = _MEMORY.get(_key(email))
        if not entry:
            return 0
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        return entry["attempts"]


def delete_otp(email: str) -> None:
    """Forget the OTP — call after success or fatal failure."""
    client = _redis_client()
    if client is not None:
        try:
            client.delete(_key(email))
            return
        except Exception as exc:
            logger.warning("Redis delete_otp failed for %s: %s", email, exc)

    with _MEMORY_LOCK:
        _MEMORY.pop(_key(email), None)
