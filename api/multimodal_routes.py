"""Multimodal chat routes — handles queries that involve uploaded files.

This module provides the /chat/multimodal endpoint that:
1. Detects what pipeline to use (text, PDF RAG, analytics, vision)
2. Executes the appropriate pipeline
3. Returns structured results including charts, citations, etc.

A new **/chat/multimodal/stream** SSE endpoint streams the answer text
chunk-by-chunk so the frontend never stares at a blank screen while the
LLM thinks. Metadata (citations, charts) is appended in the final `done`
event.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth_routes import get_current_user
from app.config import get_settings
from app.workspace import uploads_dir, vectors_dir, parquet_dir, list_uploads
from llm.client import achat_completion_stream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["multimodal"])

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".csv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class MultimodalRequest(BaseModel):
    query: str = Field(..., min_length=1)
    chat_id: str = Field(..., min_length=1)
    model_choice: str = "Llama"
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    max_output_tokens: int = Field(default=8192, ge=256, le=16384)
    # Names of files freshly attached to *this* user turn. Lets handlers
    # distinguish "files attached with the current question" from older
    # files already present in the chat workspace.
    current_files: list[str] = Field(default_factory=list)


class MultimodalResponse(BaseModel):
    answer: str
    pipeline: str
    citations: list[dict[str, Any]] = []
    chart: dict[str, Any] | None = None
    analytics_result: dict[str, Any] | None = None


def _chat_file_state(user_id: str, chat_id: str) -> dict[str, bool]:
    """Check what types of files exist in the chat."""
    files = list_uploads(user_id, chat_id)
    has_pdfs = any(f.lower().endswith(".pdf") for f in files)
    has_spreadsheets = any(
        any(f.lower().endswith(ext) for ext in SPREADSHEET_EXTENSIONS)
        for f in files
    )
    has_images = any(
        any(f.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)
        for f in files
    )
    return {"pdfs": has_pdfs, "spreadsheets": has_spreadsheets, "images": has_images}


@router.post("/multimodal", response_model=MultimodalResponse)
async def multimodal_chat(
    request: MultimodalRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Intelligent multimodal chat endpoint."""
    user_id = user["user_id"]
    chat_id = request.chat_id
    query = request.query

    # Determine what's in the chat
    file_state = _chat_file_state(user_id, chat_id)

    # Normalise current_files: keep only names that actually exist in the chat
    # workspace, so a stale frontend list can never break the pipeline.
    all_files = set(list_uploads(user_id, chat_id))
    current_files = [f for f in (request.current_files or []) if f in all_files]

    # Route the query — give the router a hint about the current attachments
    # so that "attached_file" wins over "chat_has_*" when both apply.
    from app.multimodal_router import route_query
    attached_hint = [{"filename": f} for f in current_files]
    routing = route_query(
        query,
        attached_files=attached_hint,
        chat_has_pdfs=file_state["pdfs"],
        chat_has_spreadsheets=file_state["spreadsheets"],
        chat_has_images=file_state["images"],
    )

    logger.info(
        "Multimodal routing: %s for query=%s current_files=%s",
        routing.pipeline, query[:80], current_files,
    )

    try:
        if routing.pipeline == "pdf_rag":
            return await _handle_pdf_rag(
                user_id, chat_id, query,
                request.model_choice, request.temperature, request.max_output_tokens,
                current_files=current_files,
            )

        elif routing.pipeline == "analytics":
            return await _handle_analytics(
                user_id, chat_id, query,
                request.model_choice, request.temperature,
                current_files=current_files,
            )

        elif routing.pipeline == "vision":
            return await _handle_vision(user_id, chat_id, query, current_files=current_files)

        elif routing.pipeline == "pdf_vision":
            target_page = routing.extra.get("target_page", 1)
            return await _handle_pdf_vision(
                user_id, chat_id, query, target_page,
                current_files=current_files,
            )

        else:
            # Default text pipeline — fall through to normal /chat/stream
            return MultimodalResponse(
                answer="",
                pipeline="text",
            )

    except Exception as e:
        logger.error("Multimodal pipeline error: %s", e, exc_info=True)
        return MultimodalResponse(
            answer=f"Error in {routing.pipeline} pipeline: {str(e)}",
            pipeline=routing.pipeline,
        )


