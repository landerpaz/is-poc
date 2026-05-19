import re

# ---------------------------------------------------------------------------
# Email masking
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)


def _mask_email(match: re.Match) -> str:
    full = match.group(0)
    local, domain = full.split("@", 1)
    masked_local = local[0] + "***" if len(local) > 1 else "***"
    parts = domain.split(".")
    masked_domain = parts[0][0] + "***" if len(parts[0]) > 1 else "***"
    tld = parts[-1]
    return f"{masked_local}@{masked_domain}.{tld}"


def mask_emails(text: str) -> str:
    """Replace email addresses with a masked form (e.g. j***@e***.com)."""
    return _EMAIL_RE.sub(_mask_email, text)


# ---------------------------------------------------------------------------
# Prompt injection detection
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: list[re.Pattern] = [
    # instruction override
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|your)\s+(instructions?|prompts?|rules?|constraints?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above|your)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(your|the|previous)\s+(instructions?|prompts?|rules?|context)", re.IGNORECASE),
    re.compile(r"override\s+(your\s+)?(instructions?|rules?|constraints?|system\s+prompt)", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(your\s+)?(instructions?|rules?|guidelines?)", re.IGNORECASE),

    # persona hijack
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(a\s+|an\s+)?(?!application|agent)", re.IGNORECASE),
    re.compile(r"\bpretend\s+(you\s+are|to\s+be)\b", re.IGNORECASE),
    re.compile(r"\broleplay\s+as\b", re.IGNORECASE),
    re.compile(r"\byour\s+new\s+(role|persona|identity|instructions?)\b", re.IGNORECASE),

    # system prompt extraction
    re.compile(r"\brepeat\s+(your|the)\s+system\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bprint\s+(your|the)\s+(system\s+prompt|instructions?)\b", re.IGNORECASE),
    re.compile(r"\bshow\s+me\s+(your|the)\s+(system\s+prompt|instructions?)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(are|is)\s+your\s+(system\s+prompt|instructions?|rules?)\b", re.IGNORECASE),

    # jailbreaks
    re.compile(r"\bDAN\b"),                          # "Do Anything Now"
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+mode\b", re.IGNORECASE),
    re.compile(r"\bno\s+restrictions?\b", re.IGNORECASE),

    # inline injection markers
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"\[system\]", re.IGNORECASE),
    re.compile(r"#{2,}\s*system", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"system\s+prompt\s*:", re.IGNORECASE),
]


class PromptInjectionError(ValueError):
    """Raised when a prompt injection attempt is detected in user input."""


def check_prompt_injection(text: str) -> None:
    """Raise PromptInjectionError if the text contains injection patterns."""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            raise PromptInjectionError(
                f"Input blocked: possible prompt injection detected "
                f"(matched pattern: {pattern.pattern!r})."
            )


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------

def sanitize(text: str) -> str:
    """
    Validate and sanitize user input before it reaches the LLM.

    Steps:
      1. Detect prompt injection → raises PromptInjectionError if found.
      2. Mask email addresses in-place.

    Returns the sanitized text.
    """
    check_prompt_injection(text)
    return mask_emails(text)
