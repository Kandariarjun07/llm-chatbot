"""PostgreSQL database layer for Supabase.

Uses SQLAlchemy 2.0 async ORM with asyncpg.  The table schemas mirror the
original SQLite tables so that ``app/db.py`` can delegate here when
``SUPABASE_DB_URL`` is configured.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    JSON,
    Boolean,
    select,
    insert,
    update,
    delete,
    func,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base

from app.config import get_settings

# ── Schema ───────────────────────────────────────────────────────
Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    title = Column(Text, nullable=False, default="New conversation")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    messages = Column(JSON, nullable=False, default=list)


class Diagram(Base):
    __tablename__ = "diagrams"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    title = Column(Text, nullable=False, default="Untitled Diagram")
    diagram_type = Column(String, nullable=False, default="flowchart")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    nodes = Column(JSON, nullable=False, default=list)
    edges = Column(JSON, nullable=False, default=list)
    mermaid_code = Column(Text, nullable=False, default="")
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)


class UserVerification(Base):
    __tablename__ = "user_verifications"

    user_id = Column(String, primary_key=True)
    otp_verified = Column(Boolean, nullable=False, default=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(String, primary_key=True)
    instructions = Column(Text, nullable=False, default="")


class AiCreditsSpend(Base):
    __tablename__ = "aicredits_spend"

    id = Column(Integer, primary_key=True)
    total_inr = Column(Numeric(12, 6), nullable=False, default=0.0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    calls = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ── Engine & Session ──────────────────────────────────────────────
_engine: Any = None
_SessionLocal: Any = None


def _get_db_url() -> str | None:
    """Return the async PostgreSQL URL if configured, else None."""
    settings = get_settings()
    url = settings.supabase_db_url
    if not url:
        return None
    # Ensure the asyncpg driver is specified.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif not url.startswith("postgresql+asyncpg://"):
        url = url.replace("://", "+asyncpg://", 1)
    return url


def _init_engine() -> Any:
    """Lazy-initialise the async engine."""
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    db_url = _get_db_url()
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL is not configured")
    _engine = create_async_engine(
        db_url,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        echo=os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true",
    )
    _SessionLocal = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return _engine


async def async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for dependency injection / context use."""
    _init_engine()
    async with _SessionLocal() as session:
        yield session


async def init_postgres_tables() -> None:
    """Create all tables in the connected PostgreSQL database."""
    engine = _init_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Conversation helpers ──────────────────────────────────────────

async def pg_get_conversations(user_id: str) -> list[dict]:
    async for session in async_session():
        result = await session.execute(
            select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "createdAt": r.created_at.timestamp() if r.created_at else 0,
                "updatedAt": r.updated_at.timestamp() if r.updated_at else 0,
                "messages": r.messages if r.messages is not None else [],
            }
            for r in rows
        ]
    return []


