"""Microsoft Bing Web Search API provider."""

import os

import requests

from app.search_providers._base import SearchProvider, SearchResult


class BingProvider(SearchProvider):
    name = "bing"

    def is_available(self) -> bool:
        return bool(os.getenv("BING_API_KEY"))

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        api_key = os.getenv("BING_API_KEY")
        if not api_key:
            return []

        endpoint = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": api_key}
        params = {"q": query, "count": max_results, "textDecorations": False, "textFormat": "HTML"}

        try:
            resp = requests.get(endpoint, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("webPages", {}).get("value", []):
                body = item.get("snippet") or item.get("description") or ""
                results.append(
                    SearchResult(
                        title=item.get("name", ""),
                        body=body,
                        source=item.get("url", ""),
                        backend=self.name,
                        score=1.0,
                    )
                )
            return results
        except Exception:
            return []
