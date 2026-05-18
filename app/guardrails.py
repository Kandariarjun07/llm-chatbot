import re
from dataclasses import dataclass
from typing import Any


DEFAULT_FORBIDDEN_TOPIC_PATTERNS = (
    r"\bmake\s+(?:a\s+)?bomb\b",
    r"\bbuild\s+(?:a\s+)?bomb\b",
    r"\b(?:kill|murder|assassinate)\s+(?:someone|a person|people)\b",
    r"\bself[-\s]?harm\b",
    r"\bsuicide\b",
    r"\b(?:steal|exfiltrate)\s+(?:passwords?|credentials?|api keys?)\b",
    r"\b(?:bypass|crack)\s+(?:login|password|authentication)\b",
    r"\bmalware\b",
    r"\bransomware\b",
)

DEFAULT_OUTPUT_MODERATION_PATTERNS = (
    r"\bhere(?:'s| is)\s+how\s+to\s+(?:make|build)\s+(?:a\s+)?bomb\b",
    r"\bsteps?\s+to\s+(?:kill|murder|assassinate)\b",
    r"\b(?:steal|exfiltrate)\s+(?:passwords?|credentials?|api keys?)\b",
    r"\bdeploy\s+(?:malware|ransomware)\b",
)


# Heuristic indicators of a prompt-injection attempt. These are not
# foolproof — a determined attacker can paraphrase around them — but
# they catch the lazy, copy-pasted jailbreak prompts that make up the
# vast majority of real-world abuse attempts. The patterns deliberately
# require strong signal (verb + target) rather than single suspicious
# words, to keep the false-positive rate sane on legitimate engineering
# questions like "ignore the previous error and try again".
PROMPT_INJECTION_PATTERNS = (
    r"ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?|directives?)",
    r"disregard\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?)",
    r"forget\s+(?:everything|all)\s+(?:you|that)\s+(?:were|have been|was)\s+told",
    r"you\s+are\s+now\s+(?:a\s+)?(?:new|different)\s+(?:ai|assistant|model|bot)",
    r"act\s+as\s+(?:if\s+)?(?:you\s+(?:are|were)\s+)?(?:dan|jailbroken|unrestricted|no\s+rules)",
    r"reveal\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions?|directives?)",
    r"(?:print|show|display|output|leak|repeat)\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions?)",
    r"what\s+(?:are|were)\s+(?:your|the)\s+(?:system\s+)?(?:instructions?|prompts?)",
    r"developer\s+mode|dan\s+mode|jailbreak\s+mode",
    r"<\s*\|\s*im_start\s*\|\s*>\s*system",  # raw chat-template injection
    # Indirect injection markers commonly found in poisoned documents.
    r"###\s*new\s+(?:instructions?|task|prompt)\s*###",
    r"\[\s*system\s*\]\s*:\s*you\s+(?:are|must|will)",
)

SAFE_COMPLETION = (
    "I can't help with that request. I can still help with safe, educational, "
    "or defensive information on the topic."
)


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reason: str = ""
    matched_pattern: str = ""


@dataclass(frozen=True)
class ReferenceCheckResult:
    passed: bool
    reason: str = ""


def _split_patterns(value: str | None) -> list[str]:
    if not value:
        return []
    return [pattern.strip() for pattern in value.split("||") if pattern.strip()]


def _compile_patterns(patterns: list[str] | tuple[str, ...]) -> list[re.Pattern]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            continue
    return compiled


def detect_prompt_injection(prompt: str) -> GuardrailResult:
    """Return a non-allowed result if the prompt looks like an injection attempt.

    Kept as a standalone function (rather than inlined into
    ``validate_prompt``) so callers like the orchestrator can decide
    whether to *block* the prompt outright, *strip* the suspicious lines,
    or merely *log* the signal without disrupting the user's request.
    """
    text = prompt or ""
    for pattern in _compile_patterns(list(PROMPT_INJECTION_PATTERNS)):
        if pattern.search(text):
            return GuardrailResult(
                False,
                reason="Prompt matched a prompt-injection heuristic.",
                matched_pattern=pattern.pattern,
            )
    return GuardrailResult(True)


def validate_prompt(
    prompt: str,
    custom_patterns: str | None = None,
    *,
    enabled: bool = True,
    check_injection: bool = True,
) -> GuardrailResult:
    if not enabled:
        return GuardrailResult(True)

    patterns = [*DEFAULT_FORBIDDEN_TOPIC_PATTERNS, *_split_patterns(custom_patterns)]
    for pattern in _compile_patterns(patterns):
        if pattern.search(prompt or ""):
            return GuardrailResult(
                False,
                reason="Prompt matched a forbidden topic rule.",
                matched_pattern=pattern.pattern,
            )

    # Treat prompt-injection attempts as a sub-class of forbidden content.
    # Disabled per-call when callers (e.g. internal LLM utilities that
    # legitimately reference "the previous instructions") need to opt out.
    if check_injection:
        injection = detect_prompt_injection(prompt)
        if not injection.allowed:
            return injection

    return GuardrailResult(True)


def moderate_output(
    output: str,
    custom_patterns: str | None = None,
    *,
    enabled: bool = True,
) -> GuardrailResult:
    if not enabled:
        return GuardrailResult(True)

    patterns = [*DEFAULT_OUTPUT_MODERATION_PATTERNS, *_split_patterns(custom_patterns)]
    for pattern in _compile_patterns(patterns):
        if pattern.search(output or ""):
            return GuardrailResult(
                False,
                reason="Model output matched a moderation rule.",
                matched_pattern=pattern.pattern,
            )

    return GuardrailResult(True)


def _source_tokens(context_items: list[dict[str, Any]]) -> set[str]:
    tokens = set()
    for index, item in enumerate(context_items, start=1):
        tokens.add(f"[{index}]")
        for key in ("title", "source"):
            value = str(item.get(key) or "").strip()
            if value:
                tokens.add(value.lower())
    return tokens


def check_references(
    answer: str,
    context_items: list[dict[str, Any]],
    *,
    enabled: bool = True,
) -> ReferenceCheckResult:
    if not enabled or not context_items:
        return ReferenceCheckResult(True)

    answer_text = (answer or "").lower()
    if not answer_text.strip() or answer_text.startswith("error:"):
        return ReferenceCheckResult(True)

    for token in _source_tokens(context_items):
        if token and token.lower() in answer_text:
            return ReferenceCheckResult(True)

    return ReferenceCheckResult(
        False,
        "Answer used retrieved context but did not reference any retrieved title, source, or citation marker.",
    )


def append_reference_notice(answer: str, context_items: list[dict[str, Any]]) -> str:
    references = []
    for index, item in enumerate(context_items, start=1):
        title = str(item.get("title") or "Untitled").strip()
        source = str(item.get("source") or "unknown").strip()
        references.append(f"[{index}] {title} ({source})")

    if not references:
        return answer

    return f"{answer.rstrip()}\n\nReferences checked:\n" + "\n".join(references)
