# Workflows

Workflows are reusable multi-step automations defined in YAML. They support conditions, approval gates, cross-bot delegation, scoped secrets, and multiple trigger methods.

---

## Quick Start

Create a YAML file in the `workflows/` directory:

```yaml
# workflows/daily-summary.yaml
id: daily-summary
name: "Daily Summary"
description: Gather updates and compile a summary.

params:
  focus_area:
    type: string
    required: false
    default: "all"

steps:
  - id: gather
    prompt: |
      Search for recent activity related to "{{focus_area}}".
      Summarize what you find.
    tools: [web_search]

  - id: compile
    prompt: |
      Based on the research results:
      {{steps.gather.result}}

      Write a concise daily summary report.
```

Restart the server — the workflow appears in **Admin > Workflows** and is available to bots via the `manage_workflow` tool.

---

## Triggering Workflows

### From the UI

1. Go to **Admin > Workflows**
2. Click a workflow → **Runs** tab → **Trigger**
3. Fill in parameters and click **Run**

### From a Bot

Bots can trigger workflows conversationally:

> "Run the daily-summary workflow with focus_area set to security"

The bot uses the `manage_workflow` tool with `action: trigger`.

### From a Heartbeat

Set `workflow_id` on a channel heartbeat to trigger a workflow on a schedule instead of running an inline prompt. See the [Heartbeats guide](heartbeats.md).

### From the API

```bash
curl -X POST /api/v1/admin/workflows/daily-summary/run \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"params": {"focus_area": "security"}, "bot_id": "default"}'
```

---

## YAML Reference

### Top-Level Fields

```yaml
id: my-workflow              # Unique ID (kebab-case)
name: "My Workflow"           # Display name
description: |                # Optional description
  What this workflow does.

params:                       # Parameters (provided at trigger time)
  param_name:
    type: string              # string | number | boolean
    required: true
    default: "fallback"

secrets:                      # Required secrets (must exist in Admin > Secrets)
  - MY_API_TOKEN

defaults:                     # Applied to all steps unless overridden
  model: gemma4:e4b
  timeout: 120
  tools: [web_search]
  carapaces: [researcher]
  inject_prior_results: true
  prior_result_max_chars: 500
  result_max_chars: 2000

triggers:                     # Which trigger methods are allowed
  api: true
  tool: true
  heartbeat: true

tags: [monitoring, daily]     # Categorization
session_mode: isolated        # isolated | shared

steps:
  - id: step-one
    # ... (see Step Fields below)
```

### Step Fields

```yaml
steps:
  - id: step-id               # Unique within this workflow
    type: agent                # agent (default) | exec | tool

    # --- Prompt (agent and exec types) ---
    prompt: |
      Use {{param_name}} for parameter interpolation.
      Use {{steps.prior_step.result}} for prior step output.
      Use {{steps.prior_step.status}} for prior step status.

    # --- Execution config (overrides defaults) ---
    model: gemini/gemini-2.5-pro
    timeout: 300
    tools: [web_search, exec_command]
    carapaces: [code-review]
    secrets: [MY_API_TOKEN]    # Scoped to workflow-declared secrets

    # --- Conditional execution ---
    when:
      step: prior-step
      status: done

    # --- Approval gate ---
    requires_approval: true

    # --- Failure handling ---
    on_failure: abort          # abort | continue | retry:N

    # --- Result config ---
    result_max_chars: 3000
    inject_prior_results: true
    prior_result_max_chars: 500

    # --- Exec type only ---
    args: [--verbose]
    working_directory: /workspace

    # --- Tool type only ---
    tool_name: manage_channel
    tool_args:
      action: create
      name: "{{channel_name}}"
```

### Step Types

| Type | What it does | Creates a Task? |
|------|-------------|-----------------|
| `agent` | Runs the full agent loop with tools, skills, carapaces | Yes |
| `exec` | Executes a shell command | Yes |
| `tool` | Calls a local tool function directly | No (inline) |

