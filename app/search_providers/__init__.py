"""Pluggable web search providers."""

from app.search_providers._base import SearchProvider, SearchResult
from app.search_providers._registry import async_search_all, get_provider, list_providers, search_all

__all__ = [
    "SearchProvider",
    "SearchResult",
    "async_search_all",
    "get_provider",
    "list_providers",
    "search_all",
]