def _current_pdfs(current_files: list[str]) -> list[str]:
    return [f for f in current_files if f.lower().endswith(".pdf")]


async def _handle_pdf_rag(
    user_id: str,
    chat_id: str,
    query: str,
    model_choice: str,
    temperature: float,
    max_output_tokens: int,
    *,
    current_files: list[str] | None = None,
) -> MultimodalResponse:
    """RAG pipeline: search per-chat vectors → grounded LLM answer with citations.

    When ``current_files`` is provided, chunks coming from those PDFs are
    surfaced first (re-ranked to the top) and the LLM is explicitly told
    which document(s) the user just attached.
    """
    from app.embedding_manager import ChatVectorStore
    from llm.client import chat_completion

    vstore = ChatVectorStore(vectors_dir(user_id, chat_id))

    if vstore.count == 0:
        return MultimodalResponse(
            answer="No documents have been indexed in this chat yet. Please upload a PDF first.",
            pipeline="pdf_rag",
        )

    current_pdfs = _current_pdfs(current_files or [])
    # Pull more candidates when we need to re-rank by current-file membership.
    raw_top_k = 12 if current_pdfs else 8
    raw_results = await asyncio.to_thread(vstore.search, query, top_k=raw_top_k)

    if not raw_results:
        return MultimodalResponse(
            answer="No relevant content found in the uploaded documents for your query.",
            pipeline="pdf_rag",
        )

    # Re-rank: chunks from currently-attached PDFs come first, preserving
    # original score order within each group.
    if current_pdfs:
        current_set = {p.lower() for p in current_pdfs}
        primary = [r for r in raw_results if str(r.get("source", "")).lower() in current_set]
        secondary = [r for r in raw_results if str(r.get("source", "")).lower() not in current_set]
        # Keep a healthy mix: prefer primary, but still include up to 3 secondary
        # chunks so cross-document follow-ups still work.
        results = (primary[:6] + secondary[:3])[:8] or raw_results[:8]
    else:
        results = raw_results[:8]

    # Build context from retrieved chunks
    context_parts = []
    citations = []
    for i, r in enumerate(results, 1):
        source = r.get("source", "unknown")
        page = r.get("page", "?")
        text = r.get("text", "")
        marker = " (just attached)" if current_pdfs and str(source).lower() in {p.lower() for p in current_pdfs} else ""
        context_parts.append(f"[{i}] (Source: {source}{marker}, Page {page})\n{text}")
        citations.append({
            "ref": i,
            "source": source,
            "page": page,
            "score": r.get("score", 0),
            "excerpt": text[:200] + "..." if len(text) > 200 else text,
        })

    context_text = "\n\n".join(context_parts)

    # Tell the LLM exactly which files the user just attached, so follow-up
    # questions aimed at the *new* document aren't conflated with older
    # documents already indexed in the chat.
    if current_pdfs:
        attached_note = (
            "FILES THE USER JUST ATTACHED IN THIS MESSAGE: "
            + ", ".join(current_pdfs)
            + "\nIf the user's question is about *these* files, focus on them. "
              "Other documents may be referenced in the context only as supporting background."
        )
    else:
        attached_note = "NOTE: No files were newly attached to this question — answer using the existing chat documents."

    prompt = f"""You are a highly knowledgeable document analyst. The user has uploaded one or more documents and is asking about them.

{attached_note}

Your job is to provide a **thorough, detailed, and comprehensive** answer based on the document content below.

Rules:
- Give a DETAILED answer — not a 2-3 line summary. Explain concepts, provide context, highlight key details.
- Use the document content extensively. Quote specific sections when relevant.
- Include citations using [1], [2], etc. to reference the source.
- If the user asks a general question like "what is this" or "summarize", provide a full overview covering:
  • What the document is about
  • Key sections and their content
  • Important details, numbers, dates, names
  • Overall purpose and conclusions
- If the context doesn't fully answer the question, explain what IS available and what might be missing.
- Use markdown formatting (headers, bullet points, bold) for readability.
- Be conversational and helpful, like a smart assistant who has read the document.

Document Content:
{context_text}

User Question: {query}

Detailed Answer:"""

    messages = [{"role": "user", "content": prompt}]
    answer = await asyncio.to_thread(
        chat_completion,
        messages,
        model_choice,
        temperature=temperature,
        max_output_tokens=4096,  # Increase for detailed PDF analysis
    )

    return MultimodalResponse(
        answer=answer,
        pipeline="pdf_rag",
        citations=citations,
    )


