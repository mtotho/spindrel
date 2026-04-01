---
name: workflows
description: >
  Workflow system reference for orchestrators. Load when creating, triggering,
  or managing reusable multi-step workflow templates. Covers YAML format,
  conditions, approval gates, scoped secrets, and execution patterns.
---

# Workflow System Reference

## Overview

Workflows are reusable, parameterized multi-step templates. Each step runs an independent LLM call — the workflow engine handles sequencing, conditions, and control flow deterministically. Use workflows when you need **repeatable automation** that goes beyond single-turn delegation.

**When to use workflows vs delegation:**

| Scenario | Use |
|---|---|
| One-off task for a specific bot | `delegate_to_agent` |
| Repeatable multi-step process with conditions | Workflow |
| Fan-out to multiple bots simultaneously | Delegation (parallel delegates) |
| Sequential steps with approval gates | Workflow |
| Steps that need scoped secret access | Workflow |

## manage_workflow Tool

```python
# List available workflows
manage_workflow(action="list")

# Get full workflow definition
manage_workflow(action="get", id="system-diagnostics")

# Trigger a workflow run
manage_workflow(
    action="trigger",
    id="media-search",
    params='{"series_name": "Breaking Bad", "quality": "1080p"}',
    bot_id="media-bot",           # Optional: overrides workflow default
    channel_id="<uuid>",          # Optional: channel context
)
# Returns: {"run_id": "...", "status": "running", "step_count": 3}

# Create a new workflow from bot
manage_workflow(
    action="create",
    id="my-workflow",
    name="My Custom Workflow",
    description="Does the thing",
    steps='[{"id": "step1", "prompt": "Do the first thing."}]',
    defaults='{"bot_id": "helper-bot", "model": "gemini/gemini-2.5-flash"}',
)
```

## YAML Workflow Format

Workflows live in `workflows/*.yaml` (auto-synced on startup and file change):

```yaml
id: system-diagnostics
name: "System Diagnostics"
description: "Check system health across disk, memory, services, and logs"

params:
  target:
    type: string
    default: "all"
    description: "What to check: all, disk, memory, services, logs"
  verbose:
    type: boolean
    default: false

secrets:
  - MONITORING_API_KEY

defaults:
  bot_id: ops-bot
  model: gemini/gemini-2.5-flash
  carapaces: [ops-automation]
  timeout: 120

triggers:
  heartbeat: true
  tool: true
  api: true

# Session mode: "isolated" (default) = each step gets a fresh session
#              "shared" = all steps share one conversation session
session_mode: isolated

steps:
  - id: check_disk
    prompt: 'Check disk usage on the system. Target: "{{target}}".'
    tools: [exec_command]

  - id: check_services
    prompt: 'Check running services and their health status.'
    when:
      any:
        - param: target
          equals: "all"
        - param: target
          equals: "services"
    tools: [exec_command]

  - id: analyze
    prompt: |
      Analyze results:
      - Disk: {{steps.check_disk.result}}
      - Services: {{steps.check_services.result}}
      Flag any issues that need attention.
    when:
      step: check_disk
      status: done

  - id: alert
    prompt: 'Send alert about: {{steps.analyze.result}}'
    when:
      step: analyze
      output_contains: "CRITICAL"
    requires_approval: true
```

## Step Fields

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | string | required | Unique within workflow, used in `when` refs |
| `prompt` | string | required | `{{param}}` and `{{steps.id.result}}` substitution |
| `when` | dict/null | null (always) | Condition — skip step if false |
| `requires_approval` | bool | false | Pause for human approval before running |
| `on_failure` | string | "abort" | `"abort"`, `"continue"`, `"retry:N"` |
| `secrets` | list | [] | Subset of workflow secrets for this step |
| `tools` | list | [] | Additional tools to inject |
| `carapaces` | list | [] | Additional carapaces |
| `model` | string | null | Override model for this step |
| `timeout` | int | null | Override timeout (seconds) |

## Session Mode

Controls how step conversations relate to each other:

| Mode | Behavior |
|---|---|
| `isolated` (default) | Each step runs in its own fresh session. Steps communicate only through `{{steps.id.result}}` template substitution. |
| `shared` | All steps share a same session — each step's conversation builds on previous steps. The LLM sees the full conversation history. |

