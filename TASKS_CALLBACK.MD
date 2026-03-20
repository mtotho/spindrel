# Pending Tasks

## Agent Self-Debugging Tool (`get_trace`)

Build a local tool that lets the agent inspect its own current request trace for self-debugging.

**How it works:**
- New file: `tools/get_trace.py` (auto-discovered at startup)
- Tool name: `get_trace` (no required args)
- Reads `current_correlation_id` from context
- Queries `trace_events` + `tool_calls` for that correlation, ordered by `created_at`
- Returns a formatted text summary (event type, name, count/similarity, tool args/results)

**Use case:** Agent can call this mid-conversation to see what RAG injections fired, which tools ran and what they returned, token usage, and any errors — enabling it to reason about its own context and debug why it's missing information.
