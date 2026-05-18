"""Provider registry and tiered multi-engine aggregator.

Tiering strategy:
- *Standard search* prefers paid tier-1 (Brave) for ranking + snippet quality;
  falls back to free tier (DDG) when Brave is unavailable or returns thin
  results. DDG diversification compensates for index gaps.
- *Deep research* runs paid tier-1 (Brave + Tavily) in parallel for breadth +
  Tavily's full-page extraction; falls back to free tier on quota exhaustion.
- Bing is treated as an additional paid tier-1 source when configured.

This keeps the normal-path latency low (one provider) and saves Tavily quota
for research queries that actually benefit from full-page extraction.
"""

import asyncio
import copy
import hashlib
import json
import logging
import threading
import time
from typing import Any

from app.reranker import rerank_results
from app.search_providers._base import SearchProvider, SearchResult
from app.search_providers.bing_provider import BingProvider
from app.search_providers.brave_provider import BraveProvider
from app.search_providers.ddgs_provider import DuckDuckGoProvider
from app.search_providers.hn_provider import HackerNewsProvider
from app.search_providers.reddit_provider import RedditProvider
from app.search_providers.serper_provider import SerperProvider
from app.search_providers.stackexchange_provider import StackExchangeProvider
from app.search_providers.tavily_provider import TavilyProvider
from app.search_providers.wikipedia_provider import WikipediaProvider


logger = logging.getLogger(__name__)

_ALL_PROVIDERS: list[type[SearchProvider]] = [
    DuckDuckGoProvider,
    BingProvider,
    BraveProvider,
    SerperProvider,
    TavilyProvider,
    # Free, specialized fallback sources — engaged only when the paid tier
    # returns thin/empty. Each contributes a different "tier" of evidence:
    # HN/Reddit (community), Wikipedia (factual), StackExchange (canonical Q&A).
    HackerNewsProvider,
    RedditProvider,
    WikipediaProvider,
    StackExchangeProvider,
]

# Standard search: only the highest-priority paid provider is queried (saves
# quota). Order: Serper > Brave > Bing.
_STANDARD_PAID_ORDER: list[str] = ["serper", "brave", "bing"]
# Deep research: query these paid providers in parallel for breadth +
# extraction. Tavily is included for its full-page extraction value.
_DEEP_PAID_ORDER: list[str] = ["serper", "tavily", "brave", "bing"]
# Free tier used as last-resort fallback when paid tier returns thin/empty.
# DDG covers generic web; the rest cover specialized content tiers.
_FREE_FALLBACK: set[str] = {
    "ddgs",
    "web_search",
    "hackernews",
    "reddit",
    "wikipedia",
    "stackexchange",
}

# Quality threshold below which we escalate to fallback providers.
_MIN_RESULTS_FOR_QUALITY = 2
_MIN_TOTAL_CHARS_FOR_QUALITY = 300

# ── Result cache ─────────────────────────────────────────────────────────
# Repeated identical queries (same user retrying, multiple users asking the
# same trending question) would otherwise re-burn Serper / Brave / Tavily
# quota. A short TTL keeps results fresh enough for "today's news" while
# absorbing duplicate-query traffic. Cache stores DEEP COPIES of result
# dicts so downstream mutation (rerank, scoring, prompt-injection) can't
# poison the next read.
_RESULTS_CACHE: dict[str, tuple[list[dict[str, Any]], float]] = {}
_RESULTS_CACHE_LOCK = threading.RLock()
_RESULTS_CACHE_TTL_SECONDS = 600  # 10 minutes — matches tools_web_search
_RESULTS_CACHE_MAX_ENTRIES = 256  # bounded to prevent unbounded growth


