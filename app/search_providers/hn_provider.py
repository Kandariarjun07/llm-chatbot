"""Hacker News search via the Algolia HN API.

Free, no auth required. Best for tech sentiment, launch posts, "is X actually
good in production" discussions, and historical context on dev tooling.

The endpoint is the de facto HN search backend (used by the official site).
"""

from __future__ import annotations

import requests

from app.search_providers._base import SearchProvider, SearchResult


HN_ALGOLIA_ENDPOINT = "https://hn.algolia.com/api/v1/search"


class HackerNewsProvider(SearchProvider):
    name = "hackernews"

    def is_available(self) -> bool:
        # Public endpoint — always available barring network issues.
        return True

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": max_results,
        }
        try:
            resp = requests.get(HN_ALGOLIA_ENDPOINT, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        results: list[SearchResult] = []
        for hit in data.get("hits", []) or []:
            title = hit.get("title") or hit.get("story_title") or ""
            url = hit.get("url") or hit.get("story_url") or ""
            if not title or not url:
                continue
            points = hit.get("points") or 0
            num_comments = hit.get("num_comments") or 0
            created = (hit.get("created_at") or "")[:10]
            # HN snippets aren't rich; surface the social signal that makes
            # HN distinctive (points + comments + freshness).
            body_meta = f"[HN · {points} pts · {num_comments} comments"
            if created:
                body_meta += f" · {created}"
            body_meta += "]"
            body = f"{body_meta} {title}"
            results.append(
                SearchResult(
                    title=title,
                    body=body,
                    source=url,
                    backend=self.name,
                    score=1.0,
                )
            )

        return results[:max_results]
