"""
Server-side proxy for Pollinations AI image generation.

Why a proxy:
- Pollinations secret keys (sk_...) must NEVER be exposed in the browser.
- The free anonymous endpoint blocks browser fetch() with CORS 403, but
  server-to-server calls are unrestricted.
- Centralizing this lets us swap providers later without touching the UI.

Env vars (project root .env):
- POLLINATIONS_API_KEY  : sk_... (preferred) or pk_... key
- POLLINATIONS_BASE_URL : optional override, default https://gen.pollinations.ai/image
"""
from __future__ import annotations

import os
from typing import Any, Literal
from urllib.parse import quote

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.auth_routes import get_current_user
from app.rate_limits import RateLimit

router = APIRouter(prefix="/images", tags=["images"])

DEFAULT_GATEWAY = "https://gen.pollinations.ai/image"
FREE_FALLBACK = "https://image.pollinations.ai/prompt"

ALLOWED_MODELS = {
    "flux", "zimage", "klein",
}


class GenerateBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = Field(default="flux")
    width: int = Field(default=1024, ge=64, le=2048)
    height: int = Field(default=1024, ge=64, le=2048)
    seed: int = Field(default=42, ge=0, le=10_000_000)

    def __init__(self, **data):
        super().__init__(**data)
        if self.model not in ALLOWED_MODELS:
            raise ValueError(f"Model '{self.model}' not allowed. Allowed: {', '.join(sorted(ALLOWED_MODELS))}")


def _key() -> str:
    return os.getenv("POLLINATIONS_API_KEY", "").strip()


@router.get("/status")
def status() -> dict[str, Any]:
    """Get Pollinations configuration and available models (public)."""
    k = _key()
    return {
        "configured": bool(k),
        "key_kind": (
            "secret" if k.startswith("sk_")
            else "publishable" if k.startswith("pk_")
            else "unknown" if k else "none"
        ),
        "available_models": sorted(ALLOWED_MODELS),
        "note": "Models may require a higher tier API key. Use /images/test-model/{model} to check availability."
    }


@router.post("/generate", dependencies=[Depends(RateLimit("images.generate", per_minute=10, per_day=80))])
def generate(
    body: GenerateBody,
    _user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    """Stream a generated PNG/JPEG back to the client."""
    key = _key()
    base = os.getenv("POLLINATIONS_BASE_URL", DEFAULT_GATEWAY).rstrip("/")

    params = {
        "width": body.width,
        "height": body.height,
        "model": body.model,
        "seed": body.seed,
    }
    if key:
        params["key"] = key
        params["nologo"] = "true"
        url = f"{base}/{quote(body.prompt, safe='')}"
    else:
        # No key configured — fall back to the public endpoint.
        url = f"{FREE_FALLBACK}/{quote(body.prompt, safe='')}"

    try:
        r = requests.get(url, params=params, timeout=120, stream=False)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Pollinations request failed: {e}")

    if not r.ok:
        # Surface upstream error text without leaking the key.
        msg = r.text[:500] if r.text else r.reason
        
        # Categorize common errors
        if r.status_code == 403:
            detail = f"Model '{body.model}' may require a higher tier API key or is temporarily unavailable. (Pollinations 403)"
        elif r.status_code == 429:
            detail = "Rate limit exceeded. Please wait a moment before trying again. (Pollinations 429)"
        elif r.status_code == 400:
            detail = f"Invalid request for model '{body.model}'. The model may not exist or parameters are unsupported. (Pollinations 400: {msg})"
        elif r.status_code == 401:
            detail = "API key authentication failed. Please check your POLLINATIONS_API_KEY. (Pollinations 401)"
        else:
            detail = f"Pollinations error {r.status_code}: {msg}"
        
        raise HTTPException(status_code=r.status_code if r.status_code in (400, 401, 403, 404, 429) else 502,
                            detail=detail)

    content_type = r.headers.get("Content-Type", "image/jpeg")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=502, detail=f"Unexpected upstream content-type: {content_type}")

    return Response(
        content=r.content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Pollinations-Model": body.model,
            "X-Pollinations-Seed": str(body.seed),
        },
    )


