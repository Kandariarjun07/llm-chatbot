"""Recursive deep-research pipeline.

A single shallow retrieval pass is fine for most questions, but research-grade
queries ("compare X vs Y for production startups", "what are the tradeoffs of
Z for healthcare RAG") need a planner that decomposes the question, retrieves
per sub-question, audits coverage, and runs a targeted follow-up pass to fill
gaps.

Pipeline:

    user_query
      ├─ 1. decompose_research_question  → 3-5 sub-questions
      ├─ 2. parallel retrieval per sub-question (diversified expansion + paid tier-1)
      ├─ 3. identify_research_gaps       → 0-3 follow-up queries
      ├─ 4. one follow-up retrieval round (capped)
      └─ 5. merge + dedupe + rerank

Returns the same `list[dict]` shape as `async_search_all`, so the orchestrator
just swaps the call site without touching downstream synthesis.

Cost / latency notes:
  - Decomposition + gap analysis = 2 cheap LLM calls (Groq Llama, ~1-2s each).
  - Retrieval calls are bounded: N_sub × diversified_search + 1 follow-up.
  - The recursion is *non-nested* — exactly one extra round, never a tree.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.reranker import rerank_results
from app.search_providers._registry import async_search_all
from app.tools_web_search import interpret_search_intent
from llm.client import chat_completion


logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# JSON-array extraction helper (LLMs occasionally wrap output in markdown).
# ────────────────────────────────────────────────────────────────────────────

def _extract_json_array(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    if not cleaned.startswith("["):
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    return cleaned


# ────────────────────────────────────────────────────────────────────────────
# Step 1 — Question decomposition.
# ────────────────────────────────────────────────────────────────────────────

_DECOMPOSE_PROMPT = """You are a research planner. The user has asked a complex question that benefits from being broken down before searching the web.

Decompose the question into 3-5 focused, complementary sub-questions. Each sub-question must target a *distinct* angle (pricing, performance, ecosystem, drawbacks, alternatives, real-world experience, etc.). Avoid duplication.

Hard rules:
- Each sub-question must be standalone and answerable via web search.
- Preserve specific product / library / company names from the user's question exactly.
- If the question is already narrow and atomic, return a single-element array containing the original question.
- Output ONLY a valid JSON array of strings. No markdown fences, no commentary.

User question: {query}
Sub-questions:"""


async def decompose_research_question(
    query: str,
    model_choice: str = "Llama",
) -> list[str]:
    """Split a complex research query into 3-5 focused sub-questions.

    Falls back to ``[query]`` whenever the LLM output is unparseable, so the
    pipeline degrades gracefully to current single-query behavior.
    """
    prompt = _DECOMPOSE_PROMPT.format(query=query)
    try:
        raw = await asyncio.to_thread(
            chat_completion,
            [{"role": "user", "content": prompt}],
            model_choice,
            temperature=0.3,
            max_output_tokens=300,
        )
    except Exception as exc:
        logger.warning("Research decomposition failed: %s", exc)
        return [query]

    if not raw or (isinstance(raw, str) and raw.startswith("Error:")):
        return [query]

    try:
        subs = json.loads(_extract_json_array(raw))
    except Exception as exc:
        logger.warning("Research decomposition parse failed: %s", exc)
        return [query]

    if not isinstance(subs, list) or not subs:
        return [query]

    cleaned = [str(s).strip() for s in subs[:5] if str(s).strip()]
    return cleaned or [query]


# ────────────────────────────────────────────────────────────────────────────
# Step 3 — Gap analysis.
# ────────────────────────────────────────────────────────────────────────────

_GAP_ANALYSIS_PROMPT = """You are a research auditor reviewing the evidence gathered so far for a complex question.

Original question: {query}

Sub-questions investigated:
{sub_lines}

Evidence gathered (titles + snippets):
{summary}

Identify 0-3 *specific factual gaps* — concrete things the final answer would need but which aren't covered or aren't backed by strong evidence yet. Return targeted search queries that would close those gaps.

Hard rules:
- If coverage looks substantively complete, return an empty array `[]`.
- Each query must be standalone and search-engine ready.
- Prefer queries that target *different* sources / angles than the existing evidence.
- Output ONLY a valid JSON array of strings (max 3). No markdown fences, no commentary.