async def _handle_analytics(
    user_id: str,
    chat_id: str,
    query: str,
    model_choice: str,
    temperature: float,
    *,
    current_files: list[str] | None = None,
) -> MultimodalResponse:
    """Analytics pipeline: generate SQL → execute → chart.

    When the user just attached a spreadsheet, prefer that file's parquet
    over the (potentially older) first parquet found on disk.
    """
    from app.excel_processor import execute_analytics, select_chart_type
    from llm.client import chat_completion

    # Find parquet files
    pq_dir = parquet_dir(user_id, chat_id)
    parquet_files = list(pq_dir.glob("*.parquet")) if pq_dir.exists() else []

    if not parquet_files:
        return MultimodalResponse(
            answer="No spreadsheet data found in this chat. Please upload an Excel or CSV file first.",
            pipeline="analytics",
        )

    # Prefer a parquet whose stem matches a freshly-attached spreadsheet.
    current_sheets = [
        f for f in (current_files or [])
        if any(f.lower().endswith(ext) for ext in SPREADSHEET_EXTENSIONS)
    ]
    current_stems = {Path(f).stem.lower() for f in current_sheets}
    pq_path = next(
        (p for p in parquet_files if p.stem.lower() in current_stems),
        parquet_files[0],
    )

    # Load schema for the chosen parquet file
    import polars as pl
    df = pl.read_parquet(pq_path)
    schema_info = {
        "columns": df.columns,
        "dtypes": {col: str(df[col].dtype) for col in df.columns},
        "row_count": len(df),
        "sample_rows": df.head(3).to_dicts(),
    }

    # Ask LLM to generate a SQL query
    active_file_note = (
        f"\nActive file (just attached by the user): {pq_path.stem}"
        if current_sheets else ""
    )
    sql_prompt = f"""You are a data analyst. Given the following table schema, write a SQL query to answer the user's question.

Table name: data{active_file_note}
Schema:
{json.dumps(schema_info['dtypes'], indent=2)}

Row count: {schema_info['row_count']}
Sample rows:
{json.dumps(schema_info['sample_rows'], indent=2)}

User question: {query}

RULES:
- Write ONLY a SELECT query. No DDL, no DML.
- Use standard SQL syntax.
- Aggregate data when appropriate (don't return millions of rows).
- Limit results to 50 rows max.
- Respond with ONLY the SQL query, no explanation.

SQL:"""

    messages = [{"role": "user", "content": sql_prompt}]
    sql_raw = await asyncio.to_thread(
        chat_completion, messages, model_choice, temperature=0.0
    )

    # Clean SQL
    sql = sql_raw.strip()
    if sql.startswith("```"):
        sql = sql.split("\n", 1)[1] if "\n" in sql else sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    sql = sql.strip()

    # Execute
    try:
        result = await asyncio.to_thread(execute_analytics, pq_path, sql)
    except Exception as e:
        return MultimodalResponse(
            answer=f"I generated this query but it failed:\n```sql\n{sql}\n```\nError: {str(e)}",
            pipeline="analytics",
        )

    # Auto-select chart
    chart_config = select_chart_type(result["columns"], result["rows"], query)

    # Generate natural language summary
    summary_prompt = f"""Summarize these analytics results in 2-3 sentences for a non-technical user.

SQL Query: {sql}
Results ({result['row_count']} rows):
{json.dumps(result['rows'][:10], indent=2, default=str)}

User's original question: {query}

Summary:"""

    summary_messages = [{"role": "user", "content": summary_prompt}]
    summary = await asyncio.to_thread(
        chat_completion, summary_messages, model_choice, temperature=0.2
    )

    return MultimodalResponse(
        answer=summary,
        pipeline="analytics",
        chart=chart_config,
        analytics_result={
            "sql": sql,
            "columns": result["columns"],
            "rows": result["rows"][:50],  # Cap at 50 for frontend
            "row_count": result["row_count"],
        },
    )


