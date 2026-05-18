"""Stack Exchange search (defaults to Stack Overflow).

Free, no auth required (10k requests/day per IP without a key). Best for
canonical coding answers, error-message lookups, and "how do I X in
language Y" type questions where curated Q&A beats general web search.

The provider returns the question rows (titles + URLs + signal). The actual
answer body lives behind the link; the LLM can chase the link via search
context if needed.
"""

from __future__ import annotations

import requests

from app.search_providers._base import SearchProvider, SearchResult


STACKEXCHANGE_ENDPOINT = "https://api.stackexchange.com/2.3/search/advanced"


class StackExchangeProvider(SearchProvider):
    name = "stackexchange"

    def is_available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        params = {
            "q": query,
            "site": "stackoverflow",
            "order": "desc",
            "sort": "relevance",
            "pagesize": max_results,
            # Default filter returns title/link/score/answer_count/tags/is_answered.
            "filter": "default",
        }
        try:
            resp = requests.get(STACKEXCHANGE_ENDPOINT, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        # Stack Exchange returns 200 with `error_id` set when throttled or
        # malformed. Bail out cleanly rather than treating it as success.
        if data.get("error_id"):
            return []

        results: list[SearchResult] = []
        for item in data.get("items", []) or []:
            title = item.get("title") or ""
            link = item.get("link") or ""
            if not title or not link:
                continue

            score = item.get("score", 0)
            answer_count = item.get("answer_count", 0)
            is_answered = "✓" if item.get("is_answered") else ""
            tags = ", ".join((item.get("tags") or [])[:3])

            meta_parts = [f"SO · {score} ↑ · {answer_count} answers"]
            if is_answered:
                meta_parts.append("✓ accepted")
            if tags:
                meta_parts.append(tags)
            meta = "[" + " · ".join(meta_parts) + "]"
            body = f"{meta} {title}"
            results.append(
                SearchResult(
                    title=title,
                    body=body,
                    source=link,
                    backend=self.name,
                    score=1.0,
                )
            )

        return results[:max_results]
