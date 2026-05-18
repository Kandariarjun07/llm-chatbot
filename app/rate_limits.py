"""Unified rate-limiting primitives for the app.

The public surface is:

    check_rate_limit(key, limit, window_s) -> RateLimitResult
        Generic sliding-window check. Returns (allowed, remaining,
        retry_after). Increments a counter keyed by ``key`` that expires
        after ``window_s`` seconds. Redis-backed when configured, with a
        process-local fallback for local dev / single-worker deploys.

    RateLimit(scope, per_minute=..., per_day=..., per_ip=False)
        A FastAPI dependency factory. Use it like:

            @router.post("/things", dependencies=[Depends(
                RateLimit("things.create", per_minute=30, per_day=500)
            )])
            def create(...): ...

        The dependency resolves the authenticated user (or IP when
        per_ip=True) and raises HTTP 429 when either window is exhausted.

Legacy helpers (``check_deep_research_limit``, ``consume_deep_research_use``)
remain for the deep-research weekly quota.

The in-memory fallback is *per process*. Production deployments with
multiple workers MUST set ``REDIS_HOST`` to get accurate counting across
replicas. The code silently falls back rather than failing open, so a
single-worker dev box still enforces limits.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status

from app.config import get_settings

logger = logging.getLogger(__name__)


# ── Redis / memory backend ────────────────────────────────────────

def _redis_client() -> Any | None:
    """Return a cached Redis client if configured, else ``None``.

    The client is cached on first success so we don't rebuild it per
    request. Connection failures degrade to the in-memory fallback.
    """
    settings = get_settings()
    if not settings.redis_host:
        return None
    if getattr(_redis_client, "_cached", None) is not None:
        return _redis_client._cached  # type: ignore[attr-defined]
    try:
        import redis  # type: ignore
        client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            decode_responses=True,
            socket_timeout=1.5,
            socket_connect_timeout=1.5,
        )
        # Fail fast if misconfigured.
        client.ping()
        _redis_client._cached = client  # type: ignore[attr-defined]
        return client
    except Exception as e:
        logger.warning("Redis unavailable for rate limiting: %s", e)
        _redis_client._cached = None  # type: ignore[attr-defined]
        return None


# Process-local fallback. Each entry is {"count": int, "expires_at": float}.
_MEMORY: dict[str, dict[str, Any]] = {}
_MEMORY_LOCK = threading.Lock()


def _memory_incr(key: str, window_s: int) -> tuple[int, float]:
    """Increment a process-local counter with a fresh TTL.

    Returns (current_count, expires_at_epoch). If the entry already
    exists and hasn't expired, the existing expires_at is preserved so
    counters behave as a fixed-window across requests.
    """
    now = time.time()
    with _MEMORY_LOCK:
        entry = _MEMORY.get(key)
        if not entry or entry["expires_at"] <= now:
            entry = {"count": 1, "expires_at": now + window_s}
        else:
            entry["count"] += 1
        _MEMORY[key] = entry

        # Opportunistic GC so the dict doesn't grow forever in long-lived
        # processes. Only runs ~1% of the time and only scans up to 256
        # stale keys per pass.
        if len(_MEMORY) > 1024 and (int(now) % 100 == 0):
            stale = [k for k, v in list(_MEMORY.items())[:256] if v["expires_at"] <= now]
            for k in stale:
                _MEMORY.pop(k, None)

        return entry["count"], entry["expires_at"]


# ── Public API ────────────────────────────────────────────────────

@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int  # seconds


def check_rate_limit(key: str, limit: int, window_s: int) -> RateLimitResult:
    """Increment ``key`` and return whether it stays under ``limit``.

    Uses a **fixed window**: the first request in a new window sets the
    TTL; subsequent requests within ``window_s`` seconds share the same
    counter. This is the simplest, cheapest option for our scale and
    plays nicely with both Redis ``INCR+EXPIRE`` and the in-memory fallback.
    """
    if limit <= 0:
        return RateLimitResult(allowed=False, remaining=0, retry_after=window_s)

    client = _redis_client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            count = int(count)
            if ttl is None or ttl < 0:
                client.expire(key, window_s)
                ttl = window_s
            remaining = max(0, limit - count)
            retry_after = int(ttl) if count > limit else 0
            return RateLimitResult(
                allowed=count <= limit,
                remaining=remaining,
                retry_after=retry_after,
            )
        except Exception as e:
            logger.warning("Redis rate-limit check failed (%s); falling back", e)

    count, expires_at = _memory_incr(key, window_s)
    remaining = max(0, limit - count)
    retry_after = max(0, int(expires_at - time.time())) if count > limit else 0
    return RateLimitResult(
        allowed=count <= limit,
        remaining=remaining,
        retry_after=retry_after,
    )


def _user_id_from_request(request: Request) -> str | None:
    """Pull the authenticated user id off ``request.state`` if present.

    We populate ``request.state.user`` in a middleware / dependency
    chain (see ``api.auth_routes.get_current_user``). Falls back to
    ``None`` when the endpoint is not yet authenticated.
    """
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        return user.get("user_id")
    return None


def _client_ip(request: Request) -> str:
    """Best-effort client IP, respecting X-Forwarded-For for hosted deploys."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # First hop is the actual client; the rest are intermediate proxies.
        return fwd.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def RateLimit(  # noqa: N802  — named to read as a class at call sites
    scope: str,
    *,
    per_minute: int | None = None,
    per_day: int | None = None,
    per_ip: bool = False,
) -> Callable[..., None]:
    """Return a FastAPI dependency that enforces rate limits for ``scope``.

    Args:
        scope: Unique identifier used in the storage key. Keep stable —
            changing it resets all counters.
        per_minute: Requests allowed per 60-second window. ``None`` skips.
        per_day: Requests allowed per rolling 24h window. ``None`` skips.
        per_ip: When True, key off client IP instead of user_id. Used for
            pre-auth endpoints (signin/signup/OTP).

    On breach, raises HTTP 429 with a descriptive detail and a
    ``Retry-After`` header so clients can back off intelligently.
    """
    if per_minute is None and per_day is None:
        raise ValueError("RateLimit requires at least one of per_minute / per_day")

    def _dep(request: Request) -> None:
        import time as _t
        t0 = _t.perf_counter()
        if per_ip:
            identity = f"ip:{_client_ip(request)}"
        else:
            uid = _user_id_from_request(request)
            if not uid:
                identity = f"ip:{_client_ip(request)}"
            else:
                identity = f"user:{uid}"

        if per_minute is not None:
            key = f"rl:{scope}:1m:{identity}"
            result = check_rate_limit(key, per_minute, 60)
            if not result.allowed:
                _raise_429(scope, "minute", per_minute, result.retry_after)
        if per_day is not None:
            key = f"rl:{scope}:1d:{identity}"
            result = check_rate_limit(key, per_day, 86_400)
            if not result.allowed:
                _raise_429(scope, "day", per_day, result.retry_after)
        dt = (_t.perf_counter() - t0) * 1000
        print(f"[rl] {scope}  {dt:.0f}ms", flush=True)

    return _dep