---

## Conditions

Steps can be conditionally executed with the `when` field. If the condition is false, the step is **skipped** (not failed).

### Step status check

```yaml
when:
  step: gather-data
  status: done              # done | failed | skipped
```

### Step output check

```yaml
when:
  step: analyze
  output_contains: "critical"    # Case-insensitive substring match
```

```yaml
when:
  step: analyze
  output_not_contains: "no issues"
```

### Parameter check

```yaml
when:
  param: depth
  equals: "deep"
```

### Compound conditions

```yaml
# ALL must be true
when:
  all:
    - step: gather
      status: done
    - param: mode
      equals: "advanced"

# ANY must be true
when:
  any:
    - param: depth
      equals: "quick"
    - param: depth
      equals: "standard"

# Negation
when:
  not:
    step: check
    status: failed
```

---

## Approval Gates

Add `requires_approval: true` to pause the workflow before a step executes. The workflow enters `awaiting_approval` status until someone acts.

```yaml
steps:
  - id: analyze
    prompt: Analyze the situation and recommend changes.

  - id: apply-changes
    requires_approval: true
    prompt: |
      Apply the recommended changes:
      {{steps.analyze.result}}
```

### Responding to approval gates

**From the UI:** Open the workflow run → click **Approve**, **Skip**, or **Retry** on the gated step.

**From the API:**
```bash
# Approve — creates the task and continues
POST /api/v1/admin/workflow-runs/{run_id}/steps/{step_index}/approve

# Skip — marks step skipped, continues to next
POST /api/v1/admin/workflow-runs/{run_id}/steps/{step_index}/skip

# Retry — re-evaluate and try again
POST /api/v1/admin/workflow-runs/{run_id}/steps/{step_index}/retry
```

---

## Failure Handling

Control what happens when a step fails:

| Policy | Behavior |
|--------|----------|
| `abort` (default) | Stop the workflow, mark run as failed |
| `continue` | Mark step failed, proceed to next step |
| `retry:N` | Retry up to N times, then continue |

```yaml
steps:
  - id: risky-step
    on_failure: retry:3
    prompt: Try something that might fail.

  - id: cleanup
    on_failure: continue
    prompt: Clean up regardless of what happened.
```

---

## Secrets

Workflows can access secrets stored in **Admin > Security > Secrets**.

1. Declare required secrets at the workflow level:
   ```yaml
   secrets:
     - GITHUB_TOKEN
     - SLACK_WEBHOOK
   ```

2. Optionally scope secrets per step:
   ```yaml
   steps:
     - id: github-step
       secrets: [GITHUB_TOKEN]    # Only this secret available
   ```

3. Secrets are validated at trigger time — if any declared secret is missing from the vault, the workflow won't start.

4. At execution time, the bot accesses secrets via the `get_secret_value` tool.

---

## Session Modes

### Isolated (default)

Each step gets a fresh session. Steps don't see each other's conversation history and don't appear in the channel's chat feed.

Use prior step results via template interpolation:

```yaml
- id: step-two
  prompt: |
    The previous step found:
    {{steps.step-one.result}}
```

Or enable automatic injection:

```yaml
defaults:
  inject_prior_results: true
  prior_result_max_chars: 500
```

### Shared

All steps share one session. Each step sees the full conversation context from prior steps and the channel's history.

```yaml
session_mode: shared
```

Good for workflows where steps build on each other conversationally. Note that step prompts appear in the channel's chat feed.

---

## Template Variables

Prompts support `{{variable}}` interpolation:

| Variable | Resolves to |
|----------|-------------|
| `{{param_name}}` | Parameter value from trigger |
| `{{steps.step_id.result}}` | Output of a completed step |
| `{{steps.step_id.status}}` | Step status: `pending`, `running`, `done`, `failed`, `skipped` |

