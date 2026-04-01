"""Shared helpers for ARR media stack tools."""

import json
import re
from urllib.parse import urlparse

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


def validate_url(url: str, service_name: str) -> str | None:
    """Validate a service URL. Returns an error string if invalid, None if OK."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"{service_name} URL is malformed (missing http:// or bad scheme): {url!r}"
    if not parsed.hostname:
        return f"{service_name} URL has no hostname: {url!r}"
    try:
        if parsed.port is not None and parsed.port < 0:
            return f"{service_name} URL has invalid port: {url!r}"
    except ValueError:
        return f"{service_name} URL has invalid port (check for typos in the IP address): {url!r}"
    return None