async def _handle_vision(
    user_id: str,
    chat_id: str,
    query: str,
    *,
    current_files: list[str] | None = None,
) -> MultimodalResponse:
    """Image understanding via Gemini Vision — supports multiple images.

    Behaviour:
    - If ``current_files`` lists image names that exist on disk, ONLY those
      images are sent to Gemini and the user's question is prefixed with the
      filenames so the model knows which image(s) are being asked about.
    - Otherwise the legacy behaviour applies: send all images in the chat,
      sorted by mtime, capped at 10.
    """
    from app.vision_pipeline import understand_image_from_file, understand_multiple_images

    upload_path = uploads_dir(user_id, chat_id)
    all_images = sorted(
        [f for f in upload_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS],
        key=lambda f: f.stat().st_mtime,
    ) if upload_path.exists() else []

    if not all_images:
        return MultimodalResponse(
            answer="No images found in this chat. Please upload an image first.",
            pipeline="vision",
        )

    # Filter to only the images attached in the current turn (if any).
    current_image_names = {
        f for f in (current_files or [])
        if any(f.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)
    }
    if current_image_names:
        focused = [img for img in all_images if img.name in current_image_names]
    else:
        focused = []

    images = focused if focused else all_images
    capped = images[:10]

    # Build a focused prompt that names the current-turn images so the LLM
    # knows which file the user is *actually* asking about right now.
    if focused:
        names = ", ".join(img.name for img in capped)
        focused_query = (
            f"The user just attached the following image(s) with this message: {names}.\n"
            f"Focus your answer on those image(s).\n\n"
            f"User question: {query}"
        )
    else:
        focused_query = query

    if len(capped) == 1:
        answer = await asyncio.to_thread(understand_image_from_file, capped[0], focused_query)
    else:
        answer = await asyncio.to_thread(understand_multiple_images, capped, focused_query)

    return MultimodalResponse(answer=answer, pipeline="vision")


async def _handle_pdf_vision(
    user_id: str,
    chat_id: str,
    query: str,
    page_num: int,
    *,
    current_files: list[str] | None = None,
) -> MultimodalResponse:
    """Lazy PDF page image analysis via Gemini Vision."""
    from app.vision_pipeline import understand_pdf_page

    # Find PDFs
    upload_path = uploads_dir(user_id, chat_id)
    pdfs = [f for f in upload_path.iterdir() if f.suffix.lower() == ".pdf"] if upload_path.exists() else []

    if not pdfs:
        return MultimodalResponse(
            answer="No PDFs found in this chat.",
            pipeline="pdf_vision",
        )

    # Prefer a PDF freshly attached in this turn; otherwise fall back to the
    # most recently uploaded PDF.
    current_pdf_names = {f for f in (current_files or []) if f.lower().endswith(".pdf")}
    target_pdf = next(
        (p for p in pdfs if p.name in current_pdf_names),
        max(pdfs, key=lambda f: f.stat().st_mtime),
    )

    focused_query = (
        f"The user just attached '{target_pdf.name}' and is asking about page {page_num}.\n\n"
        f"User question: {query}"
        if target_pdf.name in current_pdf_names
        else query
    )
    answer = await asyncio.to_thread(understand_pdf_page, target_pdf, page_num, focused_query)

    return MultimodalResponse(
        answer=answer,
        pipeline="pdf_vision",
        citations=[{"source": target_pdf.name, "page": page_num}],
    )


# ── Streaming variants ─────────────────────────────────────────────


