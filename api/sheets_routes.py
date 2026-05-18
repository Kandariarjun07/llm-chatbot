"""Sheets workspace — natural-language Excel/CSV querying for non-SQL users.

Design choices (per user request):
- **One active spreadsheet per user** — uploading replaces the previous file.
  Disk footprint per user stays at ~5–10 MB (source + parquet + meta.json).
- **Schema-only context to the LLM** — the model sees columns, dtypes,
  row count, and summary stats. Never the raw rows. This is the same
  privacy/efficiency pattern used by ``_handle_analytics``.
- **Export streams; never persists** — Download-as-Excel writes to a temp
  file, streams it back, then deletes it. No download history on disk.

Endpoints:
    POST   /sheets/upload      Replace the active sheet (.xlsx, .xls, .csv).
    GET    /sheets/current     Schema, stats, sample rows of the active sheet.
    POST   /sheets/query       NL question → SQL via LLM → result rows.
    POST   /sheets/export      NL question → SQL → streamed .xlsx download.
    POST   /sheets/export-csv  NL question → SQL → streamed .csv download.
    DELETE /sheets/current     Wipe the user's sheets workspace.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from api.auth_routes import get_current_user
from app.excel_processor import (
    convert_to_parquet,
    execute_to_dataframe,
    export_query_to_excel,
    parse_spreadsheet,
    select_chart_type,
    validate_sql,
)
from app.rate_limits import RateLimit
from app.workspace import reset_sheets_dir, sheets_dir
from llm.client import chat_completion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sheets", tags=["sheets"])

_SHEETS_SYSTEM_PROMPT = """You are an expert AI Data Analyst. Your sole job is to translate a user's natural-language question into a single, valid DuckDB SELECT query.

RULES (strict — never violate):
- Output ONLY the SQL query. No prose, no markdown fences, no JSON, no explanations.
- It MUST be exactly one SELECT statement. No DDL/DML (no CREATE, DROP, INSERT, UPDATE, DELETE).
- Use ONLY column names that exist in the provided schema.
- Quote column names containing spaces or special chars with double-quotes, e.g. "Employee ID".
- Prefer aggregates / GROUP BY for counts, averages, totals, etc.
- Add LIMIT only when the user explicitly asks for "top N" / "first N".
- If the question implies a chart (bar, pie, line, scatter, area, histogram), write SQL that returns the right shape:
  • pie / bar  → one categorical column + one numeric aggregate
  • line       → ordered categories / time + one or more numeric values
  • scatter    → two or more numeric columns
  • histogram  → one numeric column (optionally binned via ROUND/FLOOR/CAST)
- If the request is impossible with the available columns, output exactly: -- IMPOSSIBLE: <reason>
- Never hallucinate tables, columns, or values."""

# ── Limits ───────────────────────────────────────────────────────
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB — same as /upload
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
META_FILENAME = "meta.json"
PARQUET_FILENAME = "data.parquet"
PREVIEW_ROW_CAP = 100      # rows shown in /query response
EXPORT_ROW_CAP = 100_000   # safety cap for /export


# ── Schema / response models ─────────────────────────────────────

class SheetMeta(BaseModel):
    filename: str
    row_count: int
    column_count: int
    columns: list[str]
    schema_: list[dict[str, Any]] = Field(alias="schema")
    statistics: dict[str, dict[str, float]]
    sample_rows: list[dict[str, Any]]

    class Config:
        populate_by_name = True


class QueryBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    model_choice: str = "Llama"


class QueryResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    summary: str | None = None
    chart: dict[str, Any] | None = None


class SuggestionsResponse(BaseModel):
    suggestions: list[str]


# ── Internal helpers ─────────────────────────────────────────────

def _source_file(user_id: str) -> Path | None:
    """Return the user's active spreadsheet on disk, if any."""
    d = sheets_dir(user_id)
    for ext in ALLOWED_EXTENSIONS:
        p = d / f"source{ext}"
        if p.exists():
            return p
    return None


def _parquet_file(user_id: str) -> Path:
    return sheets_dir(user_id) / PARQUET_FILENAME


def _meta_file(user_id: str) -> Path:
    return sheets_dir(user_id) / META_FILENAME


def _load_meta(user_id: str) -> dict[str, Any] | None:
    mf = _meta_file(user_id)
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load meta for %s: %s", user_id, e)
        return None


