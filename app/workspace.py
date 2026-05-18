"""Per-chat workspace manager.

Every chat session gets an isolated directory tree:

    workspace/{user_id}/{chat_id}/
        uploads/        ← raw uploaded files
        chunks/         ← JSON chunk metadata
        vectors/        ← FAISS index files
        parquet/        ← converted spreadsheet data
        image_refs/     ← extracted PDF image metadata

All paths are relative to the project root ``workspace/`` dir.

Security: ``user_id`` and ``chat_id`` go directly into filesystem paths,
so we validate them before use. See ``_safe_id`` — anything not matching
the allowlist is rejected, closing the path-traversal attack surface
(``../../../etc/passwd`` etc.).
"""

import os
import re
import json
import shutil
import time
import threading
from pathlib import Path
from typing import Any

_WORKSPACE_ROOT = Path(os.path.dirname(os.path.dirname(__file__))) / "workspace"

# Per-user storage ceiling. Hard-coded rather than env-driven because it
# intentionally constrains what we'll let a single user consume on the
# free tier. Override via ``WORKSPACE_QUOTA_BYTES`` if you really need to.
DEFAULT_QUOTA_BYTES = 250 * 1024 * 1024  # 250 MB
MAX_QUOTA_BYTES = int(os.getenv("WORKSPACE_QUOTA_BYTES", str(DEFAULT_QUOTA_BYTES)))

# Firebase UIDs, chat UUIDs, and OTP emails can all be expressed with
# this character set. Rejecting anything else rules out traversal and
# path-separator tricks without having to rely on canonicalisation.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


def _safe_id(value: str, kind: str) -> str:
    """Return ``value`` unchanged if it's a safe filesystem id, else raise.

    We use a strict allowlist instead of blacklisting ``..`` / ``/`` etc.
    because `Path(user_id)` on Windows accepts many sneaky forms
    (``C:``, UNC paths, backslashes). A restrictive character class is
    the only reliable defence.
    """
    if not isinstance(value, str) or not _ID_PATTERN.match(value):
        raise ValueError(f"Invalid {kind}: must match [A-Za-z0-9_.-]{{1,128}}.")
    return value


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _assert_within_root(p: Path) -> Path:
    """Canonicalise and assert that ``p`` stays under the workspace root.

    Defence-in-depth: even after ``_safe_id`` sanitisation, this belt
    check catches bugs where an attacker-controlled path segment slips
    past validation.
    """
    resolved = p.resolve()
    root = _WORKSPACE_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"Path escapes workspace root: {resolved}")
    return p


# ── directory helpers ────────────────────────────────────────────

def workspace_root() -> Path:
    return _ensure(_WORKSPACE_ROOT)


def chat_dir(user_id: str, chat_id: str) -> Path:
    uid = _safe_id(user_id, "user_id")
    cid = _safe_id(chat_id, "chat_id")
    p = _ensure(_WORKSPACE_ROOT / uid / cid)
    _assert_within_root(p)
    return p


def uploads_dir(user_id: str, chat_id: str) -> Path:
    return _ensure(chat_dir(user_id, chat_id) / "uploads")


def chunks_dir(user_id: str, chat_id: str) -> Path:
    return _ensure(chat_dir(user_id, chat_id) / "chunks")


def vectors_dir(user_id: str, chat_id: str) -> Path:
    return _ensure(chat_dir(user_id, chat_id) / "vectors")


def parquet_dir(user_id: str, chat_id: str) -> Path:
    return _ensure(chat_dir(user_id, chat_id) / "parquet")


def image_refs_dir(user_id: str, chat_id: str) -> Path:
    return _ensure(chat_dir(user_id, chat_id) / "image_refs")


# ── /sheets workspace (single active spreadsheet per user) ─────

