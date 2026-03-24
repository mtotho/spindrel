"""Shared helpers for ARR media stack tools."""

import json
import re

# Patterns that indicate prompt injection in free-text fields
_INJECTION_PATTERNS = re.compile(
    r"(?i)"
    r"(?:ignore\s+(?:all\s+)?previous|you\s+are\s+now|"
    r"\[SYSTEM\]|disregard|new\s+instructions|"
    r"forget\s+(?:all\s+)?(?:your\s+)?instructions|"
    r"override\s+(?:your\s+)?(?:system|prompt))",
)


def sanitize(text: str, max_len: int = 500) -> str:
    """Strip prompt injection patterns and truncate untrusted free-text."""
    if not text:
        return text
    cleaned = _INJECTION_PATTERNS.sub("[filtered]", text)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "..."
    return cleaned


def error(msg: str) -> str:
    return json.dumps({"error": msg})
