import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chat_history.db"


def _init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
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


def get_conversations(user_id: str) -> list[dict]:
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


def upsert_conversation(user_id: str, conv: dict) -> None:
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


def delete_conversation(user_id: str, conv_id: str) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM conversations WHERE id = ? AND user_id = ?",
        (conv_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0


def clear_conversations(user_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    conn.commit()


def is_user_verified(user_id: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT otp_verified FROM user_verifications WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    if row:
        return bool(row["otp_verified"])
    return False


def mark_user_verified(user_id: str) -> None:
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


def get_diagrams(user_id: str) -> list[dict]:
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


def get_diagram(user_id: str, diag_id: str) -> dict | None:
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


def upsert_diagram(user_id: str, diag: dict) -> None:
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


def delete_diagram(user_id: str, diag_id: str) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM diagrams WHERE id = ? AND user_id = ?",
        (diag_id, user_id),
    )
    conn.commit()
    return cur.rowcount > 0
