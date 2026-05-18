"""Brave Search API provider."""

import os

import requests

from app.search_providers._base import SearchProvider, SearchResult


class BraveProvider(SearchProvider):
    name = "brave"

    def is_available(self) -> bool:
        return bool(os.getenv("BRAVE_API_KEY"))

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        api_key = os.getenv("BRAVE_API_KEY")
        if not api_key:
            return []

        endpoint = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        }
        params = {"q": query, "count": max_results}

        try:
            resp = requests.get(endpoint, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", []):
                body = item.get("description") or ""
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        body=body,
                        source=item.get("url", ""),
                        backend=self.name,
                        score=1.0,
                    )
                )
            return results
        except Exception:
            return []
