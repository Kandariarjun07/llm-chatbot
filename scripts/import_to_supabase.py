"""Import JSON migration files into Supabase PostgreSQL.

Prerequisites:
    Set SUPABASE_DB_URL environment variable.

Usage:
    python scripts/import_to_supabase.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

os.environ["SUPABASE_DB_URL"] = os.environ.get("SUPABASE_DB_URL", "")
if not os.environ["SUPABASE_DB_URL"]:
    print("Error: Set SUPABASE_DB_URL env var first.")
    sys.exit(1)

from app.db_postgres import (
    init_postgres_tables,
    async_session,
    Conversation,
    Diagram,
    UserVerification,
)
from sqlalchemy import insert
from datetime import datetime, timezone


def _to_ts(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return datetime.now(timezone.utc)


async def import_conversations() -> int:
    path = project_root / "scripts" / "migrations" / "conversations.json"
    if not path.exists():
        print("  [skip] conversations.json not found")
        return 0
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    async for session in async_session():
        for row in data:
            stmt = (
                insert(Conversation)
                .values(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row.get("title", "New conversation"),
                    created_at=_to_ts(row.get("created_at", row.get("createdAt"))),
                    updated_at=_to_ts(row.get("updated_at", row.get("updatedAt"))),
                    messages=row.get("messages", []),
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await session.execute(stmt)
            count += 1
        await session.commit()
    return count


async def import_diagrams() -> int:
    path = project_root / "scripts" / "migrations" / "diagrams.json"
    if not path.exists():
        print("  [skip] diagrams.json not found")
        return 0
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    async for session in async_session():
        for row in data:
            stmt = (
                insert(Diagram)
                .values(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row.get("title", "Untitled Diagram"),
                    diagram_type=row.get("diagram_type", row.get("diagramType", "flowchart")),
                    created_at=_to_ts(row.get("created_at", row.get("createdAt"))),
                    updated_at=_to_ts(row.get("updated_at", row.get("updatedAt"))),
                    nodes=row.get("nodes", []),
                    edges=row.get("edges", []),
                    mermaid_code=row.get("mermaid_code", row.get("mermaidCode", "")),
                    metadata=row.get("metadata", {}),
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await session.execute(stmt)
            count += 1
        await session.commit()
    return count


async def import_verifications() -> int:
    path = project_root / "scripts" / "migrations" / "verifications.json"
    if not path.exists():
        print("  [skip] verifications.json not found")
        return 0
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    async for session in async_session():
        for row in data:
            stmt = (
                insert(UserVerification)
                .values(
                    user_id=row["user_id"],
                    otp_verified=bool(row.get("otp_verified", 0)),
                )
                .on_conflict_do_nothing(index_elements=["user_id"])
            )
            await session.execute(stmt)
            count += 1
        await session.commit()
    return count


async def main() -> None:
    print("[init] Creating tables if missing...")
    await init_postgres_tables()

    print("[import] Conversations...")
    n = await import_conversations()
    print(f"  → {n} rows imported")

    print("[import] Diagrams...")
    n = await import_diagrams()
    print(f"  → {n} rows imported")

    print("[import] Verifications...")
    n = await import_verifications()
    print(f"  → {n} rows imported")

    print("\nDone. Data is now in Supabase PostgreSQL.")


if __name__ == "__main__":
    asyncio.run(main())
