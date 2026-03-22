---
status: draft
last_updated: 2026-03-22
owner: mtoth
summary: >
  Implement a generic async exec primitive that runs any shell command
  with deferred callback on completion and mid-run output tailing.
  Harnesses become named aliases on top of it.
---

# delegate_to_exec — Generic Async Exec Primitive

## Goal

Replace the harness-specific execution path with a generic `delegate_to_exec` tool that:

1. **Takes any command**: `command`, `args`, `working_directory`, optional `stream_to` (file path for live output)
2. **Posts callback** to the originating channel on completion (same deferred mechanism as current harness flow)
3. **Writes output to a known file** mid-run so callers can `exec_sandbox` + `cat`/`tail -f` to monitor progress
4. **Preserves harnesses.yaml** as a thin alias layer — named presets that resolve to command+args, keeping the ergonomic "run claude-code" UX

`delegate_to_harness` becomes a convenience wrapper: look up the alias, expand `{prompt}` / `{working_directory}`, then call the exec primitive.

---

## Current Architecture

### End-to-end harness flow

```
Bot LLM calls delegate_to_harness(harness="claude-code", prompt="...", mode="deferred")
  │
  ├─ app/tools/local/delegation.py:delegate_to_harness()
  │    ├─ Validates bot.harness_access
  │    ├─ mode="sync"  → harness_service.run() → subprocess → return result inline
  │    └─ mode="deferred" → creates Task row:
  │         dispatch_type="harness"
  │         callback_config={harness_name, working_directory, output_dispatch_type/config,
  │                          sandbox_instance_id, notify_parent, parent_bot_id, parent_session_id}
  │
  ├─ app/agent/tasks.py:task_worker()  [polls every 5s]
  │    └─ fetch_due_tasks() → run_task() → dispatch_type=="harness" → run_harness_task()
  │
  ├─ app/agent/tasks.py:run_harness_task()
  │    ├─ Extracts config from callback_config
  │    ├─ harness_service.run(harness_name, prompt, working_directory, bot, sandbox_instance_id)
  │    ├─ Formats result text (stdout + stderr + exit code + duration)
  │    ├─ Stores result in Task row (status=complete)
  │    ├─ schedule_harness_completion_record() → audit trail (tool_calls + trace_events)
  │    ├─ dispatcher.deliver() → posts to output channel (Slack, webhook, etc.)
  │    └─ If notify_parent → creates callback Task for parent bot to react
  │
  └─ app/services/harness.py:HarnessService.run()
       ├─ Loads HarnessConfig from harnesses.yaml
       ├─ Validates bot.harness_access
       ├─ Substitutes {prompt}, {working_directory} in args
       ├─ Builds shell command: `cd <wd> && <command> <args>`
       └─ Executes via:
            ├─ sandbox_service.exec(instance, script)  [docker exec into named sandbox]
            └─ sandbox_service.exec_bot_local(bot_id, script, bot_sandbox_config)  [bot-local container]
```

### What's load-bearing (must be preserved)

1. **Sandbox-only execution** — harnesses never run on the host; always `docker exec` into a container (bot_sandbox or named sandbox instance). The new exec primitive must enforce the same constraint.

2. **Bot access control** — `bot.harness_access` allowlist gates which harnesses a bot can invoke. The exec primitive needs its own access control (or harness aliases inherit the existing check).

3. **Deferred task lifecycle** — Task row creation → task_worker pickup → status transitions (pending→running→complete/failed) → dispatcher delivery → parent notification. This is generic infrastructure, not harness-specific.

4. **Audit trail** — `schedule_harness_completion_record()` writes to `tool_calls` and `trace_events`. Should generalize to exec completions.

5. **Callback config structure** — The `callback_config` JSONB on the Task row carries all orchestration state. Changing its shape requires careful migration of any in-flight tasks.

6. **Template substitution** — `{prompt}` and `{working_directory}` in harnesses.yaml args. Must still work for alias resolution.

7. **Both sync and deferred modes** — sync returns result inline to the LLM; deferred creates a background task.

---

## Proposed Changes

### 1. New tool: `delegate_to_exec`

**File:** `app/tools/local/delegation.py` (add alongside existing tools)

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | yes | Executable name (e.g. `claude`, `python`, `npm`) |
| `args` | string[] | no | Arguments to pass |
| `working_directory` | string | no | Working dir inside the container |
| `sandbox_instance_id` | string | no | Target sandbox; falls back to bot_sandbox |
| `stream_to` | string | no | File path inside the container where stdout+stderr are tee'd for mid-run tailing |
| `mode` | "sync" \| "deferred" | no | Default: "sync" |
| `reply_in_thread` | boolean | no | Deferred mode: post result as thread reply |
| `notify_parent` | boolean | no | Deferred mode: re-run parent agent with result |

