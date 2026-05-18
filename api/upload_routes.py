"""File upload API routes with validation and rate limiting.

Endpoints:
    POST /upload              — Upload files (PDF, Excel, CSV, images)
    GET  /upload/files/{cid}  — List files in a chat
    GET  /upload/status/{cid} — Check processing status
    DELETE /upload/{cid}/{fn} — Remove a specific file

Processing is done in a background task so uploads return instantly.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from api.auth_routes import get_current_user
from app.rate_limits import RateLimit
from app.workspace import (
    check_storage_quota,
    save_upload,
    uploads_dir,
    list_uploads,
    vectors_dir,
    parquet_dir,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["upload"])

# ── Limits ───────────────────────────────────────────────────────
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_PDF_PAGES = 100
MAX_PDF_PER_UPLOAD = 2
MAX_IMAGE_PER_UPLOAD = 3
MAX_PDF_PER_DAY = 5
MAX_IMAGE_PER_DAY = 10

ALLOWED_EXTENSIONS = {
    ".pdf", ".xlsx", ".xls", ".csv",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".csv"}

# Magic-number signatures for content-type validation.
# Extension-only checks let an attacker rename `malware.exe` to `cv.pdf`.
# We sniff the leading bytes to confirm the format matches what the
# extension claims, closing that gap. CSV has no magic number so we
# fall back to a UTF-8 / printable-ASCII heuristic for it.
_FILE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".bmp": (b"BM",),
    # XLSX / XLSM are ZIP-packaged Office Open XML.
    ".xlsx": (b"PK\x03\x04",),
    # Legacy XLS is an OLE compound document.
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
}


def _is_valid_content(ext: str, content: bytes) -> tuple[bool, str]:
    """Return (ok, reason) after sniffing the file's magic bytes.

    The check is deliberately conservative — anything we can't positively
    identify is rejected for binary types. CSV is handled separately
    because plain text has no signature.
    """
    if not content:
        return False, "Empty file."

    # WEBP signature is two-part: "RIFF" + 4 bytes + "WEBP".
    if ext == ".webp":
        if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return True, ""
        return False, "File contents do not match WEBP format."

    signatures = _FILE_SIGNATURES.get(ext)
    if signatures:
        if any(content.startswith(sig) for sig in signatures):
            return True, ""
        return False, f"File contents do not match {ext} format (possible renamed file)."

    if ext == ".csv":
        # Reject obvious binaries: a real CSV is text. Allow up to 1% control
        # bytes (excluding tab/CR/LF) before deciding it's binary in disguise.
        sample = content[:4096]
        if not sample:
            return False, "Empty file."
        bad = sum(1 for b in sample if b < 9 or (13 < b < 32 and b != 27))
        if bad / max(1, len(sample)) > 0.01:
            return False, "CSV contents look binary, not text."
        return True, ""

    # Unknown extension reached this branch — shouldn't happen because
    # ALLOWED_EXTENSIONS gates above, but be defensive.
    return False, "Unrecognised file type."


# Simple in-memory daily counters (reset on restart)
_daily_counts: dict[str, dict[str, int]] = {}

# Track background processing status per chat
_processing_status: dict[str, dict[str, Any]] = {}


def _check_daily_limit(user_id: str, file_type: str) -> bool:
    today = time.strftime("%Y-%m-%d")
    key = f"{user_id}:{today}"
    if key not in _daily_counts:
        _daily_counts[key] = {"pdf": 0, "image": 0}
    counts = _daily_counts[key]
    if file_type == "pdf":
        return counts.get("pdf", 0) < MAX_PDF_PER_DAY
    elif file_type == "image":
        return counts.get("image", 0) < MAX_IMAGE_PER_DAY
    return True


def _increment_daily(user_id: str, file_type: str):
    today = time.strftime("%Y-%m-%d")
    key = f"{user_id}:{today}"
    if key not in _daily_counts:
        _daily_counts[key] = {"pdf": 0, "image": 0}
    _daily_counts[key][file_type] = _daily_counts[key].get(file_type, 0) + 1


# ── Summary builders for chat context ────────────────────────────

def _build_pdf_summary(filename: str, extracted: dict) -> str:
    """Build a brief summary of a processed PDF for chat context."""
    pages = extracted.get("pages", [])
    total = extracted.get("total_pages", 0)
    # Take first ~300 chars of first page as preview
    preview = ""
    for p in pages:
        text = p.get("text", "").strip()
        if text:
            preview = text[:300].replace("\n", " ").strip()
            if len(text) > 300:
                preview += "…"
            break
    image_pages = extracted.get("image_pages", [])
    img_note = f" Contains images on pages: {image_pages[:5]}." if image_pages else ""
    return f"📄 **{filename}** — {total} page(s).{img_note}\nPreview: {preview}"


def _build_spreadsheet_summary(filename: str, schema_info: dict) -> str:
    """Build a brief summary of a processed spreadsheet for chat context."""
    rows = schema_info.get("row_count", 0)
    cols = schema_info.get("column_count", 0)
    col_names = schema_info.get("columns", [])
    col_list = ", ".join(col_names[:10])
    if len(col_names) > 10:
        col_list += f" … (+{len(col_names) - 10} more)"
    return f"📊 **{filename}** — {rows} rows × {cols} columns.\nColumns: {col_list}"


# ── Background processing ───────────────────────────────────────

def _process_pdf(filepath: Path, filename: str, user_id: str, chat_id: str):
    """Heavy PDF processing in background thread."""
    status_key = f"{user_id}:{chat_id}:{filename}"
    _processing_status[status_key] = {"status": "processing", "step": "extracting"}
    try:
        from app.pdf_processor import extract_text_from_pdf
        from app.chunker import chunk_text
        from app.embedding_manager import ChatVectorStore
        from app.workspace import save_chunks_meta

        _processing_status[status_key]["step"] = "extracting text"
        extracted = extract_text_from_pdf(filepath)

        _processing_status[status_key]["step"] = "chunking"
        chunks = chunk_text(
            extracted["pages"],
            doc_id=extracted["doc_id"],
            filename=filename,
            chat_id=chat_id,
            user_id=user_id,
        )

        _processing_status[status_key]["step"] = "saving chunks"
        save_chunks_meta(user_id, chat_id, extracted["doc_id"], chunks)

        _processing_status[status_key]["step"] = "embedding"
        vstore = ChatVectorStore(vectors_dir(user_id, chat_id))
        added = vstore.add(chunks)

        _processing_status[status_key] = {
            "status": "done",
            "pages": extracted["total_pages"],
            "chunks": len(chunks),
            "vectors": added,
            "summary": _build_pdf_summary(filename, extracted),
        }
        logger.info("PDF processed: %s (%d pages, %d chunks, %d vectors)", filename, extracted["total_pages"], len(chunks), added)
    except Exception as e:
        logger.error("PDF background processing error for %s: %s", filename, e, exc_info=True)
        _processing_status[status_key] = {"status": "error", "error": str(e)}


def _process_spreadsheet(filepath: Path, filename: str, user_id: str, chat_id: str):
    """Spreadsheet processing in background thread."""
    status_key = f"{user_id}:{chat_id}:{filename}"
    _processing_status[status_key] = {"status": "processing", "step": "parsing"}
    try:
        from app.excel_processor import parse_spreadsheet, convert_to_parquet

        _processing_status[status_key]["step"] = "parsing schema"
        schema_info = parse_spreadsheet(filepath)

        _processing_status[status_key]["step"] = "converting to parquet"
        pq_path = convert_to_parquet(filepath, parquet_dir(user_id, chat_id))

        _processing_status[status_key] = {
            "status": "done",
            "rows": schema_info["row_count"],
            "columns": schema_info["column_count"],
            "summary": _build_spreadsheet_summary(filename, schema_info),
        }
        logger.info("Spreadsheet processed: %s (%d rows, %d cols)", filename, schema_info["row_count"], schema_info["column_count"])
    except Exception as e:
        logger.error("Spreadsheet background processing error for %s: %s", filename, e, exc_info=True)
        _processing_status[status_key] = {"status": "error", "error": str(e)}


class UploadResponse(BaseModel):
    status: str
    files: list[dict[str, Any]]
    chat_id: str


@router.post("", response_model=UploadResponse, dependencies=[Depends(RateLimit("upload.create", per_minute=15, per_day=60))])
async def upload_files(
    chat_id: str = Form(...),
    files: list[UploadFile] = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Upload files to a chat session. Returns immediately; processing runs in background."""
    user_id = user["user_id"]
    results: list[dict[str, Any]] = []

    # Count by type
    pdf_count = sum(1 for f in files if f.filename and f.filename.lower().endswith(".pdf"))
    image_count = sum(
        1 for f in files
        if f.filename and any(f.filename.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)
    )

    if pdf_count > MAX_PDF_PER_UPLOAD:
        raise HTTPException(400, f"Maximum {MAX_PDF_PER_UPLOAD} PDFs per upload.")
    if image_count > MAX_IMAGE_PER_UPLOAD:
        raise HTTPException(400, f"Maximum {MAX_IMAGE_PER_UPLOAD} images per upload.")

    for upload in files:
        filename = upload.filename or "unnamed"
        ext = ("." + filename.rsplit(".", 1)[-1]).lower() if "." in filename else ""

        # Validate extension
        if ext not in ALLOWED_EXTENSIONS:
            results.append({"filename": filename, "status": "rejected", "reason": f"Unsupported file type: {ext}"})
            continue

        # Read content
        content = await upload.read()

        # Validate size BEFORE running expensive checks. A 5GB stream of
        # zero bytes shouldn't trigger a magic-number sniff over the whole file.
        if len(content) > MAX_FILE_SIZE:
            results.append({"filename": filename, "status": "rejected", "reason": "File too large (max 20MB)"})
            continue

        # Magic-number / content-type validation — protects against
        # renamed executables and other extension spoofing.
        ok, reason = _is_valid_content(ext, content)
        if not ok:
            results.append({"filename": filename, "status": "rejected", "reason": reason})
            continue

        # Storage-quota guard: reject before writing to disk.
        allowed, _ = check_storage_quota(user_id, incoming_bytes=len(content))
        if not allowed:
            results.append({
                "filename": filename,
                "status": "rejected",
                "reason": f"Storage quota exceeded. Delete old files to free space.",
            })
            continue

        # Check daily limits
        file_category = "pdf" if ext == ".pdf" else "image" if ext in IMAGE_EXTENSIONS else "other"
        if file_category in ("pdf", "image") and not _check_daily_limit(user_id, file_category):
            limit = MAX_PDF_PER_DAY if file_category == "pdf" else MAX_IMAGE_PER_DAY
            results.append({"filename": filename, "status": "rejected", "reason": f"Daily {file_category} limit ({limit}) reached"})
            continue

        # Validate PDF page count
        if ext == ".pdf":
            try:
                import fitz
                doc = fitz.open(stream=content, filetype="pdf")
                page_count = len(doc)
                doc.close()
                if page_count > MAX_PDF_PAGES:
                    results.append({"filename": filename, "status": "rejected", "reason": f"PDF has {page_count} pages (max {MAX_PDF_PAGES})"})
                    continue
            except Exception as e:
                results.append({"filename": filename, "status": "rejected", "reason": f"Invalid PDF: {e}"})
                continue

        # Save file to disk (fast)
        filepath = await asyncio.to_thread(save_upload, user_id, chat_id, filename, content)

        # Build response info
        info: dict[str, Any] = {"filename": filename, "status": "uploaded", "size": len(content), "type": ext}

        if ext == ".pdf":
            _increment_daily(user_id, "pdf")
            info["status"] = "processing"
            # Kick off heavy processing in background
            background_tasks.add_task(_process_pdf, filepath, filename, user_id, chat_id)

        elif ext in SPREADSHEET_EXTENSIONS:
            info["status"] = "processing"
            background_tasks.add_task(_process_spreadsheet, filepath, filename, user_id, chat_id)

        elif ext in IMAGE_EXTENSIONS:
            _increment_daily(user_id, "image")
            info["status"] = "uploaded"

        results.append(info)

    return UploadResponse(status="ok", files=results, chat_id=chat_id)


