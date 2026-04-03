---
name: Model Efficiency
description: >
  Guide for cost-effective delegation using model tiers. Load when the orchestrator
  needs to choose between tiers for delegation, or when the user asks about model
  costs and optimization.
---

# Model Efficiency — Tier-Based Delegation

## Core Principle

Every delegate has a **model tier** that controls cost. Use the cheapest tier that
can handle the task. Tiers are resolved automatically — you rarely need to override.

## Available Tiers

| Tier | Cost | Use For |
|------|------|---------|
| `free` | $0 | Trivial routing, no-op tasks |
| `fast` | Lowest | Scanning, summarization, extraction, classification |
| `standard` | Moderate | Code generation, research, reviews, structured tasks |
| `capable` | Higher | Complex debugging, architecture, polished writing |
| `frontier` | Highest | Novel reasoning, ambiguous multi-step problems |

## How Tier Resolution Works

When you call `delegate_to_agent`, the model is resolved in this order:

1. **Explicit `model_tier` param** on the `delegate_to_agent` call (highest priority)
2. **Delegate entry default** — the `model_tier` set in your carapace's `delegates` list
3. **Bot's configured model** — the target bot's default model (fallback)

Most of the time, the delegate entry default is correct — you defined it when setting up
the carapace. Only override explicitly when a specific task is unusually complex or simple
for its delegate type.

```python
# Uses the delegate entry's default tier (standard for researcher)
delegate_to_agent(
    bot_id="researcher",
    prompt="Research current best practices for WebSocket authentication"
)

# Override to capable for an unusually complex research task
delegate_to_agent(
    bot_id="researcher",
    prompt="Compare 5 auth frameworks across security, performance, and DX",
    model_tier="capable"
)
```

## Your Delegate Toolkit

### Cheap Workers (fast tier) — Use Liberally
- **scanner** — Bulk file reading, pattern extraction, usage searches. Delegate freely
  for any grunt-work: "find all usages of X", "list all API endpoints", "scan for TODO comments".
- **summarizer** — Compress large inputs. Use when there's too much text to process
  efficiently: conversation history, long docs, multi-channel status updates.

### Standard Workers — The Workhorses
- **researcher** — Web research with citations. Use for anything requiring current info.
- **presenter** — Slide deck creation. Use when content needs visual presentation.
- **qa** — Test planning and execution. Use after code changes.
- **code-review** — Structured review. Use when code needs careful human-quality review.

### Capable Workers — Use When Quality Matters
- **writer** — Long-form docs, reports, proposals. The output will be read carefully by humans.
- **bug-fix** — Systematic debugging. The problem requires multi-step reasoning.

## Cost Optimization Patterns

### 1. Cheap Scan → Expensive Synthesis
Use fast-tier workers to gather and compress, then hand the distilled input to a
capable-tier worker for the final output:

```
1. scanner (fast)    → read 50 files, extract relevant snippets
2. summarizer (fast) → compress findings to key points
3. writer (capable)  → produce polished report from the digest
```

### 2. Heartbeat Economy
Heartbeats run frequently. Set channel model overrides to cheap tiers:
```python
manage_channel(action="update", channel_id="...", model_override="your-fast-model")
```

### 3. Fan-Out at the Right Tier
When breaking a task into parallel subtasks, match each subtask to its tier:
```
Task: "Audit the project and write a report"
  → scanner (fast): scan all source files for patterns
  → researcher (standard): look up best practices
  → writer (capable): synthesize findings into report
```

### 4. Escalation Pattern
Start cheap. If the result is insufficient, retry at a higher tier:
```python
# First try cheap
delegate_to_agent(bot_id="scanner", prompt="...", model_tier="fast")
# If result is too shallow, escalate
delegate_to_agent(bot_id="researcher", prompt="...", model_tier="standard")
```

## Discovering Available Models

Use `GET /api/v1/admin/models` to see models with cost info. Check on cold start
and note the cheapest models per tier in workspace MEMORY.md for quick reference.

## Decision Heuristic

1. **How complex is the reasoning?** Simple extraction → fast. Multi-step analysis → capable.
2. **Who reads the output?** Internal/transient → economize. User-facing → invest.
3. **How often does this run?** Hourly heartbeat → fast. One-off report → capable is fine.
4. **Is this retriable?** If you can retry on failure, start cheap and escalate.
