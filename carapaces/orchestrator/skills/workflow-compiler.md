---
name: workflow-compiler
description: >
  Guide for analyzing, optimizing, and compiling workflows. Load when asked to convert
  workflow steps to deterministic tool calls, optimize a workflow, analyze a run's
  execution, compile/export/script a workflow, or debug why a step was skipped.
---

# Workflow Compiler & Optimizer

## Purpose

This skill covers three related workflows:

1. **Optimization** — Convert expensive `agent` (LLM) steps into cheap `tool`/`exec` steps
2. **Compilation** — Turn a workflow into a standalone script (Python, Bash)
3. **Forensic analysis** — Reconstruct exactly what a workflow run did

---

## Workflow Optimization: Agent → Tool/Exec Conversion

The most impactful optimization: identify workflow steps where the LLM is just calling a tool with known arguments, and replace them with `type: tool` (direct call, no LLM, instant, free) or `type: exec` (shell command, no LLM).

### The Decision Framework

For each `agent` step, ask: **"Is the LLM adding value, or just wrapping a deterministic action?"**

| What the agent step does | Convert to | Why |
|---|---|---|
| Calls a single tool with args derivable from params/prior results | `type: tool` | No LLM needed — direct call, instant, zero cost |
| Runs a shell command that could be written as a template | `type: exec` | No LLM needed — runs directly in sandbox |
| Calls a tool but interprets/formats the result for humans | Keep `agent`, simplify prompt | LLM adds value in presentation |
| Makes decisions, analyzes data, synthesizes multiple sources | Keep `agent` | LLM reasoning is the point |
| Calls a tool, then decides next action based on output | Keep `agent` (or split into tool + conditional agent) | Decision-making needs LLM |

### Step-by-Step Optimization Process

#### 1. Get the full run data

```python
# Get workflow definition (for reference)
manage_workflow(action="get", id="<workflow_id>")

# Get the run with FULL results and step definitions
manage_workflow(
    action="get_run",
    run_id="<run_id>",
    include_definitions=true,   # Shows each step's prompt, tool_name, when, etc.
    full_results=true,          # Shows complete step output (not 500-char preview)
)
```

The response includes for each step:
- `id`, `type`, `status` — what the step is and what happened
- `definition.prompt` — what the LLM was told to do
- `definition.tool_name`/`tool_args` — for existing tool steps
- `definition.when` — conditions for this step
- `result` — the full output (what the LLM actually produced)

#### 2. Classify each agent step

Read each step's **prompt** and **result** together. Look for these patterns:

**Pattern A — Pure tool wrapper** (convert to `tool`):
- Prompt says "Call X with Y" or "Search for Z" or "Create a channel named ..."
- Result is essentially the raw tool output, maybe with light formatting
- The LLM didn't make any decisions — it just translated the prompt into a tool call

**Pattern B — Shell command wrapper** (convert to `exec`):
- Prompt says "Run this command" or "Execute ..." or "Check disk space"
- Result is command output
- The command could be written as a template with `{{param}}` substitution

**Pattern C — Lightweight analysis** (simplify, keep agent):
- Prompt asks for interpretation of prior step output
- Result shows reasoning but the core action was one tool call
- Consider splitting: tool step for the call, agent step only for the analysis

**Pattern D — Real reasoning** (keep agent as-is):
- Prompt requires multi-step analysis, decision-making, or synthesis
- Result shows genuine LLM reasoning that can't be templated
- This step SHOULD be an LLM call

#### 3. Map to tool calls

Common local tools and their parameters (for conversion):

**Channel/bot management:**
```yaml
# manage_channel — create, configure, update channels
- type: tool
  tool_name: manage_channel
  tool_args:
    action: create           # or configure, update, list
    name: "{{channel_name}}"
    bot_id: "{{bot_id}}"

# manage_bot — update bot config
- type: tool
  tool_name: manage_bot
  tool_args:
    action: update
    bot_id: "{{bot_id}}"
    config: '{"carapaces": ["qa"]}'

# manage_integration — configure integrations
- type: tool
  tool_name: manage_integration
  tool_args:
    action: configure
    integration_id: "slack"
    config: '{"channel": "#alerts"}'
```

