---
name: Bot Audits & Tuning
description: >
  Decision table for choosing the right audit pipeline when a user asks to evaluate,
  tune, or diagnose a bot's behavior.
triggers:
  - audit
  - evaluate
  - tune
  - diagnose
  - discovery
  - expensive
---

# Bot Audits & Tuning

When a user asks whether a bot is configured well, prefer the audit pipelines over
ad-hoc guesswork. They gather evidence, analyze it, and render proposals for review.

## Audit selection

| User says... | Run pipeline | What it tunes |
|---|---|---|
| "discovery is off" | `orchestrator.analyze_discovery` | discovery thresholds, tool pinning, skill descriptions |
| "skills feel stale" | `orchestrator.analyze_skill_quality` | skill descriptions, triggers, enrollments |
| "context is bloated" | `orchestrator.analyze_memory_quality` | compaction and memory knobs |
| "tool X never gets used" | `orchestrator.analyze_tool_usage` | tool set and tool description quality |
| "this is too expensive" | `orchestrator.analyze_costs` | model and compaction cost levers |

Use the broader scan pipelines for configuration drift or full-fleet checks.

## Running one

```python
run_pipeline(
    pipeline_id="orchestrator.analyze_discovery",
    params={"bot_id": "crumb"},
)
```

## Response style

Tell the user which audit you launched and that proposals will appear in the review widget.
Do not manually invent changes the pipeline did not propose.