def _clean_sql(raw: str, columns: list[str] | None = None) -> str:
    """Strip code fences / language tags an LLM may add around SQL.

    If ``columns`` is supplied, bare occurrences of column names that
    contain spaces are wrapped in double-quotes (DuckDB requirement).
    """
    sql = raw.strip()
    if sql.startswith("```"):
        # Drop opening fence (and optional language tag)
        sql = re.sub(r"^```[a-zA-Z]*\s*", "", sql)
    if sql.endswith("```"):
        sql = sql[: -3]
    sql = sql.strip().rstrip(";")

    if columns:
        sql = _quote_known_columns(sql, columns)
    return sql


def _quote_known_columns(sql: str, columns: list[str]) -> str:
    """Wrap bare occurrences of known column names (with spaces) in quotes.

    Surgical replacement based on the actual schema — much safer than a
    generic tokenizer because we only touch identifiers we KNOW exist.

    For each column name containing whitespace or special characters,
    we replace bare occurrences (not preceded or followed by a word
    character or a double-quote) with the double-quoted form.
    """
    out = sql
    # Longest first so "Employee ID" is processed before "ID" (avoids
    # partial replacement collisions).
    for col in sorted(columns, key=len, reverse=True):
        if not re.search(r"[\s\W]", col) or col.isalnum():
            # Safe identifier — DuckDB doesn't need it quoted.
            continue
        # Match `col` only when NOT inside a quoted string/identifier and
        # NOT part of a larger word. Exclusions on either side:
        #   \w  → no adjacent letters/digits/underscore (so "name" inside
        #         "username" is not matched)
        #   "   → already a quoted identifier
        #   '   → inside a single-quoted string literal (e.g. WHERE x = 'First Name')
        pattern = r'(?<![\w"\'])' + re.escape(col) + r'(?![\w"\'])'
        out = re.sub(pattern, f'"{col}"', out)
    return out


def _build_sql_prompt(question: str, meta: dict[str, Any]) -> str:
    """Build the schema-only prompt sent to the LLM."""
    schema_lines = [
        f"  - {c['column']} ({c['dtype']}, non_null={c['non_null_count']})"
        for c in meta.get("schema", [])
    ]
    stats_blob = (
        json.dumps(meta.get("statistics", {}), indent=2, default=str)
        if meta.get("statistics") else "(no numeric columns)"
    )
    sample_blob = json.dumps(meta.get("sample_rows", [])[:3], indent=2, default=str)

    return f"""You are a SQL analyst. Translate the user's question into a single DuckDB SELECT query.

Table name: data
Columns:
{chr(10).join(schema_lines)}

Total rows: {meta.get('row_count', 0)}

Numeric column statistics:
{stats_blob}

Sample rows (for column-content hints only — do NOT assume these are representative):
{sample_blob}

User question: {question}

RULES (strict):
- Output ONLY a SQL query — no prose, no markdown, no code fences.
- It MUST be a single SELECT statement. No DDL / DML / multiple statements.
- Use exact column names as listed above.
- **CRITICAL**: If a column name contains spaces or special characters,
  wrap it in double-quotes, e.g. "Employee ID", "First Name".
  DuckDB is case-sensitive for quoted identifiers.
- Prefer aggregates / GROUP BY for "how many", "average", "total", etc.
- Filter aggressively when the user describes conditions ("where ...", "with ID ...").
- Do NOT add LIMIT unless the user asks for "top N" / "first N" — the caller
  caps results separately.

SQL:"""


async def _llm_sql(question: str, meta: dict[str, Any], model_choice: str) -> str:
    """Ask the LLM for a SQL query and return the cleaned string.

    Always routes through Groq with llama-3.3-70b-versatile for Sheets queries
    so we get the best SQL generation quality regardless of the user's chat
    model choice.
    """
    prompt = _build_sql_prompt(question, meta)
    raw = await asyncio.to_thread(
        chat_completion,
        [{"role": "user", "content": prompt}],
        model_choice="Llama",
        temperature=0.0,
        max_output_tokens=512,
        system=_SHEETS_SYSTEM_PROMPT,
        model="llama-3.3-70b-versatile",
    )
    columns = list(meta.get("columns", []))
    sql = _clean_sql(raw or "", columns=columns)
    if not sql:
        raise HTTPException(
            status_code=400,
            detail="I couldn't translate that question into a query. Try rephrasing — e.g. "
                   "\"show rows where Age > 30\" or \"average salary by department\".",
        )
    ok, reason = validate_sql(sql)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="This type of question can't be answered safely — only read-only "
                   "queries are allowed (no edits, deletes, or schema changes). "
                   "Try asking to filter, count, or summarise rows instead.",
        )
    return sql


