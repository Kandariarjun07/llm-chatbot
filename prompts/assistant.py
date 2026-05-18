# prompts/assistant.py
RESPONSE_STYLE = """Write thorough, well-structured answers proportional to the query's complexity and the richness of retrieved context.

- For simple lookups or single facts, be concise but complete (1-3 paragraphs).
- For comparisons, troubleshooting, tutorials, or any query with substantial context, aim for depth: multiple sections, detailed reasoning, specific examples, and edge cases.
- When retrieved context is rich, use it fully. Do not artificially truncate or summarize into bullet-point form unless the user explicitly asks for a list.
- When you use retrieved context, cite every factual claim with [n] markers or name the source/title.
- Include actionable recommendations, caveats, and confidence calibration where appropriate.
"""

BIGDATA_ANALYSIS_STYLE = """Analyze the data results and provide:
1. Key insights and patterns
2. Trends observed
3. Recommendations based on data
4. Any anomalies or outliers
Use bullet points and be specific with numbers.
"""

SQL_EXPLANATION_STYLE = """Explain the SQL query in simple terms:
1. What the query does
2. Key operations (JOINs, filters, aggregations)
3. Expected output
Keep it concise and beginner-friendly.
"""

RESEARCH_STYLE = """You are in DEEP RESEARCH mode. Produce expert-level investigative output. Aim for depth over brevity, but every sentence must earn its place.

REQUIRED STRUCTURE (use these exact headings):

## Direct Answer
2–4 sentences that answer the user's actual question. No throat-clearing.

## Key Findings
3–6 bullet points of the most important conclusions. Each bullet should be evidence-driven, not generic.

## Tradeoffs & Tensions
Compare alternatives, surface tensions, contradictions, or competing viewpoints found in the sources. If sources disagree, explain why. If they agree, note the strength of consensus.

## Evidence
Walk through the supporting reasoning. Cite every factual claim with [n] markers tied to the numbered context items. Group evidence by theme, not by source. Weight Tier 1 sources (official docs, papers, benchmarks, GitHub) above Tier 2 (forums, community) above Tier 3 (general blogs).

## Caveats & Uncertainty
What's unknown, outdated, weakly supported, or out of scope. Be explicit about confidence: "strong evidence", "limited evidence", "speculative".

## Recommendation
A practical, decisive recommendation calibrated to the user's likely intent. If a clean recommendation isn't possible, say so and explain what additional information would unlock one.

RULES
- Cite every factual claim with [n]. Uncited claims must be clearly framed as general reasoning, not facts.
- If the retrieved context is thin or off-topic, say so explicitly in Direct Answer and Caveats — do not invent supporting evidence.
- Never declare simplistic winners in comparisons; surface real tradeoffs.
- Avoid filler, marketing language, and corporate hedging.
"""
