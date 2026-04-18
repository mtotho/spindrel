---
id: carapaces/orchestrator/audits
name: Bot Audits & Tuning
description: >-
  Decision table for choosing the right audit pipeline when a user asks to
  evaluate, tune, or diagnose a bot. Covers discovery, skill quality, memory
  cadence, tool usage, and cost.
triggers:
  - audit
  - analyze
  - evaluate
  - tune
  - hygiene
  - diagnose
  - "not finding"
  - "isn't picking"
  - "wrong tool"
  - "slow bot"
  - "expensive"
  - "token usage"
  - "memory bloated"
  - "skills stale"
  - "why is"
---

# Bot Audits & Tuning

When a user asks you to evaluate, tune, or diagnose a bot's behavior, you don't do the analysis yourself — you launch a **system pipeline** that gathers the right evidence, has an LLM analyze it against whitelisted knobs, and returns proposals for the user to approve in-chat.

## The five audits

| User says... | Run pipeline | What it tunes |
|---|---|---|
| *"isn't finding the right tools"*, *"discovery is off"*, *"X should have been selected"* | `orchestrator.analyze_discovery` | `tool_similarity_threshold`, `pinned_tools`, skill triggers/descriptions |
| *"skills feel stale"*, *"wrong skill firing"*, *"skill X never gets used"* | `orchestrator.analyze_skill_quality` | skill descriptions/triggers, bot skill enrollments |
| *"compaction weird"*, *"context overflow"*, *"memory bloat"*, *"hygiene not working"* | `orchestrator.analyze_memory_quality` | `compaction_interval`, `compaction_keep_turns`, `memory_max_inject_chars`, `memory_hygiene_interval_hours` |
| *"tool X never called"*, *"always errors on Y"*, *"prune tools"* | `orchestrator.analyze_tool_usage` | `pinned_tools`, `local_tools`, tool description (advisory) |
| *"burning tokens"*, *"too expensive"*, *"primary model unreliable"* | `orchestrator.analyze_costs` | `compaction_interval`, `compaction_keep_turns`, `fallback_models` reorder |

Use the broader `orchestrator.full_scan` for "audit the whole fleet's config" (drift-style, not behavior-style), and `orchestrator.deep_dive_bot` for a per-bot config drift check.

## How to run one

Every audit pipeline takes a single required param: `bot_id`. Default the channel to the current channel so the approval widget renders where the user is watching.

```
run_pipeline(
  pipeline_id="orchestrator.analyze_discovery",
  params={"bot_id": "crumb"}
)
```

You can pass either the slug (`orchestrator.analyze_discovery`) or the pipeline UUID — slug is preferred.

To see the full catalog at runtime (e.g. user asks *"what audits are available?"*):

```
list_pipelines(source="system")
```

## What happens after launch

1. The pipeline fetches trace evidence + current config (non-LLM steps, fast).
2. An LLM step produces proposals as JSON — each proposal is a PATCH body keyed to a specific knob, with 2+ correlation_ids of evidence.
3. A review step renders an **approval widget** in the current channel. The user approves/rejects each proposal individually.
4. Approved proposals are PATCH'd against the admin API automatically.

You don't need to read or summarize proposals yourself — the widget shows everything. Just tell the user which pipeline you launched and point them at the widget.

## Responding to the user

Keep it brief. Example:

> I launched `analyze_discovery` for crumb. Proposals will appear in the review widget here once the trace data is processed (~30s). Approve the ones you want applied.

If the pipeline comes back with `{"proposals": []}` (healthy), say so and move on. Don't narrate what *could* have been proposed if things were broken.

## When NOT to use an audit pipeline

- User wants a **one-off answer** about a bot ("what tools does X have?") — use `call_api` + `/admin/bots/{id}` instead.
- User wants to **change** a specific field they already named ("set crumb's threshold to 0.25") — just PATCH it directly with `call_api`, skip the audit.
- User wants to **monitor** live behavior — that's for `get_trace` / `search_bot_memory`, not an audit.

Audits are for the open-ended *"is this configured well?"* question, where the knobs aren't pre-chosen.

## Debugging your own audit runs

If an audit returns empty proposals when you expected some, the trace evidence may be too thin (turns-since-last-activity too few). Check with:

```
get_trace(event_type="discovery_summary", bot_id="<bot>", limit=20, include_user_message=true)
```

If the trace count is low (<10 turns), the audit's evidence bar (2+ correlation_ids per proposal) is legitimately unmet. Wait for more activity before re-running.
