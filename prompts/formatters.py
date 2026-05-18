NO_CONTEXT_MESSAGE = "No relevant local context found."

RAG_ANSWER_PROMPT = """Answer the user's question thoroughly and accurately. Treat this as a well-researched answer, not a quick summary.

Instructions:
- First use the retrieved context when it is relevant. Use it fully — do not artificially truncate.
- Cite retrieved context with reference markers like [n] or by naming the title/source.
- If the context does not contain the answer, say that clearly and then use general knowledge.
- Do not invent facts that are not supported by the context.
- Calibrate confidence: distinguish "strong evidence", "limited evidence", and "speculation".

OUTPUT STRUCTURE (use these exact headings when the question is non-trivial; for trivial lookups a direct answer is fine):

## Direct Answer
A complete, well-developed answer to the user's question (3-8 sentences). Include specific numbers, dates, versions, or names where available. Cite [n].

## Key Details
3-7 bullets covering the most important specifics, evidence, or steps from the context. Each bullet must be substantive — at least one full sentence with a citation [n].

## Deep Dive / Explanation
Walk through the reasoning, background, or mechanics. Use multiple paragraphs if needed. Explain why things work the way they do, not just what they are. Cite [n].

## Tradeoffs & Nuance
(Include when the question involves comparisons, decisions, or contested topics.) Surface real-world tradeoffs, contradictions, or competing viewpoints found in the sources.

## Caveats & Confidence
What's unknown, outdated, weakly supported, or out of scope. Be explicit about confidence levels.

## Recommendation (if applicable)
A practical, decisive recommendation calibrated to the user's likely intent.

Language and style:
{language_instructions}

User Question:
{user_query}

Retrieved Context:
{context}

Answer:"""

BIGDATA_ANALYSIS_PROMPT = """SQL Query:
{sql_query}

Results Summary:
{results_summary}

User Question:
{user_query}

Provide analysis:"""

SQL_EXPLANATION_PROMPT = """Explain this SQL query:
{sql_query}"""

WEB_SEARCH_PROMPT = """You are operating in SMART SEARCH mode with live web results. Synthesize researched intelligence — a full analysis, not a snippet summary. Your audience is a technical professional who wants depth, not a tl;dr.

GROUNDING RULES
- Base every factual claim ONLY on the numbered web results below. Cite with [n] markers.
- Do NOT use pre-trained knowledge for facts, dates, names, numbers, prices, versions, or current events. General reasoning and definitions are fine if clearly framed as such.
- If results are thin or off-topic, say so explicitly in Direct Answer — do not invent supporting evidence. Use this exact phrase if nothing relevant was found: "I couldn't find current information on that topic from live web search."
- When results include dates, use them. For time-sensitive questions, prefer the most recent source and call out staleness when relevant.

EVIDENCE DISCIPLINE
- Weight sources: official docs / research / GitHub / benchmarks > forums / community > general blogs.
- If sources contradict each other, acknowledge it and explain the likely reason (different versions, dates, contexts, opinions).
- If multiple sources agree, note the strength of consensus.
- Calibrate confidence honestly: "strong evidence", "limited evidence", "conflicting reports", "speculative".

OUTPUT STRUCTURE (use these exact headings when the question is non-trivial; for simple lookups, give a direct multi-sentence answer with citations)

## Direct Answer
A complete, well-developed answer (4-10 sentences). Include specific numbers, dates, versions, or names where the sources provide them. Do not stop at a surface-level summary — explain the "why" and "how". Cite [n].

## Key Findings
5-8 bullets with the most important specifics from the results. Each bullet must be substantive (at least one full sentence with specifics, not generic statements). Every bullet cited with [n].

## Deep Dive / Background
Walk through the supporting reasoning, history, architecture, or mechanics. Use multiple paragraphs if the sources provide enough material. Explain patterns and cause-effect relationships. Cite [n].

## Tradeoffs / Nuance
(Include when the question involves comparisons, decisions, or contested topics.) Surface real-world tradeoffs, contradictions, or competing perspectives. Do not declare simplistic winners.

## Caveats & Confidence
What's unknown, outdated, weakly supported, or out of scope. Be explicit about confidence levels.

## Recommendation (if applicable)
A practical, decisive recommendation calibrated to the user's likely intent. If a clean recommendation isn't possible, say so and explain what additional information would unlock one.

Language and style:
{language_instructions}

User Question:
{user_query}

Web Search Results:
{context}

Answer:"""


def format_context_snippets(context_snippets: list[str], limit: int = 10) -> str:
    return "\n\n".join(context_snippets[:limit]) if context_snippets else NO_CONTEXT_MESSAGE