def _make_cache_key(
    queries: list[str],
    *,
    max_results: int,
    deep: bool,
    original_query: str,
) -> str:
    """Stable hash of every input that affects the returned result list.

    Order of queries DOES matter (parallel-search order is preserved through
    dedupe ranking), so we don't sort. ``original_query`` is included because
    it drives the reranker output.
    """
    payload = json.dumps(
        {
            "queries": queries,
            "max_results": int(max_results),
            "deep": bool(deep),
            "original": original_query or "",
        },
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    """Return a deep-copied, non-stale cached entry or None."""
    with _RESULTS_CACHE_LOCK:
        entry = _RESULTS_CACHE.get(key)
        if not entry:
            return None
        results, expires_at = entry
        if time.monotonic() >= expires_at:
            _RESULTS_CACHE.pop(key, None)
            return None
        return copy.deepcopy(results)


def _cache_set(key: str, value: list[dict[str, Any]]) -> None:
    """Store a deep copy of `value` under `key` with the configured TTL."""
    with _RESULTS_CACHE_LOCK:
        # Crude size bound: when we breach the cap, drop the oldest expiring
        # entry. Good enough for an in-memory dev cache; replace with Redis
        # if this ever needs to scale across replicas.
        if len(_RESULTS_CACHE) >= _RESULTS_CACHE_MAX_ENTRIES:
            try:
                oldest_key = min(
                    _RESULTS_CACHE,
                    key=lambda k: _RESULTS_CACHE[k][1],
                )
                _RESULTS_CACHE.pop(oldest_key, None)
            except ValueError:
                pass
        _RESULTS_CACHE[key] = (
            copy.deepcopy(value),
            time.monotonic() + _RESULTS_CACHE_TTL_SECONDS,
        )


def _get_instances() -> list[SearchProvider]:
    """Return instantiated providers that are currently available."""
    instances = []
    for cls in _ALL_PROVIDERS:
        try:
            inst = cls()
            if inst.is_available():
                instances.append(inst)
        except Exception:
            continue
    return instances


def _get_tier_providers(*, deep: bool) -> tuple[list[SearchProvider], list[SearchProvider]]:
    """Split available providers into (primary_tier, fallback_tier).

    - Standard mode: primary = the *single* highest-priority paid provider
      configured (Serper > Brave > Bing). Saves quota by not double-querying.
      Fallback = DDG.
    - Deep mode: primary = all configured paid providers in priority order
      (Serper, Tavily, Brave, Bing) running in parallel for breadth +
      Tavily's full-page extraction. Fallback = DDG.

    If no paid provider is configured, the free fallback is promoted to
    primary so the user still gets results.
    """
    available = _get_instances()
    by_name = {p.name.lower(): p for p in available}

    order = _DEEP_PAID_ORDER if deep else _STANDARD_PAID_ORDER
    primary: list[SearchProvider] = []
    if deep:
        # Run every configured paid provider in parallel for breadth.
        primary = [by_name[n] for n in order if n in by_name]
    else:
        # Pick only the top-priority paid provider; rely on fallback if it
        # returns thin/empty results.
        for name in order:
            if name in by_name:
                primary = [by_name[name]]
                break

    fallback = [
        inst for inst in available if inst.name.lower() in _FREE_FALLBACK
    ]

    # If no paid tier-1 is configured, promote the free fallback so the user
    # still gets results.
    if not primary and fallback:
        return fallback, []
    return primary, fallback


def _is_quality_results(ranked: list[dict[str, Any]]) -> bool:
    """Return True when results look substantive enough to skip fallback."""
    if len(ranked) < _MIN_RESULTS_FOR_QUALITY:
        return False
    total_body = sum(len(r.get("body", "")) for r in ranked)
    return total_body >= _MIN_TOTAL_CHARS_FOR_QUALITY


def list_providers() -> list[str]:
    """Return names of all available providers."""
    return [p.name for p in _get_instances()]


def get_provider(name: str) -> SearchProvider | None:
    """Get a specific provider by name, or None if unavailable."""
    for cls in _ALL_PROVIDERS:
        if cls.name == name:
            try:
                inst = cls()
                return inst if inst.is_available() else None
            except Exception:
                return None
    return None


def _normalize_queries(queries: str | list[str]) -> list[str]:
    if isinstance(queries, str):
        return [queries.strip()] if queries.strip() else []
    return [str(query).strip() for query in queries if str(query).strip()]


def _dedupe_ranked_results(results: list[SearchResult], max_results: int) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    unique_results: list[SearchResult] = []

    for result in results:
        url_key = result.source.lower().rstrip("/")
        if not url_key or url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        unique_results.append(result)

    # Ranking applied during URL deduplication when the same result is
    # returned by multiple providers. Paid tier-1 sits above free tier-1;
    # within free tier, specialized sources (curated content) rank above
    # generic DDG snippets. Order roughly:
    #   serper > tavily > brave > bing > wikipedia ≥ stackexchange > reddit ≥ hn > ddgs
    _rank = {
        "serper": 10,
        "tavily": 8,
        "brave": 6,
        "bing": 5,
        "wikipedia": 4,      # high-quality factual ground truth
        "stackexchange": 4,  # canonical Q&A, dense per-result signal
        "reddit": 3,         # community sentiment / practitioner experience
        "hackernews": 3,     # tech sentiment / launches
        "ddgs": 1,
        "web_search": 1,
    }
    unique_results.sort(key=lambda r: _rank.get(r.backend, 0), reverse=True)
    return [r.to_dict() for r in unique_results[:max_results]]


async def _search_provider_query(
    provider: SearchProvider,
    query: str,
    limit: int,
) -> list[SearchResult]:
    try:
        logger.info("deep_search_query provider=%s query=%s limit=%s", provider.name, query, limit)
        return await provider.async_search(query, max_results=limit)
    except Exception as exc:
        logger.warning("Search provider failed provider=%s query=%r error=%s", provider.name, query, exc)
        return []


async def _run_providers(
    providers: list[SearchProvider],
    query_list: list[str],
    *,
    max_results: int,
    deep: bool,
) -> list[SearchResult]:
    """Run a tier of providers in parallel against the diversified query set."""
    if not providers or not query_list:
        return []

    per_provider_limit = max_results if not deep else max(10, max_results)
    limit_per_query = max(2, per_provider_limit // len(query_list))

    tasks = [
        _search_provider_query(provider, query, limit_per_query)
        for provider in providers
        for query in query_list
    ]
    result_lists = await asyncio.gather(*tasks, return_exceptions=True)

    collected: list[SearchResult] = []
    for result_list in result_lists:
        if isinstance(result_list, Exception):
            logger.warning("Search task failed: %s", result_list)
            continue
        collected.extend(result_list)
    return collected


async def async_search_all(
    queries: str | list[str],
    max_results: int = 5,
    *,
    deep: bool = False,
    original_query: str = "",
) -> list[dict[str, Any]]:
    """Tiered search: try paid tier-1 first, fall back to free tier on failure.

    - Primary tier runs in parallel across whichever paid providers are
      configured (Brave for standard search; Brave + Tavily for deep).
    - Free fallback (DDG) is invoked only when the primary tier returns no
      usable results — keeps normal-path latency low and saves paid quota.
    - Identical input tuples within ``_RESULTS_CACHE_TTL_SECONDS`` short-
      circuit the network entirely (saves Serper / Brave / Tavily quota
      under duplicate traffic).
    """
    query_list = _normalize_queries(queries)
    if not query_list:
        return []

    cache_key = _make_cache_key(
        query_list,
        max_results=max_results,
        deep=deep,
        original_query=original_query,
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info(
            "search_cache_hit deep=%s queries=%d max_results=%d",
            deep,
            len(query_list),
            max_results,
        )
        return cached

    primary, fallback = _get_tier_providers(deep=deep)
    if not primary and not fallback:
        return []

    primary_results = await _run_providers(
        primary, query_list, max_results=max_results, deep=deep
    )
    ranked = _dedupe_ranked_results(primary_results, max_results=max_results)

    # Escalate to free fallback if the paid tier returned nothing usable.
    if fallback and not _is_quality_results(ranked):
        logger.info(
            "search_tier_escalation primary=%s fallback=%s reason=thin_or_empty",
            [p.name for p in primary],
            [p.name for p in fallback],
        )
        fallback_results = await _run_providers(
            fallback, query_list, max_results=max_results, deep=deep
        )
        # Merge primary + fallback, dedupe, rerank.
        merged = primary_results + fallback_results
        ranked = _dedupe_ranked_results(merged, max_results=max_results)

    if original_query and ranked:
        ranked = await asyncio.to_thread(rerank_results, original_query, ranked, top_k=max_results)

    final = ranked[:max_results]
    # Only cache non-empty results — caching empties would lock in transient
    # provider failures (rate limit, network blip) for the full TTL.
    if final:
        _cache_set(cache_key, final)
    return final


def search_all(queries: str | list[str], max_results: int = 5, *, deep: bool = False) -> list[dict[str, Any]]:
    """
    Query ALL available providers and merge/deduplicate results.
    Deep mode doubles max_results per provider for broader coverage.
    """
    providers = _get_instances()
    if not providers:
        return []

    query_list = _normalize_queries(queries)
    if not query_list:
        return []

    per_provider_limit = max_results if not deep else max(10, max_results)
    # Distribute the limit across queries so we don't fetch 100 results
    limit_per_query = max(2, per_provider_limit // len(query_list))
    
    all_results: list[SearchResult] = []

    for provider in providers:
        try:
            for query in query_list:
                results = provider.search(query, max_results=limit_per_query)
                all_results.extend(results)
            # Small stagger between providers to be polite
            time.sleep(0.2)
        except Exception:
            continue

    return _dedupe_ranked_results(all_results, max_results=max_results)