**System operations:**
```yaml
# get_system_status — system health snapshot
- type: tool
  tool_name: get_system_status

# list_tasks — check running/pending tasks
- type: tool
  tool_name: list_tasks
  tool_args:
    status: "running"

# get_task_result — get a specific task's output
- type: tool
  tool_name: get_task_result
  tool_args:
    task_id: "{{task_id}}"

# schedule_task — schedule deferred work
- type: tool
  tool_name: schedule_task
  tool_args:
    bot_id: "{{bot_id}}"
    prompt: "{{task_prompt}}"
    scheduled_at: "+1h"
```

**Search/retrieval:**
```yaml
# web_search — search with known query
- type: tool
  tool_name: web_search
  tool_args:
    query: "{{search_term}}"

# search_channel_workspace — search workspace files
- type: tool
  tool_name: search_channel_workspace
  tool_args:
    query: "{{search_query}}"
```

**Workflow/carapace management:**
```yaml
# manage_workflow — trigger sub-workflows
- type: tool
  tool_name: manage_workflow
  tool_args:
    action: trigger
    id: "{{sub_workflow_id}}"
    params: '{"key": "{{value}}"}'

# manage_carapace — CRUD carapaces
- type: tool
  tool_name: manage_carapace
  tool_args:
    action: list
```

**Shell commands** — use `type: exec` instead of `type: tool`:
```yaml
# Direct shell commands
- type: exec
  prompt: "curl -s https://api.example.com/status"
  timeout: 30

# Commands with parameter substitution
- type: exec
  prompt: "pg_dump -Fc {{database}} > /tmp/backup-$(date +%Y%m%d).dump"
```

**Discovering available tools:** The above is not exhaustive. Run `get_system_status` to see all registered tools on the current instance, or use `manage_workflow(action="get", id="...")` on an existing workflow to see what tools its steps use.

#### 4. Handle result references

When converting agent→tool, the step result format changes:
- **Agent steps** return free-form text (LLM output)
- **Tool steps** return the raw tool function output (usually JSON)

If a downstream step uses `{{steps.X.result}}` and expects human-readable text, but X is now a tool step returning JSON, you may need to:
- Adjust the downstream prompt to handle JSON input
- Or keep a lightweight agent step to format the output

#### 5. Generate the optimized workflow

Use `manage_workflow(action="create", ...)` to create the new version, or present the YAML for manual placement.

### Optimization Examples

**Before — 4 agent steps, 4 LLM calls:**
```yaml
steps:
  - id: check-status
    prompt: "Check the system status and report what you find."
  - id: create-channel
    prompt: "Create a channel called '{{name}}' for bot '{{bot_id}}'."
  - id: configure
    prompt: "Enable workspace on the channel you just created."
  - id: summarize
    prompt: "Summarize what was set up and any issues."
```

**After — 2 tool steps + 1 agent step (75% LLM cost reduction):**
```yaml
steps:
  - id: check-status
    type: tool
    tool_name: get_system_status

  - id: create-channel
    type: tool
    tool_name: manage_channel
    tool_args:
      action: create
      name: "{{name}}"
      bot_id: "{{bot_id}}"

  - id: configure-and-summarize
    prompt: |
      System status: {{steps.check-status.result}}
      Channel created: {{steps.create-channel.result}}

      Enable workspace on the new channel, then summarize
      what was set up. Note any issues from the system status.
    tools: [manage_channel]
```

**Hybrid pattern — deterministic data gathering + LLM analysis:**
```yaml
steps:
  - id: gather-status
    type: tool
    tool_name: get_system_status

  - id: gather-tasks
    type: tool
    tool_name: list_tasks
    tool_args:
      status: "running"

  - id: search-recent
    type: tool
    tool_name: search_channel_workspace
    tool_args:
      query: "{{topic}}"

  - id: analyze
    type: agent
    prompt: |
      Analyze the current state:

      System: {{steps.gather-status.result}}
      Tasks: {{steps.gather-tasks.result}}
      Workspace: {{steps.search-recent.result}}

      Identify issues, recommend actions, and prioritize.
```

**Full deterministic — zero LLM cost:**
```yaml
# When every step is a known operation with known parameters.
# Note: tool step results are raw JSON, so {{steps.X.result}} gives
# the full JSON string. This works if the downstream tool can accept
# it, or if you use an agent step to extract specific fields.
steps:
  - id: create-channel
    type: tool
    tool_name: manage_channel
    tool_args: { action: create, name: "{{name}}", bot_id: "{{bot_id}}" }

  - id: configure
    type: agent
    prompt: |
      The channel was created: {{steps.create-channel.result}}
      Extract the channel ID from the JSON above, then call
      manage_channel(action="configure", channel_id=<the id>,
        config='{"channel_workspace_enabled": true}')
    tools: [manage_channel]

  - id: schedule-heartbeat
    type: tool
    tool_name: schedule_task
    tool_args:
      bot_id: "{{bot_id}}"
      prompt: "Daily check-in"
      scheduled_at: "+24h"
      recurrence: "+24h"
```