@router.get("/status/{chat_id}")
def get_processing_status(chat_id: str, user: dict[str, Any] = Depends(get_current_user)):
    """Check the processing status of files in a chat."""
    user_id = user["user_id"]
    prefix = f"{user_id}:{chat_id}:"
    statuses = {}
    for key, val in _processing_status.items():
        if key.startswith(prefix):
            filename = key[len(prefix):]
            statuses[filename] = val
    
    all_done = all(s.get("status") in ("done", "error") for s in statuses.values()) if statuses else True
    return {"chat_id": chat_id, "files": statuses, "all_done": all_done}


@router.get("/files/{chat_id}")
async def list_chat_files(chat_id: str, user: dict[str, Any] = Depends(get_current_user)):
    """List all uploaded files in a chat."""
    import asyncio as _asyncio
    user_id = user["user_id"]
    files = await _asyncio.to_thread(list_uploads, user_id, chat_id)
    file_details = []
    upload_path = uploads_dir(user_id, chat_id)
    for f in files:
        fp = upload_path / f
        ext = ("." + f.rsplit(".", 1)[-1]).lower() if "." in f else ""
        status_key = f"{user_id}:{chat_id}:{f}"
        proc_status = _processing_status.get(status_key, {})
        size = await _asyncio.to_thread(lambda p: p.stat().st_size if p.exists() else 0, fp)
        file_details.append({
            "filename": f,
            "size": size,
            "type": ext,
            "category": "pdf" if ext == ".pdf" else "image" if ext in IMAGE_EXTENSIONS else "spreadsheet" if ext in SPREADSHEET_EXTENSIONS else "other",
            "processing": proc_status.get("status", "unknown"),
        })
    return {"files": file_details, "chat_id": chat_id}


@router.delete("/{chat_id}/{filename}")
async def delete_file(chat_id: str, filename: str, user: dict[str, Any] = Depends(get_current_user)):
    import asyncio as _asyncio
    user_id = user["user_id"]
    fp = uploads_dir(user_id, chat_id) / filename
    exists = await _asyncio.to_thread(lambda p: p.exists(), fp)
    if not exists:
        raise HTTPException(404, "File not found")
    await _asyncio.to_thread(lambda p: p.unlink(), fp)
    return {"status": "deleted", "filename": filename}
