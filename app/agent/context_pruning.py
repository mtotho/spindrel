"""Non-destructive pruning of stale tool results from the active context.

At context assembly time, old tool result messages have their content replaced
with a short marker.  Recent turns (configurable) are kept intact so the agent
can see what it just did.  User messages, assistant text, and system messages
are never touched.
"""

import json
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
    # Memory files (MEMORY.md, daily logs) are re-fetched repeatedly during
    # hygiene runs — keep them verbatim so the bot doesn't burn iterations
    # asking for the same file across pruning cycles.
    "get_memory_file",
})


_PRUNED_ARGS_SENTINEL = "_spindrel_pruned_tool_args"


def build_pruned_tool_call_arguments_marker(tool_name: str, original_chars: int) -> str:
    """Return the JSON marker used when compacting historical tool-call args."""
    return json.dumps({
        _PRUNED_ARGS_SENTINEL: True,
        "tool": tool_name,
        "original_chars": original_chars,
        "note": "Historical tool-call arguments were compacted for context replay.",
    }, separators=(",", ":"))


def tool_call_arguments_are_pruned(args: object) -> bool:
    if not isinstance(args, str):
        return False
    try:
        parsed = json.loads(args)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and bool(parsed.get(_PRUNED_ARGS_SENTINEL))


def estimate_tool_call_argument_pruning(tool_calls: object, min_content_length: int) -> dict[str, int]:
    """Estimate savings from compacting oversized assistant tool-call arguments."""
    if not isinstance(tool_calls, list):
        return {"count": 0, "chars": 0, "marker_chars": 0, "chars_saved": 0}

    count = 0
    chars = 0
    marker_chars = 0
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            continue
        args = fn.get("arguments", "")
        if not isinstance(args, str):
            args = json.dumps(args)
        if len(args) < min_content_length or tool_call_arguments_are_pruned(args):
            continue
        marker = build_pruned_tool_call_arguments_marker(
            str(fn.get("name") or "tool"),
            len(args),
        )
        count += 1
        chars += len(args)
        marker_chars += len(marker)
    return {
        "count": count,
        "chars": chars,
        "marker_chars": marker_chars,
        "chars_saved": max(0, chars - marker_chars),
    }


def build_pruned_tool_result_marker(
    tool_name: str,
    original_length: int,
    *,
    record_id: str | None = None,
) -> str:
    if record_id:
        return (
            f"[Tool output from {tool_name} ({original_length:,} chars)"
            f" — use read_conversation_history(section='tool:{record_id}')"
            f" to retrieve]"
        )
    return f"[Tool result pruned — {tool_name}: {original_length} chars]"


def _empty_turn_stats() -> dict:
    return {
        "pruned_count": 0,
        "chars_saved": 0,
        "turns_pruned": 0,
        "tool_call_args_pruned": 0,
        "tool_call_arg_chars_saved": 0,
    }


def _empty_iteration_stats() -> dict:
    return {
        "pruned_count": 0,
        "chars_saved": 0,
        "iterations_pruned": 0,
        "tool_call_args_pruned": 0,
        "tool_call_arg_chars_saved": 0,
    }


def _compact_tool_call_arguments(msg: dict, min_content_length: int) -> dict[str, int]:
    """Replace oversized assistant tool-call arguments with a valid JSON marker."""
    tool_calls = msg.get("tool_calls")
    if not isinstance(tool_calls, list):
        return {"count": 0, "chars_saved": 0}

    changed = False
    count = 0
    chars_saved = 0
    new_tool_calls = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            new_tool_calls.append(tc)
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            new_tool_calls.append(tc)
            continue
        args = fn.get("arguments", "")
        if not isinstance(args, str):
            args = json.dumps(args)
        if len(args) < min_content_length:
            new_tool_calls.append(tc)
            continue
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict) and parsed.get(_PRUNED_ARGS_SENTINEL):
                new_tool_calls.append(tc)
                continue
        except (TypeError, ValueError):
            pass

        marker = build_pruned_tool_call_arguments_marker(
            str(fn.get("name") or "tool"),
            len(args),
        )
        new_tool_calls.append({
            **tc,
            "function": {
                **fn,
                "arguments": marker,
            },
        })
        changed = True
        count += 1
        chars_saved += max(0, len(args) - len(marker))

    if changed:
        msg["tool_calls"] = new_tool_calls
    return {"count": count, "chars_saved": chars_saved}


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
        return _empty_turn_stats()

    conv_msgs = messages[conv_start:conv_end]
    if not conv_msgs:
        return _empty_turn_stats()

    # --- split into turns (each starting with a user message) ---
    turns = _split_into_turns(conv_msgs)
    if not turns:
        return _empty_turn_stats()

    # --- build tool_call_id → tool_name map from assistant messages ---
    tool_name_map = _build_tool_name_map(conv_msgs)

    pruned_count = 0
    chars_saved = 0
    turns_pruned = 0
    tool_call_args_pruned = 0
    tool_call_arg_chars_saved = 0

    for turn_msgs in turns:
        turn_had_pruning = False
        for msg in turn_msgs:
            if msg.get("role") == "assistant":
                arg_stats = _compact_tool_call_arguments(msg, min_content_length)
                if arg_stats["count"] > 0:
                    tool_call_args_pruned += arg_stats["count"]
                    tool_call_arg_chars_saved += arg_stats["chars_saved"]
                    chars_saved += arg_stats["chars_saved"]
                    turn_had_pruning = True
                continue
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
            marker = build_pruned_tool_result_marker(
                tool_name,
                original_length,
                record_id=record_id,
            )
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
        "tool_call_args_pruned": tool_call_args_pruned,
        "tool_call_arg_chars_saved": tool_call_arg_chars_saved,
    }