async def _llm_summary(
    question: str,
    sql: str,
    sample_rows: list[dict[str, Any]],
    row_count: int,
    model_choice: str,
    aggregates: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Optional natural-language summary of the result for non-technical users.

    Critical distinction the prompt has to teach the model:
        - An *aggregate* result (e.g. ``COUNT``, ``SUM``, ``AVG``) always
          returns exactly **one row** whose VALUES are the actual answer.
        - A *listing* result returns many rows that ARE the answer.

    Additionally, when ``aggregates`` is provided (computed on the FULL
    result, not just the sample), the prompt feeds them in as ground
    truth so the LLM doesn't extrapolate ranges from the 5 sample rows.
    """
    if not sample_rows:
        return "No rows matched your question."

    # Single-row result with only numeric values → almost certainly an aggregate.
    is_aggregate = (
        row_count == 1
        and len(sample_rows) == 1
        and all(isinstance(v, (int, float)) or v is None for v in sample_rows[0].values())
    )

    if is_aggregate:
        kv = ", ".join(f"{k} = {v}" for k, v in sample_rows[0].items())
        prompt = f"""The user asked: {question}

The query returned a single aggregate result: {kv}

Write ONE short sentence (max 20 words) that answers the question directly
using that value. Do NOT mention "1 row" or "rows returned" — for aggregate
queries the row count is always 1, that's not informative.

Answer:"""
    else:
        agg_blob = _format_aggregates_for_prompt(aggregates) if aggregates else ""
        prompt = f"""The user asked: {question}

SQL executed: {sql}
Total rows in result: {row_count}

{agg_blob}First 5 sample rows (illustrative ONLY — do NOT use these to infer ranges):
{json.dumps(sample_rows[:5], indent=2, default=str)}

Write ONE or TWO short sentences (max 35 words) summarising the result for
a non-technical user.

STRICT RULES:
- For ANY numeric statement (min, max, average, range, "from X to Y"), use
  ONLY the column statistics block above. NEVER infer numeric ranges from
  the sample rows.
- If a statistic isn't listed, do NOT make claims about it.
- Mention the total row count when useful, but do not pad with filler.

Summary:"""

    try:
        text = await asyncio.to_thread(
            chat_completion,
            [{"role": "user", "content": prompt}],
            model_choice="Llama",
            temperature=0.1,
            max_output_tokens=160,
            model="llama-3.3-70b-versatile",
        )
        return (text or "").strip()
    except Exception as e:
        logger.warning("Summary generation failed: %s", e)
        return ""


def _compute_result_aggregates(df) -> dict[str, dict[str, Any]]:
    """Compute per-column aggregates on the FULL query result.

    Returns a dict keyed by column name:
        - numeric column → {"min", "max", "mean", "null_count"}
        - other column   → {"distinct_count", "null_count", "top_value"}

    Used as ground truth for the summary LLM so it stops extrapolating
    ranges from sample rows.
    """
    try:
        import polars as pl
    except ImportError:
        return {}

    if df is None or len(df) == 0:
        return {}

    out: dict[str, dict[str, Any]] = {}
    numeric_dtypes = (
        pl.Float64, pl.Float32,
        pl.Int64, pl.Int32, pl.Int16, pl.Int8,
        pl.UInt64, pl.UInt32, pl.UInt16, pl.UInt8,
    )

    for col in df.columns:
        try:
            series = df[col]
            null_count = int(series.null_count())
            non_null = series.drop_nulls()
            if len(non_null) == 0:
                out[col] = {"null_count": null_count, "all_null": True}
                continue

            if series.dtype in numeric_dtypes:
                out[col] = {
                    "min": _to_py_scalar(non_null.min()),
                    "max": _to_py_scalar(non_null.max()),
                    "mean": _to_py_scalar(non_null.mean()),
                    "null_count": null_count,
                }
            elif series.dtype == pl.Date or series.dtype == pl.Datetime:
                out[col] = {
                    "min": str(non_null.min()),
                    "max": str(non_null.max()),
                    "null_count": null_count,
                }
            else:
                # categorical / string — count distinct + most common value
                distinct = int(non_null.n_unique())
                top_value: Any = None
                try:
                    vc = non_null.value_counts(sort=True)
                    if len(vc) > 0:
                        top_value = _to_py_scalar(vc[col][0])
                except Exception:
                    pass
                out[col] = {
                    "distinct_count": distinct,
                    "null_count": null_count,
                    "top_value": top_value,
                }
        except Exception as e:
            # Best-effort — never let aggregate computation break the response.
            logger.debug("Aggregate failed for column %s: %s", col, e)
            continue

    return out


def _to_py_scalar(v: Any) -> Any:
    """Convert a Polars/Arrow scalar to a plain Python type for JSON."""
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    # Polars sometimes returns numpy scalars or Decimal — coerce.
    try:
        if hasattr(v, "item"):
            return v.item()
    except Exception:
        pass
    return str(v)


def _format_aggregates_for_prompt(aggregates: dict[str, dict[str, Any]]) -> str:
    """Render aggregates as a compact prompt-friendly block."""
    if not aggregates:
        return ""
    lines = ["Column statistics (computed on the FULL result — use these for any numeric claims):"]
    for col, agg in aggregates.items():
        parts: list[str] = []
        if "min" in agg and "max" in agg:
            parts.append(f"min={agg['min']}, max={agg['max']}")
        if "mean" in agg and agg.get("mean") is not None:
            mean = agg["mean"]
            parts.append(f"mean={mean:.2f}" if isinstance(mean, float) else f"mean={mean}")
        if "distinct_count" in agg:
            parts.append(f"distinct={agg['distinct_count']}")
        if "top_value" in agg and agg.get("top_value") is not None:
            parts.append(f"most_common={agg['top_value']!r}")
        if agg.get("null_count"):
            parts.append(f"nulls={agg['null_count']}")
        if parts:
            lines.append(f"  - {col}: {', '.join(parts)}")
    return "\n".join(lines) + "\n\n"


# ── Routes ───────────────────────────────────────────────────────

@router.post("/upload", response_model=SheetMeta, dependencies=[Depends(RateLimit("sheets.upload", per_minute=15, per_day=60))])
async def upload_sheet(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(get_current_user),
) -> SheetMeta:
    """Replace the user's active spreadsheet.

    Old files are deleted first so disk usage stays bounded to ~one
    spreadsheet per user (source + parquet + meta.json).
    """
    user_id = user["user_id"]
    filename = file.filename or "upload"
    ext = ("." + filename.rsplit(".", 1)[-1]).lower() if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB).")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    # Fresh workspace — purges any previous spreadsheet for this user.
    d = reset_sheets_dir(user_id)
    source_path = d / f"source{ext}"
    source_path.write_bytes(content)

    # Parse + convert + cache schema. Sync because the existing helpers
    # are not async; offload to a thread to keep the event loop free.
    def _process() -> dict[str, Any]:
        meta = parse_spreadsheet(source_path)
        convert_to_parquet(source_path, d)
        # parse_spreadsheet writes the parquet to f"{stem}.parquet" — rename
        # to the canonical name so query/export can find it deterministically.
        produced = d / f"{source_path.stem}.parquet"
        target = d / PARQUET_FILENAME
        if produced.exists() and produced != target:
            if target.exists():
                target.unlink()
            produced.rename(target)
        meta_with_filename = {**meta, "filename": filename}
        _meta_file(user_id).write_text(
            json.dumps(meta_with_filename, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return meta_with_filename

    try:
        meta = await asyncio.to_thread(_process)
    except Exception as e:
        logger.error("Sheet processing failed: %s", e, exc_info=True)
        # Clean up partial state so the user doesn't see a broken half-upload.
        reset_sheets_dir(user_id)
        raise HTTPException(status_code=400, detail=f"Failed to read spreadsheet: {e}")

    return SheetMeta(**meta)


@router.get("/current", response_model=SheetMeta | None, dependencies=[Depends(RateLimit("sheets.read", per_minute=120))])
def get_current_sheet(user: dict[str, Any] = Depends(get_current_user)) -> SheetMeta | None:
    """Return the active sheet's schema, or null if no sheet is loaded."""
    meta = _load_meta(user["user_id"])
    if not meta:
        return None
    return SheetMeta(**meta)


@router.get("/suggestions", response_model=SuggestionsResponse, dependencies=[Depends(RateLimit("sheets.read", per_minute=60))])
async def get_suggestions(user: dict[str, Any] = Depends(get_current_user)) -> SuggestionsResponse:
    """Return LLM-generated natural-language query suggestions tailored to the current sheet."""
    user_id = user["user_id"]
    meta = _load_meta(user_id)
    if not meta:
        return SuggestionsResponse(suggestions=[])

    columns = meta.get("columns", [])
    sample_rows = meta.get("sample_rows", [])[:3]
    row_count = meta.get("row_count", 0)
    filename = meta.get("filename", "spreadsheet")

    prompt = f"""You are a helpful data analyst. Given the following spreadsheet metadata, generate 6 to 8 natural-language query suggestions that a non-technical user might ask to explore this data.

Spreadsheet: {filename}
Rows: {row_count}
Columns: {', '.join(columns)}
Sample rows:
{json.dumps(sample_rows, indent=2, default=str)}

Rules:
- Each suggestion must be a single, concise sentence in English.
- Include a mix: simple lookups, aggregations (sum, count, average), filtering, sorting, and chart/visualization requests (bar chart, pie chart, line chart, scatter plot).
- Do NOT use column names that don't exist in the list above.
- Respond with ONLY a numbered list, one suggestion per line. No preamble, no explanation.

Example format:
1. Show the first 20 rows
2. How many total records are there?
3. Bar chart of total sales by region
"""

    messages = [{"role": "user", "content": prompt}]
    try:
        raw = await asyncio.to_thread(
            chat_completion, messages, "Llama", temperature=0.7,
            model="llama-3.3-70b-versatile",
        )
    except Exception as e:
        logger.warning("LLM suggestions failed: %s", e)
        return SuggestionsResponse(suggestions=[])

    suggestions: list[str] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading numbering like "1. " or "- "
        if len(line) > 2 and line[0].isdigit() and line[1] == '.':
            line = line[2:].strip()
        elif line.startswith('-'):
            line = line[1:].strip()
        if line:
            suggestions.append(line)

    # Deduplicate and cap
    seen = set()
    unique = []
    for s in suggestions:
        lower = s.lower()
        if lower not in seen and len(unique) < 8:
            seen.add(lower)
            unique.append(s)

    return SuggestionsResponse(suggestions=unique)


@router.post("/query", response_model=QueryResponse, dependencies=[Depends(RateLimit("sheets.query", per_minute=20, per_day=300))])
async def query_sheet(
    body: QueryBody,
    user: dict[str, Any] = Depends(get_current_user),
) -> QueryResponse:
    """Translate the user's natural-language question into SQL and run it."""
    user_id = user["user_id"]
    meta = _load_meta(user_id)
    pq = _parquet_file(user_id)
    if not meta or not pq.exists():
        raise HTTPException(status_code=404, detail="No active spreadsheet. Upload one first.")

    sql = await _llm_sql(body.question, meta, body.model_choice)

    try:
        df = await asyncio.to_thread(execute_to_dataframe, pq, sql)
    except ValueError as e:
        # validate_sql failure → safe to expose
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Query execution failed: %s\nSQL: %s", e, sql, exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=(
                "I couldn't run that query on your spreadsheet. The question might be "
                "ambiguous, reference columns that don't exist, or ask for something the "
                "data doesn't support. Try rephrasing — e.g. specify exact column names "
                "or simpler conditions."
            ),
        )

    total = len(df)
    columns = list(df.columns)
    # Compute aggregates on the FULL result (cheap with Polars) BEFORE we
    # truncate to the preview cap — otherwise stats would be wrong.
    aggregates = _compute_result_aggregates(df)
    rows = df.head(PREVIEW_ROW_CAP).to_dicts()
    summary = await _llm_summary(
        body.question, sql, rows, total, body.model_choice,
        aggregates=aggregates,
    )

    chart_config = select_chart_type(columns, rows, body.question)

    return QueryResponse(
        sql=sql,
        columns=columns,
        rows=rows,
        row_count=total,
        truncated=total > len(rows),
        summary=summary or None,
        chart=chart_config if chart_config.get("type") != "none" else None,
    )