> **Limitation:** `{{steps.X.result}}` injects the raw return value. For tool steps, that's usually JSON. If a downstream tool step needs a specific field (like a channel ID), you need an agent step to extract it — or ensure the tool's return value is directly usable as the argument.

### Optimization Checklist

After converting, verify:

1. **Tool steps return useful data** — downstream steps can parse tool output
2. **Conditions still work** — `output_contains` checks against raw tool output, not LLM prose
3. **Error handling matches** — tool steps that fail behave differently than agent steps
4. **Parameter substitution** — `{{param}}` works in `tool_args` values
5. **No circular dependencies** — tool steps execute inline (no task), so they can't be monitored via `get_task_result`

---

## Compilation: Workflow → Standalone Script

### Step 1: Gather the Run Data

```python
manage_workflow(action="get", id="<workflow_id>")
manage_workflow(action="get_run", run_id="<run_id>", include_definitions=true, full_results=true)
```

From `get`: params schema, defaults, steps, session_mode, secrets.
From `get_run`: actual params used, per-step status/result/error/timestamps, step definitions.

### Step 2: Analyze the Execution Path

Walk through steps in order:

| Step State | What Happened |
|---|---|
| `done` | Ran successfully — `result` is the output |
| `skipped` | `when` condition was false |
| `failed` | Errored — check `error` and `on_failure` |
| `pending` | Never reached (workflow aborted earlier) |

### Step 3: Reconstruct Condition Logic

```yaml
# Workflow:
when:
  step: check
  output_contains: "NOT_FOUND"

# Python:
if "NOT_FOUND" in steps["check"]["result"].upper():
```

Rules: `output_contains`/`output_not_contains` are case-insensitive. `all` = AND, `any` = OR, `not` = negate.

### Step 4: Generate the Script

#### Python Template

```python
#!/usr/bin/env python3
"""Compiled from workflow: {workflow_name}, Run: {run_id}"""
import os, json, requests

SERVER_URL = os.environ.get("AGENT_SERVER_URL", "http://localhost:8000")
API_KEY = os.environ.get("AGENT_API_KEY", "")
BOT_ID = "{bot_id}"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

params = {params_dict}

def run_step(step_id, prompt, model=None):
    payload = {"message": prompt, "bot_id": BOT_ID, "client_id": f"compiled-{step_id}"}
    if model: payload["model_override"] = model
    resp = requests.post(f"{SERVER_URL}/v1/chat", json=payload, headers=HEADERS)
    resp.raise_for_status()
    return {"status": "done", "result": resp.json().get("response", "")}

steps = {}
# Step: {step_id}
{condition_check}
steps["{step_id}"] = run_step("{step_id}", """{prompt}""")
```

### Step 5: Handle Edge Cases

- `on_failure: abort` → `sys.exit(1)`. `continue` → catch + continue. `retry:N` → retry loop.
- `requires_approval` → `input("Approve? [y/N] ")` or skip for unattended.
- `{{steps.X.result}}` → reference `steps["X"]["result"]` in Python.
- `shared` session mode → concatenate prior results or use a single session_id.

### Output Checklist

Include: header comment (workflow ID, run ID, timestamp), env vars, parameter docs, execution path annotations, idempotency notes.

---

## Forensic Analysis

When understanding what happened (not generating a script):

```python
manage_workflow(action="get_run", run_id="<run_id>", include_definitions=true, full_results=true)
```

Present a timeline:
```
[00:00] Step 'check' (agent) started
[00:03] Step 'check' completed → "STATUS: NOT_FOUND — title not in library"
[00:03] Step 'diagnose' (agent) started (condition met: check contains "NOT_FOUND")
[00:08] Step 'diagnose' completed → "DIAGNOSIS: Sonarr has series but no episodes..."
[00:08] Step 'fix' (agent) skipped (condition not met: diagnose contains "DOWNLOADING")
[00:08] Step 'report' (agent) started
[00:10] Step 'report' completed
```

Highlight anomalies: retries, failures, unexpectedly skipped steps, long durations, steps where the LLM just called one tool (optimization opportunity).
