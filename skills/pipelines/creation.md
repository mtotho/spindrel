---
name: Pipeline Creation
description: >
  Decision guide for creating Pipelines: when to use a Pipeline vs work inline,
  `define_pipeline` usage, step type selection across the five types (exec,
  tool, agent, user_prompt, foreach), and worked examples.
use_when: >
  Deciding if work belongs in a Pipeline at all, choosing between the five
  step types, wiring up params for a reusable Pipeline, or picking
  user_prompt vs agent-asks-a-question for an approval gate.
triggers: create pipeline, define pipeline, multi-step automation, schedule pipeline, automate steps, when to pipeline, build automation, approval gate, batch operation, iterate list
category: pipelines
---

# Pipeline Creation Guide

## When to Use a Pipeline

| Situation | Use | Why |
|---|---|---|
| One-off reasoning or analysis | `schedule_prompt` (single-prompt Automation) | No orchestration needed |
| Multi-step with conditions/branching | **`define_pipeline`** | Deterministic control flow |
| Mix shell ops + tool calls + LLM reasoning | **`define_pipeline`** | Each step uses the right engine |
| Fan-out to multiple bots simultaneously | `delegate_to_agent` (parallel) | Pipelines are sequential |
| Recurring multi-step checks | **`define_pipeline`** + `recurrence` | Steps re-execute on schedule |
| Purely deterministic (no LLM needed) | **`define_pipeline`** with exec/tool only | Zero LLM cost |

**Rule of thumb:** if you'd chain 3+ actions in sequence, or need to branch on a prior result, use a Pipeline.

## Creating a Pipeline

Use `define_pipeline` — `steps` is required:

```
define_pipeline(
  title="Health check",
  steps='[
    {"id": "check", "type": "exec", "prompt": "df -h / && free -h"},
    {"id": "analyze", "type": "agent", "prompt": "Flag any concerns from the health data."}
  ]'
)
```

`define_pipeline` also accepts `scheduled_at`, `recurrence`, `bot_id`, `trigger_config`, `execution_config`, and `max_run_seconds`.

For advanced overrides (model, tools, skills), pass `execution_config`:

```
define_pipeline(
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
| Human approval before continuing | `user_prompt` | Free | "Apply these 5 patches?", multi-item review |
| Run a sub-step per item in a list | `foreach` | Per-iteration | Apply 10 patches, notify 3 channels |

**Decision question for each step:** "Is the LLM adding value, or just wrapping a deterministic action?" If the action has fixed inputs and predictable output, use `exec` or `tool`.

### user_prompt vs. asking the agent

Use `user_prompt` — **not** an agent step that prompts the user — when:
- The pipeline must **block** until a human responds (agent steps just emit text and move on)
- You want a **structured response** (binary approve/reject, per-item selection) rather than free-form prose
- You want the response **auditable** (it's stored in `step_states[i].result` as validated JSON, not a chat message)

Use an agent step asking a question when the "response" is really just *the next message in the conversation* and the pipeline doesn't need to gate on it.

### foreach vs. an agent step "just call the tool N times"

Use `foreach` when:
- The list is **deterministic** (comes from a prior step / params) — don't pay LLM tokens to dispatch N identical tool calls
- You want **per-iteration failure handling** (`on_failure: continue` inside the `do` block) without the LLM giving up after the first error
- You want **predictable cost** — one iteration = one tool call, not N × agent-loop turns

Use an agent step when the *choice* of what to do per item needs judgment.

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

### Review → Approve → Apply
Agent proposes, human approves, foreach applies. Zero bespoke apply-tools:

```json
[
  {"id": "scan", "type": "tool", "tool_name": "list_api_endpoints"},
  {"id": "review", "type": "agent",
   "prompt": "Scan results:\n{{steps.scan.result}}\n\nPropose a JSON list of patches: [{bot_id, patch}, ...]"},
  {"id": "approve", "type": "user_prompt",
   "widget_template": "confirmation_card",
   "widget_args": {"title": "Apply proposed patches?", "body": "{{steps.review.result}}"},
   "response_schema": {"type": "binary"}},
  {"id": "apply", "type": "foreach",
   "over": "{{steps.review.result.proposals}}",
   "do": [{
     "id": "apply_one", "type": "tool", "tool_name": "call_api",
     "tool_args": {"method": "PATCH", "path": "/api/v1/admin/bots/{{item.bot_id}}", "body": "{{item.patch}}"},
     "when": {"step": "approve", "output_contains": "approve"}
   }],
   "on_failure": "continue"}
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

## Managing Task Definitions

### Updating a Pipeline

Use `update_task` to iterate on pipeline steps, execution config, or event triggers:

```
update_task(
  task_id="<uuid>",
  steps='[{"id": "check", "type": "exec", "prompt": "df -h /"}]'
)
```

You can also update `execution_config` (model, tools, skills) and `trigger_config` (event-based triggers).

### Triggering a Run Manually

Use `run_task` to immediately execute a task definition:

```
run_task(task_id="<definition-uuid>")
```

Pass `params` to bind runtime inputs into `{{params.*}}` substitutions inside the pipeline:

```
run_task(
  task_id="<definition-uuid>",
  params='{"target_bot": "rolland", "dry_run": true}'
)
```

This spawns a concrete child task and returns its ID. The definition itself is not modified.

### Viewing Run History

Use `list_tasks` with `parent_task_id` to see past runs of a definition:

```
list_tasks(parent_task_id="<definition-uuid>")
```

Returns runs with status, timing, result previews, and step progress summaries.

### Inspecting a Run

Use `get_task_result` to see step-by-step progress of a pipeline run:

```
get_task_result(task_id="<run-uuid>")
```

Returns `step_states` with per-step status, output, and timing.

### Event-Triggered Pipelines

Use `trigger_config` on `define_pipeline` to create Pipelines that fire on events:

```
define_pipeline(
  title="Deploy on push",
  steps='[...]',
  trigger_config='{"type": "event", "event_source": "github", "event_type": "push"}'
)
```

For single-prompt event-triggered Automations (no steps), use `schedule_prompt` with the same `trigger_config` argument.

## Cross-Reference

For the full step JSON schema — conditions, templates, failure handling, environment variables, model tiers — see the **Pipeline Authoring** skill.