class ExportBody(BaseModel):
    question: str | None = Field(default=None, max_length=2000)
    # Allow passing a pre-computed SQL string so the user can re-download the
    # exact preview they just inspected without re-asking the LLM.
    sql: str | None = Field(default=None, max_length=10_000)
    model_choice: str = "Llama"


@router.post("/export", dependencies=[Depends(RateLimit("sheets.export", per_minute=15, per_day=100))])
async def export_sheet(
    body: ExportBody,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Run a query and stream the result back as a fresh .xlsx file.

    Either ``sql`` (preferred — re-uses the query the user already saw) or
    ``question`` must be provided. The generated file is deleted immediately
    after streaming so nothing is persisted on the server.
    """
    if not body.sql and not body.question:
        raise HTTPException(status_code=400, detail="Provide either 'sql' or 'question'.")

    user_id = user["user_id"]
    meta = _load_meta(user_id)
    pq = _parquet_file(user_id)
    if not meta or not pq.exists():
        raise HTTPException(status_code=404, detail="No active spreadsheet. Upload one first.")

    columns = list(meta.get("columns", []))
    sql = (
        _clean_sql(body.sql, columns=columns)
        if body.sql
        else await _llm_sql(body.question or "", meta, body.model_choice)
    )
    ok, reason = validate_sql(sql)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="This query can't be exported — only read-only SELECTs are allowed.",
        )

    # Stream-friendly temp file. NamedTemporaryFile with delete=False lets
    # FastAPI re-open it; the BackgroundTask cleans it up after the body
    # has been fully sent to the client.
    tmp = tempfile.NamedTemporaryFile(prefix="sheet_export_", suffix=".xlsx", delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)

    source_xlsx = _source_file(user_id)

    def _run_export() -> dict[str, Any]:
        info = export_query_to_excel(pq, sql, tmp_path, source_xlsx=source_xlsx)
        if info["row_count"] > EXPORT_ROW_CAP:
            raise ValueError(
                f"Result has {info['row_count']} rows which exceeds the export cap "
                f"({EXPORT_ROW_CAP}). Narrow your filter and try again."
            )
        return info

    try:
        info = await asyncio.to_thread(_run_export)
    except ValueError as e:
        # Row-cap or validate_sql — safe to surface verbatim.
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        logger.error("Export failed: %s\nSQL: %s", e, sql, exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=(
                "Couldn't generate the Excel export for that query. Try running it as a "
                "preview first to make sure it works, then download."
            ),
        )

    # Derive a friendly download name from the source filename.
    source_stem = Path(meta.get("filename", "result")).stem
    download_name = f"{source_stem}_filtered.xlsx"

    # HTTP headers must be ASCII and single-line. Sanitise the SQL preview
    # so a multi-line query can't break the response.
    sql_header = re.sub(r"\s+", " ", sql)[:500]
    sql_header = sql_header.encode("ascii", errors="ignore").decode("ascii")

    return FileResponse(
        path=tmp_path,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "X-Sheet-Rows": str(info["row_count"]),
            "X-Sheet-Columns": str(info["column_count"]),
            "X-Sheet-SQL": sql_header,
        },
        # Single-shot cleanup that runs only after the file body has been
        # fully streamed. Using starlette's BackgroundTask (singular)
        # avoids double-registering with FastAPI's BackgroundTasks collection.
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )


@router.post("/export-csv", dependencies=[Depends(RateLimit("sheets.export", per_minute=15, per_day=100))])
async def export_csv(
    body: ExportBody,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Run a query and stream the result back as a fresh .csv file."""
    user_id = user["user_id"]
    meta = _load_meta(user_id)
    pq = _parquet_file(user_id)
    if not meta or not pq.exists():
        raise HTTPException(status_code=404, detail="No active spreadsheet. Upload one first.")

    sql = body.sql
    if not sql:
        schema_str = _format_schema_for_prompt(meta)
        sql = await _generate_sql(body.question or "", schema_str, user_id, body.model_choice)
    sql = _clean_sql(sql)

    df, info = await asyncio.to_thread(
        execute_to_dataframe,
        pq,
        sql,
        limit=None,
    )

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(df.columns.tolist())
    for row in df.to_numpy():
        writer.writerow(row.tolist())
    buf.seek(0)

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", meta["filename"].rsplit(".", 1)[0])[:40]
    download_name = f"{safe_name}_export.csv"

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "X-Sheet-Rows": str(info["row_count"]),
            "X-Sheet-Columns": str(info["column_count"]),
            "X-Sheet-SQL": sql[:512],
        },
    )


@router.delete("/current", dependencies=[Depends(RateLimit("sheets.delete", per_minute=10))])
def delete_sheet(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    """Wipe the user's sheets workspace."""
    reset_sheets_dir(user["user_id"])
    return {"status": "deleted"}