def _raise_429(scope: str, window_label: str, limit: int, retry_after: int) -> None:
    """Raise a 429 with a friendly body + ``Retry-After`` header."""
    detail = (
        f"Rate limit reached for {scope} ({limit} per {window_label}). "
        f"Try again in {max(retry_after, 1)}s."
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(max(retry_after, 1))},
    )


# ── Legacy: deep-research weekly quota ───────────────────────────

def _week_key() -> str:
    import datetime
    today = datetime.date.today()
    iso = today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


_DEEP_RESEARCH_MAX = 5


def check_deep_research_limit(user_id: str) -> tuple[bool, int]:
    """Return ``(allowed, remaining_uses)`` for the current calendar week."""
    week = _week_key()
    key = f"deep_research:{week}:{user_id}"
    client = _redis_client()
    if client is not None:
        try:
            current = client.get(key)
            used = int(current) if current else 0
            remaining = max(0, _DEEP_RESEARCH_MAX - used)
            return remaining > 0, remaining
        except Exception:
            pass
    entry = _MEMORY.get(key, {"count": 0, "expires_at": 0.0})
    remaining = max(0, _DEEP_RESEARCH_MAX - int(entry["count"]))
    return remaining > 0, remaining


def consume_deep_research_use(user_id: str) -> int:
    """Increment the user's weekly usage, return remaining."""
    week = _week_key()
    key = f"deep_research:{week}:{user_id}"
    client = _redis_client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, 7 * 24 * 3600)
            results = pipe.execute()
            used = int(results[0])
            return max(0, _DEEP_RESEARCH_MAX - used)
        except Exception:
            pass
    with _MEMORY_LOCK:
        entry = _MEMORY.get(key, {"count": 0, "expires_at": time.time() + 7 * 86_400})
        entry["count"] += 1
        _MEMORY[key] = entry
    return max(0, _DEEP_RESEARCH_MAX - int(entry["count"]))