async def _stream_pdf_rag(
    user_id: str,
    chat_id: str,
    query: str,
    model_choice: str,
    temperature: float,
    max_output_tokens: int,
    *,
    current_files: list[str] | None = None,
):
    """Yield SSE events for the PDF RAG pipeline."""
    from app.embedding_manager import ChatVectorStore

    vstore = ChatVectorStore(vectors_dir(user_id, chat_id))

    if vstore.count == 0:
        yield json.dumps({"event": "error", "message": "No documents have been indexed in this chat yet. Please upload a PDF first."})
        return

    current_pdfs = _current_pdfs(current_files or [])
    raw_top_k = 12 if current_pdfs else 8
    raw_results = await asyncio.to_thread(vstore.search, query, top_k=raw_top_k)

    if not raw_results:
        yield json.dumps({"event": "error", "message": "No relevant content found in the uploaded documents for your query."})
        return

    if current_pdfs:
        current_set = {p.lower() for p in current_pdfs}
        primary = [r for r in raw_results if str(r.get("source", "")).lower() in current_set]
        secondary = [r for r in raw_results if str(r.get("source", "")).lower() not in current_set]
        results = (primary[:6] + secondary[:3])[:8] or raw_results[:8]
    else:
        results = raw_results[:8]

    context_parts = []
    citations = []
    for i, r in enumerate(results, 1):
        source = r.get("source", "unknown")
        page = r.get("page", "?")
        text = r.get("text", "")
        marker = " (just attached)" if current_pdfs and str(source).lower() in {p.lower() for p in current_pdfs} else ""
        context_parts.append(f"[{i}] (Source: {source}{marker}, Page {page})\n{text}")
        citations.append({
            "ref": i,
            "source": source,
            "page": page,
            "score": r.get("score", 0),
            "excerpt": text[:200] + "..." if len(text) > 200 else text,
        })

    context_text = "\n\n".join(context_parts)
    if current_pdfs:
        attached_note = (
            "FILES THE USER JUST ATTACHED IN THIS MESSAGE: "
            + ", ".join(current_pdfs)
            + "\nIf the user's question is about *these* files, focus on them. "
              "Other documents may be referenced in the context only as supporting background."
        )
    else:
        attached_note = "NOTE: No files were newly attached to this question — answer using the existing chat documents."

    prompt = f"""You are a highly knowledgeable document analyst. The user has uploaded one or more documents and is asking about them.

{attached_note}

Your job is to provide a **thorough, detailed, and comprehensive** answer based on the document content below.

Rules:
- Give a DETAILED answer — not a 2-3 line summary. Explain concepts, provide context, highlight key details.
- Use the document content extensively. Quote specific sections when relevant.
- Include citations using [1], [2], etc. to reference the source.
- If the user asks a general question like "what is this" or "summarize", provide a full overview covering:
  • What the document is about
  • Key sections and their content
  • Important details, numbers, dates, names
  • Overall purpose and conclusions
- If the context doesn't fully answer the question, explain what IS available and what might be missing.
- Use markdown formatting (headers, bullet points, bold) for readability.
- Be conversational and helpful, like a smart assistant who has read the document.

Document Content:
{context_text}

User Question: {query}

Detailed Answer:"""

    yield json.dumps({"event": "start", "pipeline": "pdf_rag", "model": model_choice})

    messages = [{"role": "user", "content": prompt}]
    buffer = ""
    try:
        async for delta in achat_completion_stream(
            messages,
            model_choice=model_choice,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ):
            buffer += delta
            yield json.dumps({"event": "delta", "delta": delta})
    except Exception as e:
        yield json.dumps({"event": "error", "message": str(e)})
        return

    yield json.dumps({"event": "done", "answer": buffer, "citations": citations})


