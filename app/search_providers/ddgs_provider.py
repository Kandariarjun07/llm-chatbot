"""DuckDuckGo search provider (free, no API key)."""

from app.search_providers._base import SearchProvider, SearchResult


def _extract_fields(raw: dict) -> SearchResult | None:
    title = raw.get("title", "")
    body = raw.get("body") or raw.get("snippet") or raw.get("abstract") or raw.get("summary") or ""
    if not body and title:
        body = title
    source = raw.get("href") or raw.get("url") or raw.get("source") or ""
    if not body or not source:
        return None
    return SearchResult(title=title, body=body, source=source, backend=DuckDuckGoProvider.name, score=1.0)


class DuckDuckGoProvider(SearchProvider):
    name = "ddgs"

    def is_available(self) -> bool:
        try:
            import ddgs  # noqa: F401
            return True
        except ImportError:
            return False

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            from ddgs import DDGS

            raw_results = list(DDGS().text(query, max_results=max_results))
            return [result for raw in raw_results if (result := _extract_fields(raw))]
        except Exception:
            return []

    async def async_search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        from app.tools_web_search import async_web_search

        try:
            raw_results = await async_web_search(query, max_results=max_results, original_query=query)
            return [
                SearchResult(
                    title=r["title"],
                    body=r["body"],
                    source=r["source"],
                    backend=self.name,
                    score=r.get("score", 1.0),
                )
                for r in raw_results
            ]
        except Exception:
            return []
