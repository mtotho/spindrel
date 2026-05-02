"""Helpers for keeping tool result envelopes linked to tool calls."""

from __future__ import annotations

from typing import Any


def normalize_tool_result_envelope_ids(
    tool_calls: list[Any] | None,
    envelopes: list[Any] | None,
) -> list[Any] | None:
    """Repair envelope ``tool_call_id`` values from same-message tool calls.

    Secret redaction can false-positive on provider-generated IDs. These IDs
    are structural render keys, so when the raw tool calls are available on
    the same message they are the source of truth.
    """

    if not isinstance(envelopes, list):
        return envelopes

    candidates: list[str] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        call_id = call.get("id")
        if not isinstance(call_id, str) or not call_id or call_id.startswith("auto:"):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = call.get("name") or fn.get("name")
        if name == "auto-approved":
            continue
        candidates.append(call_id)
    if not candidates:
        return envelopes

    candidate_set = set(candidates)
    next_candidate_index = 0
    normalized: list[Any] = []
    changed = False
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            normalized.append(envelope)
            continue
        current_id = envelope.get("tool_call_id")
        if isinstance(current_id, str) and current_id in candidate_set:
            normalized.append(envelope)
            if current_id in candidates[next_candidate_index:]:
                next_candidate_index = candidates.index(current_id) + 1
            continue
        if "content_type" not in envelope or next_candidate_index >= len(candidates):
            normalized.append(envelope)
            continue
        repaired = dict(envelope)
        repaired["tool_call_id"] = candidates[next_candidate_index]
        next_candidate_index += 1
        normalized.append(repaired)
        changed = True
    return normalized if changed else envelopes
