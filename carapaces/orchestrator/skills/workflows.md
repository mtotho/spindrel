---
name: workflows
description: >
  Workflow system reference for orchestrators. Load when creating, triggering,
  or managing reusable multi-step workflow templates. Covers YAML format,
  conditions, approval gates, scoped secrets, design patterns, and integration composition.
---

# Workflow System Reference

## Overview

Workflows are reusable, parameterized multi-step templates. Steps can be `agent` (LLM call), `tool` (direct tool call, no LLM), or `exec` (shell command, no LLM). The workflow engine handles sequencing, conditions, and control flow deterministically. Use workflows when you need **repeatable automation** that goes beyond single-turn delegation.

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

# Trigger a workflow run (bot_id and channel_id auto-default from context)
manage_workflow(
    action="trigger",
    id="media-troubleshoot",
    params='{"title": "The Pitt S02E13", "media_type": "tv"}',
)
# Returns: {"run_id": "...", "status": "running", "step_count": 4}
# bot_id defaults to current bot, channel_id defaults to current channel.
# Override explicitly only when triggering for a different bot:
#   bot_id="media-bot", channel_id="<uuid>"

# Check run status and step progress
manage_workflow(action="get_run", run_id="<run_id>")
# Returns: status, per-step progress (status, result preview, errors), timestamps

# List recent runs for a workflow (last 10)
manage_workflow(action="list_runs", id="media-troubleshoot")
# Returns: run_id, status, progress summary, timestamps

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

### Monitoring Workflow Runs

After triggering a workflow, use `get_run` to check progress:

```python
# Trigger and capture the run_id
result = manage_workflow(action="trigger", id="system-diagnostics")
# result.run_id = "abc-123..."

# Check progress (can call repeatedly)
manage_workflow(action="get_run", run_id="abc-123...")
# Shows: status, done/failed/skipped counts, per-step details

# See all recent runs for a workflow
manage_workflow(action="list_runs", id="system-diagnostics")
```

**Completion notifications** dispatch automatically to the originating channel's integration (Slack, webhook, etc.) at three points: workflow started, each step done/failed, and workflow completed/failed. No manual notification needed.

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
| `type` | string | `"agent"` | `"agent"` (LLM call), `"exec"` (shell command), `"tool"` (local tool call) |
| `prompt` | string | required | `{{param}}` and `{{steps.id.result}}` substitution. For `exec` type, this IS the command. |
| `when` | dict/null | null (always) | Condition — skip step if false |
| `requires_approval` | bool | false | Pause for human approval before running |
| `on_failure` | string | "abort" | `"abort"`, `"continue"`, `"retry:N"` |
| `secrets` | list | [] | Subset of workflow secrets for this step |
| `tools` | list | [] | Additional tools to inject (agent type only) |
| `carapaces` | list | [] | Additional carapaces (agent type only) |
| `model` | string | null | Override model for this step (agent type only) |
| `timeout` | int | null | Override timeout (seconds) |
| `tool_name` | string | — | **Required for `type: tool`**. Name of the local tool to call |
| `tool_args` | dict | {} | Arguments for the tool call. Values support `{{param}}` substitution |
| `args` | list | [] | CLI arguments for `type: exec` |
| `working_directory` | string | null | Working directory for `type: exec` |

## Step Types

Three step types let you skip the LLM for deterministic operations:

| Type | Behavior | Task created? | Use for |
|---|---|---|---|
| `agent` (default) | Full LLM agent call with tool access | Yes (`task_type="workflow"`) | Creative work, analysis, decision-making |
| `exec` | Run shell command in bot's sandbox | Yes (`task_type="exec"`) | Database backups, file operations, scripts |
| `tool` | Call a local tool directly, inline | No — executes immediately | API lookups, quick data fetches, deterministic operations |

### When to Use Each Type

**Use `type: tool` when:**
- The step calls exactly one tool with known arguments
- Arguments can be derived from params (`{{param}}`) or prior step results (`{{steps.X.result}}`)
- No LLM reasoning is needed — the action is deterministic
- Examples: create a channel, search for files, get system status, trigger a sub-workflow

**Use `type: exec` when:**
- The step runs a shell command that can be expressed as a template
- Examples: database backups, `curl` calls, file operations, running scripts