**When to use `shared`:** When steps need rich context from previous steps beyond what result summaries provide — e.g., iterative refinement, multi-turn analysis, code generation that builds on prior output.

**When to use `isolated`:** When steps are independent or communicate through structured outputs. Default and recommended for most workflows — keeps context clean and token-efficient.

```yaml
session_mode: shared  # All steps share conversation context
```

## Condition Syntax

Conditions are dict-based (no eval, no expression parsing):

```yaml
# Step completed successfully
when:
  step: search
  status: done

# Step result contains text (case-insensitive)
when:
  step: search
  status: done
  output_contains: '"found": true'

# Step result does NOT contain text
when:
  step: search
  output_not_contains: "error"

# Parameter check
when:
  param: verbose
  equals: true

# AND — all must be true
when:
  all:
    - step: search
      status: failed
    - param: fallback_enabled
      equals: true

# OR — any must be true
when:
  any:
    - step: search
      status: done
    - step: cache_lookup
      status: done

# NOT — negation
when:
  not:
    step: search
    status: done
```

## Prompt Templates

Use `{{variable}}` for substitution:

- `{{param_name}}` → resolved parameter value
- `{{steps.step_id.result}}` → prior step's result text
- `{{steps.step_id.status}}` → prior step's status (done/failed/skipped)

Unresolved templates are left as-is (safe for missing optional refs).

## Scoped Secrets

Workflows declare allowed secrets at the workflow level. Steps can further restrict to a subset:

```yaml
secrets: [API_KEY_A, API_KEY_B, DB_PASSWORD]

steps:
  - id: fetch
    secrets: [API_KEY_A]  # Only API_KEY_A injected into sandbox
  - id: store
    secrets: [DB_PASSWORD]  # Only DB_PASSWORD injected
```

Secrets must exist in the SecretValue store — workflow trigger fails if any are missing.

## API Endpoints

All under `/api/v1/admin/` with `workflows:read` or `workflows:write` scopes:

| Method | Path | Scope |
|---|---|---|
| GET | `/workflows` | read |
| POST | `/workflows` | write |
| GET | `/workflows/{id}` | read |
| PUT | `/workflows/{id}` | write |
| DELETE | `/workflows/{id}` | write |
| POST | `/workflows/{id}/run` | write |
| GET | `/workflows/{id}/runs` | read |
| GET | `/workflow-runs/{run_id}` | read |
| POST | `/workflow-runs/{run_id}/cancel` | write |
| POST | `/workflow-runs/{run_id}/steps/{idx}/approve` | write |
| POST | `/workflow-runs/{run_id}/steps/{idx}/skip` | write |
| POST | `/workflow-runs/{run_id}/steps/{idx}/retry` | write |

## Execution Model

1. `trigger_workflow()` validates params + secrets, creates `WorkflowRun`
2. `advance_workflow()` loops through pending steps:
   - Evaluates `when` condition → skip if false
   - Checks `requires_approval` → pause if true
   - Creates a `Task` (type=`workflow`) → task worker executes it
3. Task completes → `after_task_complete` hook fires → `on_step_task_completed()`
4. Step result captured, `on_failure` policy applied, then `advance_workflow()` again
5. All steps terminal → run marked `complete` or `failed`

Each step's task gets a unique `correlation_id` stored in `step_states` for token tracking.

## Common Patterns

**Heartbeat-triggered workflow:**
Pin `manage_workflow` in the heartbeat's bot tools, then use a heartbeat prompt like:
```
Check if conditions warrant running the diagnostics workflow.
If disk usage > 80% or any service is degraded, trigger it:
manage_workflow(action="trigger", id="system-diagnostics")
```

**Conditional fallback chain:**
```yaml
steps:
  - id: primary
    prompt: "Try the primary approach."
  - id: fallback
    prompt: "Primary failed. Try fallback."
    when:
      step: primary
      status: failed
    on_failure: continue
  - id: report
    prompt: "Summarize what happened."
```

**Approval-gated deployment:**
```yaml
steps:
  - id: build
    prompt: "Build and test the project."
  - id: deploy
    prompt: "Deploy to production."
    when:
      step: build
      status: done
      output_not_contains: "test failures"
    requires_approval: true
  - id: verify
    prompt: "Verify deployment health."
    when:
      step: deploy
      status: done
```
