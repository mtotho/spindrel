---
name: claude_code_harness
description: "Load when delegating work to Claude Code via the delegate_to_harness tool, when discussing claude-code harness strategy, or when troubleshooting a failed/interrupted Claude Code subprocess. Trigger on: 'run claude-code', 'delegate to claude', 'harness failed', 'resume claude session', 'check harness status', 'claude-code best practices', or any task involving the claude-code harness entry in harnesses.yaml. Do NOT trigger for general CLI usage, non-Claude harnesses (cursor), or direct LLM API calls."
---

# Claude Code Harness — Usage Patterns

## Core Principle

Claude Code is a stateful CLI agent. Every run produces a **session ID** that can be resumed. The default `--print` mode discards this. Always use `--output-format json` to capture session metadata so interrupted or partial runs can be continued instead of re-run from scratch.

---

## How We Run Claude Code

Our harness config (`harnesses.yaml`) runs Claude Code as a subprocess inside a Docker sandbox with JSON output and turn limits:

```yaml
claude-code:
  command: claude
  args: ["--print", "{prompt}", "--dangerously-skip-permissions", "--output-format", "json", "--max-turns", "30"]
  working_directory: "{working_directory}"
  timeout: 1800
```

This runs via `delegate_to_harness(harness="claude-code", prompt=..., working_directory=...)` which executes `docker exec ... sh -c 'cd {wd} && claude --print {prompt} --dangerously-skip-permissions --output-format json --max-turns 30'` inside the bot's sandbox container.

**JSON output** means `result.stdout` is a structured JSON object containing `session_id`, `result`, `cost_usd`, `num_turns`, `is_error`, and `usage`. The harness task runner (`app/agent/tasks.py`) and sync delegation tool (`app/tools/local/delegation.py`) automatically parse this.

**Session resume**: When a harness task fails or times out with a captured `session_id`, the task worker automatically retries with `--resume <session_id>` and a continuation prompt instead of re-running from scratch. Controlled by `HARNESS_MAX_RESUME_RETRIES` (default 1).

---

## Critical Flags for Harness Use

### Output Format

| Flag | Behavior | When to Use |
|---|---|---|
| `--print` / `-p` | Non-interactive, single prompt, exits after | Always (subprocess mode) |
| `--output-format json` | Returns `{session_id, result, usage, cost, duration_ms, is_error, num_turns}` | **Always** — captures session_id for resume |
| `--output-format stream-json` | NDJSON streaming events in real-time | When you need progress monitoring |
| `--output-format text` | Plain text stdout (default) | Only for simple pipe-and-forget |

**Implemented**: Our harness uses `--output-format json` to capture structured output including `session_id` for resume.

### Session Management

| Flag | Behavior |
|---|---|
| `--continue` / `-c` | Resume most recent session in the working directory |
| `--resume <session-id>` / `-r <id>` | Resume a specific session by ID or name |
| `--session-id <uuid>` | Explicitly set a session UUID (must be valid UUID) |
| `--name <name>` / `-n <name>` | Set a display name for the session (for easier resume) |
| `--fork-session` | Create a new session branched from the resumed one |
| `--no-session-persistence` | Don't save session to disk (print mode only) |

**Resume pattern**: Parse `session_id` from JSON output, store it on the Task row, then on retry:
```
claude --resume <session_id> -p "continue from where you left off" --output-format json
```

### Resource Control

| Flag | Behavior | Recommended |
|---|---|---|
| `--max-turns N` | Limit agentic loop iterations | Set to prevent runaway (e.g., 25) |
| `--max-budget-usd N` | Stop if API spend exceeds $N | Set for expensive tasks (e.g., 5.00) |
| `--bare` | Skip auto-discovery (hooks, CLAUDE.md, MCP, memory) | Faster cold start for isolated tasks |
| `--effort high\|medium\|low` | Reasoning effort level | `high` for complex code tasks |
| `--fallback-model sonnet` | Fallback if primary model overloaded | Good for reliability |

### Context Injection

| Flag | Behavior |
|---|---|
| `--append-system-prompt "text"` | Append instructions to system prompt |
| `--append-system-prompt-file path` | Append from file |
| `--system-prompt "text"` | Replace entire system prompt |
| `--add-dir ../other-project` | Add extra directories to context |
| `--mcp-config ./mcp.json` | Load MCP servers |
| `--allowedTools "Bash,Read,Edit"` | Auto-approve specific tools (no prompts) |
| `--tools "Bash,Read,Edit"` | Restrict available tools |

---

## Session Storage on Disk

Sessions live at `~/.claude/projects/<encoded-cwd>/` where `<encoded-cwd>` replaces non-alphanumeric chars with `-`.

```
~/.claude/
├── projects/
│   └── -workspace-myproject/       # encoded working directory
│       ├── <session-uuid>.jsonl    # conversation history
│       └── memory/
│           └── MEMORY.md           # auto-memory (if enabled)
├── plans/                          # plan mode artifacts
└── settings.json                   # global settings
```

