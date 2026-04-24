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

## Batch When You Can

Hygiene runs visit many channels and logs in sequence. Keep the iteration count low:

- **Archive in one call.** Use `file(operation="archive_older_than", path="memory/logs/", older_than_days=14, destination="memory/logs/archive/")` instead of issuing N `file(operation="move", ...)` calls. It's idempotent — safe to re-run, skips files already archived.
- **Bulk read / edit.** When you need to read or edit several files, use `file(operation="batch", ops=[{"op": "read", "path": "a.md"}, {"op": "append", "path": "b.md", "content": "..."}, ...])` — one iteration instead of N.
- **Create-or-update skills in one call.** Use `manage_bot_skill(action="upsert", ...)` when you're not sure whether a skill already exists. `create` errors on duplicates and costs a round-trip.
- **Batch-get multiple skill bodies.** `manage_bot_skill(action="get", names=["skill-a", "skill-b", ...])` returns `{skills: [...], missing: [...]}` in one call. Skip the redundant `action="list"` entirely — the Working Set snapshot already carries `category`, `stale`, and `script_count` for authored skills.
- **Read multiple channels in one call.** `read_conversation_history(channel_ids=[id1, id2, id3])` and `list_sub_sessions(channel_ids=[...])` return a map keyed by `channel_id`. Use these for the per-channel sweep instead of N single-channel calls.
- **Bundle prune with updates.** `prune_enrolled_skills(...)` can run in the same iteration as `manage_bot_skill(update/create/upsert, ...)` calls — they don't depend on each other. Splitting the prune into its own iteration wastes an LLM round-trip.
- **Heading-based section edits.** `file(operation="replace_section", heading="## Reflections", content="...")` replaces a MEMORY.md section without sending the current content as the `find` string of a plain `edit`.

## Don't Re-Fetch Your Own Tool Results

`read_conversation_history(section="tool:<uuid>")` hydrates a prior tool result by its call ID. **It is NOT a substitute for keeping notes.** If you just called a tool in this same run, its result is still in context. Re-fetching the same UUID across multiple iterations wastes the budget and delays the final response. Use `section="tool:..."` only when you genuinely need data from a prior session, not within the current run.

## Common Mistakes

- Skipping `list_sub_sessions` during maintenance
- Promoting speculative summaries instead of checked facts
- Writing reusable patterns to memory instead of a skill
- Confusing cross-session raw search with current-session archive browsing
- Calling `file(operation="move", ...)` for each old log instead of one `archive_older_than` call
- Calling `manage_bot_skill(action="create", ...)` when the skill might already exist — use `upsert`
- Using `section="tool:<uuid>"` to re-read data from earlier in the same run
- Calling `manage_bot_skill(action="list")` when the Working Set snapshot already has category/stale/script_count
- Issuing N `manage_bot_skill(action="get", name=...)` calls instead of one `names=[...]` batch
- Splitting `prune_enrolled_skills` into its own iteration after an update batch
- Calling `read_conversation_history` once per channel when you could pass `channel_ids=[...]`

## Related Skills

- [History And Memory](index.md)
- [Session History](session_history.md)
- `search_history`
- `context_mastery`
