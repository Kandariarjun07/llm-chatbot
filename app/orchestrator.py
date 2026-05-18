import asyncio
import logging
import re
import time
from app.access_control import build_access_policy
from app.cache import answer_cache
from app.config import get_settings
from app.guardrails import (
    SAFE_COMPLETION,
    append_reference_notice,
    check_references,
    moderate_output,
    validate_prompt,
)
from app.language import build_language_context
from app.model_routing import select_model_for_query
from app.security import RedactionResult, redact_pii
from app.telemetry import log_chat_event
from app.token_budget import trim_to_token_budget
from app.tools import calculator_tool, file_analyzer_tool
from app.deep_research import deep_research_pipeline
from app.rate_limits import check_deep_research_limit, consume_deep_research_use
from app.search_providers._registry import async_search_all, list_providers
from app.tools_web_search import async_web_search, interpret_search_intent
from data.rag import format_context, retrieve_context
from llm.client import chat_completion
from app.preferences import get_custom_instructions
from prompts.compose import build_rag_answer_prompt, build_research_prompt, build_web_search_prompt, build_tool_selection_prompt


logger = logging.getLogger(__name__)
SEARCH_BACKENDS = {"web_search", "ddgs", "bing", "brave", "tavily"}

# Conversation-history budget. We deliberately keep this smaller than the
# full input window so the prompt + RAG context + current question still
# have room to land cleanly. Trimming is "newest-first wins" so the most
# relevant turns survive when budgets are tight.
_MAX_HISTORY_TURNS = 12
_DEFAULT_HISTORY_TOKEN_BUDGET = 1500


def _is_search_context(item):
    return item.get("backend") in SEARCH_BACKENDS


def _format_conversation_history(
    history: list[dict] | None,
    *,
    max_turns: int = _MAX_HISTORY_TURNS,
    max_tokens: int = _DEFAULT_HISTORY_TOKEN_BUDGET,
) -> str:
    """Render prior chat turns as a labeled, token-budgeted text block.

    The block is intended to be prepended to the *current* user query so
    every provider (which only reads ``messages[-1]["content"]``) still
    receives the conversational context.

    Strategy:
      - Drop empty / whitespace-only turns and the live placeholder.
      - Keep at most ``max_turns`` of the most recent messages.
      - Walk newest → oldest, accumulating until the token budget is hit,
        then reverse for chronological output.
      - Returns an empty string when history is missing or all-empty so
        callers can short-circuit.
    """
    if not history:
        return ""

    # Filter to non-empty user/assistant turns. Anything else (system,
    # tool, weird custom roles) is intentionally ignored — the orchestrator
    # owns the system prompt.
    cleaned: list[dict] = []
    for msg in history:
        role = (msg.get("role") or "").lower()
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        cleaned.append({"role": role, "content": content})

    if not cleaned:
        return ""

    # Take the tail (most recent), then walk in reverse to apply the budget.
    cleaned = cleaned[-max_turns:]

    rendered_reverse: list[str] = []
    used_tokens = 0
    for msg in reversed(cleaned):
        label = "User" if msg["role"] == "user" else "Assistant"
        line = f"[{label}]: {msg['content']}"
        budget = trim_to_token_budget(line, max_tokens - used_tokens)
        line_text = budget.text
        # If even the trimmed line is empty, we've hit the budget.
        if not line_text.strip():
            break
        rendered_reverse.append(line_text)
        used_tokens += budget.original_tokens
        if used_tokens >= max_tokens:
            break

    if not rendered_reverse:
        return ""

    body = "\n".join(reversed(rendered_reverse))
    return f"=== CONVERSATION SO FAR ===\n{body}\n=== END HISTORY ===\n\n"


