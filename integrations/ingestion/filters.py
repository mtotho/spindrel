"""Layer 2 — Deterministic injection filters.

Checks:
  - Zero-width / invisible unicode characters
  - NFKC normalization then regex matching against known prompt-injection patterns
"""

import re
import unicodedata

# Zero-width and invisible characters that should never appear in legitimate text
_ZERO_WIDTH_CHARS: set[str] = {
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\u2060",  # word joiner
    "\ufeff",  # zero width no-break space / BOM
    "\u00ad",  # soft hyphen
    "\u200e",  # left-to-right mark
    "\u200f",  # right-to-left mark
    "\u2061",  # function application
    "\u2062",  # invisible times
    "\u2063",  # invisible separator
    "\u2064",  # invisible plus
}

# Patterns matched against NFKC-normalized, lowercased text.
# Each tuple: (pattern_name, compiled_regex)
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_previous", re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|context)", re.IGNORECASE)),
    ("system_prompt_override", re.compile(r"(you\s+are\s+now|new\s+instructions?|override\s+system\s+prompt)", re.IGNORECASE)),
    ("role_injection", re.compile(r"<\s*\|?\s*(system|assistant|user)\s*\|?\s*>", re.IGNORECASE)),
    ("prompt_leak_request", re.compile(r"(repeat|reveal|show|output|print)\s+(your\s+)?(system\s+prompt|instructions|initial\s+prompt)", re.IGNORECASE)),
    ("jailbreak_dan", re.compile(r"\bD\.?A\.?N\.?\b.*\bmode\b", re.IGNORECASE)),
    ("base64_payload", re.compile(r"(decode|eval|execute)\s+(this\s+)?base64", re.IGNORECASE)),
    ("markdown_injection", re.compile(r"!\[.*?\]\(https?://", re.IGNORECASE)),
    ("hidden_instruction", re.compile(r"(hidden|secret)\s+instruction", re.IGNORECASE)),
]


def detect_zero_width(text: str) -> list[str]:
    """Return flag names for any zero-width / invisible characters found."""
    found = _ZERO_WIDTH_CHARS.intersection(text)
    if found:
        return [f"zero_width_char:U+{ord(c):04X}" for c in sorted(found)]
    return []


def detect_injection_patterns(text: str) -> list[str]:
    """Return flag names for regex-matched injection patterns in normalized text."""
    normalized = unicodedata.normalize("NFKC", text)
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(normalized)]


def run_filters(text: str) -> list[str]:
    """Run all Layer 2 filters. Returns list of flag names (empty = clean)."""
    flags: list[str] = []
    flags.extend(detect_zero_width(text))
    flags.extend(detect_injection_patterns(text))
    return flags