**Use `type: agent` when:**
- The step needs to analyze, interpret, or synthesize information
- The step needs to make decisions or choose between actions
- The step needs to call multiple tools dynamically based on context
- The output needs to be human-readable prose, not raw tool output

### `exec` Steps

The rendered `prompt` becomes the command. Supports `args` and `working_directory`:

```yaml
- id: backup_db
  type: exec
  prompt: "pg_dump -Fc mydb > /tmp/backup.dump"
  timeout: 120
```

### `tool` Steps

Call any registered local tool with arguments. Executes inline (no task worker delay). Result is captured into step state immediately:

```yaml
- id: search_files
  type: tool
  tool_name: web_search
  tool_args:
    query: "{{topic}}"
    count: "5"
```

`tool_args` values support `{{param}}` and `{{steps.X.result}}` substitution, same as prompts. The raw tool return value becomes the step's result (usually JSON).

### Mixing Types

Combine all three in one workflow — use tool/exec for data gathering, agent for analysis:

```yaml
steps:
  - id: fetch_data
    type: tool
    tool_name: web_search
    tool_args:
      query: "{{topic}}"

  - id: save_snapshot
    type: exec
    prompt: "curl -o /tmp/data.json '{{steps.fetch_data.result}}'"
    timeout: 30

  - id: analyze
    type: agent
    prompt: "Analyze the data from {{steps.fetch_data.result}} and provide insights."
    carapaces: [qa]
```

### Analyzing Existing Runs for Optimization

To identify which agent steps could be converted to tool/exec:

```python
# Get a completed run with full step details
manage_workflow(action="get_run", run_id="<id>",
    include_definitions=true, full_results=true)
```

This returns each step's definition (prompt, type, tool_name, conditions) alongside its actual result. Look for agent steps where the result is just a tool call's output — those are candidates for `type: tool`. For the full optimization process and conversion patterns, fetch `get_skill('carapaces/orchestrator/workflow-compiler')`.

## Session Mode

| Mode | Behavior | Best For |
|---|---|---|
| `isolated` (default) | Each step gets fresh session. Steps communicate via `{{steps.id.result}}` templates. | Independent steps, structured outputs, token efficiency |
| `shared` | All steps share one conversation session. LLM sees full history. | Diagnostic chains, iterative refinement, troubleshooting where context accumulates |

**Rule of thumb:** Use `shared` when the workflow is a conversation (each step builds on prior understanding). Use `isolated` when steps are independent tasks that pass structured data.

### Override at Trigger Time

Session mode can be overridden per-trigger without changing the workflow definition. The cascade is: **trigger override → workflow default → "isolated"**.

- **API**: `POST /workflows/{id}/trigger` with `session_mode: "shared"` or `"isolated"` in body
- **Bot tool**: `manage_workflow(action="trigger", id="...", session_mode="shared")`
- **Heartbeat**: Set `workflow_session_mode` on the channel heartbeat config

Use case: a workflow defined as `isolated` for normal automated runs can be triggered with `shared` for interactive debugging, so the operator sees step outputs in chat.

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

1. `trigger_workflow()` validates params + secrets, **snapshots the workflow definition** (steps, defaults, secrets) onto the run → creates `WorkflowRun` → dispatches "started" event
2. `advance_workflow()` loops through pending steps (reads from **snapshot**, not live definition):
   - Evaluates `when` condition → skip if false
   - Checks `requires_approval` → pause if true
   - **`type: tool`** → calls tool inline, captures result, continues to next step (no task created)
   - **`type: exec`** → creates `Task` (type=`exec`) with command in `execution_config` → task worker runs in sandbox
   - **`type: agent`** (default) → creates `Task` (type=`workflow`) → task worker runs LLM agent call
3. Task completes → `after_task_complete` hook fires → `on_step_task_completed()` → dispatches "step_done"/"step_failed"
4. Step result captured, `on_failure` policy applied, then `advance_workflow()` again
5. All steps terminal → run marked `complete` or `failed` → dispatches "completed"/"failed" → fires `after_workflow_complete` hook

**Definition snapshot:** Editing a workflow while a run is in progress won't affect that run — it uses the snapshot from trigger time. Old runs without snapshots gracefully fall back to the live definition.

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
# bot_id and channel_id auto-resolve from current context
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
