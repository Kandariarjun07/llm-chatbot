import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_routes import get_current_user
from app.db import (
    delete_conversation,
    get_conversations,
    upsert_conversation,
    clear_conversations,
)

router = APIRouter(prefix="/chat", tags=["chat"])

# In-memory cache for conversation lists (per-user, 3s TTL)
_history_cache: dict[str, tuple[list[dict], float]] = {}
_HISTORY_CACHE_TTL = 3.0


class ChatMessageItem(BaseModel):
    id: str
    role: str
    content: str
    createdAt: float


class ConversationItem(BaseModel):
    id: str
    title: str
    createdAt: float
    updatedAt: float
    messages: list[ChatMessageItem]


class UpsertBody(BaseModel):
    id: str = Field(..., min_length=1)
    title: str = Field(default="New conversation")
    createdAt: float
    updatedAt: float
    messages: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/history", response_model=list[ConversationItem])
async def list_history(user: dict[str, Any] = Depends(get_current_user)) -> list[dict]:
    uid = user["user_id"]
    now = time.time()
    cached = _history_cache.get(uid)
    if cached and now - cached[1] < _HISTORY_CACHE_TTL:
        return cached[0]
    rows = await get_conversations(uid)
    _history_cache[uid] = (rows, now)
    return rows


@router.post("/history")
async def save_history(body: UpsertBody, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    await upsert_conversation(
        user["user_id"],
        {
            "id": body.id,
            "title": body.title,
            "createdAt": body.createdAt,
            "updatedAt": body.updatedAt,
            "messages": body.messages,
        },
    )
    _history_cache.pop(user["user_id"], None)
    return {"status": "saved"}


@router.delete("/history/{conv_id}")
async def delete_history(conv_id: str, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    if await delete_conversation(user["user_id"], conv_id):
        _history_cache.pop(user["user_id"], None)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Conversation not found")


@router.delete("/history")
async def clear_history(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    await clear_conversations(user["user_id"])
    _history_cache.pop(user["user_id"], None)
    return {"status": "cleared"}