@router.get("/test-model/{model}", dependencies=[Depends(RateLimit("images.test", per_minute=5))])
def test_model(model: str, _user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Quick test if a model is available - uses a tiny image to save credits/time."""
    if model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail=f"Model '{model}' not in allowed list.")
    
    key = _key()
    base = os.getenv("POLLINATIONS_BASE_URL", DEFAULT_GATEWAY).rstrip("/")
    
    # Use tiny dimensions for a quick test
    params = {"width": 64, "height": 64, "model": model, "seed": 1}
    if key:
        params["key"] = key
        params["nologo"] = "true"
        url = f"{base}/test"
    else:
        url = f"{FREE_FALLBACK}/test"
    
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.ok and r.headers.get("Content-Type", "").startswith("image/"):
            return {"model": model, "status": "available", "http_status": r.status_code}
        else:
            return {"model": model, "status": "unavailable", "http_status": r.status_code, "detail": r.text[:200]}
    except requests.RequestException as e:
        return {"model": model, "status": "error", "detail": str(e)}


# ── Cloud-Sync Image History ───────────────────────────────────────

from pathlib import Path
import json
import time

LOCAL_HISTORY_FILE = Path("data/image_history.json")

def _load_local_history() -> dict[str, list[dict]]:
    if not LOCAL_HISTORY_FILE.exists():
        return {}
    try:
        with open(LOCAL_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_local_history(data: dict[str, list[dict]]) -> None:
    LOCAL_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class SaveImageBody(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = Field(...)
    width: int = Field(...)
    height: int = Field(...)
    seed: int = Field(...)


@router.get("/history")
async def get_image_history(user: dict[str, Any] = Depends(get_current_user)) -> list[dict]:
    user_id = user["user_id"]
    if os.getenv("SUPABASE_DB_URL"):
        try:
            from app.db_postgres import pg_get_user_images
            return await pg_get_user_images(user_id)
        except Exception:
            pass
            
    # Local JSON fallback
    history = _load_local_history()
    return history.get(user_id, [])


@router.post("/history")
async def save_image_history(
    body: SaveImageBody,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    user_id = user["user_id"]
    if os.getenv("SUPABASE_DB_URL"):
        try:
            from app.db_postgres import pg_save_user_image
            return await pg_save_user_image(
                user_id=user_id,
                prompt=body.prompt,
                model=body.model,
                width=body.width,
                height=body.height,
                seed=body.seed,
            )
        except Exception:
            pass
            
    # Local JSON fallback
    history = _load_local_history()
    user_list = history.get(user_id, [])
    new_img = {
        "id": int(time.time() * 1000),
        "prompt": body.prompt,
        "model": body.model,
        "width": body.width,
        "height": body.height,
        "seed": body.seed,
        "created_at": time.time(),
    }
    user_list.insert(0, new_img)
    history[user_id] = user_list
    _save_local_history(history)
    return new_img


@router.delete("/history/{image_id}")
async def delete_image_history(
    image_id: int,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    user_id = user["user_id"]
    if os.getenv("SUPABASE_DB_URL"):
        try:
            from app.db_postgres import pg_delete_user_image
            success = await pg_delete_user_image(user_id, image_id)
            return {"status": "success", "deleted": success}
        except Exception:
            pass
            
    # Local JSON fallback
    history = _load_local_history()
    user_list = history.get(user_id, [])
    next_list = [img for img in user_list if img.get("id") != image_id]
    history[user_id] = next_list
    _save_local_history(history)
    return {"status": "success", "deleted": len(user_list) != len(next_list)}


@router.delete("/history")
async def clear_image_history(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    user_id = user["user_id"]
    if os.getenv("SUPABASE_DB_URL"):
        try:
            from app.db_postgres import pg_delete_all_user_images
            await pg_delete_all_user_images(user_id)
            return {"status": "success"}
        except Exception:
            pass
            
    # Local JSON fallback
    history = _load_local_history()
    if user_id in history:
        history[user_id] = []
        _save_local_history(history)
    return {"status": "success"}
