---
name: workflows
description: >
  Workflow system reference for orchestrators. Load when creating, triggering,
  or managing reusable multi-step workflow templates. Covers YAML format,
  conditions, approval gates, scoped secrets, design patterns, and integration composition.
---

# Workflow System Reference

## Overview

Workflows are reusable, parameterized multi-step templates. Each step runs an independent LLM call — the workflow engine handles sequencing, conditions, and control flow deterministically. Use workflows when you need **repeatable automation** that goes beyond single-turn delegation.

**Key principle:** LLMs make unreliable orchestrators — use code for plumbing, LLMs for creative work. Workflows handle sequencing, conditions, and control flow deterministically; each step's LLM call handles the creative work.

## When to Use What

| Scenario | Use | Why |
|---|---|---|
| One-off task for a specific bot | `delegate_to_agent` | No reuse needed, just fire and forget |
| Repeatable multi-step process with conditions | **Workflow** | Define once, trigger many times with different params |
| Fan-out to multiple bots simultaneously | Delegation (parallel) | Workflows run steps sequentially |
| Sequential steps with approval gates | **Workflow** | Built-in `requires_approval` with UI approval flow |
| Diagnostic/troubleshooting chains | **Workflow** | Conditions let you branch on findings |
| Steps that need scoped secret access | **Workflow** | Per-step secret restriction |
| Periodic checks that may escalate | Heartbeat → **Workflow** | Heartbeat detects, workflow remediates |
| "If X then do Y, else do Z" logic | **Workflow** | Conditions are deterministic, not LLM-guessed |

## manage_workflow Tool

