---
name: Pipeline Creation
description: >
  Decision guide for creating task pipelines. When to use a pipeline vs work
  inline, how to use schedule_task with steps, step type selection (exec/tool/agent),
  optimization tips, and worked examples. Load when building multi-step automations
  or deciding whether a task needs a pipeline.
triggers: create pipeline, pipeline task, multi-step task, schedule pipeline, automate steps, when to pipeline, build automation
category: core
---

# Pipeline Creation Guide

## When to Use a Pipeline

| Situation | Use | Why |
|---|---|---|
| One-off reasoning or analysis | Single-prompt `schedule_task` | No orchestration needed |
| Multi-step with conditions/branching | **Pipeline** (steps param) | Deterministic control flow |
| Mix shell ops + tool calls + LLM reasoning | **Pipeline** | Each step uses the right engine |
| Fan-out to multiple bots simultaneously | `delegate_to_agent` (parallel) | Pipelines are sequential |
| Recurring multi-step checks | **Pipeline** + `recurrence` | Steps re-execute on schedule |
| Purely deterministic (no LLM needed) | **Pipeline** with exec/tool only | Zero LLM cost |

**Rule of thumb:** if you'd chain 3+ actions in sequence, or need to branch on a prior result, use a pipeline.

## Creating a Pipeline Task

Use `schedule_task` with the `steps` parameter (JSON array):

```
schedule_task(
  title="Health check",
  steps='[
    {"id": "check", "type": "exec", "prompt": "df -h / && free -h"},
    {"id": "analyze", "type": "agent", "prompt": "Flag any concerns from the health data."}
  ]'
)
```

When `steps` is provided, `prompt` is optional — a placeholder is auto-generated. You can still pass `scheduled_at`, `recurrence`, `bot_id`, and all other `schedule_task` parameters.

For advanced overrides (model, tools, skills), pass `execution_config`:

```
schedule_task(
  title="Research pipeline",
  steps='[...]',
  execution_config='{"model_override": "gpt-4o-mini", "tools": ["web_search"]}'
)
```

## Step Type Selection

Pick the cheapest step type that gets the job done:

| What you need | Step type | Cost | Example |
|---|---|---|---|
| Run a shell command | `exec` | Free | `df -h`, `docker ps`, `curl` |
| Call a tool with known args | `tool` | Free | `web_search`, `slack-send_message` |
| Interpret, reason, or decide | `agent` | LLM tokens | Analyze results, write a report |

**Decision question for each step:** "Is the LLM adding value, or just wrapping a deterministic action?" If the action has fixed inputs and predictable output, use `exec` or `tool`.

### Common Conversions

| If an agent step just does this... | Convert to |
|---|---|
| Calls one tool with known args | `tool` step |
| Runs a shell command | `exec` step |
| Sends a fixed message | `tool` step (`slack-send_message`) |
| Parses JSON and extracts a field | `exec` step (`jq`) |

### When to Keep Agent Steps

- Output needs interpretation or judgment
- The step must choose between multiple tools based on context
- The step writes prose (reports, summaries, recommendations)
- Input is ambiguous and needs reasoning

## Patterns

### Gather → Analyze
Most common pattern: deterministic data gathering + one agent step for analysis.

```json
[
  {"id": "data", "type": "exec", "prompt": "docker stats --no-stream --format json"},
  {"id": "logs", "type": "exec", "prompt": "docker logs app --tail 50 2>&1"},
  {"id": "report", "type": "agent", "prompt": "Analyze the container health data and flag issues."}
]
```

### Conditional Branching
Use `when` conditions instead of asking the LLM to decide:

```json
[
  {"id": "check", "type": "exec", "prompt": "df -h / | awk 'NR==2{print $5}' | tr -d '%'"},
  {"id": "cleanup", "type": "exec", "prompt": "docker system prune -af",
   "when": {"step": "check", "output_contains": "9"}, "on_failure": "continue"},
  {"id": "report", "type": "agent", "prompt": "Report disk status and any cleanup actions taken."}
]
```

### Tool Chain
Purely deterministic — zero LLM cost:

```json
[
  {"id": "search", "type": "tool", "tool_name": "web_search",
   "tool_args": {"query": "weather forecast tomorrow"}},
  {"id": "notify", "type": "tool", "tool_name": "slack-send_message",
   "tool_args": {"channel": "#general", "text": "Forecast: {{steps.search.result}}"}}
]
```

## Cross-Reference

For the full step JSON schema — conditions, templates, failure handling, environment variables, model tiers — see the **Pipeline Authoring** skill.