def prune_in_loop_tool_results(
    messages: list[dict],
    keep_iterations: int = 1,
    min_content_length: int = 200,
) -> dict:
    """Prune tool results from older iterations within an in-progress turn.

    Called between iterations of the agent loop, before the next LLM call.
    Keeps the most recent ``keep_iterations`` rounds of tool results verbatim
    so the LLM can still reason about what it just learned. Older iterations'
    tool results get the same retrieval-pointer marker as turn-boundary pruning.

    Iteration boundaries are inferred from assistant messages with ``tool_calls``:
    each such message marks the end of one iteration. Walking backwards from
    the end of the message list, we count ``keep_iterations`` of these boundaries
    and prune everything before that point.

    Sticky tool results (``_no_prune=True``) are kept verbatim. Already-pruned
    messages are detected by their short marker length and skipped, so this is
    safe to call repeatedly.

    Parameters
    ----------
    messages : list[dict]
        The full message list (mutated in-place).
    keep_iterations : int
        Number of recent iterations whose tool results stay verbatim. Must be
        >= 1 — pruning the just-produced tool results would break the next
        LLM call. With ``keep_iterations=1``, only the latest iteration is
        protected; older iterations get pruned.
    min_content_length : int
        Tool results shorter than this are always kept (e.g. "OK", errors,
        already-pruned markers).

    Returns
    -------
    dict
        ``{"pruned_count": int, "chars_saved": int, "iterations_pruned": int}``
    """
    if keep_iterations < 1:
        keep_iterations = 1

    # Walk backwards: count assistant-with-tool-calls messages. The
    # ``keep_iterations``-th one from the end marks the boundary; everything
    # before it (inclusive of its own tool results — wait, no: its tool results
    # are AFTER it, so they fall in the kept region) is eligible for pruning.
    boundary_idx: int | None = None
    seen = 0
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            seen += 1
            if seen >= keep_iterations:
                # Tool results AFTER this assistant message belong to the
                # last ``keep_iterations`` iterations and must stay verbatim.
                # Tool results BEFORE this index are eligible for pruning.
                boundary_idx = i
                break

    if boundary_idx is None:
        # Not enough iterations to prune.
        return _empty_iteration_stats()

    # Build tool_call_id → tool_name map only for the prunable prefix —
    # tool calls in the kept tail aren't referenced from pruned messages.
    tool_name_map = _build_tool_name_map(messages[:boundary_idx])

    pruned_count = 0
    chars_saved = 0
    iterations_pruned = 0
    tool_call_args_pruned = 0
    tool_call_arg_chars_saved = 0
    current_iter_had_prunes = False

    for i in range(boundary_idx):
        msg = messages[i]
        # Each assistant-with-tool-calls message ends one iteration. If that
        # iteration produced any prunes, count it now and reset the flag.
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            if current_iter_had_prunes:
                iterations_pruned += 1
                current_iter_had_prunes = False
            arg_stats = _compact_tool_call_arguments(msg, min_content_length)
            if arg_stats["count"] > 0:
                tool_call_args_pruned += arg_stats["count"]
                tool_call_arg_chars_saved += arg_stats["chars_saved"]
                chars_saved += arg_stats["chars_saved"]
                current_iter_had_prunes = True
            continue
        if msg.get("role") != "tool":
            continue
        if msg.get("_no_prune"):
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        if len(content) < min_content_length:
            # Already-pruned markers are well under min_content_length, so
            # this also serves as the "don't re-prune" guard.
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
            marker = f"[Tool result pruned (older iteration) — {tool_name}: {original_length} chars]"
        msg["content"] = marker
        pruned_count += 1
        chars_saved += original_length - len(marker)
        current_iter_had_prunes = True

    # The trailing iteration (the one that ends at boundary_idx) doesn't get
    # closed by the loop body, so flush it here.
    if current_iter_had_prunes:
        iterations_pruned += 1

    return {
        "pruned_count": pruned_count,
        "chars_saved": chars_saved,
        "iterations_pruned": iterations_pruned,
        "tool_call_args_pruned": tool_call_args_pruned,
        "tool_call_arg_chars_saved": tool_call_arg_chars_saved,
    }


def should_prune_in_loop(
    messages: list[dict],
    *,
    available_budget_tokens: int,
    pressure_threshold: float,
    tool_schema_tokens: int = 0,
) -> tuple[bool, float]:
    """Decide whether in-loop tool-result pruning should run this iteration."""
    if available_budget_tokens <= 0:
        return (True, 0.0)
    from app.agent.prompt_sizing import messages_prompt_tokens
    live_tokens = messages_prompt_tokens(messages) + max(0, int(tool_schema_tokens or 0))
    utilization = live_tokens / available_budget_tokens
    return (utilization >= pressure_threshold, utilization)


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