# TOOL DECISION (heuristic — instant, no LLM call)
#
# Catches the obvious cases:
#   • Calculator: simple arithmetic with operators and digits ("12 * 7", "(3+4)/2")
#   • File:       handled separately by the >1000-char short-circuit upstream
#   • None:       everything else
#
# This replaces a per-query Groq call (~200-500ms) for >95% of queries.
# The LLM-based `decide_tool_llm` is kept as a fallback for code paths
# that need full classification (e.g. tests, /chat non-streaming path).
_CALC_REGEX = re.compile(
    r"^\s*[\d\s\+\-\*\/\(\)\.\^%×÷=]+\s*[\?]?\s*$"
)
_CALC_KEYWORDS = (
    "calculate", "compute", "what is ", "what's ",
    "solve", "evaluate",
)


def _heuristic_tool_decision(query: str) -> str:
    """Fast regex-based tool classification. Returns 'calculator',
    'file', or 'none'. No LLM call."""
    if not query:
        return "none"
    stripped = query.strip()

    # Pure arithmetic expression — must contain at least one operator.
    if _CALC_REGEX.match(stripped) and re.search(r"[\+\-\*\/\^×÷]", stripped):
        return "calculator"

    # Natural-language calc requests like "what is 23 * 17?"
    lower = stripped.lower()
    if (
        any(lower.startswith(kw) for kw in _CALC_KEYWORDS)
        and re.search(r"\d", stripped)
        and re.search(r"[\+\-\*\/\^×÷]", stripped)
    ):
        return "calculator"

    return "none"


