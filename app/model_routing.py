import re
from dataclasses import dataclass
from typing import Any

from app.security import estimate_tokens


HIGH_RISK_PATTERNS = (
    r"\bmedical\b|\bdiagnos(?:e|is)\b|\btreatment\b",
    r"\blegal\b|\blawsuit\b|\bcontract\b",
    r"\binvest(?:ment|ing)\b|\bstock\b|\btax\b|\bfinancial advice\b",
    r"\bcredential\b|\bsecret\b|\bapi key\b|\bpassword\b",
    r"\bsecurity incident\b|\bbreach\b|\bmalware\b|\bransomware\b",
    r"\banalyze this dataset\b|\bbigquery\b|\bsql query\b",
    r"\n\nfile content:",
)


@dataclass(frozen=True)
class ModelRoutingDecision:
    requested_model: str
    selected_model: str
    routed: bool
    reason: str

    def trace(self) -> dict[str, Any]:
        return {
            "requested_model": self.requested_model,
            "selected_model": self.selected_model,
            "routed": self.routed,
            "reason": self.reason,
        }


def _is_low_risk(query: str, token_threshold: int) -> tuple[bool, str]:
    token_count = estimate_tokens(query)
    if token_count > token_threshold:
        return False, "over_low_risk_token_threshold"

    query_text = query or ""
    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, query_text, re.IGNORECASE):
            return False, "matched_high_risk_pattern"

    return True, "low_risk_short_query"


def select_model_for_query(
    query: str,
    requested_model: str,
    settings: Any,
) -> ModelRoutingDecision:
    if not getattr(settings, "model_auto_routing_enabled", True):
        return ModelRoutingDecision(requested_model, requested_model, False, "disabled")

    cheap_model = getattr(settings, "cheap_model_choice", "Llama")
    premium_model = getattr(settings, "premium_model_choice", "Gemini")
    threshold = getattr(settings, "low_risk_token_threshold", 500)

    requested = requested_model or cheap_model
    is_auto = requested.lower() == "auto"
    is_premium = requested.lower() == premium_model.lower()

    # If user explicitly picked a specific model (not Auto), respect it.
    if not is_auto:
        return ModelRoutingDecision(requested, requested, False, "requested_model_kept")

    low_risk, reason = _is_low_risk(query, threshold)
    if low_risk:
        return ModelRoutingDecision(requested, cheap_model, requested != cheap_model, reason)

    return ModelRoutingDecision(requested, premium_model, True, reason)
