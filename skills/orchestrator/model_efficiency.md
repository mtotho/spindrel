---
name: Model Efficiency
id: shared/orchestrator/model-efficiency
description: >
  Cost-aware delegation guidance for choosing the right model tier for a task or bot.
triggers: model tier, model efficiency, cheap model, expensive model, cost-aware, which model to use, delegation model, model selection
category: core
---

# Model Efficiency

Use the cheapest model tier that can reliably finish the task. Most delegation calls
should rely on existing defaults unless the task is unusually simple or unusually hard.

## Typical tiers

| Tier | Use for |
|---|---|
| `free` | trivial routing or no-op work |
| `fast` | scanning, extraction, summarization |
| `standard` | coding, research, structured execution |
| `capable` | complex debugging, architecture, polished writing |
| `frontier` | ambiguous or novel high-stakes reasoning |

## Resolution order

When you delegate, the effective model comes from:

1. an explicit override on the call
2. the target bot's configured defaults
3. broader server fallback logic

## Cost patterns

### Cheap scan -> expensive synthesis

Use low-cost workers to gather and compress, then one stronger worker to synthesize.

### Start cheap, escalate if needed

If the task is retryable, use a cheaper tier first and only escalate if quality is inadequate.

### Match frequency to cost

Recurring or heartbeat-style work should default to cheaper tiers than one-off user-facing deliverables.
