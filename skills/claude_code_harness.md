---
name: claude-code-operator
description: Use this skill to delegate work to Claude Code via the `delegate_to_harness` tool. Covers sync and deferred execution modes, prompt construction, response parsing, working directory targeting, and error handling. Trigger whenever you need to run Claude Code against a codebase — code review, implementation, refactoring, test generation, analysis, migration, or any coding task that benefits from Claude Code's agentic file editing and shell access. Also trigger when the user asks you to "use claude code", "run claude code", "have claude code do X", or references the claude-code harness.
---

# Claude Code Harness — Agent Operator Skill

You invoke Claude Code through the `delegate_to_harness` tool with `harness: "claude-code"`. You do **not** run the `claude` CLI directly. The harness system handles subprocess execution, prompt delivery, output capture, and timeout management.

---

## What the Harness Provides

The `claude-code` harness is pre-configured in `harnesses.yaml`:

| Setting | Value | Meaning |
|---|---|---|
| `--dangerously-skip-permissions` | always on | No interactive permission prompts |
| `--output-format json` | always on | Structured JSON response |
| `--max-turns 30` | always on | Safety cap on agentic loops |
| `prompt_mode: stdin` | always on | Your prompt is piped via heredoc, not embedded in args |
| `timeout` | 1800s (30 min) | Process killed after this |

You do **not** pass these flags yourself. They are injected by the harness service.

---

## Tool Interface

```json
{
  "harness": "claude-code",
  "prompt": "<your instructions>",
  "working_directory": "/workspace/project-name",
  "mode": "sync | deferred",
  "reply_in_thread": false,
  "notify_parent": true
}
```

### Required parameters
- **harness**: Always `"claude-code"`.
- **prompt**: The full instruction set for Claude Code. This is the entire context it receives — be explicit and self-contained.

### Optional parameters
- **working_directory**: Path inside the container (e.g. `/workspace`, `/workspace/my-repo`). Claude Code starts here and has filesystem access relative to it. Defaults to `/workspace` if omitted.
- **mode**: `"sync"` (default) blocks until completion and returns output. `"deferred"` returns a task_id immediately; result posts to the channel when done.
- **sandbox_instance_id**: UUID of a specific sandbox instance. Omit to use the bot's workspace container (the normal path).
- **reply_in_thread**: Deferred mode only. Posts result as a Slack thread reply.
- **notify_parent**: Deferred mode only. When true (default), you receive the harness output as a follow-up message so you can review/react.

---

## Sync vs Deferred

### Use sync when:
- Task completes in under ~5 minutes (analysis, small edits, reviews of single files/diffs)
- You need the result immediately to continue your workflow
- The user is waiting for an answer

### Use deferred when:
- Task is large (multi-file implementation, full test suite generation, migrations)
- Task may approach the 30-minute timeout
- You want to continue doing other work while Claude Code runs
- Fire-and-forget with `notify_parent: false` if you don't need to act on the result

---

## Response Format (Sync Mode)

The tool returns a JSON string. When Claude Code produces valid JSON output (the normal case), the harness parses it into a structured response:

```json
{
  "exit_code": 0,
  "duration_ms": 45200,
  "result": "Claude Code's text response — summary of what it did",
  "session_id": "uuid-of-the-session",
  "is_error": false,
  "cost_usd": 0.045,
  "num_turns": 8
}
```

**Key fields:**
- `result`: The main output text. This is what Claude Code "said" — its summary, findings, or confirmation of work done.
- `is_error`: `true` if Claude Code hit an error or turn limit. Check this first.
- `exit_code`: Non-zero means the process itself failed (crash, timeout, OOM). Distinct from `is_error` which is Claude Code's internal error state.
- `session_id`: Informational — identifies the Claude Code session. **There is no resume capability through the harness** (see Session Limitations below).

If Claude Code's stdout isn't valid JSON (rare — usually means a crash), you get:
```json
{
  "exit_code": 1,
  "duration_ms": 2100,
  "stdout": "raw output text",
  "stderr": "error details if any"
}
```

**Always check `is_error` and `exit_code` before trusting `result`.**

---

## Prompt Construction

Claude Code receives **only your prompt** — no conversation history, no channel context, no memory. Every invocation is a cold start. Write prompts that are:

1. **Self-contained**: Include all relevant context, file paths, requirements, and constraints.
2. **Specific about scope**: Name exact files, directories, functions, or patterns to target.
3. **Explicit about deliverables**: State what Claude Code should produce or change.
4. **Clear on constraints**: If it should NOT modify certain files, say so.

### Prompt template

```
## Task
<one-line summary of what to do>

## Context
<background info Claude Code needs — architecture decisions, conventions, dependencies, relevant prior decisions>

## Scope
<exact files, directories, or patterns to work on>

## Requirements
<specific technical requirements, acceptance criteria>

## Constraints
- Do not modify <files/dirs>
- Do not install new dependencies unless <condition>
- <other guardrails>

## Deliverables
<what the final state should look like — files changed, tests passing, output produced>
```

