"""Detect and correct tool-refusal history poisoning.

When a weak model once says "I don't have that tool" in a turn, that assistant
message enters the conversation history. On subsequent turns, even capable
models tend to pattern-match on those prior refusals and refuse again — even
when the tool IS now present in the authorized tool list.

This module scans recent assistant turns for refusal phrases combined with
references to currently-authorized tools, and builds a corrective system
message that:

- Standing (A): reminds the model that tool availability is reassessed per
  turn and the current tool list is authoritative.
- Targeted (B): names the specific tools that were refused in the past but
  ARE in the current list, and explicitly tells the model those prior
  refusals were stale.

The block is injected in the late, cache-safe band of context_assembly — it
sits alongside the temporal block and pinned-widget block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Phrases that indicate the assistant refused or disclaimed tool access.
# Matched case-insensitively as substrings. Kept conservative to avoid false
# positives on neutral statements.
_REFUSAL_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bnot (?:currently )?available\b",
        r"\b(?:do|does) not have access\b",
        r"\bdon't have access\b",
        r"\bdon't have (?:a|the|any) (?:tool|ability)\b",
        r"\bunable to (?:perform|execute|access|call|use|search)\b",
        r"\bcannot (?:perform|execute|access|call|use|search)\b",
        r"\bcan't (?:perform|execute|access|call|use|search)\b",
        r"\bnot (?:in my|currently in my) (?:configuration|tool list|available tools)\b",
        r"\bI lack (?:the|access)\b",
        r"\bno (?:tool|access) (?:for|to)\b",
    )
)

# Keep the scan window small — we care about recent context, not ancient
# history. 5 assistant turns covers one full conversational back-and-forth
# plus a buffer.
_ASSISTANT_SCAN_LIMIT = 5

# Cap the targeted list to keep the injected message short. If more than N
# tools were refused, we stop naming them and fall back to the standing
# message.
_MAX_NAMED_TOOLS = 5


@dataclass
class RefusalScanResult:
    """Output of scanning assistant history for stale tool refusals."""
    any_refusal: bool
    stale_refused: list[str]  # names of tools refused earlier that ARE now authorized


def scan_assistant_refusals(
    assistant_contents: list[str],
    authorized_tool_names: set[str],
) -> RefusalScanResult:
    """Scan recent assistant turns for refusal + tool-name co-occurrence.

    Parameters
    ----------
    assistant_contents
        Plain-text content of recent assistant turns, newest first or oldest
        first — order doesn't matter. Only up to _ASSISTANT_SCAN_LIMIT are
        considered.
    authorized_tool_names
        Names of tools authorized for the current turn. A refusal in history
        is "stale" if it names one of these.

    Returns
    -------
    RefusalScanResult
        `any_refusal` is True if any turn matched a refusal pattern.
        `stale_refused` lists tool names that were both refused in history
        AND are currently authorized. Order of first appearance preserved.
    """
    contents = [c for c in assistant_contents if isinstance(c, str) and c.strip()][
        :_ASSISTANT_SCAN_LIMIT
    ]
    if not contents or not authorized_tool_names:
        any_refusal = any(_matches_refusal(c) for c in contents)
        return RefusalScanResult(any_refusal=any_refusal, stale_refused=[])

    seen: set[str] = set()
    stale: list[str] = []
    any_refusal = False

    # Pre-compile word-boundary matchers per tool name so "search" doesn't
    # falsely match inside "search_memory". Underscores are word characters
    # in Python regex, so \b correctly separates tokens.
    name_matchers: list[tuple[str, re.Pattern]] = [
        (name, re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE))
        for name in sorted(authorized_tool_names, key=len, reverse=True)
    ]

    for content in contents:
        if not _matches_refusal(content):
            continue
        any_refusal = True
        for name, matcher in name_matchers:
            if name in seen:
                continue
            if matcher.search(content):
                stale.append(name)
                seen.add(name)
                if len(stale) >= _MAX_NAMED_TOOLS:
                    break
        if len(stale) >= _MAX_NAMED_TOOLS:
            break

    return RefusalScanResult(any_refusal=any_refusal, stale_refused=stale)


def _matches_refusal(text: str) -> bool:
    for pat in _REFUSAL_PATTERNS:
        if pat.search(text):
            return True
    return False


def build_tool_authority_block(result: RefusalScanResult) -> str | None:
    """Build a corrective system message, or None if none needed.

    - If `stale_refused` is non-empty: a named correction naming each stale
      tool and ordering the model to call it when appropriate (B).
    - Else if `any_refusal`: a standing corrective that tool availability
      is per-turn and prior refusals may be stale (A).
    - Else: None — no prior refusals found, no reason to inject.
    """
    if result.stale_refused:
        names = ", ".join(f"`{n}`" for n in result.stale_refused)
        return (
            "⚠️ TOOL AVAILABILITY CORRECTION: In an earlier turn you said one or "
            "more tools were unavailable. That claim is stale — the following "
            f"tools ARE in your current tool list: {names}. "
            "If the user's request matches one of these, CALL IT. Do not refuse "
            "based on memory of prior turns; your current tool list supersedes "
            "any earlier statement about tool availability."
        )
    if result.any_refusal:
        return (
            "⚠️ Note on tool availability: earlier turns in this conversation "
            "disclaimed tool access. Tool availability is reassessed every "
            "turn — your CURRENT tool list is authoritative, and prior refusals "
            "may be stale. If a listed tool fits the user's request, CALL IT."
        )
    return None
