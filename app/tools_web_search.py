"""Async web search tools using DuckDuckGo via the ddgs library."""

from typing import Any

import asyncio
import json
import logging
import threading
import time
from datetime import date

from app.reranker import rerank_results
from llm.client import chat_completion


logger = logging.getLogger(__name__)


def _extract_fields(r: dict) -> dict[str, str] | None:
    """Pull title/body/source from a ddgs result dict."""
    title = r.get("title", "")
    body = r.get("body") or r.get("snippet") or r.get("abstract") or r.get("summary") or ""
    if not body and title:
        body = title
    if not body:
        return None
    source = r.get("href") or r.get("url") or r.get("source") or "web"
    date = r.get("date") or r.get("published") or ""
    if date:
        body = f"[{date}] {body}"
    return {"title": title, "body": body, "source": source}


async def interpret_search_intent(
    user_query: str,
    model_choice: str = "Llama",
    *,
    deep: bool = False,
) -> list[str]:
    """
    Rewrite a vague or conversational user query into diversified search variants.

    Diversification strategy hits different *tiers* of sources rather than just
    rephrasing — official docs, community discussion, benchmarks, and recent
    coverage each surface different pages.

    Args:
        deep: when True, returns 5 variants tuned for deep research; otherwise 3.
    """
    current_year = date.today().year
    n_variants = 5 if deep else 3

    if deep:
        diversification = f"""Generate exactly 5 distinct queries, each targeting a *different source tier*:
1. Broad overview — direct, high-level phrasing for general web results
2. Official / authoritative — append qualifiers like "official documentation", "github", "spec", or vendor names to surface tier-1 sources
3. Community / practitioner — append qualifiers like "reddit", "hacker news", "stackoverflow", or "site:reddit.com" to surface real-world experiences
4. Benchmarks / comparisons — phrase as comparison/benchmark/review and include "vs", "benchmark", or "comparison" if the topic supports it
5. Recent / time-sensitive — append "{current_year}" and "latest" so fresh pages rank higher
"""
    else:
        diversification = f"""Generate exactly 3 distinct queries, each targeting a *different source tier*:
1. Broad overview — direct, high-level phrasing
2. Official / authoritative — append qualifiers like "official documentation", "github", or vendor names to surface tier-1 sources
3. Community / practitioner — append qualifiers like "reddit", "stackoverflow", or "{current_year}" to surface fresh real-world discussion
"""

    prompt = f"""You are a search query optimizer. Rewrite the user's query into precise, diversified web search queries.

{diversification}
Hard rules:
- Each query must be standalone and search-engine ready (no filler, no question marks unless natural).
- If the query is about current events, news, prices, releases, or "latest X", include "{current_year}" or "latest" in at least one variant.
- If the user names a specific product, library, or company, preserve that exact name in every variant.
- Return ONLY a valid JSON array of {n_variants} strings. No markdown fences, no commentary.

User query: {user_query}
Search queries:"""

    try:
        rewritten = await asyncio.to_thread(
            chat_completion,
            [{"role": "user", "content": prompt}],
            model_choice=model_choice,
            temperature=0.2,
            max_output_tokens=250 if deep else 150,
        )
        if not rewritten or rewritten.startswith("Error:"):
            return [user_query]
        
        # Clean potential markdown wrapping
        cleaned = rewritten.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        cleaned = cleaned.strip()
        if not cleaned.startswith("["):
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]
            
        queries = json.loads(cleaned)
        if isinstance(queries, list) and len(queries) > 0:
            cleaned_queries = [str(q).strip() for q in queries[:n_variants] if str(q).strip()]
            return cleaned_queries or [user_query]
        return [user_query]
    except Exception as exc:
        logger.warning("Search intent rewrite failed: %s", exc)
        return [user_query]


def _is_search_low_quality(results: list[dict[str, Any]], min_results: int = 2, min_total_chars: int = 300) -> bool:
    """Check if search results are too thin to be useful."""
    if len(results) < min_results:
        return True
    total_body = sum(len(r.get("body", "")) for r in results)
    return total_body < min_total_chars


# Simple in-memory cache for repeated identical queries.
# Each entry is (results, expires_at_monotonic). Without a TTL the cache
# would happily serve hour-old news as "fresh" search results.
_search_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
_search_cache_lock = threading.RLock()
_SEARCH_CACHE_TTL_SECONDS = 600  # 10 minutes
# Hard upper bound for any single DDGS query. DDGS occasionally hangs on
# rate-limit responses without raising; this prevents one bad query from
# blocking a worker thread indefinitely.
_DDGS_QUERY_TIMEOUT_SECONDS = 12.0


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    with _search_cache_lock:
        entry = _search_cache.get(key)
        if not entry:
            return None
        results, expires_at = entry
        if time.monotonic() >= expires_at:
            _search_cache.pop(key, None)
            return None
        return [dict(item) for item in results]


def _cache_set(key: str, value: list[dict[str, Any]]) -> None:
    with _search_cache_lock:
        _search_cache[key] = (
            [dict(item) for item in value],
            time.monotonic() + _SEARCH_CACHE_TTL_SECONDS,
        )


async def _fetch_ddgs(query: str, limit: int) -> list[dict[str, Any]]:
    """Helper to run synchronous ddgs text search in a thread pool."""
    def run_sync():
        try:
            from ddgs import DDGS
            ddgs = DDGS()
            return list(ddgs.text(query, max_results=limit))
        except Exception as exc:
            logger.warning("DDGS search failed for query %r: %s", query, exc)
            return []

    logger.info("web_search_query=%s limit=%s", query, limit)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(run_sync),
            timeout=_DDGS_QUERY_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("DDGS search timed out for query %r after %ss", query, _DDGS_QUERY_TIMEOUT_SECONDS)
        return []

async def async_web_search(queries: str | list[str], max_results: int = 5, deep: bool = False, original_query: str = "") -> list[dict[str, Any]]:
    """
    Search the web async via DuckDuckGo and return top result snippets.
    Executes multiple queries in parallel.
    """
    if isinstance(queries, str):
        query_list = [queries]
    else:
        query_list = [str(query).strip() for query in queries if str(query).strip()]

    if not query_list:
        return []

    cache_key = json.dumps(
        {
            "queries": sorted(query_list),
            "max_results": max_results,
            "deep": deep,
            "original_query": original_query,
        },
        sort_keys=True,
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Distribute limits
    limit_per_query = max(2, (max_results if not deep else max(10, max_results)) // len(query_list))
    
    # Run searches concurrently
    tasks = [_fetch_ddgs(q, limit_per_query) for q in query_list]
    raw_results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    seen_urls = set()

    # Flatten and deduplicate
    for raw_list in raw_results_lists:
        if isinstance(raw_list, Exception):
            logger.warning("DDGS task failed: %s", raw_list)
            continue
        for r in raw_list:
            extracted = _extract_fields(r)
            if extracted and extracted["source"] not in seen_urls:
                seen_urls.add(extracted["source"])
                results.append(
                    {
                        "title": extracted["title"],
                        "body": extracted["body"],
                        "source": extracted["source"],
                        "backend": "web_search",
                        "score": 1.0,
                    }
                )

    # Auto deep-search: if total pooled results are thin
    if not deep and _is_search_low_quality(results):
        deep_results = await async_web_search(query_list, max_results=max_results, deep=True, original_query=original_query)
        if len(deep_results) > len(results):
            results = deep_results

    # Rerank against original query if provided
    if original_query and results:
        results = await asyncio.to_thread(rerank_results, original_query, results, top_k=max_results)

    results = results[:max_results]
    _cache_set(cache_key, results)
    return results