async def _stream_analytics(
    user_id: str,
    chat_id: str,
    query: str,
    model_choice: str,
    temperature: float,
    *,
    current_files: list[str] | None = None,
):
    """Yield SSE events for the analytics pipeline."""
    from app.excel_processor import execute_analytics, select_chart_type

    pq_dir = parquet_dir(user_id, chat_id)
    parquet_files = list(pq_dir.glob("*.parquet")) if pq_dir.exists() else []

    if not parquet_files:
        yield json.dumps({"event": "error", "message": "No spreadsheet data found in this chat. Please upload an Excel or CSV file first."})
        return

    current_sheets = [
        f for f in (current_files or [])
        if any(f.lower().endswith(ext) for ext in SPREADSHEET_EXTENSIONS)
    ]
    current_stems = {Path(f).stem.lower() for f in current_sheets}
    pq_path = next(
        (p for p in parquet_files if p.stem.lower() in current_stems),
        parquet_files[0],
    )

    import polars as pl
    df = pl.read_parquet(pq_path)
    schema_info = {
        "columns": df.columns,
        "dtypes": {col: str(df[col].dtype) for col in df.columns},
        "row_count": len(df),
        "sample_rows": df.head(3).to_dicts(),
    }

    active_file_note = (
        f"\nActive file (just attached by the user): {pq_path.stem}"
        if current_sheets else ""
    )
    sql_prompt = f"""You are a data analyst. Given the following table schema, write a SQL query to answer the user's question.

Table name: data{active_file_note}
Schema:
{json.dumps(schema_info['dtypes'], indent=2)}

Row count: {schema_info['row_count']}
Sample rows:
{json.dumps(schema_info['sample_rows'], indent=2)}

User question: {query}

RULES:
- Write ONLY a SELECT query. No DDL, no DML.
- Use standard SQL syntax.
- Aggregate data when appropriate (don't return millions of rows).
- Limit results to 50 rows max.
- Respond with ONLY the SQL query, no explanation.

SQL:"""

    messages = [{"role": "user", "content": sql_prompt}]
    from llm.client import chat_completion
    sql_raw = await asyncio.to_thread(chat_completion, messages, model_choice, temperature=0.0)

    sql = sql_raw.strip()
    if sql.startswith("```"):
        sql = sql.split("\n", 1)[1] if "\n" in sql else sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    sql = sql.strip()

    try:
        result = await asyncio.to_thread(execute_analytics, pq_path, sql)
    except Exception as e:
        yield json.dumps({"event": "error", "message": f"I generated this query but it failed:\n```sql\n{sql}\n```\nError: {str(e)}"})
        return

    chart_config = select_chart_type(result["columns"], result["rows"], query)

    summary_prompt = f"""Summarize these analytics results in 2-3 sentences for a non-technical user.

SQL Query: {sql}
Results ({result['row_count']} rows):
{json.dumps(result['rows'][:10], indent=2, default=str)}

User's original question: {query}

Summary:"""

    yield json.dumps({"event": "start", "pipeline": "analytics", "model": model_choice})

    summary_messages = [{"role": "user", "content": summary_prompt}]
    buffer = ""
    try:
        async for delta in achat_completion_stream(
            summary_messages,
            model_choice=model_choice,
            temperature=0.2,
            max_output_tokens=1024,
        ):
            buffer += delta
            yield json.dumps({"event": "delta", "delta": delta})
    except Exception as e:
        yield json.dumps({"event": "error", "message": str(e)})
        return

    yield json.dumps({
        "event": "done",
        "answer": buffer,
        "chart": chart_config,
        "analytics_result": {
            "sql": sql,
            "columns": result["columns"],
            "rows": result["rows"][:50],
            "row_count": result["row_count"],
        },
    })


async def _stream_vision(
    user_id: str,
    chat_id: str,
    query: str,
    *,
    current_files: list[str] | None = None,
):
    """Vision is synchronous (Gemini Vision) — emit the full answer as one chunk."""
    from app.vision_pipeline import understand_image_from_file, understand_multiple_images

    upload_path = uploads_dir(user_id, chat_id)
    all_images = sorted(
        [f for f in upload_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS],
        key=lambda f: f.stat().st_mtime,
    ) if upload_path.exists() else []

    if not all_images:
        yield json.dumps({"event": "error", "message": "No images found in this chat. Please upload an image first."})
        return

    current_image_names = {
        f for f in (current_files or [])
        if any(f.lower().endswith(ext) for ext in IMAGE_EXTENSIONS)
    }
    if current_image_names:
        focused = [img for img in all_images if img.name in current_image_names]
    else:
        focused = []

    images = focused if focused else all_images
    capped = images[:10]

    if focused:
        names = ", ".join(img.name for img in capped)
        focused_query = (
            f"The user just attached the following image(s) with this message: {names}.\n"
            f"Focus your answer on those image(s).\n\n"
            f"User question: {query}"
        )
    else:
        focused_query = query

    if len(capped) == 1:
        answer = await asyncio.to_thread(understand_image_from_file, capped[0], focused_query)
    else:
        answer = await asyncio.to_thread(understand_multiple_images, capped, focused_query)

    yield json.dumps({"event": "start", "pipeline": "vision"})
    yield json.dumps({"event": "delta", "delta": answer})
    yield json.dumps({"event": "done", "answer": answer})


