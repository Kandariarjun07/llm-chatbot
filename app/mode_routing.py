"""Product-mode → internal model routing.

Users pick a *product experience* (Fast / Think), not a model. This module
translates that intent into the existing `model_choice` token consumed by
`llm/client.py` and the orchestrator, keeping internal pipelines unchanged.

- "Fast" maps to a cheap, low-latency streaming model (Groq Llama).
- "Think" maps to a stronger reasoning model (Gemini).
- Web Search and Deep Research are orthogonal flags that layer on top of the
  selected mode — they don't appear in this map.
- Centralizing this lets us retarget providers later without touching every
  call site.
"""

from __future__ import annotations

from typing import Literal


Mode = Literal["Fast", "Think"]


_MODE_TO_MODEL: dict[str, str] = {
    "Fast": "Llama",
    "Think": "Think",  # routes to DeepSeek-R1 via llm/client.py
}


def mode_to_model_choice(mode: str | None, fallback: str = "Llama") -> str:
    """Translate a product mode to the internal `model_choice` token.

    Returns ``fallback`` when ``mode`` is None / unknown so legacy callers
    that still pass `model_choice` directly keep working unchanged.
    """
    if not mode:
        return fallback
    return _MODE_TO_MODEL.get(mode, fallback)


def available_modes() -> list[str]:
    return list(_MODE_TO_MODEL.keys())
