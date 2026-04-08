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


def coerce_list(value, item_type=None):
    """Coerce a value that should be a list but might arrive as a JSON string.

    LLMs frequently pass array parameters as JSON-encoded strings, e.g.
    ``"[1, 2, 3]"`` instead of ``[1, 2, 3]``.  This helper normalises both
    forms to a plain Python list, with optional per-item type conversion.
    """
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            value = json.loads(value)
        else:
            # Single bare value
            value = [value]
    if not isinstance(value, list):
        value = [value]
    if item_type is not None:
        value = [item_type(v) for v in value]
    return value


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