```python
# List available workflows
manage_workflow(action="list")

# Get full workflow definition
manage_workflow(action="get", id="system-diagnostics")

# Trigger a workflow run
manage_workflow(
    action="trigger",
    id="media-troubleshoot",
    params='{"title": "The Pitt S02E13", "media_type": "tv"}',
    bot_id="media-bot",           # Optional: overrides workflow default
    channel_id="<uuid>",          # Optional: channel context
)
# Returns: {"run_id": "...", "status": "running", "step_count": 4}

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

Workflows live in `workflows/*.yaml` and `integrations/*/workflows/*.yaml` (auto-synced on startup and file change):

```yaml
id: media-troubleshoot
name: "Media Troubleshoot"
description: "Diagnose why content isn't on Jellyfin"

params:
  title:
    type: string
    required: true
    description: "Show or movie name"
  media_type:
    type: string
    default: "auto"

defaults:
  model: gemini/gemini-2.5-flash
  carapaces: [arr]          # Give steps access to integration tools
  timeout: 180

triggers:
  heartbeat: true           # Heartbeat can trigger this
  tool: true                # Bot can trigger via manage_workflow
  api: true                 # Admin API can trigger

tags: [media, troubleshooting]
session_mode: shared        # Steps share conversation context

steps:
  - id: check_jellyfin
    prompt: 'Search Jellyfin for "{{title}}"...'
  - id: diagnose
    prompt: 'Check the download chain...'
    when:
      step: check_jellyfin
      output_contains: "NOT_FOUND"
  - id: fix
    prompt: 'Take corrective action...'
    when:
      all:
        - step: diagnose
          status: done
        - step: diagnose
          output_not_contains: "DOWNLOADING"
    on_failure: continue
  - id: report
    prompt: 'Summarize what happened...'
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

| Mode | Behavior | Best For |
|---|---|---|
| `isolated` (default) | Each step gets fresh session. Steps communicate via `{{steps.id.result}}` templates. | Independent steps, structured outputs, token efficiency |
| `shared` | All steps share one conversation session. LLM sees full history. | Diagnostic chains, iterative refinement, troubleshooting where context accumulates |

**Rule of thumb:** Use `shared` when the workflow is a conversation (each step builds on prior understanding). Use `isolated` when steps are independent tasks that pass structured data.

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
  output_contains: "NOT_FOUND"

# Step result does NOT contain text
when:
  step: search
  output_not_contains: "DOWNLOADING"

# Parameter check
when:
  param: verbose
  equals: true

# AND — all must be true
when:
  all:
    - step: check
      status: done
    - step: check
      output_not_contains: "OK"

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

- `{{param_name}}` → resolved parameter value
- `{{steps.step_id.result}}` → prior step's result text
- `{{steps.step_id.status}}` → prior step's status (done/failed/skipped)

Unresolved templates are left as-is (safe for missing optional refs).

## Scoped Secrets

Workflows declare allowed secrets at the workflow level. Steps can further restrict:

```yaml
secrets: [API_KEY_A, API_KEY_B, DB_PASSWORD]
steps:
  - id: fetch
    secrets: [API_KEY_A]  # Only API_KEY_A injected into sandbox
  - id: store
    secrets: [DB_PASSWORD]  # Only DB_PASSWORD injected
```

Note: Integration tools (arr, github, slack) use their own config lookup (`IntegrationSetting` table), not sandbox env injection. Scoped secrets are for tools that read env vars directly (like `exec_command`).

## API Endpoints

All under `/api/v1/admin/`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/workflows` | List workflow definitions |
| POST | `/workflows` | Create workflow |
| GET | `/workflows/{id}` | Get workflow definition |
| PUT | `/workflows/{id}` | Update (manual/bot source only) |
| DELETE | `/workflows/{id}` | Delete workflow |
| POST | `/workflows/{id}/run` | Trigger run (body: params, bot_id, channel_id) |
| GET | `/workflows/{id}/runs` | List runs for a workflow |
| GET | `/workflow-runs/{run_id}` | Get run details + step states |
| POST | `/workflow-runs/{run_id}/cancel` | Cancel active run |
| POST | `/workflow-runs/{run_id}/steps/{idx}/approve` | Approve gated step |
| POST | `/workflow-runs/{run_id}/steps/{idx}/skip` | Skip gated step |
| POST | `/workflow-runs/{run_id}/steps/{idx}/retry` | Retry failed step |

## Execution Model

1. `trigger_workflow()` validates params + secrets, creates `WorkflowRun`
2. `advance_workflow()` loops through pending steps:
   - Evaluates `when` condition → skip if false
   - Checks `requires_approval` → pause if true
   - Creates a `Task` (type=`workflow`) → task worker executes it
3. Task completes → `after_task_complete` hook fires → `on_step_task_completed()`
4. Step result captured, `on_failure` policy applied, then `advance_workflow()` again
5. All steps terminal → run marked `complete` or `failed`

Each step's task gets a `correlation_id` in `step_states` for token/cost tracking.

---

## Design Patterns

### Pattern 1: Diagnostic Chain (Check → Diagnose → Fix → Report)

The most common workflow shape. First step checks for a problem, middle steps investigate and remediate, final step summarizes.

**Key technique — output markers:** Instruct steps to include specific text markers (e.g., `"STATUS: NOT_FOUND"`, `"DIAGNOSIS: STALLED"`) that downstream conditions can key off. This bridges the LLM's free-form output to the deterministic condition evaluator.

```yaml
session_mode: shared   # Diagnostic chains need accumulated context
steps:
  - id: check
    prompt: |
      Check if the problem exists.
      If found: reply with "STATUS: OK"
      If not found: reply with "STATUS: PROBLEM"
  - id: diagnose
    prompt: "Investigate the root cause..."
    when:
      step: check
      output_contains: "PROBLEM"
  - id: fix
    prompt: "Take corrective action based on your diagnosis..."
    when:
      step: diagnose
      status: done
    on_failure: continue    # Don't abort if fix fails
  - id: report
    prompt: "Summarize findings and actions taken."
```

**Real example:** `media-troubleshoot` — checks Jellyfin availability, investigates Sonarr/Radarr/qBit download chain, remediates (re-searches, grabs releases, triggers scans), and reports back conversationally.

### Pattern 2: Conditional Fallback Chain

Try a primary approach, fall back to secondary if it fails.

```yaml
steps:
  - id: primary
    prompt: "Try the primary approach."
  - id: fallback
    prompt: "Primary failed. Try the fallback approach."
    when:
      step: primary
      status: failed
    on_failure: continue
  - id: escalate
    prompt: "Both approaches failed. Escalate."
    when:
      all:
        - step: primary
          status: failed
        - step: fallback
          status: failed
    requires_approval: true
```

### Pattern 3: Approval-Gated Actions

Automated analysis with human approval before taking action. Use for anything destructive, expensive, or visible to others.

```yaml
steps:
  - id: analyze
    prompt: "Analyze the situation and recommend actions."
  - id: execute
    prompt: "Execute the recommended actions."
    when:
      step: analyze
      status: done
    requires_approval: true     # Pauses here until human approves
  - id: verify
    prompt: "Verify the actions were successful."
    when:
      step: execute
      status: done
```

### Pattern 4: Heartbeat-Triggered Workflow

A heartbeat detects a condition; a workflow handles the multi-step remediation. This separates detection (simple, cheap, frequent) from remediation (complex, multi-step, occasional).

Pin `manage_workflow` in the heartbeat bot's tools. Heartbeat prompt:
```
Check download queues. If any torrents are stalled for >1 hour:
manage_workflow(action="trigger", id="media-troubleshoot",
  params='{"title": "<stalled item name>", "media_type": "tv"}')
```

### Pattern 5: Integration Composition

Workflows get power from integration carapaces. Set `carapaces` in `defaults` to give all steps access to an integration's tools:

```yaml
defaults:
  carapaces: [arr]         # All arr tools available to every step
  model: gemini/gemini-2.5-flash
```

Or scope carapaces per-step for tighter control:
```yaml
steps:
  - id: check_jellyfin
    carapaces: [arr]       # Only this step gets arr tools
  - id: notify
    tools: [web_search]    # Different tools for this step
```

Available integration carapaces: `arr` (media stack), plus any custom carapaces from integrations or `carapaces/*.yaml`.

### Pattern 6: Parameterized Templates

Design workflows as reusable templates with sensible defaults. Good param design means the same workflow handles many situations:

```yaml
params:
  title:
    type: string
    required: true          # Must be provided
  media_type:
    type: string
    default: "auto"         # Sensible default
  quality:
    type: string
    default: "1080p"
```

Use params in conditions to control which steps run:
```yaml
when:
  param: include_subtitles
  equals: true
```

## Step Prompt Design Tips

1. **Be specific about tools.** Name the exact tool calls the step should make. Don't say "check the system" — say "run `sonarr_queue()` and `qbit_torrents(filter='stalled')`".

2. **Use output markers for conditions.** When downstream steps branch on output, tell the LLM exactly what markers to include: "End with STATUS: FOUND or STATUS: NOT_FOUND".

3. **Include the full tool call syntax.** Steps are independent LLM calls — they don't know your tool syntax conventions. Write out `tool_name(param="value")` explicitly.

4. **Keep prompts self-contained.** In `isolated` mode, each step only has its own prompt + any `{{steps.id.result}}` templates. In `shared` mode, it has conversation history but still benefits from a focused prompt.

5. **Set `on_failure: continue` for non-critical steps.** If a step failing shouldn't stop the whole workflow, mark it. The report step can still reference `{{steps.fix.status}}` to know what happened.

6. **Use shared mode for troubleshooting.** Diagnostic workflows accumulate context — "I checked X, then Y, then Z" is naturally a conversation. Isolated mode works for pipelines where each step transforms data.
