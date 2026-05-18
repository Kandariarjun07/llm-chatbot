"""Wikipedia search via the MediaWiki API.

Free, no auth, no quota. Best as a factual anchor for definitions, "who/what
is X", historical timelines, and any encyclopedic baseline that paid search
engines can over- or under-index.

Two-step: first list matching titles, then fetch plain-text intros in one
batch request so we ship usable snippets (not just titles).
"""

from __future__ import annotations

import re

import requests

from app.search_providers._base import SearchProvider, SearchResult


WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
# Strip MediaWiki's HTML highlight markup so snippets are readable.
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _wiki_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")


class WikipediaProvider(SearchProvider):
    name = "wikipedia"

    def is_available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        # Step 1 — find matching titles.
        try:
            search_resp = requests.get(
                WIKIPEDIA_ENDPOINT,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": max_results,
                    "format": "json",
                },
                timeout=10,
            )
            search_resp.raise_for_status()
            search_data = search_resp.json()
        except Exception:
            return []

        hits = search_data.get("query", {}).get("search", []) or []
        if not hits:
            return []

        # Step 2 — fetch plain-text intros for the matched pages in one call.
        title_to_extract: dict[str, str] = {}
        try:
            titles = "|".join(h.get("title", "") for h in hits if h.get("title"))
            if titles:
                extract_resp = requests.get(
                    WIKIPEDIA_ENDPOINT,
                    params={
                        "action": "query",
                        "prop": "extracts",
                        "exintro": True,
                        "explaintext": True,
                        "exchars": 400,
                        "titles": titles,
                        "format": "json",
                    },
                    timeout=10,
                )
                extract_resp.raise_for_status()
                pages = extract_resp.json().get("query", {}).get("pages", {}) or {}
                title_to_extract = {
                    p.get("title", ""): (p.get("extract") or "")
                    for p in pages.values()
                }
        except Exception:
            # Non-fatal — fall back to the raw search snippet below.
            title_to_extract = {}

        results: list[SearchResult] = []
        for hit in hits[:max_results]:
            title = hit.get("title") or ""
            if not title:
                continue
            extract = title_to_extract.get(title) or hit.get("snippet") or ""
            extract = _HTML_TAG_RE.sub("", extract).strip()
            results.append(
                SearchResult(
                    title=title,
                    body=extract or title,
                    source=_wiki_url(title),
                    backend=self.name,
                    score=1.0,
                )
            )

        return results[:max_results]
