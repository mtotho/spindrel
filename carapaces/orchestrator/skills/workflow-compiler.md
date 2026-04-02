---
name: workflow-compiler
description: >
  Guide for analyzing completed workflow runs and generating equivalent standalone
  scripts (Python, Bash, or YAML). Load when asked to "compile", "export", or
  "script" a workflow, or when debugging a workflow run by reconstructing what happened.
---

# Workflow Compiler

## Purpose

Turn completed workflow runs into standalone, reproducible scripts. This is useful when:
- A workflow worked well and should become a cron job or CI step
- Someone needs to understand exactly what a workflow did (forensics)
- You want to test a workflow's logic without the engine overhead
- A workflow needs to run in an environment without the agent server

## Compilation Process

### Step 1: Gather the Run Data

```python
# Get the workflow definition
manage_workflow(action="get", id="<workflow_id>")

# Get the specific run with step states
manage_workflow(action="get_run", run_id="<run_id>")
```

From `get` you get: params schema, defaults, steps (prompts, conditions, tools, carapaces), session_mode, secrets.
From `get_run` you get: actual param values used, per-step status/result/error/timestamps, overall outcome.

### Step 2: Analyze the Execution Path

Walk through `step_states` in order. For each step:

| Step State | What Happened |
|---|---|
| `done` | Step ran successfully — its `result` is the LLM output |
| `skipped` | `when` condition evaluated false — step was bypassed |
| `failed` | Step errored — check `error` field and `on_failure` policy |
| `pending` | Never reached (workflow aborted earlier) |

Map the actual execution path: which steps ran, which were skipped, what conditions resolved to. This is the "trace" of the run.

### Step 3: Reconstruct Condition Logic

Translate `when` clauses into script conditionals:

```yaml
# Workflow condition:
when:
  step: check
  output_contains: "NOT_FOUND"

# Becomes Python:
if "NOT_FOUND" in steps["check"]["result"].upper():
    # run this step

# Workflow condition:
when:
  all:
    - step: diagnose
      status: done
    - step: diagnose
      output_not_contains: "DOWNLOADING"

# Becomes Python:
if (steps["diagnose"]["status"] == "done"
    and "DOWNLOADING" not in steps["diagnose"]["result"].upper()):
    # run this step
```

Key rules:
- `output_contains` / `output_not_contains` are **case-insensitive** — use `.upper()` or `.lower()` in scripts
- `all` = AND (all conditions must be true)
- `any` = OR (at least one must be true)
- `not` = negate the inner condition
- `param` + `equals` = check parameter value
- Missing/null `when` = always run

### Step 4: Generate the Script

Choose the output format based on context:

| Format | Best For |
|---|---|
| **Python** | Complex conditions, API calls, error handling, tool integration |
| **Bash** | Simple sequential steps, cron jobs, CI pipelines |
| **YAML** (new workflow) | When the goal is a modified/simplified workflow definition |

#### Python Template

```python
#!/usr/bin/env python3
"""
Compiled from workflow: {workflow_name}
Run ID: {run_id}
Generated: {timestamp}

Original params: {params}
Session mode: {session_mode}
"""
import os
import sys
import json
import requests

# --- Configuration ---
SERVER_URL = os.environ.get("AGENT_SERVER_URL", "http://localhost:8000")
API_KEY = os.environ.get("AGENT_API_KEY", "")
BOT_ID = "{bot_id}"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# --- Parameters (from original run) ---
params = {params_dict}

# --- Step execution helper ---
def run_step(step_id: str, prompt: str, model: str | None = None,
             tools: list[str] | None = None) -> dict:
    """Send a prompt to the agent and return the response."""
    payload = {
        "message": prompt,
        "bot_id": BOT_ID,
        "client_id": f"compiled-{step_id}",
    }
    if model:
        payload["model_override"] = model
    resp = requests.post(f"{SERVER_URL}/v1/chat", json=payload, headers=HEADERS)
    resp.raise_for_status()
    return {"status": "done", "result": resp.json().get("response", "")}


steps = {}

# --- Step: {step_id} ---
# {step_prompt_summary}
{condition_check}
steps["{step_id}"] = run_step("{step_id}", """{prompt}""")
print(f"[{step_id}] {steps['{step_id}']['status']}")

# ... repeat for each step ...

# --- Summary ---
print("\\n=== Workflow Complete ===")
for sid, state in steps.items():
    print(f"  {sid}: {state['status']}")
```

