"""User preferences manager (Custom Instructions)"""

import json
import os
from typing import Any, Dict
from pathlib import Path

from app.config import get_settings

PREFERENCES_FILE = Path("data/user_preferences.json")

def _redis_client() -> Any | None:
    """Return a Redis client if configured, else None."""
    settings = get_settings()
    if not settings.redis_host:
        return None
    try:
        import redis
        return redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            decode_responses=True,
        )
    except Exception:
        return None

def _load_local() -> Dict[str, str]:
    if not PREFERENCES_FILE.exists():
        return {}
    try:
        with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_local(data: Dict[str, str]) -> None:
    PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_custom_instructions(user_id: str) -> str:
    """Get the user's custom instructions (up to 150 words)."""
    redis_client = _redis_client()
    if redis_client:
        try:
            return redis_client.get(f"custom_instructions:{user_id}") or ""
        except Exception:
            pass
            
    # Fallback to local
    data = _load_local()
    return data.get(user_id, "")

def set_custom_instructions(user_id: str, instructions: str) -> None:
    """Set the user's custom instructions."""
    # Enforce word limit (150 words)
    words = instructions.split()
    if len(words) > 150:
        instructions = " ".join(words[:150])
        
    redis_client = _redis_client()
    if redis_client:
        try:
            redis_client.set(f"custom_instructions:{user_id}", instructions)
        except Exception:
            pass
            
    # Always save to local fallback as persistent backup
    data = _load_local()
    data[user_id] = instructions
    _save_local(data)