**Access control:** New bot YAML field `exec_access: true/false` (default false). When false, the tool returns an error. This is separate from `harness_access` — harness aliases implicitly have exec access since they go through the alias layer which checks `harness_access`.

**Sync mode:** Calls a new `ExecService.run()` (or reuses sandbox_service directly) that:
- Builds `sh -c 'cd <wd> && <command> <args>'`
- If `stream_to` is set: wraps as `sh -c '(<command> <args>) 2>&1 | tee <stream_to>; exit ${PIPESTATUS[0]}'`
- Executes via `sandbox_service.exec()` or `sandbox_service.exec_bot_local()`
- Returns stdout, stderr, exit_code, duration_ms, truncated

**Deferred mode:** Creates Task row with:
- `dispatch_type="exec"` (new type, parallel to "harness")
- `callback_config` carries: command, args, working_directory, stream_to, sandbox_instance_id, output dispatch info, notify_parent state

### 2. Changes to `app/services/harness.py`

**HarnessService stays**, but becomes thinner:
- `run()` still loads the `HarnessConfig`, checks access, substitutes templates
- Instead of directly calling `sandbox_service.exec()`, it builds the final command+args and delegates to the new exec primitive (or just calls the same sandbox exec — the key is that the *tool layer* changes, not necessarily the service layer)

Actually, the cleaner approach: **HarnessService stays as-is**. The harness service already handles config loading, template substitution, and sandbox execution. The new `delegate_to_exec` tool just provides a *raw* path that bypasses the harness config lookup. The two tools share the sandbox execution backend but have different entry points:

```
delegate_to_harness  →  HarnessService.run()  →  sandbox_service.exec()
delegate_to_exec     →  (direct)              →  sandbox_service.exec()
```

This is simpler and lower-risk than refactoring HarnessService internals.

### 3. Does `delegate_to_harness` still exist?

**Yes.** It stays as the ergonomic named-alias interface. No changes needed to the tool itself — it already works. The only question is whether we want harnesses.yaml to *also* be invocable via `delegate_to_exec` by name. Answer: no. Keep them separate. Harness aliases are for curated presets; exec is for raw commands. If someone wants to run `claude --print "foo"` directly, they use `delegate_to_exec`. If they want the `claude-code` preset with all its args pre-configured, they use `delegate_to_harness`.

### 4. Harnesses.yaml aliases

**No changes to harnesses.yaml format.** It continues to define named presets consumed by `HarnessService`. The plan's original concept of "harnesses become thin named aliases that resolve to a command+args" is achieved by the *coexistence* of the two tools: harnesses.yaml is the alias layer, `delegate_to_exec` is the raw layer.

Future enhancement (out of scope for this plan): a `resolve_harness` helper that returns the expanded command+args for a harness name, so a caller could inspect what a harness would run before executing it.

### 5. Output streaming file

**Location inside container:** `/tmp/exec-output/<task_id>.log`
- Directory created by the exec wrapper script before running the command
- When `stream_to` is explicitly provided, use that path instead
- The bot can tail this file mid-run via `exec_sandbox(command="tail -f /tmp/exec-output/<task_id>.log")`

**Implementation:** The subprocess command is wrapped:

```bash
mkdir -p /tmp/exec-output
(<command> <args>) 2>&1 | tee /tmp/exec-output/<task_id>.log
exit ${PIPESTATUS[0]}
```

For sync mode with `stream_to`: same tee wrapper, but the caller gets the full result back when it completes. The file is a bonus for external monitoring.

For deferred mode: the task_id is known at Task creation time, so the output path is deterministic. Include the path in the tool's return value so the bot knows where to look:

```json
{"task_id": "abc-123", "status": "deferred", "output_file": "/tmp/exec-output/abc-123.log"}
```

### 6. Task worker changes

**File:** `app/agent/tasks.py`

Add a new handler parallel to `run_harness_task`:

```python
async def run_exec_task(task: Task) -> None:
    """Execute a raw exec task: run command in sandbox, store result, dispatch."""
```

Update `run_task()` routing:

```python
if task.dispatch_type == "harness":
    await run_harness_task(task)
    return
if task.dispatch_type == "exec":
    await run_exec_task(task)
    return
```