Inside the Docker sandbox, this maps to the container user's home. If the container is ephemeral, sessions are lost on container removal. **For resumable sessions, the container must persist between runs** (our bot_sandbox containers do persist).

---

## Best Practices for Our Harness

### 1. Always Capture JSON Output

Change harness args to include `--output-format json`. Parse the result to extract:
- `session_id` — store on Task for resume
- `is_error` — detect failures without parsing text
- `num_turns` — check if max_turns was hit (likely incomplete)
- `cost` — track spending
- `result` — the actual text response

### 2. Name Sessions for Traceability

Use `--name` with a meaningful identifier:
```
args: ["-p", "{prompt}", "--dangerously-skip-permissions", "--output-format", "json", "--name", "task-{task_id}"]
```

### 3. Resume Instead of Re-run

When a harness task fails or times out:
1. Check if `session_id` was captured from prior run
2. If yes: `claude --resume <session_id> -p "continue" --output-format json`
3. If no: `claude --continue -p "continue" --output-format json` (resumes most recent in that working_directory)
4. Only re-run from scratch as last resort

### 4. Set Resource Limits

Always pass `--max-turns` and optionally `--max-budget-usd` to prevent runaway:
```
args: ["-p", "{prompt}", "--dangerously-skip-permissions", "--output-format", "json", "--max-turns", "30"]
```

### 5. Use --bare for Isolated Tasks

When the task is self-contained and doesn't need the sandbox's CLAUDE.md or MCP servers:
```
args: ["--bare", "-p", "{prompt}", "--dangerously-skip-permissions", "--output-format", "json"]
```
Faster cold start, more predictable behavior.

### 6. Streaming for Long Tasks

For tasks dispatched as deferred (mode=deferred), consider `--output-format stream-json` with `--verbose` to capture progress events. Stream events include:
- `assistant` messages with `content[].text` (response tokens)
- `system` events (tool calls, retries, errors)
- `result` final event with full metadata

### 7. Checking Status of Fire-and-Forget Runs

Claude Code has **no built-in status API**. Options:
- **Process monitoring**: Check if the `claude` PID is still running (`ps aux | grep claude`)
- **Session file polling**: Watch `~/.claude/projects/<encoded-cwd>/` for JSONL file growth
- **Our Task system**: The task_worker already tracks status (pending/running/complete/failed) — use `get_task` to check
- **Timeout**: The harness timeout (1800s default) is the ultimate backstop

### 8. Plan Recovery

Claude Code stores plans in `~/.claude/plans/` (configurable via `plansDirectory` in settings.json). If a Claude Code run created a plan but was interrupted before completing it:
1. Resume the session (`--resume <id>`) — the plan context is in the conversation history
2. Or read the plan file directly from the container filesystem

---

## Recommended Harness Config

Upgraded `harnesses.yaml` entry optimized for our use case:

```yaml
claude-code:
  command: claude
  args:
    - "--print"
    - "{prompt}"
    - "--dangerously-skip-permissions"
    - "--output-format"
    - "json"
    - "--max-turns"
    - "30"
  working_directory: "{working_directory}"
  timeout: 1800
```

With this, `result.stdout` will be a JSON object containing `session_id`, `result`, `cost`, `num_turns`, `is_error`, and `usage`.

---

## Parsing JSON Output

When `--output-format json` is used, stdout is a single JSON object:

```json
{
  "type": "result",
  "subtype": "success",
  "session_id": "abc-123-...",
  "is_error": false,
  "num_turns": 12,
  "result": "I've fixed the bug in auth.py...",
  "cost_usd": 0.42,
  "duration_ms": 45000,
  "duration_api_ms": 38000,
  "usage": {
    "input_tokens": 15000,
    "output_tokens": 3000,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 12000
  }
}
```

Parse this in the harness result handler to:
1. Extract `result` as the text response
2. Store `session_id` for potential resume
3. Check `is_error` for failure detection
4. Log `cost_usd` and `usage` for tracking

---

## Failure Modes

| Failure | Symptom | Recovery |
|---|---|---|
| Timeout | Process killed after 1800s | Resume session with `--resume <id>` or `--continue` |
| Max turns hit | `num_turns` equals `--max-turns` value | Resume with higher limit or refined prompt |
| Rate limited | `is_error: true`, error mentions rate limit | Wait and resume (Claude Code has built-in retry) |
| Container died | Docker exec fails | Re-create container, start fresh (no resume possible) |
| OOM | Process killed | Reduce task scope, split into subtasks |
| Permission denied | Tool blocked by permission system | Add to `--allowedTools` or use `--dangerously-skip-permissions` |

---

## Delegation Checklist

Before delegating to Claude Code:

- [ ] Task is well-scoped (single objective, clear success criteria)
- [ ] Working directory is set and exists in the sandbox
- [ ] Prompt includes all necessary context (don't assume Claude has prior knowledge)
- [ ] Resource limits set (`--max-turns`, timeout)
- [ ] Output format is `json` (not bare text)
- [ ] For resumable tasks: session_id will be captured and stored
- [ ] For long tasks: mode=deferred with notify_parent=true
- [ ] For fire-and-forget: mode=deferred with notify_parent=false