async def pg_upsert_conversation(user_id: str, conv: dict) -> None:
    conv_id = conv["id"]
    title = conv.get("title", "New conversation")
    created = conv.get("createdAt", conv.get("created_at"))
    updated = conv.get("updatedAt", conv.get("updated_at"))
    messages = conv.get("messages", [])

    # Convert timestamps
    created_dt = _to_datetime(created)
    updated_dt = _to_datetime(updated)

    async for session in async_session():
        # Upsert via ON CONFLICT (SQLite-compatible syntax also works in PG)
        stmt = (
            insert(Conversation)
            .values(
                id=conv_id,
                user_id=user_id,
                title=title,
                created_at=created_dt,
                updated_at=updated_dt,
                messages=messages,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "title": title,
                    "updated_at": updated_dt,
                    "messages": messages,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


async def pg_delete_conversation(user_id: str, conv_id: str) -> bool:
    async for session in async_session():
        result = await session.execute(
            delete(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == user_id
            )
        )
        await session.commit()
        return result.rowcount > 0
    return False


async def pg_clear_conversations(user_id: str) -> None:
    async for session in async_session():
        await session.execute(delete(Conversation).where(Conversation.user_id == user_id))
        await session.commit()


# ── Verification helpers ──────────────────────────────────────────

async def pg_is_user_verified(user_id: str) -> bool:
    async for session in async_session():
        result = await session.execute(
            select(UserVerification.otp_verified).where(UserVerification.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        return bool(row) if row is not None else False
    return False


async def pg_mark_user_verified(user_id: str) -> None:
    async for session in async_session():
        stmt = (
            insert(UserVerification)
            .values(user_id=user_id, otp_verified=True)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={"otp_verified": True},
            )
        )
        await session.execute(stmt)
        await session.commit()


# ── Diagram helpers ─────────────────────────────────────────────

async def pg_get_diagrams(user_id: str) -> list[dict]:
    async for session in async_session():
        result = await session.execute(
            select(Diagram).where(Diagram.user_id == user_id).order_by(Diagram.updated_at.desc())
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "diagramType": r.diagram_type,
                "createdAt": r.created_at.timestamp() if r.created_at else 0,
                "updatedAt": r.updated_at.timestamp() if r.updated_at else 0,
                "nodes": r.nodes if r.nodes is not None else [],
                "edges": r.edges if r.edges is not None else [],
                "mermaidCode": r.mermaid_code,
                "metadata": r.metadata_ if r.metadata_ is not None else {},
            }
            for r in rows
        ]
    return []


async def pg_get_diagram(user_id: str, diag_id: str) -> dict | None:
    async for session in async_session():
        result = await session.execute(
            select(Diagram).where(Diagram.id == diag_id, Diagram.user_id == user_id)
        )
        r = result.scalar_one_or_none()
        if not r:
            return None
        return {
            "id": r.id,
            "title": r.title,
            "diagramType": r.diagram_type,
            "createdAt": r.created_at.timestamp() if r.created_at else 0,
            "updatedAt": r.updated_at.timestamp() if r.updated_at else 0,
            "nodes": r.nodes if r.nodes is not None else [],
            "edges": r.edges if r.edges is not None else [],
            "mermaidCode": r.mermaid_code,
            "metadata": r.metadata_ if r.metadata_ is not None else {},
        }
    return None


async def pg_upsert_diagram(user_id: str, diag: dict) -> None:
    diag_id = diag["id"]
    title = diag.get("title", "Untitled Diagram")
    diagram_type = diag.get("diagramType", diag.get("diagram_type", "flowchart"))
    created = diag.get("createdAt", diag.get("created_at"))
    updated = diag.get("updatedAt", diag.get("updated_at"))
    nodes = diag.get("nodes", [])
    edges = diag.get("edges", [])
    mermaid_code = diag.get("mermaidCode", diag.get("mermaid_code", ""))
    metadata = diag.get("metadata", {})

    async for session in async_session():
        stmt = (
            insert(Diagram)
            .values(
                id=diag_id,
                user_id=user_id,
                title=title,
                diagram_type=diagram_type,
                created_at=_to_datetime(created),
                updated_at=_to_datetime(updated),
                nodes=nodes,
                edges=edges,
                mermaid_code=mermaid_code,
                metadata=metadata,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "title": title,
                    "diagram_type": diagram_type,
                    "updated_at": _to_datetime(updated),
                    "nodes": nodes,
                    "edges": edges,
                    "mermaid_code": mermaid_code,
                    "metadata": metadata,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


async def pg_delete_diagram(user_id: str, diag_id: str) -> bool:
    async for session in async_session():
        result = await session.execute(
            delete(Diagram).where(Diagram.id == diag_id, Diagram.user_id == user_id)
        )
        await session.commit()
        return result.rowcount > 0
    return False


# ── Preferences helpers ───────────────────────────────────────────

async def pg_get_custom_instructions(user_id: str) -> str:
    async for session in async_session():
        result = await session.execute(
            select(UserPreference.instructions).where(UserPreference.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        return row or ""
    return ""


async def pg_set_custom_instructions(user_id: str, instructions: str) -> None:
    # Enforce 150-word limit
    words = instructions.split()
    if len(words) > 150:
        instructions = " ".join(words[:150])

    async for session in async_session():
        stmt = (
            insert(UserPreference)
            .values(user_id=user_id, instructions=instructions)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={"instructions": instructions},
            )
        )
        await session.execute(stmt)
        await session.commit()


# ── AI Credits helpers ────────────────────────────────────────────

async def pg_get_spend() -> dict[str, Any]:
    async for session in async_session():
        result = await session.execute(select(AiCreditsSpend).where(AiCreditsSpend.id == 1))
        row = result.scalar_one_or_none()
        if row:
            return {
                "total_inr": float(row.total_inr),
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "calls": row.calls,
            }
        # Seed row if missing
        session.add(AiCreditsSpend(id=1))
        await session.commit()
        return {"total_inr": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    return {"total_inr": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}


async def pg_record_usage(prompt_tokens: int, completion_tokens: int, inr: float) -> dict[str, Any]:
    async for session in async_session():
        # Atomic update using RETURNING
        stmt = (
            update(AiCreditsSpend)
            .where(AiCreditsSpend.id == 1)
            .values(
                total_inr=AiCreditsSpend.total_inr + inr,
                prompt_tokens=AiCreditsSpend.prompt_tokens + prompt_tokens,
                completion_tokens=AiCreditsSpend.completion_tokens + completion_tokens,
                calls=AiCreditsSpend.calls + 1,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(AiCreditsSpend)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        await session.commit()
        if row:
            return {
                "total_inr": float(row.total_inr),
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "calls": row.calls,
            }
    return await pg_get_spend()


async def pg_reset_spend() -> None:
    async for session in async_session():
        await session.execute(
            update(AiCreditsSpend)
            .where(AiCreditsSpend.id == 1)
            .values(
                total_inr=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                calls=0,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


# ── Utils ─────────────────────────────────────────────────────────

def _to_datetime(value: Any) -> datetime:
    """Normalise a timestamp (float, int, or datetime) to UTC datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    # Fallback to now if unparseable
    return datetime.now(timezone.utc)
