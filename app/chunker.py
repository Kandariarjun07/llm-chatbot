"""Token-aware text chunker with overlap.

Creates chunks suitable for embedding and RAG retrieval.
Each chunk carries metadata for citation back to the source document.
"""

from typing import Any


def _estimate_tokens(text: str) -> int:
    """Rough token count: ~4 chars per token for English."""
    return max(1, len(text) // 4)


def chunk_text(
    pages: list[dict[str, Any]],
    *,
    doc_id: str,
    filename: str,
    chat_id: str,
    user_id: str,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> list[dict[str, Any]]:
    """Split page texts into overlapping chunks with metadata.

    Args:
        pages: List of page dicts from pdf_processor (must have 'page' and 'text').
        doc_id: Unique document identifier.
        filename: Original filename for citations.
        chat_id: Chat session ID (for scoped RAG).
        user_id: Owner user ID.
        chunk_size: Target chunk size in estimated tokens.
        chunk_overlap: Overlap between chunks in estimated tokens.

    Returns:
        List of chunk dicts: {chunk_id, text, metadata}
    """
    chunks: list[dict[str, Any]] = []
    chunk_idx = 0

    for page_info in pages:
        page_num = page_info["page"]
        text = page_info.get("text", "").strip()
        if not text:
            continue

        # Split text into sentences for better chunk boundaries
        sentences = _split_sentences(text)
        current_chunk: list[str] = []
        current_tokens = 0

        for sentence in sentences:
            sent_tokens = _estimate_tokens(sentence)

            if current_tokens + sent_tokens > chunk_size and current_chunk:
                # Emit current chunk
                chunk_text_str = " ".join(current_chunk)
                chunks.append({
                    "chunk_id": f"{doc_id}_c{chunk_idx}",
                    "text": chunk_text_str,
                    "metadata": {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "document_id": doc_id,
                        "page": page_num,
                        "source": filename,
                        "chunk_index": chunk_idx,
                        "method": page_info.get("method", "unknown"),
                    },
                })
                chunk_idx += 1

                # Keep overlap: retain last N tokens worth of sentences
                overlap_tokens = 0
                overlap_start = len(current_chunk)
                for i in range(len(current_chunk) - 1, -1, -1):
                    overlap_tokens += _estimate_tokens(current_chunk[i])
                    if overlap_tokens >= chunk_overlap:
                        overlap_start = i
                        break
                current_chunk = current_chunk[overlap_start:]
                current_tokens = sum(_estimate_tokens(s) for s in current_chunk)

            current_chunk.append(sentence)
            current_tokens += sent_tokens

        # Emit remaining text for this page
        if current_chunk:
            chunk_text_str = " ".join(current_chunk)
            chunks.append({
                "chunk_id": f"{doc_id}_c{chunk_idx}",
                "text": chunk_text_str,
                "metadata": {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "document_id": doc_id,
                    "page": page_num,
                    "source": filename,
                    "chunk_index": chunk_idx,
                    "method": page_info.get("method", "unknown"),
                },
            })
            chunk_idx += 1

    return chunks


def _split_sentences(text: str) -> list[str]:
    """Split text into rough sentence-level segments."""
    import re
    # Split on sentence-ending punctuation followed by space or newline
    raw = re.split(r'(?<=[.!?])\s+|\n{2,}', text)
    # Further split very long segments on newlines
    result = []
    for seg in raw:
        seg = seg.strip()
        if not seg:
            continue
        if _estimate_tokens(seg) > 300:
            # Split on single newlines too
            for sub in seg.split("\n"):
                sub = sub.strip()
                if sub:
                    result.append(sub)
        else:
            result.append(seg)
    return result
