"""One-time export of existing SQLite data to JSON files for Supabase migration.

Usage:
    python scripts/export_sqlite.py

Creates:
    migrate_conversations.json
    migrate_diagrams.json
    migrate_verifications.json
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

# Add project root to path so we can import app.db
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Force SQLite mode (ignore any SUPABASE_DB_URL env var)
os.environ.pop("SUPABASE_DB_URL", None)

from app.db import get_conn


def export_table(table: str, conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(f"SELECT * FROM {table}")
    rows = [dict(row) for row in cursor.fetchall()]
    # Parse JSON columns
    for row in rows:
        for key in row:
            if isinstance(row[key], str) and row[key].startswith("[") or row[key].startswith("{"):
                try:
                    row[key] = json.loads(row[key])
                except json.JSONDecodeError:
                    pass
    return rows


def main() -> None:
    conn = get_conn()
    output_dir = project_root / "scripts" / "migrations"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[export] Conversations...")
    conversations = export_table("conversations", conn)
    with open(output_dir / "conversations.json", "w", encoding="utf-8") as f:
        json.dump(conversations, f, ensure_ascii=False, indent=2)
    print(f"  → {len(conversations)} rows")

    print("[export] Diagrams...")
    diagrams = export_table("diagrams", conn)
    with open(output_dir / "diagrams.json", "w", encoding="utf-8") as f:
        json.dump(diagrams, f, ensure_ascii=False, indent=2)
    print(f"  → {len(diagrams)} rows")

    print("[export] User Verifications...")
    verifications = export_table("user_verifications", conn)
    with open(output_dir / "verifications.json", "w", encoding="utf-8") as f:
        json.dump(verifications, f, ensure_ascii=False, indent=2)
    print(f"  → {len(verifications)} rows")

    print(f"\nDone. Files saved to: {output_dir}")
    print("\nNext step: Set SUPABASE_DB_URL and run:")
    print("  python scripts/import_to_supabase.py")


if __name__ == "__main__":
    main()