`run_exec_task` follows the same lifecycle as `run_harness_task`:
1. Mark running
2. Extract command/args/working_directory/stream_to/sandbox_instance_id from callback_config
3. Build shell script with tee wrapper
4. Execute via sandbox_service
5. Store result, mark complete
6. Record to audit trail (generalize `schedule_harness_completion_record` → `schedule_exec_completion_record`)
7. Dispatch to output channel
8. Notify parent if configured

### 7. Bot config changes

**File:** `app/agent/bots.py`

Add `exec_access: bool = False` to `BotConfig`. Loaded from bot YAML:

```yaml
exec_access: true  # allow delegate_to_exec
```

---

## Implementation Steps

### PR 1: Add `delegate_to_exec` tool (sync mode only)

1. Add `exec_access` field to `BotConfig` in `app/agent/bots.py`
2. Add `delegate_to_exec` tool function in `app/tools/local/delegation.py`
   - Sync mode only (deferred comes in PR 2)
   - Build command string, apply tee wrapper if `stream_to` is set
   - Call `sandbox_service.exec()` or `exec_bot_local()` directly
   - Return exit_code, stdout, stderr, duration_ms, output_file (if stream_to)
3. Add unit tests: access control, command building, stream_to wrapping
4. Test manually with a bot that has `exec_access: true` and `bot_sandbox` enabled

### PR 2: Add deferred mode + task worker routing

1. Add `run_exec_task()` to `app/agent/tasks.py`, following `run_harness_task` pattern
2. Update `run_task()` to route `dispatch_type="exec"` → `run_exec_task()`
3. Update `delegate_to_exec` to support `mode="deferred"`:
   - Create Task with `dispatch_type="exec"`, `callback_config` carrying command/args/stream_to/etc.
   - Return task_id + deterministic output_file path
4. Generalize audit recording: `schedule_exec_completion_record()` (or rename existing to cover both)
5. Add tests: deferred task creation, worker pickup, result dispatch, parent notification

### PR 3: Documentation + bot YAML examples

1. Update CLAUDE.md with `delegate_to_exec` tool documentation
2. Add example bot YAML showing `exec_access: true`
3. Document the output file convention (`/tmp/exec-output/<task_id>.log`)
4. Document how to tail output mid-run

---

## Risk Assessment

### What could break

1. **Arbitrary command execution** — The biggest risk. Unlike harnesses (curated commands in harnesses.yaml), `delegate_to_exec` allows any command. Mitigation: sandbox-only execution (never on host), `exec_access` gating per bot, and the existing sandbox security model (container isolation, resource limits).

2. **Command injection via args** — If args are naively interpolated into a shell string. Mitigation: use `shlex.join()` for the command+args (same as HarnessService does), never use string interpolation for user-provided values.

3. **stream_to path traversal** — A malicious `stream_to` path could overwrite container files. Mitigation: validate that `stream_to` starts with `/tmp/` or is within a known safe prefix. Low severity since it's inside a container, but still worth guarding.

4. **In-flight harness tasks** — No migration risk since we're adding a new `dispatch_type="exec"` alongside the existing `"harness"` type, not replacing it. Existing deferred harness tasks continue to work unchanged.

5. **Bot config backward compatibility** — `exec_access` defaults to `false`, so no existing bot gains new capabilities. Safe additive change.

6. **Tee + PIPESTATUS portability** — The `tee` wrapper relies on `${PIPESTATUS[0]}` which is bash-specific. Container images using plain `sh` (alpine/busybox) won't support it. Mitigation: detect shell or use a wrapper approach that works in POSIX sh:
   ```sh
   exec > >(tee /tmp/exec-output/ID.log) 2>&1; <command> <args>
   ```
   Or write a small wrapper script. Needs testing against the standard sandbox images.

7. **Output file cleanup** — `/tmp/exec-output/` files accumulate if never cleaned. Mitigation: task worker cleans up the output file after storing the result in the Task row (or add a TTL-based cleanup). For long-lived containers, consider a cron or periodic cleanup.

### What needs careful testing

- **Sync mode with stream_to**: Verify the tee wrapper preserves exit codes correctly across different container base images (alpine, debian, ubuntu)
- **Deferred mode output tailing**: Verify a second `exec_sandbox` call can `tail -f` the output file while the first command is still running
- **Large output handling**: Current harness flow truncates output (via sandbox_service). Verify the tee wrapper doesn't cause OOM for very large outputs — the file write is unbounded while the pipe buffer to stdout is bounded
- **Concurrent exec tasks**: Multiple deferred exec tasks running in the same container — verify `/tmp/exec-output/` file naming (task_id based) prevents collisions
- **Access control edge cases**: Bot with `harness_access` but not `exec_access` should be able to use harnesses but not raw exec, and vice versa
