import hashlib
import math
import re
from dataclasses import dataclass


EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")

# Credit-card-shaped 13–19 digit runs with optional spaces/dashes. We
# additionally verify with Luhn before redacting so we don't munge order
# numbers or invoice IDs that happen to look like card numbers.
CREDIT_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

# Indian-specific IDs commonly pasted into chats.
# Aadhaar: 12 digits, often grouped 4-4-4 with spaces.
AADHAAR_PATTERN = re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")
# PAN: AAAAA9999A — 5 letters, 4 digits, 1 letter.
PAN_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

# US SSN: NNN-NN-NNNN. Strict on separators to keep false positives low.
SSN_PATTERN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

# API keys and other high-entropy secrets. These rules are intentionally
# conservative: matching real-world key prefixes for known providers
# rather than any base64-looking blob, which would mangle a lot of
# legitimate content.
API_KEY_PATTERN = re.compile(
    r"\b("
    r"sk-[A-Za-z0-9]{20,}"           # OpenAI / OpenAI-compatible
    r"|gsk_[A-Za-z0-9]{20,}"         # Groq
    r"|AIza[0-9A-Za-z_\-]{20,}"      # Google API keys
    r"|AKIA[0-9A-Z]{16}"             # AWS access key id
    r"|ghp_[A-Za-z0-9]{20,}"         # GitHub personal access token
    r"|xox[baprs]-[A-Za-z0-9-]{10,}" # Slack tokens
    r")\b"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted: bool
    counts: dict[str, int]


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _luhn_valid(digits: str) -> bool:
    """Return True if a numeric string passes the Luhn checksum.

    Used to distinguish actual card numbers from arbitrary long digit
    runs (order ids, account numbers, etc.) before redacting.
    """
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        if not ch.isdigit():
            return False
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def redact_pii(text: str) -> RedactionResult:
    counts = {
        "emails": 0,
        "phones": 0,
        "credit_cards": 0,
        "aadhaar": 0,
        "pan": 0,
        "ssn": 0,
        "api_keys": 0,
    }

    def replace_email(_match):
        counts["emails"] += 1
        return "[REDACTED_EMAIL]"

    def replace_phone(_match):
        counts["phones"] += 1
        return "[REDACTED_PHONE]"

    def replace_credit_card(match):
        digits = re.sub(r"[ -]", "", match.group(0))
        # Skip non-card-looking runs to avoid false positives on order
        # numbers, invoice IDs, etc.
        if len(digits) < 13 or len(digits) > 19 or not _luhn_valid(digits):
            return match.group(0)
        counts["credit_cards"] += 1
        return "[REDACTED_CARD]"

    def replace_aadhaar(_match):
        counts["aadhaar"] += 1
        return "[REDACTED_AADHAAR]"

    def replace_pan(_match):
        counts["pan"] += 1
        return "[REDACTED_PAN]"

    def replace_ssn(_match):
        counts["ssn"] += 1
        return "[REDACTED_SSN]"

    def replace_api_key(_match):
        counts["api_keys"] += 1
        return "[REDACTED_API_KEY]"

    redacted_text = text or ""
    # Order matters: redact the highest-entropy patterns first so a
    # PAN-looking substring inside an email local-part can't be
    # accidentally stripped first.
    redacted_text = API_KEY_PATTERN.sub(replace_api_key, redacted_text)
    redacted_text = EMAIL_PATTERN.sub(replace_email, redacted_text)
    redacted_text = AADHAAR_PATTERN.sub(replace_aadhaar, redacted_text)
    redacted_text = CREDIT_CARD_PATTERN.sub(replace_credit_card, redacted_text)
    redacted_text = SSN_PATTERN.sub(replace_ssn, redacted_text)
    redacted_text = PAN_PATTERN.sub(replace_pan, redacted_text)
    # Phones LAST — the phone regex is permissive enough that it would
    # otherwise eat parts of Aadhaar / card numbers we want named.
    redacted_text = PHONE_PATTERN.sub(replace_phone, redacted_text)

    return RedactionResult(
        text=redacted_text,
        redacted=any(counts.values()),
        counts=counts,
    )
