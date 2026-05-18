"""Serper.dev search provider — Google SERP via API.

Serper exposes Google's web index with rich result fields (organic, answer
box, knowledge graph, related searches). The free tier ships ~2.5k queries
and per-query latency is comparable to Brave/Bing.

We extract the `organic` results (title + link + snippet) and, when present,
prepend the answer-box / knowledge-graph snippet as a synthetic top result so
direct answers surface in the LLM's context.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from app.search_providers._base import SearchProvider, SearchResult


SERPER_ENDPOINT = "https://google.serper.dev/search"


class SerperProvider(SearchProvider):
    name = "serper"

    def is_available(self) -> bool:
        return bool(os.getenv("SERPER_API_KEY"))

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        api_key = os.getenv("SERPER_API_KEY")
        if not api_key:
            return []

        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }
        # Serper's `num` parameter is best-effort; cap at 20 to avoid wasting
        # credits on requests larger than the index typically returns.
        payload: dict[str, Any] = {"q": query, "num": min(max(max_results, 1), 20)}

        try:
            resp = requests.post(SERPER_ENDPOINT, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        results: list[SearchResult] = []

        # Surface answer box / knowledge graph as a synthetic high-priority
        # result so the LLM can cite the direct answer when present.
        answer_box = data.get("answerBox") or {}
        if answer_box:
            answer_text = (
                answer_box.get("answer")
                or answer_box.get("snippet")
                or answer_box.get("snippetHighlighted")
                or ""
            )
            answer_link = answer_box.get("link") or answer_box.get("source") or ""
            if answer_text:
                results.append(
                    SearchResult(
                        title=answer_box.get("title") or "Answer",
                        body=str(answer_text),
                        source=answer_link or "google_answer_box",
                        backend=self.name,
                        score=1.2,  # boost so reranker prefers direct answers
                    )
                )

        kg = data.get("knowledgeGraph") or {}
        if kg and kg.get("description"):
            results.append(
                SearchResult(
                    title=kg.get("title") or "Knowledge Graph",
                    body=str(kg.get("description") or ""),
                    source=kg.get("descriptionLink") or kg.get("website") or "google_knowledge_graph",
                    backend=self.name,
                    score=1.1,
                )
            )

        for item in data.get("organic", []) or []:
            snippet = item.get("snippet") or item.get("snippetHighlighted") or ""
            link = item.get("link") or ""
            title = item.get("title") or ""
            if not link or not title:
                continue
            # Prepend dated lines when Serper provides a freshness hint.
            date_hint = item.get("date") or ""
            body = f"[{date_hint}] {snippet}" if date_hint else snippet
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
