"""Reddit search via the public `.json` endpoint.

Free, no auth required for read. Best for practitioner experience reports —
"X vs Y in production", troubleshooting threads, real-world tradeoffs that
search engines tend to bury.

A descriptive User-Agent is required to avoid Reddit's anti-bot 429s. The
provider fails gracefully on rate limits / network errors.
"""

from __future__ import annotations

import requests

from app.search_providers._base import SearchProvider, SearchResult


REDDIT_SEARCH_ENDPOINT = "https://www.reddit.com/search.json"
# Reddit asks for a unique, descriptive User-Agent. Short-circuit 429 traffic
# by making this stable and identifiable.
REDDIT_USER_AGENT = "snti-chatbot/1.0 (research-assistant)"


class RedditProvider(SearchProvider):
    name = "reddit"

    def is_available(self) -> bool:
        # Public endpoint — always available barring network issues / 429s.
        return True

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        params = {
            "q": query,
            "limit": max_results,
            "sort": "relevance",
            "type": "link",
            "restrict_sr": "false",
        }
        headers = {"User-Agent": REDDIT_USER_AGENT}
        try:
            resp = requests.get(
                REDDIT_SEARCH_ENDPOINT,
                headers=headers,
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        results: list[SearchResult] = []
        for child in data.get("data", {}).get("children", []) or []:
            d = child.get("data", {}) or {}
            title = d.get("title") or ""
            permalink = d.get("permalink") or ""
            if not title or not permalink:
                continue

            url = "https://www.reddit.com" + permalink
            sub = d.get("subreddit_name_prefixed", "")
            score = d.get("score", 0)
            num_comments = d.get("num_comments", 0)
            selftext = (d.get("selftext") or "").strip()
            # Cap selftext aggressively so the prompt stays compact.
            if len(selftext) > 320:
                selftext = selftext[:320].rstrip() + "…"

            meta = f"[{sub} · {score} ↑ · {num_comments} comments]"
            body = f"{meta} {selftext}" if selftext else f"{meta} {title}"
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