def sheets_dir(user_id: str) -> Path:
    """Per-user single-spreadsheet workspace used by the Sheets feature.

    Layout (only ONE sheet is kept on disk at a time):
        workspace/{user_id}/sheets/
            source.xlsx | source.csv  ← original upload
            data.parquet              ← querying-optimised copy
            meta.json                 ← cached schema + statistics
    """
    uid = _safe_id(user_id, "user_id")
    p = _ensure(_WORKSPACE_ROOT / uid / "sheets")
    _assert_within_root(p)
    return p


def reset_sheets_dir(user_id: str) -> Path:
    """Wipe the user's sheets workspace and return the fresh directory."""
    uid = _safe_id(user_id, "user_id")
    d = _WORKSPACE_ROOT / uid / "sheets"
    _assert_within_root(d)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return _ensure(d)


# ── file operations ─────────────────────────────────────────────

def save_upload(user_id: str, chat_id: str, filename: str, data: bytes) -> Path:
    """Save an uploaded file and return the full path."""
    # Reject path-traversal filenames (e.g. "../../../etc/passwd")
    clean_name = Path(filename).name
    if clean_name != filename:
        raise ValueError("Invalid filename: path traversal not allowed.")
    dest = uploads_dir(user_id, chat_id) / clean_name
    dest.write_bytes(data)
    _assert_within_root(dest)
    return dest


def save_chunks_meta(user_id: str, chat_id: str, doc_id: str, chunks: list[dict[str, Any]]) -> Path:
    """Persist chunk metadata as JSON."""
    dest = chunks_dir(user_id, chat_id) / f"{doc_id}.json"
    dest.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def load_chunks_meta(user_id: str, chat_id: str, doc_id: str) -> list[dict[str, Any]]:
    src = chunks_dir(user_id, chat_id) / f"{doc_id}.json"
    if not src.exists():
        return []
    return json.loads(src.read_text(encoding="utf-8"))


def list_uploads(user_id: str, chat_id: str) -> list[str]:
    d = uploads_dir(user_id, chat_id)
    return [f.name for f in d.iterdir() if f.is_file()] if d.exists() else []


def cleanup_chat(user_id: str, chat_id: str) -> bool:
    """Delete all workspace data for a chat."""
    d = chat_dir(user_id, chat_id)
    _assert_within_root(d)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def list_user_chats(user_id: str) -> list[str]:
    uid = _safe_id(user_id, "user_id")
    user_dir = _WORKSPACE_ROOT / uid
    _assert_within_root(user_dir)
    if not user_dir.exists():
        return []
    return [d.name for d in user_dir.iterdir() if d.is_dir()]


# ── storage quota ────────────────────────────────────────────────

_QUOTA_CACHE: dict[str, tuple[int, float]] = {}  # user_id → (bytes, timestamp)
_QUOTA_CACHE_TTL = 30.0  # seconds
_QUOTA_LOCK = threading.Lock()


def _dir_size(path: Path) -> int:
    """Recursively compute the byte size of a directory tree."""
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def user_storage_usage(user_id: str) -> int:
    """Return the total bytes used by ``user_id`` under the workspace root.

    The result is cached per-process for ``_QUOTA_CACHE_TTL`` seconds
    so repeated quota checks during a single upload flow are cheap.
    """
    uid = _safe_id(user_id, "user_id")
    with _QUOTA_LOCK:
        cached = _QUOTA_CACHE.get(uid)
        if cached and (time.time() - cached[1]) < _QUOTA_CACHE_TTL:
            return cached[0]
    user_dir = _WORKSPACE_ROOT / uid
    size = _dir_size(user_dir) if user_dir.exists() else 0
    with _QUOTA_LOCK:
        _QUOTA_CACHE[uid] = (size, time.time())
    return size


def check_storage_quota(user_id: str, incoming_bytes: int = 0) -> tuple[bool, int]:
    """Return ``(allowed, remaining_bytes)`` for the user's workspace.

    ``incoming_bytes`` is the estimated size of the new file being
    uploaded so we can reject *before* writing it to disk.
    """
    current = user_storage_usage(user_id)
    total = current + incoming_bytes
    remaining = max(0, MAX_QUOTA_BYTES - total)
    return total <= MAX_QUOTA_BYTES, remaining
