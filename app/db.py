"""Unified database layer.

When ``SUPABASE_DB_URL`` is configured, all calls delegate to the async
PostgreSQL backend (``app/db_postgres.py``).  Otherwise they fall back to
the original SQLite file via ``asyncio.to_thread()`` so the function
signatures stay async-compatible.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from app.config import get_settings

# ── Detect mode ──────────────────────────────────────────────────
_USE_PG = bool(get_settings().supabase_db_url)

if _USE_PG:
    from app.db_postgres import (
        pg_get_conversations,
        pg_upsert_conversation,
        pg_delete_conversation,
        pg_clear_conversations,
        pg_is_user_verified,
        pg_mark_user_verified,
        pg_get_diagrams,
        pg_get_diagram,
        pg_upsert_diagram,
        pg_delete_diagram,
        init_postgres_tables,
    )
else:
    # ── SQLite fallback ──────────────────────────────────────────
    _data_dir = os.environ.get("DATA_DIR")
    if _data_dir:
        DB_PATH = Path(_data_dir) / "chat_history.db"
        _OLD_DB_PATH = None
    else:
        DB_PATH = Path(
            os.environ.get("LOCALAPPDATA", tempfile.gettempdir())
        ) / "SNTI" / "chat_history.db"
        _OLD_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chat_history.db"

    def _maybe_migrate_db() -> None:
        if DB_PATH.exists():
            return
        if _OLD_DB_PATH and _OLD_DB_PATH.exists():
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(_OLD_DB_PATH), str(DB_PATH))

    def _init_db() -> sqlite3.Connection:
        _maybe_migrate_db()
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                messages TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_verifications (
                user_id TEXT PRIMARY KEY,
                otp_verified INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS diagrams (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'Untitled Diagram',
                diagram_type TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                nodes TEXT NOT NULL DEFAULT '[]',
                edges TEXT NOT NULL DEFAULT '[]',
                mermaid_code TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_diagrams_user ON diagrams(user_id)"
        )
        conn.commit()
        return conn

    _conn: sqlite3.Connection | None = None

    def get_conn() -> sqlite3.Connection:
        global _conn
        if _conn is None:
            _conn = _init_db()
        return _conn

    def _sqlite_get_conversations(user_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at, messages FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
                "messages": json.loads(r["messages"]),
            }
            for r in rows
        ]

    def _sqlite_upsert_conversation(user_id: str, conv: dict) -> None:
        conn = get_conn()
        messages = json.dumps(conv.get("messages", []), ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO conversations (id, user_id, title, created_at, updated_at, messages)
            VALUES (:id, :user_id, :title, :created_at, :updated_at, :messages)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                updated_at = excluded.updated_at,
                messages = excluded.messages
            """,
            {
                "id": conv["id"],
                "user_id": user_id,
                "title": conv.get("title", "New conversation"),
                "created_at": conv.get("createdAt", conv.get("created_at")),
                "updated_at": conv.get("updatedAt", conv.get("updated_at")),
                "messages": messages,
            },
        )
        conn.commit()

    def _sqlite_delete_conversation(user_id: str, conv_id: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def _sqlite_clear_conversations(user_id: str) -> None:
        conn = get_conn()
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.commit()

    def _sqlite_is_user_verified(user_id: str) -> bool:
        conn = get_conn()
        row = conn.execute(
            "SELECT otp_verified FROM user_verifications WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row:
            return bool(row["otp_verified"])
        return False

    def _sqlite_mark_user_verified(user_id: str) -> None:
        conn = get_conn()
        conn.execute(
            """
            INSERT INTO user_verifications (user_id, otp_verified)
            VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET otp_verified = 1
            """,
            (user_id,)
        )
        conn.commit()

    def _sqlite_get_diagrams(user_id: str) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, title, diagram_type, created_at, updated_at, nodes, edges, mermaid_code, metadata FROM diagrams WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "diagramType": r["diagram_type"],
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
                "nodes": json.loads(r["nodes"]),
                "edges": json.loads(r["edges"]),
                "mermaidCode": r["mermaid_code"],
                "metadata": json.loads(r["metadata"]),
            }
            for r in rows
        ]

    def _sqlite_get_diagram(user_id: str, diag_id: str) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT id, title, diagram_type, created_at, updated_at, nodes, edges, mermaid_code, metadata FROM diagrams WHERE id = ? AND user_id = ?",
            (diag_id, user_id),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "diagramType": row["diagram_type"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "nodes": json.loads(row["nodes"]),
            "edges": json.loads(row["edges"]),
            "mermaidCode": row["mermaid_code"],
            "metadata": json.loads(row["metadata"]),
        }

    def _sqlite_upsert_diagram(user_id: str, diag: dict) -> None:
        conn = get_conn()
        nodes = json.dumps(diag.get("nodes", []), ensure_ascii=False)
        edges = json.dumps(diag.get("edges", []), ensure_ascii=False)
        metadata = json.dumps(diag.get("metadata", {}), ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO diagrams (id, user_id, title, diagram_type, created_at, updated_at, nodes, edges, mermaid_code, metadata)
            VALUES (:id, :user_id, :title, :diagram_type, :created_at, :updated_at, :nodes, :edges, :mermaid_code, :metadata)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                diagram_type = excluded.diagram_type,
                updated_at = excluded.updated_at,
                nodes = excluded.nodes,
                edges = excluded.edges,
                mermaid_code = excluded.mermaid_code,
                metadata = excluded.metadata
            """,
            {
                "id": diag["id"],
                "user_id": user_id,
                "title": diag.get("title", "Untitled Diagram"),
                "diagram_type": diag.get("diagramType", diag.get("diagram_type", "flowchart")),
                "created_at": diag.get("createdAt", diag.get("created_at")),
                "updated_at": diag.get("updatedAt", diag.get("updated_at")),
                "nodes": nodes,
                "edges": edges,
                "mermaid_code": diag.get("mermaidCode", diag.get("mermaid_code", "")),
                "metadata": metadata,
            },
        )
        conn.commit()

    def _sqlite_delete_diagram(user_id: str, diag_id: str) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM diagrams WHERE id = ? AND user_id = ?",
            (diag_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ── Unified async API ───────────────────────────────────────────

async def get_conversations(user_id: str) -> list[dict]:
    if _USE_PG:
        return await pg_get_conversations(user_id)
    return await asyncio.to_thread(_sqlite_get_conversations, user_id)


async def upsert_conversation(user_id: str, conv: dict) -> None:
    if _USE_PG:
        await pg_upsert_conversation(user_id, conv)
    else:
        await asyncio.to_thread(_sqlite_upsert_conversation, user_id, conv)


async def delete_conversation(user_id: str, conv_id: str) -> bool:
    if _USE_PG:
        return await pg_delete_conversation(user_id, conv_id)
    return await asyncio.to_thread(_sqlite_delete_conversation, user_id, conv_id)


async def clear_conversations(user_id: str) -> None:
    if _USE_PG:
        await pg_clear_conversations(user_id)
    else:
        await asyncio.to_thread(_sqlite_clear_conversations, user_id)


async def is_user_verified(user_id: str) -> bool:
    if _USE_PG:
        return await pg_is_user_verified(user_id)
    return await asyncio.to_thread(_sqlite_is_user_verified, user_id)


async def mark_user_verified(user_id: str) -> None:
    if _USE_PG:
        await pg_mark_user_verified(user_id)
    else:
        await asyncio.to_thread(_sqlite_mark_user_verified, user_id)


async def get_diagrams(user_id: str) -> list[dict]:
    if _USE_PG:
        return await pg_get_diagrams(user_id)
    return await asyncio.to_thread(_sqlite_get_diagrams, user_id)


async def get_diagram(user_id: str, diag_id: str) -> dict | None:
    if _USE_PG:
        return await pg_get_diagram(user_id, diag_id)
    return await asyncio.to_thread(_sqlite_get_diagram, user_id, diag_id)


async def upsert_diagram(user_id: str, diag: dict) -> None:
    if _USE_PG:
        await pg_upsert_diagram(user_id, diag)
    else:
        await asyncio.to_thread(_sqlite_upsert_diagram, user_id, diag)


async def delete_diagram(user_id: str, diag_id: str) -> bool:
    if _USE_PG:
        return await pg_delete_diagram(user_id, diag_id)
    return await asyncio.to_thread(_sqlite_delete_diagram, user_id, diag_id)


async def init_tables() -> None:
    """Create tables if they don't exist.  No-op for SQLite (lazy init)."""
    if _USE_PG:
        await init_postgres_tables()
