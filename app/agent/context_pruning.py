"""Non-destructive pruning of stale tool results from the active context.

At context assembly time, old tool result messages have their content replaced
with a short marker.  Recent turns (configurable) are kept intact so the agent
can see what it just did.  User messages, assistant text, and system messages
are never touched.
"""

import logging

logger = logging.getLogger(__name__)

# Markers used by the chat-history / compaction system to delimit the
# conversation region inside the message list.
_BEGIN_MARKER = "--- BEGIN RECENT CONVERSATION HISTORY ---"
_END_MARKER = "--- END RECENT CONVERSATION HISTORY ---"

# Tool names whose output is reference material (skills, runbooks) that
# the bot needs to keep referring back to across multiple turns.  Tool
# dispatch sets ``_no_prune=True`` on the resulting tool message so the
# pruner skips it.  Pruning is the consumer; the loop is the producer.
STICKY_TOOL_NAMES: frozenset[str] = frozenset({
    "get_skill",
    "get_skill_list",
})


def prune_tool_results(
    messages: list[dict],
    min_content_length: int = 200,
) -> dict:
    """Replace tool-result content with compact markers.

    All tool results in the conversation region are pruned — the LLM already
    consumed them in the turn they were produced.  This is safe because
    pruning only runs at ``assemble_context`` time (start of a new user
    turn), before the agent loop produces any tool results for the
    in-progress turn — so we are never replacing data the model is
    actively working with.

    If a ``_tool_record_id`` is present on the message, the marker
    includes a retrieval pointer so the bot can fetch the full output
    via ``read_conversation_history``.

    Messages with ``_no_prune: True`` are always kept verbatim — used
    for reference-style tool output (skills, runbooks) that the bot
    needs to keep referring back to across multiple turns.

    Parameters
    ----------
    messages : list[dict]
        The full message list (mutated in-place).
    min_content_length : int
        Tool results shorter than this are always kept (e.g. "OK", errors).

    Returns
    -------
    dict
        ``{"pruned_count": int, "chars_saved": int, "turns_pruned": int}``
    """
    # --- locate conversation region ---
    conv_start, conv_end = _find_conversation_region(messages)
    if conv_start is None:
        return {"pruned_count": 0, "chars_saved": 0, "turns_pruned": 0}

    conv_msgs = messages[conv_start:conv_end]
    if not conv_msgs:
        return {"pruned_count": 0, "chars_saved": 0, "turns_pruned": 0}

    # --- split into turns (each starting with a user message) ---
    turns = _split_into_turns(conv_msgs)
    if not turns:
        return {"pruned_count": 0, "chars_saved": 0, "turns_pruned": 0}

    # --- build tool_call_id → tool_name map from assistant messages ---
    tool_name_map = _build_tool_name_map(conv_msgs)

    pruned_count = 0
    chars_saved = 0
    turns_pruned = 0

    for turn_msgs in turns:
        turn_had_pruning = False
        for msg in turn_msgs:
            if msg.get("role") != "tool":
                continue
            # Sticky tool results (skills, runbooks) are reference material
            # the bot keeps referring back to — never prune them.
            if msg.get("_no_prune"):
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            if len(content) < min_content_length:
                continue

            record_id = msg.get("_tool_record_id")
            tool_call_id = msg.get("tool_call_id", "")
            tool_name = tool_name_map.get(tool_call_id, "unknown")
            original_length = len(content)
            if record_id:
                marker = (
                    f"[Tool output from {tool_name} ({original_length:,} chars)"
                    f" — use read_conversation_history(section='tool:{record_id}')"
                    f" to retrieve]"
                )
            else:
                marker = f"[Tool result pruned — {tool_name}: {original_length} chars]"
            msg["content"] = marker
            pruned_count += 1
            chars_saved += original_length - len(marker)
            turn_had_pruning = True

        if turn_had_pruning:
            turns_pruned += 1

    return {
        "pruned_count": pruned_count,
        "chars_saved": chars_saved,
        "turns_pruned": turns_pruned,
    }


def _find_conversation_region(messages: list[dict]) -> tuple[int | None, int]:
    """Return (start, end) indices of the conversation region.

    Looks for BEGIN/END markers first; falls back to the first non-system
    message through the end of the list.
    """
    begin_idx = None
    end_idx = len(messages)

    for i, msg in enumerate(messages):
        content = msg.get("content", "")
        if isinstance(content, str):
            if _BEGIN_MARKER in content:
                begin_idx = i + 1  # conversation starts *after* the marker
            elif _END_MARKER in content:
                end_idx = i

    if begin_idx is not None:
        return begin_idx, end_idx

    # Fallback: first non-system message
    for i, msg in enumerate(messages):
        if msg.get("role") != "system":
            return i, end_idx

    return None, end_idx


def _split_into_turns(msgs: list[dict]) -> list[list[dict]]:
    """Split a flat message list into turns, each starting with a ``user`` message."""
    turns: list[list[dict]] = []
    current: list[dict] = []

    for msg in msgs:
        if msg.get("role") == "user" and current:
            turns.append(current)
            current = []
        current.append(msg)

    if current:
        turns.append(current)

    return turns


def _build_tool_name_map(msgs: list[dict]) -> dict[str, str]:
    """Build a mapping from tool_call_id to tool function name."""
    name_map: dict[str, str] = {}
    for msg in msgs:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls", []):
            tc_id = tc.get("id", "")
            fn_name = (tc.get("function") or {}).get("name", "unknown")
            if tc_id:
                name_map[tc_id] = fn_name
    return name_map