#### Bash Template (simpler workflows)

```bash
#!/usr/bin/env bash
# Compiled from workflow: {workflow_name}
# Run ID: {run_id}
set -euo pipefail

SERVER="${AGENT_SERVER_URL:-http://localhost:8000}"
API_KEY="${AGENT_API_KEY}"

call_agent() {
  local step_id="$1" prompt="$2"
  curl -s -X POST "$SERVER/v1/chat" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"$prompt\", \"bot_id\": \"BOT_ID\", \"client_id\": \"compiled-$step_id\"}"
}

# Step: check
RESULT_check=$(call_agent "check" "...")
echo "[check] done"

# Step: diagnose (conditional)
if echo "$RESULT_check" | grep -qi "NOT_FOUND"; then
  RESULT_diagnose=$(call_agent "diagnose" "...")
  echo "[diagnose] done"
fi
```

### Step 5: Handle Edge Cases

**`on_failure` policies:**
- `abort` → wrap in try/except, `sys.exit(1)` on failure
- `continue` → catch exception, record error, continue to next step
- `retry:N` → wrap in a retry loop with the specified count

```python
# retry:3 pattern
for attempt in range(3):
    try:
        steps["flaky_step"] = run_step("flaky_step", "...")
        break
    except Exception as e:
        if attempt == 2:
            steps["flaky_step"] = {"status": "failed", "error": str(e)}
```

**`requires_approval` gates:**
- In scripts, replace with a confirmation prompt: `input("Approve step 'execute'? [y/N] ")`
- Or skip the gate entirely if the script is meant for unattended execution

**Template substitution:**
- `{{param_name}}` → use the actual parameter values from the run
- `{{steps.step_id.result}}` → reference the captured result from earlier steps
- In Python: f-strings or `.format()` with the steps dict

**Scoped secrets:**
- Map to environment variables in the script
- Document which env vars each step needs

**Session mode implications:**
- `isolated`: Each step is independent — the script naturally models this (separate API calls)
- `shared`: Steps share context — either use a single session_id across calls, or concatenate prior results into each step's prompt

## Output Checklist

When presenting a compiled script, include:

1. **Header comment** with source workflow ID, run ID, generation timestamp
2. **Required environment variables** (SERVER_URL, API_KEY, any scoped secrets)
3. **Parameter documentation** (what each param does, defaults used)
4. **Execution path annotation** (which steps ran in the original, which were skipped)
5. **Idempotency notes** (is it safe to re-run? which steps have side effects?)
6. **Diff from definition** (if the run deviated from the workflow definition — e.g., retries, failures)

## Forensic Analysis Mode

When the goal is understanding what happened (not generating a script):

1. Pull the run with `get_run`
2. Present a timeline:
   ```
   [00:00] Step 'check' started
   [00:03] Step 'check' completed (result: "STATUS: NOT_FOUND — title not in Jellyfin library")
   [00:03] Step 'diagnose' started (condition met: check output contains "NOT_FOUND")
   [00:08] Step 'diagnose' completed (result: "DIAGNOSIS: Sonarr has the series but no episodes grabbed...")
   [00:08] Step 'fix' skipped (condition not met: diagnose output contains "DOWNLOADING")
   [00:08] Step 'report' started
   [00:10] Step 'report' completed
   ```
3. Highlight any anomalies: retries, failures, unexpectedly skipped steps, long durations
4. Compare actual execution against the workflow definition to identify drift
