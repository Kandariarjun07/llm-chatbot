from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class SearchResult:
    title: str
    body: str
    source: str
    backend: str
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "source": self.source,
            "backend": self.backend,
            "score": self.score,
        }


class SearchProvider(ABC):
    """Base class for a web-search backend."""

    name: str = "abstract"

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Return a list of search results."""
        ...

    async def async_search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Async adapter for providers backed by synchronous SDKs."""
        return await asyncio.to_thread(self.search, query, max_results=max_results)

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider can be used (credentials/env present)."""
        ...
