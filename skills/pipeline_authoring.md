---
name: Pipeline Authoring
description: >
  Complete reference for authoring task pipeline steps — JSON schema, all five
  step types (exec / tool / agent / user_prompt / foreach), params + template
  syntax, condition logic, failure handling, environment variables, and real
  examples. Load when creating or editing pipeline definitions, generating
  steps for AI, or troubleshooting pipeline execution.
use_when: >
  Authoring or editing any pipeline step, deciding which step type to use
  (especially user_prompt vs foreach vs agent), wiring up params, writing
  `when:` conditions, or debugging why a template / step state / resolve
  call isn't behaving as expected.
triggers: pipeline, task pipeline, steps, step definition, pipeline json, create pipeline, edit pipeline, pipeline authoring, multi-step task, step executor, pipeline schema, user_prompt, foreach, approval gate, widget template
category: core
---

# Pipeline Authoring Reference

## Overview

A **pipeline** is a Task with a `steps` array — an ordered list of step definitions that execute sequentially. Each step can be a shell command (`exec`), a direct tool call (`tool`), or an LLM conversation (`agent`). The step executor handles sequencing, condition evaluation, template rendering, and result propagation.

**Key principle:** use `exec` and `tool` steps for deterministic work (they don't consume LLM tokens), and `agent` steps for creative/reasoning tasks. Design pipelines so LLMs handle judgment, not plumbing.

## Step Definition Schema

Each step is a JSON object. The `steps` field on a task is an array of these objects.

### Common Fields (all step types)

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | **yes** | — | Unique identifier within the pipeline. Used in templates and conditions. Convention: `step_1`, `check_disk`, `notify_slack` |
| `type` | `"exec"` \| `"tool"` \| `"agent"` | **yes** | — | Determines execution engine |
| `label` | string | no | — | Human-readable name shown in the timeline UI |
| `on_failure` | `"abort"` \| `"continue"` | no | `"abort"` | `abort` = stop pipeline immediately. `continue` = mark failed, proceed to next step |
| `when` | object | no | — | Conditional execution (see Conditions). If condition is false, step status = `"skipped"` |
| `result_max_chars` | number | no | 2000 | Maximum characters kept from step output. Longer results are truncated |

### Type: `exec` — Shell Command

Runs a shell command. No LLM involved. Exit code 0 = done, nonzero = failed.

| Field | Type | Description |
|-------|------|-------------|
| `prompt` | string | The shell command to execute. Supports template variables and multi-line scripts |
| `working_directory` | string \| null | Working directory for the command. Null = workspace default |
| `args` | object | Additional arguments passed as environment variables |
| `timeout` | number | Max execution time in seconds |

**Environment variables auto-injected from prior steps:**
- `$STEP_1_RESULT` — result of step at index 1 (1-based)
- `$STEP_1_STATUS` — status of step at index 1
- `$STEP_CHECK_DISK_RESULT` — result by step ID (uppercased, non-alphanumeric → `_`)
- `$STEP_CHECK_DISK_STATUS` — status by step ID

**Auto-extracted JSON keys:** If a step's result is valid JSON with top-level keys, each key is also exported as its own env var. For example, if step 1 returns `{"llm": "gpt-4o", "count": 30}`:
- `$STEP_1_llm` → `gpt-4o`
- `$STEP_1_count` → `30`
- `$STEP_1_RESULT` → the full JSON string (still available)

**Example:**
```json
{
  "id": "check_disk",
  "type": "exec",
  "label": "Check disk usage",
  "prompt": "df -h / | tail -1 | awk '{print $5}'",
  "on_failure": "continue"
}
```

**Multi-line script:**
```json
{
  "id": "deploy",
  "type": "exec",
  "prompt": "cd /opt/app\ngit pull origin main\ndocker compose up -d --build",
  "working_directory": "/opt/app",
  "on_failure": "abort"
}
```

### Type: `tool` — Direct Tool Call

Invokes a registered tool directly. No LLM involved — deterministic execution.

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | string | Exact tool name as registered (e.g. `"slack-send_message"`, `"web_search"`) |
| `tool_args` | object | Arguments to pass. Values support template substitution |

**Example:**
```json
{
  "id": "search",
  "type": "tool",
  "label": "Search the web",
  "tool_name": "web_search",
  "tool_args": {
    "query": "latest news about {{topic}}"
  }
}
```

**Example with prior step results in args:**
```json
{
  "id": "notify",
  "type": "tool",
  "tool_name": "slack-send_message",
  "tool_args": {
    "channel": "#alerts",
    "text": "Disk usage: {{steps.check_disk.result}}"
  }
}
```

### Type: `agent` — LLM Conversation

Spawns a child task that runs as an LLM conversation. Prior step results are auto-injected into the system preamble — you don't need to manually include them (but you can reference specific results with templates for emphasis).

| Field | Type | Description |
|-------|------|-------------|
| `prompt` | string | The prompt sent to the LLM. Prior results are auto-prepended |
| `model` | string \| null | Model override (e.g. `"gpt-4o"`, `"claude-sonnet-4-20250514"`). Null = inherit from task. See Model Tiers below for guidance |
| `tools` | string[] \| null | Extra tool names to **add** to what the bot already has. Additive, not a whitelist — the step still sees the bot's base tools + auto-discovered tools |
| `carapaces` | string[] \| null | Capability IDs to activate for this step (adds their tools + system prompt fragments) |
| `skills` | string[] \| null | Skill IDs to ephemerally inject for this step only. Use for just-in-time expertise (e.g. load `pipeline_authoring` for a step that writes pipelines) without enrolling them on the bot permanently |
| `timeout` | number \| null | Max seconds for the child task |

**Example:**
```json
{
  "id": "analyze",
  "type": "agent",
  "label": "Analyze findings",
  "prompt": "Given the disk usage data, determine if any partitions are above 85% and recommend cleanup actions.",
  "model": "gpt-4o-mini",
  "on_failure": "continue"
}
```

**Auto-injected preamble format** (you get this for free):
```
Previous step results:
- Check disk usage (exec, done): 78%
- List docker images (exec, done): REPOSITORY   TAG   SIZE ...
```

### Type: `user_prompt` — Human Approval Gate

Pauses the pipeline with a rendered widget and a response schema. Execution resumes when a human (or bot) posts to the `/resolve` endpoint. No LLM is involved — this is a synchronous gate.

| Field | Type | Description |
|-------|------|-------------|
| `widget_template` | string | ID of a registered widget template (see Widget Templates in the UI) |
| `widget_args` | object | Args passed to the template. Values support template substitution |
| `response_schema` | object | Shape the resolver must post. `{"type": "binary"}` (approve/reject) or `{"type": "multi_item", "items": [...]}` (per-item approval) |

While paused the step's state is `awaiting_user_input` with `widget_envelope` and `response_schema` populated. Downstream steps can read the resolved payload via `{{steps.<id>.result}}`.

**Example — binary approval gate:**
```json
{
  "id": "approve_deploy",
  "type": "user_prompt",
  "widget_template": "confirmation_card",
  "widget_args": {
    "title": "Deploy {{params.version}} to production?",
    "body": "{{steps.test.result}}"
  },
  "response_schema": { "type": "binary" }
}
```

**Resolving**: `POST /api/v1/admin/tasks/{task_id}/steps/{step_index}/resolve` with the payload shape defined by `response_schema`. The endpoint validates, writes `result`, flips state to `done`, and resumes the pipeline.

### Type: `foreach` — Iterate Over a List

Iterates a list from a prior step or param, running a `do` block of sub-steps for each item. Sequential in v1 (not parallel).

| Field | Type | Description |
|-------|------|-------------|
| `over` | string | Reference to the list to iterate: `"{{steps.<id>.result}}"`, `"{{steps.<id>.result.items}}"`, `"{{params.<key>}}"`. Must resolve to a list |
| `do` | object[] | Sub-step(s) to run per item. **v1: sub-steps must be `type: tool`** (exec / agent / user_prompt inside foreach is deferred) |
| `on_failure` | `"abort"` \| `"continue"` | Outer policy: stop iterating on the first failing iteration, or keep going |

Inside `do`, these substitutions are bound per iteration:
- `{{item}}` — the current item (full JSON-encoded if dict/list)
- `{{item.<key>}}` / `{{item.<a>.<b>}}` — dotted access for dict items
- `{{item_index}}` — 0-based index
- `{{item_count}}` — total items

**Example — apply approved patches:**
```json
{
  "id": "apply",
  "type": "foreach",
  "over": "{{steps.review.result.proposals}}",
  "do": [
    {
      "id": "apply_one",
      "type": "tool",
      "tool_name": "call_api",
      "tool_args": {
        "method": "PATCH",
        "path": "/api/v1/admin/bots/{{item.bot_id}}",
        "body": "{{item.patch}}"
      },
      "when": { "step": "review", "output_contains": "approve" }
    }
  ],
  "on_failure": "continue"
}
```

**`when:` gotcha**: the inner `when:` is evaluated against *outer* step results, not per-item. If the review step contains "approve" *anywhere*, the gate passes for *every* iteration. Per-item gating requires a richer `when:` form that can reference `{{item.id}}` against the review payload — currently parked. If you need strict per-item filtering today, pre-filter the list in an `agent`/`exec` step and have `foreach` iterate the already-approved subset.

**State shape**: `step_states[i]` for a foreach step is `{items, iterations: [[sub_state, ...], ...]}` — sub-states parallel to sub-steps across iterations.

## Params

Pipelines can accept runtime params — passed at trigger time via the `params:` body on `POST /api/v1/admin/tasks/{id}/run`, or the `params` arg of `run_task`. Params are merged into the child's `execution_config["params"]` and are visible to every step via templates.

| Pattern | Resolves to |
|---------|-------------|
| `{{params.key}}` | Top-level param value |
| `{{params.a.b.c}}` | Dotted access into nested dict params |
| `{{key}}` (bare) | Fallback — `params["key"]` if present |

Dict/list param values are JSON-encoded when substituted into a string context, so `tool_args` can safely contain `"body": "{{params.patch}}"` and the rendered result is valid JSON.

Use params for:
- Triggering the same pipeline definition with different inputs (per-bot, per-env)
- Bindings that should *not* be baked into the pipeline YAML
- Passing the output of an LLM's JSON payload into a structured `foreach` / `call_api` chain

## Template Syntax

Templates use `{{double_braces}}` and are rendered before execution.

### In Prompts (agent and exec steps)

| Pattern | Resolves to |
|---------|-------------|
| `{{steps.1.result}}` | Result of step at index 1 (1-based) |
| `{{steps.check_disk.result}}` | Result of step with id `check_disk` |
| `{{steps.1.status}}` | Status of step at index 1 (`done`, `failed`, `skipped`) |
| `{{steps.check_disk.status}}` | Status by step ID |
| `{{steps.1.result.llm}}` | Extract `llm` key from step 1's JSON result |
| `{{steps.1.result.config.model}}` | Dotted access into nested JSON: `result.config.model` |
| `{{params.key}}` / `{{param_name}}` | Runtime parameter passed to `/tasks/{id}/run` or `run_task(..., params=...)` |
| `{{item}}` / `{{item.key}}` / `{{item_index}}` / `{{item_count}}` | Bound inside `foreach` `do` sub-steps (see Foreach) |

**JSON field access:** If a step's result is valid JSON (a dict), you can drill into it with dotted notation after `.result`. For example, if step 1 returns `{"llm": "gpt-4o", "count": 30}`, then `{{steps.1.result.llm}}` resolves to `gpt-4o`. Nested access works too: `{{steps.1.result.config.model}}`. If the key doesn't exist or the result isn't JSON, the template is preserved as-is.

**Shell escaping:** In `exec` steps, template values containing single quotes are automatically shell-escaped (`it's` → `'it'\''s'`).

### In Tool Args

Tool `tool_args` values also support template substitution:
```json
"tool_args": {
  "message": "Results: {{steps.1.result}}",
  "model": "{{steps.1.result.llm}}"
}
```

### Unresolved Templates

If a template references a step that doesn't exist or hasn't run, the template string is preserved as-is (not replaced with empty string). This makes debugging easier.

## Conditions (`when`)

Conditions control whether a step executes. A step whose condition evaluates to false gets status `"skipped"`.

### Simple Conditions

**By prior step status:**
```json
{ "step": "step_1", "status": "done" }
```

**By output content (substring match):**
```json
{ "step": "step_1", "output_contains": "SUCCESS" }
{ "step": "step_1", "output_not_contains": "ERROR" }
```

**By parameter value (workflow context):**
```json
{ "param": "severity", "equals": "critical" }
```

### Compound Conditions

**All must be true (AND):**
```json
{
  "all": [
    { "step": "step_1", "status": "done" },
    { "step": "step_1", "output_contains": "READY" }
  ]
}
```

**Any must be true (OR):**
```json
{
  "any": [
    { "param": "target", "equals": "all" },
    { "param": "target", "equals": "services" }
  ]
}
```

**Negation (NOT):**
```json
{
  "not": { "step": "step_1", "status": "failed" }
}
```

**Nested compound:**
```json
{
  "all": [
    { "step": "check", "status": "done" },
    {
      "any": [
        { "step": "check", "output_contains": "CRITICAL" },
        { "step": "check", "output_contains": "WARNING" }
      ]
    }
  ]
}
```

## Failure Handling

| `on_failure` | Behavior |
|-------------|----------|
| `"abort"` (default) | Pipeline stops immediately. Task status → `"failed"`. Remaining steps are not executed |
| `"continue"` | Step is marked `"failed"` in step_states, but pipeline continues to the next step |

**Pipeline-level status rules:**
- If ANY step failed → pipeline task status = `"failed"` (even with `continue`)
- If all steps done or skipped → pipeline task status = `"complete"`
- A skipped step is not a failure

## Step States (Runtime)

During and after execution, each step has a corresponding entry in `step_states`:

```json
{
  "status": "done",        // "pending" | "running" | "done" | "failed" | "skipped" | "awaiting_user_input"
  "result": "78%",         // Step output (string or JSON, truncated to result_max_chars)
  "error": null,           // Error message if failed
  "started_at": "2026-04-16T10:00:00Z",
  "completed_at": "2026-04-16T10:00:01Z",
  "task_id": null           // For agent steps: ID of the spawned child task
}
```

For `user_prompt` steps while paused, the state also carries `widget_envelope` and `response_schema`. For `foreach` steps, `result` is replaced by `{items, iterations: [[sub_state, ...], ...]}`.

## Complete Examples

### Health Check Pipeline
```json
[
  {
    "id": "check_resources",
    "type": "exec",
    "label": "Check system resources",
    "prompt": "echo '=== Disk ===' && df -h / && echo '=== Memory ===' && free -h && echo '=== Load ===' && uptime",
    "on_failure": "continue"
  },
  {
    "id": "check_docker",
    "type": "exec",
    "label": "Check running containers",
    "prompt": "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'",
    "on_failure": "continue"
  },
  {
    "id": "analyze",
    "type": "agent",
    "label": "Analyze health",
    "prompt": "Review the system health data and flag any concerns. Be concise — bullet points only.",
    "model": "gpt-4o-mini"
  },
  {
    "id": "notify",
    "type": "tool",
    "label": "Send report",
    "tool_name": "slack-send_message",
    "tool_args": {
      "channel": "#ops",
      "text": "Health check complete. See analysis above."
    },
    "when": { "step": "analyze", "status": "done" }
  }
]
```

### Conditional Remediation Pipeline
```json
[
  {
    "id": "check",
    "type": "exec",
    "label": "Check disk usage",
    "prompt": "df -h / | tail -1 | awk '{print $5}' | tr -d '%'"
  },
  {
    "id": "cleanup",
    "type": "exec",
    "label": "Clean up if needed",
    "prompt": "docker system prune -af --volumes 2>&1 && apt-get autoremove -y 2>&1",
    "when": { "step": "check", "output_contains": "9" },
    "on_failure": "continue"
  },
  {
    "id": "report",
    "type": "agent",
    "label": "Summarize actions",
    "prompt": "Disk was at {{steps.check.result}}%. Report what cleanup actions were taken (if any) and current status."
  }
]
```

### Research & Report Pipeline
```json
[
  {
    "id": "search",
    "type": "tool",
    "label": "Web search",
    "tool_name": "web_search",
    "tool_args": { "query": "latest developments in quantum computing 2026" }
  },
  {
    "id": "deep_dive",
    "type": "agent",
    "label": "Deep analysis",
    "prompt": "Analyze the search results. Identify the 3 most significant developments and explain their implications.",
    "tools": ["web_search"]
  },
  {
    "id": "format_report",
    "type": "agent",
    "label": "Format report",
    "prompt": "Format the analysis as a concise executive briefing with headers: Key Developments, Impact Assessment, Recommended Actions.",
    "model": "gpt-4o-mini"
  }
]
```

### Multi-Service Deployment Pipeline
```json
[
  {
    "id": "test",
    "type": "exec",
    "label": "Run tests",
    "prompt": "cd /opt/app && python -m pytest tests/ -x -q 2>&1",
    "on_failure": "abort"
  },
  {
    "id": "build",
    "type": "exec",
    "label": "Build container",
    "prompt": "cd /opt/app && docker build -t myapp:latest . 2>&1 | tail -5",
    "on_failure": "abort"
  },
  {
    "id": "deploy",
    "type": "exec",
    "label": "Deploy",
    "prompt": "cd /opt/app && docker compose up -d --build 2>&1",
    "when": { "step": "build", "status": "done" },
    "on_failure": "abort"
  },
  {
    "id": "verify",
    "type": "exec",
    "label": "Health check",
    "prompt": "sleep 10 && curl -sf http://localhost:8000/health || echo 'HEALTH CHECK FAILED'",
    "when": { "step": "deploy", "status": "done" }
  },
  {
    "id": "rollback",
    "type": "exec",
    "label": "Rollback on failure",
    "prompt": "cd /opt/app && docker compose down && docker compose up -d 2>&1",
    "when": { "step": "verify", "output_contains": "FAILED" },
    "on_failure": "continue"
  },
  {
    "id": "status_update",
    "type": "agent",
    "label": "Report deployment status",
    "prompt": "Summarize the deployment: did tests pass? Did the build succeed? Is the service healthy? If rollback happened, explain why.",
    "model": "gpt-4o-mini"
  }
]
```

## Model Tiers

The system defines 5 model tiers from cheapest to most capable. When choosing a `model` for an agent step, pick the tier that matches the step's complexity — don't burn frontier-tier tokens on summarization.

| Tier | Use Case | Example Tasks |
|------|----------|---------------|
| **Free** | Zero-cost / rate-limited | Simple echo, formatting |
| **Fast** | Trivial extraction, scanning | Summarize output, extract a field, format text |
| **Standard** | Research, code review | Analyze logs, review diffs, search synthesis |
| **Capable** | Multi-step reasoning | Root cause analysis, planning, complex tool use |
| **Frontier** | Complex / high-stakes | Multi-tool orchestration, critical decisions |

The actual model mapped to each tier is configured per-instance in Settings → Model Tiers. Use the Schema modal in the pipeline editor to see your instance's current mappings.

## Design Tips

1. **Start with exec, graduate to agent.** Shell commands are fast, deterministic, and free. Only use `agent` when you need judgment or natural language.

2. **Use `on_failure: continue` for non-critical steps.** Notifications, logging, and status updates should never abort the pipeline.

3. **Keep agent prompts focused.** Each agent step should have one clear job. Don't ask an LLM to "analyze everything and then send a notification" — split into analyze + tool-notify.

4. **Template results sparingly in agent prompts.** The auto-injected preamble already includes all prior results. Only use `{{steps.X.result}}` when you need to emphasize a specific value.

5. **Use descriptive step IDs.** `check_disk` is better than `step_1` — conditions and templates become self-documenting.

6. **Truncate large outputs.** If a step produces large output (e.g. `docker logs`), set `result_max_chars` or pipe through `tail` to keep the pipeline context manageable.

7. **Use conditions for branching.** Instead of asking an LLM "should we remediate?", check the output deterministically: `"when": { "step": "check", "output_contains": "CRITICAL" }`.