Not every section is needed for every task. A simple review might just need Task + Scope. Scale the prompt to the task complexity.

### Anti-patterns
- **Vague prompts**: "Fix the bugs" — Claude Code doesn't know which bugs, where, or what "fixed" means.
- **Assuming shared context**: Claude Code doesn't know what you discussed with the user. Restate relevant decisions.
- **Multi-objective prompts without priority**: "Review, refactor, add tests, and optimize" — Pick one primary objective or explicitly order them.

---

## Session Limitations

**There is no session resume through the harness.** Each `delegate_to_harness` call is an independent Claude Code invocation. The `session_id` in the response is informational only.

If you need multi-step workflows:
1. **Chain prompts manually**: Capture the result from step 1, include relevant context in the prompt for step 2.
2. **Rely on filesystem state**: Claude Code writes to disk. The next invocation in the same working directory sees those changes.
3. **Summarize prior work**: If the previous result is large, extract the key outcomes and inject them as context.

```
Example chaining pattern:

Step 1: delegate_to_harness → "Analyze src/auth/ and list all SQL injection vectors"
Step 2: delegate_to_harness → "The following SQL injection vectors were found in src/auth/:
  1. <from step 1 result>
  2. <from step 1 result>
  Fix all of them using parameterized queries. Do not change the function signatures."
```

---

## Error Handling

| Condition | Detection | Action |
|---|---|---|
| Claude Code internal error | `is_error: true` | Read `result` for details. Retry with refined prompt or reduced scope. |
| Process crash/timeout | `exit_code != 0`, no `result` field | Check `stderr`. If timeout, split the task into smaller pieces. |
| Turn limit hit | `is_error: true`, `num_turns: 30` | Task too large for one invocation. Decompose and chain. |
| Harness not found | `error` field in response | Check harnesses.yaml config and bot's `harness_access`. |
| Permission denied | `error` field referencing harness_access | Bot needs `claude-code` in its `harness_access` list. |

---

## Common Patterns

### Code review
```json
{
  "harness": "claude-code",
  "prompt": "Review the changes in src/api/routes/ for security issues, N+1 queries, and missing error handling. List findings with file:line references and severity (critical/warning/info). Do not make any changes.",
  "working_directory": "/workspace/my-app",
  "mode": "sync"
}
```

### Targeted implementation
```json
{
  "harness": "claude-code",
  "prompt": "Add rate limiting middleware to the Express API in src/api/server.ts. Use a sliding window algorithm with Redis (already available at REDIS_URL env var). Rate limit: 100 requests per minute per API key. Add tests in tests/rate-limit.test.ts. Run the tests before finishing.",
  "working_directory": "/workspace/my-app",
  "mode": "sync"
}
```

### Large migration (deferred)
```json
{
  "harness": "claude-code",
  "prompt": "Migrate all class components in src/components/ to functional components with hooks. Preserve all existing behavior and prop interfaces. Run existing tests after each file to verify. Skip any component that uses lifecycle methods not directly translatable to hooks — list those separately at the end.",
  "working_directory": "/workspace/frontend",
  "mode": "deferred",
  "notify_parent": true
}
```

### Analysis with structured output
```json
{
  "harness": "claude-code",
  "prompt": "Analyze the dependency tree of this project. Output a JSON file at /workspace/analysis/deps.json with this structure: { \"direct\": [...], \"outdated\": [...], \"security_advisories\": [...], \"unused\": [...] }. For each entry include package name, current version, latest version, and risk level.",
  "working_directory": "/workspace/my-app",
  "mode": "sync"
}
```

---

## Working Directory Guidance

- Always provide `working_directory` when the task targets a specific repo or project.
- The default `/workspace` is always safe — it's a bind mount to the host, so all writes persist.
- **Any writes outside `/workspace` are lost** when the container exits (ephemeral overlay filesystem).
- For shared workspaces, the full workspace tree is mounted:
  ```
  /workspace/
    bots/
      dev_bot/
        repo/           # cloned repos
      other_bot/
        ...
    common/              # shared files
  ```
- For standalone bot workspaces, `/workspace` is the bot's own root.
- If Claude Code needs to reference files outside the working directory (e.g. shared configs), mention the absolute paths in your prompt.

---

## Cost Awareness

Each sync invocation blocks your agent turn and consumes Claude Code tokens. The `cost_usd` field in the response tells you what the invocation cost. Use this to:
- Decide whether to use sync (cheap, fast tasks) vs deferred (expensive, long tasks).
- Avoid redundant invocations — if you already have the information, don't re-run Claude Code.
- Decompose work efficiently — one well-scoped prompt is cheaper than three vague ones that need retries.