Unresolved variables are left as-is (safe fallback — won't crash).

---

## Bot Tool Reference

Bots interact with workflows via `manage_workflow`:

| Action | What it does |
|--------|-------------|
| `list` | List all workflows with step/param counts |
| `get` | Get workflow definition by ID |
| `trigger` | Start a run (returns run_id) |
| `get_run` | Check run status and step results |
| `list_runs` | Recent runs for a workflow |
| `create` | Define a new workflow programmatically |

---

## Examples

### Research and Report

Multi-angle research with conditional deep-dive:

```yaml
id: research-and-report
name: "Research & Report"

params:
  topic:
    type: string
    required: true
  depth:
    type: string
    default: "standard"

defaults:
  tools: [web_search]
  inject_prior_results: true

steps:
  - id: initial-search
    prompt: |
      Research "{{topic}}". Search from multiple angles.
      Depth level: {{depth}}

  - id: cross-reference
    when:
      param: depth
      equals: "deep"
    prompt: |
      Cross-reference and verify the findings:
      {{steps.initial-search.result}}

  - id: compile-report
    prompt: |
      Compile a final report on "{{topic}}".
      Include sources and confidence levels.
```

### System Diagnostics with Approval Gate

Health check that requires human approval before remediation:

```yaml
id: system-diagnostics
name: "System Diagnostics"

params:
  target:
    type: string
    default: "all"

steps:
  - id: check-resources
    prompt: Check disk usage, memory, and CPU. Flag anything above 80%.
    tools: [exec_command]

  - id: check-services
    when:
      any:
        - param: target
          equals: "all"
        - param: target
          equals: "services"
    prompt: Check that all critical services are running.
    tools: [exec_command]

  - id: analyze
    prompt: |
      Analyze the results and recommend actions:
      {{steps.check-resources.result}}
      {{steps.check-services.result}}
    inject_prior_results: true

  - id: remediate
    requires_approval: true
    on_failure: continue
    prompt: |
      Apply the recommended fixes:
      {{steps.analyze.result}}
    tools: [exec_command]
```

### Channel Setup (Tool Steps)

Automated channel creation using inline tool calls:

```yaml
id: channel-setup
name: "Channel Setup"

params:
  channel_name:
    type: string
    required: true
  bot_id:
    type: string
    default: "default"
  purpose:
    type: string
    default: "General project channel"

steps:
  - id: create-channel
    type: tool
    tool_name: manage_channel
    tool_args:
      action: create
      name: "{{channel_name}}"
      bot_id: "{{bot_id}}"

  - id: configure
    prompt: |
      A new channel was created:
      {{steps.create-channel.result}}

      Set up the workspace for: {{purpose}}
      Pick an appropriate template and configure the channel prompt.
```

---

## Managing Workflows

### From Files

Drop YAML in `workflows/` (or `integrations/*/workflows/` for integration-specific workflows). File-based workflows are read-only in the UI — edit the file and restart.

### From the UI

**Admin > Workflows** lets you create, edit, and manage workflows. Workflows created in the UI are stored in the database with source type `manual`.

### Monitoring Runs

- **Admin > Workflows > [workflow] > Runs** — Step-by-step timeline with status, results, and timing
- **Admin > Tasks** — Workflow-created tasks appear with `task_type: workflow`
- Bots can check runs via `manage_workflow` with `action: get_run`

### Chat Visibility

When a workflow runs on a channel, lifecycle messages automatically appear in the channel chat feed:

- **Started** — posted when the workflow begins
- **Step done / Step failed** — posted after each step completes, with a result preview
- **Completed / Failed** — posted when the workflow finishes, with a summary

These messages render as collapsed cards (similar to heartbeat messages) — click to expand and see the full step result. They include a step progress indicator (e.g., "2/5") and are tagged with the workflow name.

### Exporting

Export a workflow as YAML from the UI or API:

```bash
POST /api/v1/admin/workflows/{id}/export
```
