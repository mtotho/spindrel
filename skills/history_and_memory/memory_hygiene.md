---
name: Memory Hygiene
description: How to run scheduled memory maintenance without losing session context. Covers reviewing current session history, inspecting sub-sessions deliberately, and promoting durable facts into memory or skills.
triggers: memory hygiene, memory maintenance, review memory, scheduled memory pass, curate memory, promote from logs, history layout unclear
category: core
---

# Memory Hygiene

Use this when running a maintenance pass over memory, logs, or authored skills and you need the history model straight before curating.

## Review Order

1. Review the main channel history with `read_conversation_history(section="index", channel_id=...)`.
2. Call `list_sub_sessions(channel_id=...)` for the same channel.
3. Inspect relevant scratch, thread, pipeline, or eval sessions with `read_sub_session(session_id=...)`.
4. Only then decide what belongs in memory, a reference file, or a skill.

This prevents the most common failure mode: summarizing the primary session only and missing decisions made in scratch or other sub-sessions.

## Promotion Rules

- Stable user preferences, corrections, and durable facts go to memory.
- Reusable procedures or patterns go to skills.
- Detailed topical material goes to reference files.

If you need the full routing model after you recover the history, read `context_mastery`.

## History Rules During Hygiene

- Treat the current session index as one source, not the whole truth.
- Inspect adjacent sessions deliberately; do not assume they are folded into the primary index.
- Use `search_history` when you need raw older messages across sessions, not just current-session summaries.

## Common Mistakes

- Skipping `list_sub_sessions` during maintenance
- Promoting speculative summaries instead of checked facts
- Writing reusable patterns to memory instead of a skill
- Confusing cross-session raw search with current-session archive browsing

## Related Skills

- [History And Memory](index.md)
- [Session History](session_history.md)
- `search_history`
- `context_mastery`