# TOOL DECISION (LLM-based — kept for fallback / non-streaming path)
async def decide_tool_llm(query, model_choice, temperature=0.0, max_output_tokens=16):
    messages = build_tool_selection_prompt(query)

    try:
        decision = await asyncio.to_thread(
            chat_completion,
            messages,
            model_choice,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        if not decision or not isinstance(decision, str):
            return "none"

        decision = decision.strip().lower()
        decision = decision.split()[0]

        if decision not in ["calculator", "file", "none"]:
            return "none"

        return decision

    except Exception as e:
        print("Tool decision error:", e)
        return "none"


_SELF_META_PATTERNS = (
    "who are you", "what are you", "which model", "what model",
    "what llm", "which llm", "based on", "powered by", "what can you do",
    "what can u do", "your name", "who built you", "who made you",
    "your capabilities", "what is your model",
    "knsa model", "kaunsa model", "tum kaun", "tu kaun", "tumhara naam",
    "tera naam", "kya kr sakte ho", "kya kr sakta hai",
)


def _is_self_meta_question(query: str) -> bool:
    """True for identity / self / capability questions that should never
    hit web search. These must be answered from the system prompt or the
    model's own training, not from external results."""
    q = query.lower().strip()
    if len(q) > 120:
        return False
    return any(p in q for p in _SELF_META_PATTERNS)


async def is_informational_query(query: str, model_choice: str = "Llama") -> bool:
    """Detect if a query requires up-to-date external knowledge or web search."""
    # Self/identity questions must never trigger a web search.
    if _is_self_meta_question(query):
        return False

    # Fast heuristic checks first
    query_lower = query.lower()
    if any(kw in query_lower for kw in ["latest", "current", "news", "today", "who is", "what is the price", "weather", "recent"]):
        return True
        
    prompt = f"""Does this user query require searching the web for current events, facts, or external knowledge to answer accurately?
Respond with ONLY 'yes' or 'no'.

Query: {query}
Answer:"""
    try:
        response = await asyncio.to_thread(
            chat_completion,
            [{"role": "user", "content": prompt}],
            model_choice=model_choice,
            temperature=0.0,
            max_output_tokens=5,
        )
        if not response:
            return False
        return "yes" in response.strip().lower()
    except Exception:
        return False


def _status_for_response(response):
    return "error" if str(response).startswith("Error:") else "ok"


def _result(answer, include_trace=False, trace=None):
    if not include_trace:
        return answer

    trace = trace or {}
    return {
        "answer": answer,
        "used_context_count": trace.get("used_context_count", 0),
        "trace": trace,
    }


def _messages_to_text(messages):
    return "\n\n".join(
        f"{message.get('role', 'unknown')}: {message.get('content', '')}"
        for message in messages
    )


def _build_prompt_messages(
    latest_question,
    context_text,
    language_instructions,
    *,
    web_search=False,
    research=False,
    max_output_tokens=800,
):
    """Build the message list and effective token budget based on mode flags."""
    effective_max_output_tokens = max_output_tokens
    if web_search:
        effective_max_output_tokens = max(max_output_tokens, 4096)
        messages = build_web_search_prompt(
            latest_question,
            context_text,
            language_instructions=language_instructions,
        )
    elif research:
        effective_max_output_tokens = max(max_output_tokens, 8192)
        messages = build_research_prompt(
            latest_question,
            context_text,
            language_instructions=language_instructions,
        )
    else:
        messages = build_rag_answer_prompt(
            latest_question,
            context_text,
            language_instructions=language_instructions,
        )
    return messages, effective_max_output_tokens


async def build_chat_messages(
    query,
    model_choice="Llama",
    temperature=0.2,
    user_id="anonymous",
    user_context=None,
    web_search=False,
    research=False,
    history=None,
):
    """
    Run the full orchestrator pipeline up to message building.
    Returns (messages, effective_model_choice, effective_max_output_tokens, trace).
    This is used by the streaming endpoint so it shares the same
    guardrails, routing, context retrieval, and prompt construction.
    """
    settings = get_settings()
    requested_model_choice = model_choice
    effective_model_choice = model_choice
    user_context = dict(user_context or {})
    user_context.setdefault("user_id", user_id)
    access_policy = build_access_policy(user_context, settings)
    redaction = (
        redact_pii(query)
        if settings.pii_redaction_enabled
        else RedactionResult(query, False, {"emails": 0, "phones": 0})
    )
    safe_query = redaction.text

    if "The user now asks:" in safe_query:
        latest_question = safe_query.split("The user now asks:")[-1].strip()
    else:
        latest_question = safe_query.strip()

    safe_query_budget = trim_to_token_budget(safe_query, settings.max_input_tokens)
    latest_question_budget = trim_to_token_budget(latest_question, settings.max_input_tokens)
    latest_question = latest_question_budget.text
    language_context = build_language_context(latest_question, settings)
    language_instructions = language_context.prompt_instructions

    custom_instr = await asyncio.to_thread(get_custom_instructions, user_id)
    if custom_instr:
        language_instructions = f"{language_instructions}\n\nUSER PREFERENCE: {custom_instr}".strip()

    trace = {
        "query": latest_question,
        "user_id": user_id,
        "requested_model_choice": requested_model_choice,
        "model_choice": effective_model_choice,
        "temperature": temperature,
        "web_search": web_search,
        "research": research,
        "tool": "none",
        "pii_redacted": redaction.redacted,
        "pii_counts": redaction.counts,
        "prompt_validation": "not_checked",
        "data_access": access_policy.trace(),
        "model_routing": {
            "requested_model": requested_model_choice,
            "selected_model": effective_model_choice,
            "routed": False,
            "reason": "not_checked",
        },
        "language": language_context.trace(),
    }

    prompt_guardrail = validate_prompt(
        latest_question,
        settings.forbidden_topic_patterns,
        enabled=settings.prompt_validation_enabled,
    )
    trace["prompt_validation"] = "passed" if prompt_guardrail.allowed else "blocked"
    if not prompt_guardrail.allowed:
        trace["status"] = "blocked"
        trace["guardrail_reason"] = prompt_guardrail.reason
        # Return a special sentinel so the caller knows it was blocked
        return [{"role": "system", "content": SAFE_COMPLETION}], model_choice, settings.max_output_tokens, trace

    routing = select_model_for_query(latest_question, requested_model_choice, settings)
    effective_model_choice = routing.selected_model
    trace["model_choice"] = effective_model_choice
    trace["model_routing"] = routing.trace()

    # Short-circuit for very long inputs (>1000 chars) – file analyzer path
    if len(safe_query) > 1000:
        trace["tool"] = "file"
        # Streaming endpoint will need to handle this separately; here we just return a placeholder
        return [{"role": "system", "content": SAFE_COMPLETION}], effective_model_choice, settings.max_output_tokens, trace

    # ── Pre-stream pipeline optimization ──
    #
    # The previous version always ran TWO LLM calls before streaming
    # could even start:
    #   1. decide_tool_llm        — picks calculator/file/none
    #   2. is_informational_query — auto-routes to web search
    #
    # Each adds ~200-500ms. For "Hi" in Fast mode that's 500-1000ms of
    # latency BEFORE the first token. Now:
    #
    #   • Tool decision uses a fast heuristic (regex). The LLM-based
    #     `decide_tool_llm` is reserved for ambiguous queries that
    #     might be a calculator request. The heuristic catches >95%
    #     of cases instantly.
    #   • is_informational_query is skipped entirely. If the user
    #     wanted web search they'd have toggled it. Auto-routing
    #     is opt-in via the `auto_web_search` setting (off by default).
    tool = _heuristic_tool_decision(latest_question)

    rag_task = asyncio.to_thread(
        retrieve_context,
        latest_question,
        allowed_sources=access_policy.allowed_sources if access_policy.enabled else None,
    )

    # Only run the informational-query classifier when explicitly
    # enabled via settings (kept for users who want auto-routing).
    auto_route = getattr(settings, "auto_web_search", False)
    needs_info_check = auto_route and not web_search and not research

    if needs_info_check:
        info_task = is_informational_query(latest_question, effective_model_choice)
        retrieved_context, is_info = await asyncio.gather(rag_task, info_task)
    else:
        retrieved_context = await rag_task
        is_info = False

    trace["tool"] = tool

    if tool == "calculator":
        trace["tool"] = "calculator"
        # Calculator returns immediately; streaming can't handle this well, return placeholder
        return [{"role": "system", "content": SAFE_COMPLETION}], effective_model_choice, settings.max_output_tokens, trace

    if needs_info_check and is_info:
        web_search = True
        trace["auto_routed_to_search"] = True
        logger.info("auto_routed_to_search query=%s", latest_question)
    trace["web_search"] = web_search

    if web_search or research:
        # Step 1: Ask the LLM to interpret the user's intent into precise,
        # diversified search queries. Deep mode gets 5 variants targeting
        # different source tiers; standard search gets 3.
        search_query = await interpret_search_intent(latest_question, deep=research)
        trace["search_intent_original"] = latest_question
        trace["search_intent_rewritten"] = search_query
        trace["search_intent_model"] = "Llama"
        trace["search_query_count"] = len(search_query)

        # Step 2: Choose search strategy based on mode
        if research:
            # Deep Research mode: recursive pipeline with decomposition + gap analysis
            allowed, remaining = await asyncio.to_thread(check_deep_research_limit, user_id)
            trace["deep_research_allowed"] = allowed
            trace["deep_research_remaining"] = remaining

            if allowed:
                # Consume one use; run the full recursive pipeline.
                # The pipeline handles its own diversified expansion per
                # sub-question, so the round-1 `search_query` variants are
                # only useful for the trace.
                await asyncio.to_thread(consume_deep_research_use, user_id)
                trace["deep_research_engines"] = list_providers()
                search_results, dr_trace = await deep_research_pipeline(
                    latest_question,
                    target_results=20,
                )
                trace["deep_research_pipeline"] = dr_trace
            else:
                # Rate limit hit: fall back to single-engine search
                trace["deep_research_fallback"] = "rate_limited"
                search_results = await async_web_search(
                    search_query,
                    max_results=6,
                    original_query=latest_question,
                )
        else:
            # Standard Web Search: tier-1 paid (Serper/Brave) primary via
            # registry, falls back to DDG / free providers when exhausted.
            search_results = await async_search_all(
                search_query,
                max_results=6,
                deep=False,
                original_query=latest_question,
            )

        if search_results:
            retrieved_context = search_results + retrieved_context

    context_text = format_context(retrieved_context)
    context_budget = trim_to_token_budget(context_text, settings.max_context_tokens)
    context_text = context_budget.text

    trace["used_context_count"] = len(retrieved_context)
    trace["bq_hits"] = len([item for item in retrieved_context if item.get("backend") == "bigquery"])
    trace["json_hits"] = len([item for item in retrieved_context if item.get("backend") == "json"])
    trace["web_search_hits"] = len([item for item in retrieved_context if _is_search_context(item)])
    trace["context_sources"] = [
        {"title": item.get("title"), "source": item.get("source"), "backend": item.get("backend", "unknown"), "score": item.get("score")}
        for item in retrieved_context
    ]

    # Multi-turn: prepend conversation history to the prompt query so every
    # provider (which only reads ``messages[-1]["content"]``) still sees the
    # prior turns. Classifiers above already used the un-prefixed
    # `latest_question` so search/tool decisions stay focused on the
    # current turn.
    history_block = _format_conversation_history(history)
    if history_block:
        prompt_query = history_block + latest_question
        trace["history_turns"] = len([m for m in (history or []) if (m.get("content") or "").strip()])
    else:
        prompt_query = latest_question
        trace["history_turns"] = 0

    messages, effective_max_output_tokens = _build_prompt_messages(
        prompt_query,
        context_text,
        language_instructions,
        web_search=web_search,
        research=research,
        max_output_tokens=settings.max_output_tokens,
    )
    return messages, effective_model_choice, effective_max_output_tokens, trace


# MAIN FUNCTION
async def answer_query(
    query,
    model_choice="Llama",
    include_trace=False,
    temperature=0.2,
    user_id="anonymous",
    user_context=None,
    web_search=False,
    research=False,
    history=None,
):
    started_at = time.perf_counter()
    settings = get_settings()
    requested_model_choice = model_choice
    effective_model_choice = model_choice
    user_context = dict(user_context or {})
    user_context.setdefault("user_id", user_id)
    access_policy = build_access_policy(user_context, settings)
    redaction = (
        redact_pii(query)
        if settings.pii_redaction_enabled
        else RedactionResult(query, False, {"emails": 0, "phones": 0})
    )
    safe_query = redaction.text
    telemetry_query = safe_query.split("\n\nFile content:", 1)[0].strip()
    cache_meta = answer_cache.metadata()

    def duration_ms():
        return int((time.perf_counter() - started_at) * 1000)

    async def emit_event(
        response,
        status="ok",
        tool="none",
        cache_hit=False,
        context_items=None,
        error="",
        prompt_text="",
    ):
        await asyncio.to_thread(
            log_chat_event,
            query=telemetry_query,
            model_choice=effective_model_choice,
            duration_ms=duration_ms(),
            status=status,
            tool=tool,
            cache_hit=cache_hit,
            cache_backend=cache_meta["backend"],
            context_items=context_items or [],
            response=response,
            error=error,
            user_id=user_id,
            prompt_text=prompt_text or telemetry_query,
            pii_redacted=redaction.redacted,
            pii_counts=redaction.counts,
        )

    if "The user now asks:" in safe_query:
        latest_question = safe_query.split("The user now asks:")[-1].strip()
    else:
        latest_question = safe_query.strip()

    safe_query_budget = trim_to_token_budget(safe_query, settings.max_input_tokens)
    latest_question_budget = trim_to_token_budget(latest_question, settings.max_input_tokens)
    safe_query_for_model = safe_query_budget.text
    latest_question = latest_question_budget.text
    await asyncio.to_thread(answer_cache.record_query, latest_question)
    language_context = build_language_context(latest_question, settings)
    language_instructions = language_context.prompt_instructions
    
    custom_instr = await asyncio.to_thread(get_custom_instructions, user_id)
    if custom_instr:
        language_instructions = f"{language_instructions}\n\nUSER PREFERENCE: {custom_instr}".strip()

    trace = {
        "query": latest_question,
        "user_id": user_id,
        "requested_model_choice": requested_model_choice,
        "model_choice": effective_model_choice,
        "temperature": temperature,
        "web_search": web_search,
        "research": research,
        "tool": "none",
        "cache_hit": False,
        "cache_backend": cache_meta["backend"],
        "used_context_count": 0,
        "bq_hits": 0,
        "json_hits": 0,
        "context_sources": [],
        "pii_redacted": redaction.redacted,
        "pii_counts": redaction.counts,
        "prompt_validation": "not_checked",
        "output_moderation": "not_checked",
        "reference_checking": "not_checked",
        "data_access": access_policy.trace(),
        "model_routing": {
            "requested_model": requested_model_choice,
            "selected_model": effective_model_choice,
            "routed": False,
            "reason": "not_checked",
        },
        "token_budget": {
            "max_input_tokens": settings.max_input_tokens,
            "max_context_tokens": settings.max_context_tokens,
            "max_output_tokens": settings.max_output_tokens,
            "safe_query_tokens_est": safe_query_budget.original_tokens,
            "safe_query_trimmed": safe_query_budget.trimmed,
            "latest_question_tokens_est": latest_question_budget.original_tokens,
            "latest_question_trimmed": latest_question_budget.trimmed,
            "context_tokens_est": 0,
            "context_trimmed": False,
        },
        "language": language_context.trace(),
    }

    prompt_guardrail = validate_prompt(
        latest_question,
        settings.forbidden_topic_patterns,
        enabled=settings.prompt_validation_enabled,
    )
    trace["prompt_validation"] = "passed" if prompt_guardrail.allowed else "blocked"

    if not prompt_guardrail.allowed:
        trace["status"] = "blocked"
        trace["guardrail_reason"] = prompt_guardrail.reason
        await emit_event(
            SAFE_COMPLETION,
            status="blocked",
            error=prompt_guardrail.reason,
            prompt_text=latest_question,
        )
        return _result(SAFE_COMPLETION, include_trace, trace)

    routing = select_model_for_query(latest_question, requested_model_choice, settings)
    effective_model_choice = routing.selected_model
    trace["model_choice"] = effective_model_choice
    trace["model_routing"] = routing.trace()

    if len(safe_query) > 1000:
        try:
            response = await asyncio.to_thread(
                file_analyzer_tool,
                safe_query_for_model,
                effective_model_choice,
                max_output_tokens=settings.max_output_tokens,
                language_instructions=language_instructions,
            )
            output_guardrail = moderate_output(
                response,
                settings.output_moderation_patterns,
                enabled=settings.output_moderation_enabled,
            )
            trace["tool"] = "file"
            trace["output_moderation"] = "passed" if output_guardrail.allowed else "blocked"
            if not output_guardrail.allowed:
                response = SAFE_COMPLETION
                trace["status"] = "blocked"
                trace["guardrail_reason"] = output_guardrail.reason
                await emit_event(
                    response,
                    status="blocked",
                    tool="file",
                    error=output_guardrail.reason,
                    prompt_text=safe_query,
                )
                return _result(response, include_trace, trace)

            trace["status"] = _status_for_response(response)
            await emit_event(
                response,
                status=_status_for_response(response),
                tool="file",
                prompt_text=safe_query,
            )
            return _result(response, include_trace, trace)
        except Exception as e:
            response = f"Error: {str(e)}"
            trace["tool"] = "file"
            trace["status"] = "error"
            trace["error"] = str(e)
            await emit_event(response, status="error", tool="file", error=str(e), prompt_text=safe_query)
            return _result(response, include_trace, trace)

    # Parallel pre-search: tool decision + RAG retrieval + informational
    # classifier all run together to shave ~1-2s of serial latency. If the
    # tool turns out to be "calculator" we short-circuit and discard the
    # other results, but most queries benefit from the overlap.
    needs_info_check = not web_search and not research

    async def _maybe_info_check() -> bool:
        if not needs_info_check:
            return False
        return await is_informational_query(latest_question, effective_model_choice)

    tool_task = decide_tool_llm(latest_question, effective_model_choice, temperature=0.0)
    rag_task = asyncio.to_thread(
        retrieve_context,
        latest_question,
        allowed_sources=access_policy.allowed_sources if access_policy.enabled else None,
    )
    info_task = _maybe_info_check()

    tool, parallel_retrieved_context, parallel_is_info = await asyncio.gather(
        tool_task, rag_task, info_task
    )
    trace["tool"] = tool

    if tool == "calculator":
        response = calculator_tool(latest_question)
        output_guardrail = moderate_output(
            response,
            settings.output_moderation_patterns,
            enabled=settings.output_moderation_enabled,
        )
        trace["output_moderation"] = "passed" if output_guardrail.allowed else "blocked"
        if not output_guardrail.allowed:
            response = SAFE_COMPLETION
            trace["status"] = "blocked"
            trace["guardrail_reason"] = output_guardrail.reason
            await emit_event(
                response,
                status="blocked",
                tool="calculator",
                error=output_guardrail.reason,
                prompt_text=latest_question,
            )
            return _result(response, include_trace, trace)

        trace["status"] = _status_for_response(response)
        await emit_event(
            response,
            status=_status_for_response(response),
            tool="calculator",
            prompt_text=latest_question,
        )
        return _result(response, include_trace, trace)

    # Reuse the values gathered in parallel above (avoids re-running these
    # expensive calls in the answer_query path).
    retrieved_context = parallel_retrieved_context

    # Inject web search results when toggled or when the query needs current external knowledge.
    if needs_info_check and parallel_is_info:
        web_search = True
        trace["auto_routed_to_search"] = True
        logger.info("auto_routed_to_search query=%s", latest_question)
    trace["web_search"] = web_search

    if web_search or research:
        # Rewrite vague queries into diversified search variants via LLM.
        # Deep mode produces 5 variants hitting different source tiers.
        search_query = await interpret_search_intent(latest_question, deep=research)
        trace["search_intent_original"] = latest_question
        trace["search_intent_rewritten"] = search_query
        trace["search_intent_model"] = "Llama"
        trace["search_query_count"] = len(search_query)

        if research:
            # Deep Research: recursive pipeline with decomposition + gap analysis
            allowed, remaining = await asyncio.to_thread(check_deep_research_limit, user_id)
            trace["deep_research_allowed"] = allowed
            trace["deep_research_remaining"] = remaining
            if allowed:
                await asyncio.to_thread(consume_deep_research_use, user_id)
                trace["deep_research_engines"] = list_providers()
                search_results, dr_trace = await deep_research_pipeline(
                    latest_question,
                    target_results=20,
                )
                trace["deep_research_pipeline"] = dr_trace
            else:
                trace["deep_research_fallback"] = "rate_limited"
                search_results = await async_web_search(
                    search_query,
                    max_results=6,
                    original_query=latest_question,
                )
        else:
            # Standard Web Search: registry routes to Serper/Brave primary, DDG fallback
            search_results = await async_search_all(
                search_query,
                max_results=6,
                deep=False,
                original_query=latest_question,
            )

        if search_results:
            retrieved_context = search_results + retrieved_context

    context_text = format_context(retrieved_context)
    context_budget = trim_to_token_budget(context_text, settings.max_context_tokens)
    context_text = context_budget.text
    trace["token_budget"]["context_tokens_est"] = context_budget.original_tokens
    trace["token_budget"]["context_trimmed"] = context_budget.trimmed
    trace["used_context_count"] = len(retrieved_context)
    trace["bq_hits"] = len([item for item in retrieved_context if item.get("backend") == "bigquery"])
    trace["json_hits"] = len([item for item in retrieved_context if item.get("backend") == "json"])
    trace["web_search_hits"] = len([item for item in retrieved_context if _is_search_context(item)])
    trace["context_sources"] = [
        {
            "title": item.get("title"),
            "source": item.get("source"),
            "backend": item.get("backend", "unknown"),
            "score": item.get("score"),
        }
        for item in retrieved_context
    ]
    cache_key = answer_cache.make_key(
        latest_question,
        effective_model_choice,
        context_text,
        instruction_context=language_instructions,
    )

    # Multi-turn: prepend conversation history to the prompt query for the
    # LLM call. The cache key intentionally uses `latest_question` *without*
    # history — repeats of the same question with the same context should
    # hit the same cache entry regardless of preceding turns.
    history_block = _format_conversation_history(history)
    if history_block:
        prompt_query = history_block + latest_question
        trace["history_turns"] = len(
            [m for m in (history or []) if (m.get("content") or "").strip()]
        )
    else:
        prompt_query = latest_question
        trace["history_turns"] = 0

    messages, effective_max_output_tokens = _build_prompt_messages(
        prompt_query,
        context_text,
        language_instructions,
        web_search=web_search,
        research=research,
        max_output_tokens=settings.max_output_tokens,
    )
    prompt_text = _messages_to_text(messages)
    cached_response = await asyncio.to_thread(answer_cache.get, cache_key)

    if cached_response:
        reference_check = check_references(
            cached_response,
            retrieved_context,
            enabled=settings.reference_checking_enabled,
        )
        trace["reference_checking"] = "passed" if reference_check.passed else "fixed"
        if not reference_check.passed:
            cached_response = append_reference_notice(cached_response, retrieved_context)

        output_guardrail = moderate_output(
            cached_response,
            settings.output_moderation_patterns,
            enabled=settings.output_moderation_enabled,
        )
        trace["output_moderation"] = "passed" if output_guardrail.allowed else "blocked"
        if not output_guardrail.allowed:
            cached_response = SAFE_COMPLETION
            trace["status"] = "blocked"
            trace["guardrail_reason"] = output_guardrail.reason
            await emit_event(
                cached_response,
                status="blocked",
                cache_hit=True,
                context_items=retrieved_context,
                error=output_guardrail.reason,
                prompt_text=prompt_text,
            )
            return _result(cached_response, include_trace, trace)

        trace["cache_hit"] = True
        trace["status"] = "ok"
        await emit_event(
            cached_response,
            cache_hit=True,
            context_items=retrieved_context,
            prompt_text=prompt_text,
        )
        return _result(cached_response, include_trace, trace)

    try:
        response = await asyncio.to_thread(
            chat_completion,
            messages,
            effective_model_choice,
            temperature=temperature,
            max_output_tokens=effective_max_output_tokens,
        )
        output_guardrail = moderate_output(
            response,
            settings.output_moderation_patterns,
            enabled=settings.output_moderation_enabled,
        )
        trace["output_moderation"] = "passed" if output_guardrail.allowed else "blocked"
        if not output_guardrail.allowed:
            response = SAFE_COMPLETION
            trace["status"] = "blocked"
            trace["guardrail_reason"] = output_guardrail.reason
            await emit_event(
                response,
                status="blocked",
                context_items=retrieved_context,
                error=output_guardrail.reason,
                prompt_text=prompt_text,
            )
            return _result(response, include_trace, trace)

        reference_check = check_references(
            response,
            retrieved_context,
            enabled=settings.reference_checking_enabled,
        )
        trace["reference_checking"] = "passed" if reference_check.passed else "fixed"
        if not reference_check.passed:
            trace["reference_check_reason"] = reference_check.reason
            response = append_reference_notice(response, retrieved_context)

        status = _status_for_response(response)

        if status == "ok":
            await asyncio.to_thread(answer_cache.set, cache_key, response)

        trace["status"] = status
        await emit_event(response, status=status, context_items=retrieved_context, prompt_text=prompt_text)
        return _result(response, include_trace, trace)
    except Exception as e:
        response = f"Error: {str(e)}"
        trace["status"] = "error"
        trace["error"] = str(e)
        await emit_event(
            response,
            status="error",
            context_items=retrieved_context,
            error=str(e),
            prompt_text=prompt_text,
        )
        return _result(response, include_trace, trace)


async def answer_query_with_trace(
    query,
    model_choice="Llama",
    temperature=0.2,
    user_id="anonymous",
    user_context=None,
):
    return await answer_query(
        query,
        model_choice=model_choice,
        include_trace=True,
        temperature=temperature,
        user_id=user_id,
        user_context=user_context,
    )
