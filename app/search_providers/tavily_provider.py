"""Tavily Search API provider (built for AI/LLM apps)."""

import os

import requests

from app.search_providers._base import SearchProvider, SearchResult


class TavilyProvider(SearchProvider):
    name = "tavily"

    def is_available(self) -> bool:
        return bool(os.getenv("TAVILY_API_KEY"))

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return []

        endpoint = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
        }

        try:
            resp = requests.post(endpoint, json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", []):
                body = item.get("content") or item.get("snippet") or ""
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
