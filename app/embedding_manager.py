"""Per-chat embedding manager with FAISS index.

Uses Gemini Embedding API (free tier, fast, no local model needed).
Falls back to sentence-transformers if Gemini key is unavailable.
Maintains one FAISS index per chat session.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Embedding via Gemini API (fast, no local model) ─────────────

_gemini_client = None
_GEMINI_EMBED_MODEL = "gemini-embedding-001"


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        try:
            from google import genai
            _gemini_client = genai.Client(api_key=api_key)
        except ImportError:
            return None
    return _gemini_client


def _get_faiss():
    try:
        import faiss
        return faiss
    except ImportError:
        raise RuntimeError("faiss-cpu is required. Run: pip install faiss-cpu")


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of texts into vectors using Gemini API."""
    client = _get_gemini_client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is required for embeddings.")

    # Gemini API accepts up to 100 texts per batch
    all_embeddings = []
    batch_size = 50
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = client.models.embed_content(
            model=_GEMINI_EMBED_MODEL,
            contents=batch,
        )
        for emb in result.embeddings:
            all_embeddings.append(emb.values)

    return np.array(all_embeddings, dtype="float32")


def embed_query(query: str) -> np.ndarray:
    """Embed a single query string."""
    return embed_texts([query])[0]


class ChatVectorStore:
    """FAISS-backed vector store scoped to a single chat session."""

    def __init__(self, vectors_path: Path):
        self.vectors_path = vectors_path
        self.index_file = vectors_path / "index.faiss"
        self.meta_file = vectors_path / "metadata.json"
        self._index = None
        self._metadata: list[dict[str, Any]] = []
        self._load()

    def _load(self):
        faiss = _get_faiss()
        if self.index_file.exists() and self.meta_file.exists():
            self._index = faiss.read_index(str(self.index_file))
            self._metadata = json.loads(self.meta_file.read_text(encoding="utf-8"))
            logger.info("Loaded FAISS index: %d vectors", self._index.ntotal)
        else:
            self._index = None
            self._metadata = []

    def add(self, chunks: list[dict[str, Any]]) -> int:
        """Add chunks to the index.

        Each chunk must have 'text' and 'metadata' keys.
        Returns the number of vectors added.
        """
        if not chunks:
            return 0

        faiss = _get_faiss()
        texts = [c["text"] for c in chunks]
        embeddings = embed_texts(texts)
        dim = embeddings.shape[1]

        if self._index is None:
            self._index = faiss.IndexFlatIP(dim)  # Inner product (cosine after normalization)

        # Normalize for cosine similarity
        faiss.normalize_L2(embeddings)
        self._index.add(embeddings)

        for chunk in chunks:
            self._metadata.append({
                "chunk_id": chunk.get("chunk_id", ""),
                "text": chunk["text"],
                **chunk.get("metadata", {}),
            })

        self._save()
        return len(texts)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Search the index for the most relevant chunks."""
        if self._index is None or self._index.ntotal == 0:
            return []

        faiss = _get_faiss()
        query_vec = embed_query(query).reshape(1, -1)
        faiss.normalize_L2(query_vec)

        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(query_vec, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            meta = dict(self._metadata[idx])
            meta["score"] = float(score)
            results.append(meta)

        return results

    def _save(self):
        faiss = _get_faiss()
        self.vectors_path.mkdir(parents=True, exist_ok=True)
        if self._index is not None:
            faiss.write_index(self._index, str(self.index_file))
        self.meta_file.write_text(
            json.dumps(self._metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @property
    def count(self) -> int:
        return self._index.ntotal if self._index else 0

    def clear(self):
        """Remove all vectors."""
        self._index = None
        self._metadata = []
        if self.index_file.exists():
            self.index_file.unlink()
        if self.meta_file.exists():
            self.meta_file.unlink()
