"""Fuzzy matchers for non-deterministic LLM output."""

from __future__ import annotations

import re

from .streaming import StreamEvent


def assert_response_not_empty(text: str, min_chars: int = 5) -> None:
    """Assert the response is non-empty and has meaningful content."""
    assert text is not None, "Response is None"
    stripped = text.strip()
    assert len(stripped) >= min_chars, (
        f"Response too short ({len(stripped)} chars, min {min_chars}): {stripped!r}"
    )


def assert_contains_any(text: str, keywords: list[str]) -> None:
    """Assert that at least one keyword appears in the text (case-insensitive)."""
    lower = text.lower()
    found = [kw for kw in keywords if kw.lower() in lower]
    assert found, (
        f"Expected at least one of {keywords} in response, got: {text[:200]!r}"
    )


def assert_contains_all(text: str, keywords: list[str]) -> None:
    """Assert that all keywords appear in the text (case-insensitive)."""
    lower = text.lower()
    missing = [kw for kw in keywords if kw.lower() not in lower]
    assert not missing, (
        f"Missing keywords {missing} in response: {text[:200]!r}"
    )


def assert_does_not_contain(text: str, forbidden: list[str]) -> None:
    """Assert that none of the forbidden strings appear in the text."""
    lower = text.lower()
    found = [f for f in forbidden if f.lower() in lower]
    assert not found, (
        f"Found forbidden strings {found} in response: {text[:200]!r}"
    )


def assert_response_length(
    text: str,
    min_chars: int = 0,
    max_chars: int = 10000,
) -> None:
    """Assert response length is within bounds."""
    length = len(text.strip())
    assert length >= min_chars, (
        f"Response too short: {length} chars (min {min_chars})"
    )
    assert length <= max_chars, (
        f"Response too long: {length} chars (max {max_chars})"
    )


def assert_no_error_events(events: list[StreamEvent]) -> None:
    """Assert that no error events are present in the stream."""
    errors = [e for e in events if e.type == "error"]
    assert not errors, (
        f"Found {len(errors)} error event(s): "
        + "; ".join(str(e.data) for e in errors)
    )


def assert_stream_event_sequence(
    events: list[StreamEvent],
    expected_types: list[str],
) -> None:
    """Assert that the expected event types appear in order as a subsequence.

    The events don't need to be contiguous — other events can appear between them.
    """
    actual_types = [e.type for e in events]
    idx = 0
    for expected in expected_types:
        while idx < len(actual_types) and actual_types[idx] != expected:
            idx += 1
        assert idx < len(actual_types), (
            f"Expected event type {expected!r} not found in remaining sequence. "
            f"Full sequence: {actual_types}, expected: {expected_types}"
        )
        idx += 1


# -- Tool assertions --


def assert_tool_called(tools_used: list[str], expected_any: list[str]) -> None:
    """Assert that at least one of the expected tools was called."""
    found = [t for t in expected_any if t in tools_used]
    assert found, (
        f"Expected at least one of {expected_any} to be called, "
        f"but tools used were: {tools_used}"
    )


def assert_tool_called_all(tools_used: list[str], expected_all: list[str]) -> None:
    """Assert that ALL of the expected tools were called."""
    missing = [t for t in expected_all if t not in tools_used]
    assert not missing, (
        f"Expected all of {expected_all} to be called, "
        f"missing: {missing}, tools used: {tools_used}"
    )


def assert_tool_not_called(tools_used: list[str], forbidden: list[str]) -> None:
    """Assert that NONE of the forbidden tools were called."""
    found = [t for t in forbidden if t in tools_used]
    assert not found, (
        f"Expected none of {forbidden} to be called, "
        f"but found: {found}, tools used: {tools_used}"
    )


def assert_no_tools_called(tools_used: list[str]) -> None:
    """Assert that no tools were called at all."""
    assert not tools_used, (
        f"Expected no tools to be called, but got: {tools_used}"
    )


def assert_tool_count(
    tools_used: list[str],
    min_count: int | None = None,
    max_count: int | None = None,
) -> None:
    """Assert the number of unique tools called is within bounds."""
    count = len(tools_used)
    if min_count is not None:
        assert count >= min_count, (
            f"Too few tools called: {count} (min {min_count}), tools: {tools_used}"
        )
    if max_count is not None:
        assert count <= max_count, (
            f"Too many tools called: {count} (max {max_count}), tools: {tools_used}"
        )


def assert_tool_called_with_args(
    tool_events: list[StreamEvent],
    tool_name: str,
    args_contain: dict,
) -> None:
    """Assert a tool was called with specific argument values.

    Checks tool_start events for the given tool and verifies that the
    arguments dict contains the expected key-value pairs (subset match).
    """
    matching = [
        e for e in tool_events
        if e.type == "tool_start"
        and e.data.get("tool", e.data.get("name", "")) == tool_name
    ]
    assert matching, (
        f"Tool {tool_name!r} was never called. "
        f"Tool events: {[e.data.get('tool', e.data.get('name', '')) for e in tool_events]}"
    )

    for event in matching:
        args = event.data.get("arguments", event.data.get("args", {}))
        mismatches = {
            k: (v, args.get(k))
            for k, v in args_contain.items()
            if str(args.get(k, "")).lower() != str(v).lower()
        }
        if not mismatches:
            return  # found a matching call

    assert False, (
        f"Tool {tool_name!r} was called but no call matched args {args_contain}. "
        f"Calls: {[e.data for e in matching]}"
    )


def assert_response_matches(text: str, pattern: str) -> None:
    """Assert that the response text matches a regex pattern."""
    assert re.search(pattern, text, re.IGNORECASE), (
        f"Pattern {pattern!r} not found in response: {text[:300]!r}"
    )
