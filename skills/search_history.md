---
name: Search History
description: Raw message search across a channel's sessions. Use this when you need exact older messages across primary, scratch, thread, or other sub-sessions rather than the current session's structured archive.
triggers: search history, what did we talk about, find messages, look back, past conversations, exact old message, cross-session search, scratch session history, older conversation
category: core
---

# Search History Tool

## Core Principle
Messages are stored per-session, sessions belong to a channel. This tool searches across ALL sessions in a channel — it is not limited to the current session. Use it when you need raw historical messages, not the current session's structured section index.

If you need the current session's archive browser, nearby-session pointers, or scratch-vs-primary semantics, read `history_and_memory/session_history` instead.

## Tool Signature

```
search_history(
  query: str | None,       # keyword search (ILIKE), omit to return all
  start_date: str | None,  # ISO 8601, e.g. "2026-03-01"
  end_date: str | None,    # ISO 8601, e.g. "2026-03-22"
  role: str,               # "user" | "assistant" | "tool" | "system" | "all" (default)
  limit: int               # 1–100, default 50
)
```

`channel_id` and `bot_id` are injected automatically from context — do not pass them.

## Result Shape

Each result contains:

| Field | Description |
|---|---|
| `id` | Message UUID |
| `session_id` | Which session this message belongs to |
| `role` | `user`, `assistant`, `tool`, or `system` |
| `content_preview` | First 300 chars of message content |
| `created_at` | ISO timestamp |

## Behavioral Patterns

**Need the current session's archive, not cross-session search:**
Use `read_conversation_history`, not this tool.

**During compaction — context is thin:**
Call `search_history` with a relevant keyword or date range before summarizing. Don't compact blindly if there's history worth incorporating.

**User asks "what did we decide about X":**
Call with `query="X"`, `role="all"`. Scan results for decision language. If nothing found, say so — don't hallucinate.

**User asks about a specific time period:**
Use `start_date` + `end_date`. Omit `query` to get all messages in that window.

**Filtering by role:**
- Use `role="user"` to find what Michael asked/said
- Use `role="assistant"` to find what the agent previously said or decided
- Use `role="tool"` only if looking for tool output records

## Common Mistakes

- Using this when `read_conversation_history` would answer faster — this tool is for raw cross-session search, not the current session's archive browser
- Passing `channel_id` manually — it's injected from context automatically
- Using this to search memory — wrong tool, use `search_memory` or `get_memory_file`
- Treating 300-char previews as complete messages — they are truncated. If full content matters, note that the preview may be cut off
- Searching with no params and hitting the 100-result cap — always use a keyword or date range when looking for something specific

## Related Skills

- `history_and_memory/session_history` — current session vs nearby sessions, `read_conversation_history`, and sub-session navigation
- `context_mastery` — where durable knowledge should live after you find it

## When to Use Proactively

Load and call `search_history` without being asked when:
- Compaction is running and current context doesn't reflect the full history of a topic
- A user references something ("like we did before", "remember when") that isn't in current context
- A decision is being made that might contradict something discussed in a prior session