async def _stream_pdf_vision(
    user_id: str,
    chat_id: str,
    query: str,
    page_num: int,
    *,
    current_files: list[str] | None = None,
):
    """PDF Vision is synchronous — emit the full answer as one chunk."""
    from app.vision_pipeline import understand_pdf_page

    upload_path = uploads_dir(user_id, chat_id)
    pdfs = [f for f in upload_path.iterdir() if f.suffix.lower() == ".pdf"] if upload_path.exists() else []

    if not pdfs:
        yield json.dumps({"event": "error", "message": "No PDFs found in this chat."})
        return

    current_pdf_names = {f for f in (current_files or []) if f.lower().endswith(".pdf")}
    target_pdf = next(
        (p for p in pdfs if p.name in current_pdf_names),
        max(pdfs, key=lambda f: f.stat().st_mtime),
    )

    focused_query = (
        f"The user just attached '{target_pdf.name}' and is asking about page {page_num}.\n\n"
        f"User question: {query}"
        if target_pdf.name in current_pdf_names
        else query
    )
    answer = await asyncio.to_thread(understand_pdf_page, target_pdf, page_num, focused_query)

    yield json.dumps({"event": "start", "pipeline": "pdf_vision"})
    yield json.dumps({"event": "delta", "delta": answer})
    yield json.dumps({
        "event": "done",
        "answer": answer,
        "citations": [{"source": target_pdf.name, "page": page_num}],
    })


# ── /multimodal/stream endpoint ────────────────────────────────────

@router.post("/multimodal/stream")
async def multimodal_stream(
    request: MultimodalRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Stream the multimodal response as Server-Sent Events."""
    user_id = user["user_id"]
    chat_id = request.chat_id
    query = request.query

    file_state = _chat_file_state(user_id, chat_id)
    all_files = set(list_uploads(user_id, chat_id))
    current_files = [f for f in (request.current_files or []) if f in all_files]

    from app.multimodal_router import route_query
    attached_hint = [{"filename": f} for f in current_files]
    routing = route_query(
        query,
        attached_files=attached_hint,
        chat_has_pdfs=file_state["pdfs"],
        chat_has_spreadsheets=file_state["spreadsheets"],
        chat_has_images=file_state["images"],
    )

    logger.info(
        "Multimodal stream routing: %s for query=%s current_files=%s",
        routing.pipeline, query[:80], current_files,
    )

    async def event_generator():
        try:
            if routing.pipeline == "pdf_rag":
                async for event in _stream_pdf_rag(
                    user_id, chat_id, query,
                    request.model_choice, request.temperature, request.max_output_tokens,
                    current_files=current_files,
                ):
                    yield f"data: {event}\n\n"

            elif routing.pipeline == "analytics":
                async for event in _stream_analytics(
                    user_id, chat_id, query,
                    request.model_choice, request.temperature,
                    current_files=current_files,
                ):
                    yield f"data: {event}\n\n"

            elif routing.pipeline == "vision":
                async for event in _stream_vision(user_id, chat_id, query, current_files=current_files):
                    yield f"data: {event}\n\n"

            elif routing.pipeline == "pdf_vision":
                target_page = routing.extra.get("target_page", 1)
                async for event in _stream_pdf_vision(
                    user_id, chat_id, query, target_page, current_files=current_files,
                ):
                    yield f"data: {event}\n\n"

            else:
                # Text fallback — empty start + immediate done so the frontend
                # can fall through to the normal /chat/stream pipeline.
                yield f"data: {json.dumps({'event': 'start', 'pipeline': 'text'})}\n\n"
                yield f"data: {json.dumps({'event': 'done', 'answer': ''})}\n\n"

        except Exception as e:
            logger.error("Multimodal stream error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
