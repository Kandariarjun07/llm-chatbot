"""User preferences manager (Custom Instructions, About Me, Tone/Mode, Emojis)"""

import asyncio
import json
import os
from typing import Any, Dict
from pathlib import Path

from app.config import get_settings

PREFERENCES_FILE = Path("data/user_preferences.json")
_USE_PG = bool(os.environ.get("SUPABASE_DB_URL"))

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

def _load_local() -> Dict[str, Any]:
    if not PREFERENCES_FILE.exists():
        return {}
    try:
        with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_local(data: Dict[str, Any]) -> None:
    PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

async def get_user_preferences(user_id: str) -> dict:
    """Get all preferences for a user, trying PG first, then Redis, then local JSON."""
    if _USE_PG:
        try:
            from app.db_postgres import pg_get_user_preferences
            return await pg_get_user_preferences(user_id)
        except Exception:
            pass

    redis_client = _redis_client()
    if redis_client:
        try:
            # redis client is sync, so run in thread to keep loop free
            stored = await asyncio.to_thread(redis_client.get, f"user_preferences:{user_id}")
            if stored:
                return json.loads(stored)
        except Exception:
            pass

    # Fallback to local JSON
    data = _load_local()
    stored = data.get(user_id, "")
    if isinstance(stored, dict):
        return {
            "instructions": stored.get("instructions", ""),
            "about_me": stored.get("about_me", ""),
            "response_mode": stored.get("response_mode", "friendly"),
            "emoji_frequency": stored.get("emoji_frequency", "moderately"),
        }
    elif isinstance(stored, str):
        # Legacy format
        return {
            "instructions": stored,
            "about_me": "",
            "response_mode": "friendly",
            "emoji_frequency": "moderately",
        }
        
    return {
        "instructions": "",
        "about_me": "",
        "response_mode": "friendly",
        "emoji_frequency": "moderately",
    }

async def set_user_preferences(user_id: str, prefs: dict) -> None:
    """Set all preferences for a user, saving to PG, Redis, and local JSON."""
    # Ensure standard schema
    clean_prefs = {
        "instructions": prefs.get("instructions", ""),
        "about_me": prefs.get("about_me", ""),
        "response_mode": prefs.get("response_mode", "friendly"),
        "emoji_frequency": prefs.get("emoji_frequency", "moderately"),
    }

    if _USE_PG:
        try:
            from app.db_postgres import pg_set_user_preferences
            await pg_set_user_preferences(user_id, clean_prefs)
        except Exception:
            pass

    redis_client = _redis_client()
    if redis_client:
        try:
            await asyncio.to_thread(redis_client.set, f"user_preferences:{user_id}", json.dumps(clean_prefs))
        except Exception:
            pass

    # Always save to local fallback as persistent backup
    data = _load_local()
    data[user_id] = clean_prefs
    _save_local(data)

async def get_custom_instructions(user_id: str) -> str:
    """Get combined custom instructions/personalization prompt for the LLM."""
    prefs = await get_user_preferences(user_id)
    parts = []
    
    if prefs.get("about_me"):
        about_prompt = (
            f"ABOUT THE USER (PASSIVE BACKGROUND CONTEXT):\n"
            f"\"{prefs['about_me'].strip()}\"\n\n"
            f"CRITICAL SYSTEM CONSTRAINTS FOR PERSONALIZATION:\n"
            f"1. SILENT INFLUENCE: Use this information as a silent background lens to shape the technical depth, sophistication, and style of your answers depending on the query (e.g., if the user is a Computer Science student, naturally lean towards clean programming concepts, direct technical analogies, and robust code structures in your technical explanations rather than generic or overly simplified responses).\n"
            f"2. ZERO PROACTIVE GREETING CALLOUTS: Do NOT proactively mention, reference, congratulate, welcome, or bring up any of this background information in standard or initial greetings (e.g., if the user says 'Hi' or greets you, respond with a natural, simple 'Hi! How can I help you today?').\n"
            f"3. STRICT RESTRAINT ON USER INTERESTS: If the user lists personal interests (e.g., gym, anime, fitness), do NOT constantly preach, suggest, or repeatedly mention these interests in your answers. Exercise extreme restraint. Only refer to or weave these interests in very occasionally as subtle, clever analogies or lighthearted references when highly relevant and natural. The majority of your responses should remain focused on the user's core query without force-fitting their personal interests.\n"
            f"4. BE NATURAL: Avoid prefixing sentences with things like 'Since you study CSE' or 'As a gym lover'. Deliver personalized value silently and naturally."
        )
        parts.append(about_prompt)
        
    if prefs.get("instructions"):
        parts.append(f"CUSTOM INSTRUCTIONS ON HOW TO RESPOND:\n{prefs['instructions']}".strip())
        
    # Mode/Tone instructions
    mode = prefs.get("response_mode", "friendly")
    if mode == "formal":
        parts.append("RESPONSE STYLE / TONE: You must reply in a very formal, academic, structured, highly polite, and professional tone. Keep it strictly intellectual.")
    elif mode == "friendly":
        parts.append("RESPONSE STYLE / TONE: You must reply in a friendly, warm, supportive, conversational, and highly helpful tone.")
    elif mode == "professional":
        parts.append("RESPONSE STYLE / TONE: You must reply in a crisp, professional, direct, matter-of-fact, clear, and business-like tone.")
    elif mode == "creative":
        parts.append("RESPONSE STYLE / TONE: You must reply in a creative, imaginative, expressive, and engaging style, using rich descriptions.")
    elif mode == "humorous":
        parts.append("RESPONSE STYLE / TONE: You must reply in a highly humorous, witty, playful, and amusing tone, incorporating jokes or dry humor while still answering the query.")
    elif mode == "concise":
        parts.append("RESPONSE STYLE / TONE: You must reply in an extremely concise, direct, brief, and to-the-point manner. Strictly avoid any unnecessary explanation or fluff.")
        
    # Emoji usage
    emoji = prefs.get("emoji_frequency", "moderately")
    if emoji == "never":
        parts.append("EMOJI USAGE: Do not use any emojis under any circumstances.")
    elif emoji == "rarely":
        parts.append("EMOJI USAGE: Use emojis very rarely, only once in a while when highly appropriate.")
    elif emoji == "moderately":
        parts.append("EMOJI USAGE: Use emojis moderately where they fit naturally.")
    elif emoji == "frequently":
        parts.append("EMOJI USAGE: Use emojis frequently and expressively to make the response lively.")
    elif emoji == "always":
        parts.append("EMOJI USAGE: Always use emojis in almost every sentence or paragraph to be extremely engaging and lively.")
        
    return "\n\n".join(parts)

async def set_custom_instructions(user_id: str, instructions: str) -> None:
    """Set custom instructions for compatibility, updating only that field."""
    prefs = await get_user_preferences(user_id)
    prefs["instructions"] = instructions
    await set_user_preferences(user_id, prefs)
