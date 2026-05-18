import logging
import functools
from typing import Any

logger = logging.getLogger(__name__)

@functools.lru_cache(maxsize=1)
def _get_encoder():
    """Lazily load the sentence-transformers model to save memory."""
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading sentence-transformers all-MiniLM-L6-v2...")
        # L6 is very fast and lightweight for re-ranking
        return SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        logger.warning("sentence-transformers not installed. Semantic reranking will be skipped.")
        return None
    except Exception as e:
        logger.error(f"Failed to load sentence-transformers: {e}")
        return None

def rerank_results(query: str, results: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
    """
    Rerank a list of search results against the original query using cosine similarity.
    Expects each result dict to have 'title' and 'body'.
    """
    if not results:
        return []
        
    encoder = _get_encoder()
    if not encoder:
        return results[:top_k]
        
    try:
        from sentence_transformers import util
        
        # Combine title and body for the context
        docs = [f"{r.get('title', '')} {r.get('body', '')}" for r in results]
        
        # Encode query and docs
        query_emb = encoder.encode(query, convert_to_tensor=True)
        doc_embs = encoder.encode(docs, convert_to_tensor=True)
        
        # Calculate cosine similarity
        cosine_scores = util.cos_sim(query_emb, doc_embs)[0]
        
        # Add scores to results
        for i, score in enumerate(cosine_scores):
            results[i]["score"] = float(score)
            
        # Sort by score descending
        ranked = sorted(results, key=lambda x: x.get("score", 0), reverse=True)
        return ranked[:top_k]
    except Exception as e:
        logger.error(f"Error during semantic reranking: {e}")
        return results[:top_k]
