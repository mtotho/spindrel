---
name: Bot Audits & Tuning
description: >
  Decision rule for choosing between the Discovery audit pipeline and the
  configurator skill when a user asks to evaluate, tune, or diagnose a bot.
triggers:
  - audit
  - evaluate
  - tune
  - diagnose
  - discovery
  - expensive
category: core
---

# Bot Audits & Tuning

The audit-pipeline surface is now narrow on purpose. Only one structured
pipeline ships today — `orchestrator.analyze_discovery`. Everything else
that used to be an audit pipeline (skill quality, memory quality, tool
usage, costs) is handled by the configurator skill via
`propose_config_change`, which gives the operator a single review surface
backed by the existing tool-policy approval gate.

## Audit selection

| User says... | Use | What it tunes |
|---|---|---|
| "discovery is off" | `run_pipeline("orchestrator.analyze_discovery")` | discovery thresholds, tool pinning, skill descriptions |
| "skills feel stale" / "context is bloated" / "tool X never gets used" / "this is too expensive" | the configurator skill (`propose_config_change`) | bot config (system prompt, memory scheme, pinned tools, model, compaction knobs, skill triggers/descriptions) |

Use `orchestrator.full_scan` or `orchestrator.deep_dive_bot` only when the
operator explicitly wants a structured batch sweep — they are no longer the
default path for "fix my config".

## Running Analyze Discovery

```python
run_pipeline(
    pipeline_id="orchestrator.analyze_discovery",
    params={"bot_id": "crumb"},
)
```

## Response style

Tell the user which path you picked (Discovery audit vs configurator) and
where the proposals will surface (Findings widget for the pipeline; the
tool-policy approval gate for `propose_config_change`). Do not invent
changes the pipeline or the configurator did not propose.
