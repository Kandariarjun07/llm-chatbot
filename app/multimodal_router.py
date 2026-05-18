"""Multimodal router — intelligent dispatch of queries to the correct pipeline.

Routes:
    text-only query         → existing text LLM pipeline
    query + PDF context     → per-chat RAG pipeline
    query + spreadsheet     → analytics pipeline (DuckDB/Polars)
    query + image           → Gemini Vision pipeline
    query about PDF image   → Gemini Vision (lazy page extraction)
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    pipeline: str  # "text" | "pdf_rag" | "analytics" | "vision" | "pdf_vision"
    reason: str
    file_type: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def trace(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "reason": self.reason,
            "file_type": self.file_type,
            **self.extra,
        }


# File extension → pipeline mapping
_EXT_MAP = {
    ".pdf": "pdf_rag",
    ".xlsx": "analytics",
    ".xls": "analytics",
    ".csv": "analytics",
    ".png": "vision",
    ".jpg": "vision",
    ".jpeg": "vision",
    ".gif": "vision",
    ".webp": "vision",
    ".bmp": "vision",
}

# Query patterns that indicate visual/image intent
_PAGE_IMAGE_PATTERN = re.compile(
    r"page\s+(\d+)|figure\s+(\d+)|diagram\s+(\d+)|chart\s+on\s+page\s+(\d+)",
    re.IGNORECASE,
)


def route_query(
    query: str,
    attached_files: list[dict[str, Any]] | None = None,
    chat_has_pdfs: bool = False,
    chat_has_spreadsheets: bool = False,
    chat_has_images: bool = False,
) -> RoutingDecision:
    """Determine which pipeline to route a query to."""
    attached_files = attached_files or []

    # 1. Check newly attached files
    for f in attached_files:
        filename = f.get("filename", "").lower()
        ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        pipeline = _EXT_MAP.get(ext)
        if pipeline:
            return RoutingDecision(
                pipeline=pipeline,
                reason=f"attached_file:{filename}",
                file_type=ext,
            )

    # 2. If images exist in chat, route to vision
    if chat_has_images:
        return RoutingDecision(
            pipeline="vision",
            reason="chat_has_images",
        )

    # 3. Check if user is asking about a specific page image in a PDF
    page_match = _PAGE_IMAGE_PATTERN.search(query)
    if page_match and chat_has_pdfs:
        page_num = next(int(g) for g in page_match.groups() if g is not None)
        return RoutingDecision(
            pipeline="pdf_vision",
            reason=f"page_image_query:page_{page_num}",
            file_type=".pdf",
            extra={"target_page": page_num},
        )

    # 4. Check for analytics-related queries when spreadsheet context exists
    if chat_has_spreadsheets:
        analytics_keywords = [
            "sum", "average", "mean", "total", "count", "max", "min",
            "group by", "filter", "sort", "top", "bottom", "trend",
            "sales", "revenue", "profit", "compare", "analyze",
            "chart", "graph", "plot", "visualize", "show me",
        ]
        query_lower = query.lower()
        if any(kw in query_lower for kw in analytics_keywords):
            return RoutingDecision(
                pipeline="analytics",
                reason="analytics_intent_with_spreadsheet",
                file_type=".xlsx",
            )

    # 5. If chat has PDFs — route to RAG
    if chat_has_pdfs:
        return RoutingDecision(
            pipeline="pdf_rag",
            reason="chat_has_pdf_context",
            file_type=".pdf",
        )

    # 6. Default: text pipeline
    return RoutingDecision(
        pipeline="text",
        reason="default_text_pipeline",
    )