Gap queries:"""


def _summarize_results_for_audit(results: list[dict[str, Any]], cap: int = 15) -> str:
    """Compact, prompt-friendly summary of retrieved results."""
    lines: list[str] = []
    for r in results[:cap]:
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        # Hard-cap snippet length to keep the prompt small.
        if len(body) > 200:
            body = body[:200].rstrip() + "…"
        if title or body:
            lines.append(f"- {title}: {body}" if title else f"- {body}")
    return "\n".join(lines) if lines else "(no results yet)"


async def identify_research_gaps(
    user_query: str,
    sub_questions: list[str],
    results: list[dict[str, Any]],
    model_choice: str = "Llama",
) -> list[str]:
    """Ask the LLM which factual gaps remain after round-1 retrieval.

    Returns at most 3 follow-up search queries; empty list when evidence
    looks complete or when the LLM call fails (graceful degradation).
    """
    if not results:
        return []

    sub_lines = "\n".join(f"- {s}" for s in sub_questions) or f"- {user_query}"
    summary = _summarize_results_for_audit(results)

    prompt = _GAP_ANALYSIS_PROMPT.format(
        query=user_query,
        sub_lines=sub_lines,
        summary=summary,
    )

    try:
        raw = await asyncio.to_thread(
            chat_completion,
            [{"role": "user", "content": prompt}],
            model_choice,
            temperature=0.2,
            max_output_tokens=200,
        )
    except Exception as exc:
        logger.warning("Gap analysis failed: %s", exc)
        return []

    if not raw or (isinstance(raw, str) and raw.startswith("Error:")):
        return []

    try:
        gaps = json.loads(_extract_json_array(raw))
    except Exception as exc:
        logger.warning("Gap analysis parse failed: %s", exc)
        return []

    if not isinstance(gaps, list):
        return []
    return [str(g).strip() for g in gaps[:3] if str(g).strip()]


# ────────────────────────────────────────────────────────────────────────────
# Step 2 — per-sub-question retrieval (parallel).
# ────────────────────────────────────────────────────────────────────────────

async def _retrieve_for_subquestion(
    sub_query: str,
    *,
    per_sub_results: int,
    model_choice: str,
) -> list[dict[str, Any]]:
    """Run diversified expansion + paid-tier search for a single sub-question."""
    try:
        variants = await interpret_search_intent(
            sub_query, model_choice=model_choice, deep=True
        )
        return await async_search_all(
            variants,
            max_results=per_sub_results,
            deep=True,
            original_query=sub_query,
        )
    except Exception as exc:
        logger.warning("Sub-question retrieval failed: %s — %s", sub_query, exc)
        return []


# ────────────────────────────────────────────────────────────────────────────
# Top-level pipeline.
# ────────────────────────────────────────────────────────────────────────────

async def deep_research_pipeline(
    user_query: str,
    *,
    model_choice: str = "Llama",
    target_results: int = 20,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the recursive deep-research loop.

    Args:
        user_query: the original (un-rewritten) user question.
        model_choice: which LLM to use for decomposition and gap analysis.
            Llama (Groq) is the right default — these are short, cheap calls.
        target_results: cap on the final reranked result list returned to the
            orchestrator's synthesis stage.

    Returns:
        ``(results, trace)`` — `results` is a list of result-dicts in the same
        shape `async_search_all` produces, ready to be merged into the
        orchestrator's retrieved_context. `trace` carries planner metadata for
        the per-request trace.
    """
    trace: dict[str, Any] = {
        "sub_questions": [],
        "round1_count": 0,
        "gap_queries": [],
        "round2_count": 0,
        "final_count": 0,
    }

    # ── Step 1: decompose ────────────────────────────────────────────────
    sub_questions = await decompose_research_question(user_query, model_choice)
    trace["sub_questions"] = sub_questions

    # Per-sub-question budget: keep total round-1 size ~target_results so we
    # don't blow up the prompt for the gap-analysis pass.
    per_sub = max(4, target_results // max(1, len(sub_questions)))

    # ── Step 2: parallel retrieval per sub-question ──────────────────────
    coros = [
        _retrieve_for_subquestion(s, per_sub_results=per_sub, model_choice=model_choice)
        for s in sub_questions
    ]
    sub_lists = await asyncio.gather(*coros, return_exceptions=True)

    round1: list[dict[str, Any]] = []
    for sub_list in sub_lists:
        if isinstance(sub_list, Exception):
            logger.warning("Sub-question task errored: %s", sub_list)
            continue
        round1.extend(sub_list)
    trace["round1_count"] = len(round1)

    # ── Step 3: identify gaps ────────────────────────────────────────────
    gap_queries = await identify_research_gaps(
        user_query, sub_questions, round1, model_choice
    )
    trace["gap_queries"] = gap_queries

    # ── Step 4: one follow-up retrieval round (capped) ───────────────────
    round2: list[dict[str, Any]] = []
    if gap_queries:
        try:
            round2 = await async_search_all(
                gap_queries,
                max_results=max(4, target_results // 2),
                deep=True,
                original_query=user_query,
            )
        except Exception as exc:
            logger.warning("Gap-fill retrieval failed: %s", exc)
            round2 = []
    trace["round2_count"] = len(round2)

    # ── Step 5: merge → URL dedupe → rerank ──────────────────────────────
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for r in round1 + round2:
        url = (r.get("source") or "").lower().rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(r)

    if merged:
        try:
            merged = await asyncio.to_thread(
                rerank_results, user_query, merged, top_k=target_results
            )
        except Exception as exc:
            logger.warning("Final rerank failed: %s", exc)
            # Keep merged as-is; non-fatal.

    final = merged[:target_results]
    trace["final_count"] = len(final)
    return final, trace
