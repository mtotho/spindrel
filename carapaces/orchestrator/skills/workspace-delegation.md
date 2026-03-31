---
name: workspace-delegation
description: >
  Delegation patterns and tool reference for orchestrators. Load when delegating to
  bots or harnesses, choosing between delegation methods, designing multi-step workflows,
  or coordinating fan-out/pipeline/hybrid orchestration patterns.
---

# Delegation Reference

## delegate_to_agent — Async Bot Delegation

Sends a prompt to a member bot as an async task. The bot runs in its own context with its own channel/session.

```python
delegate_to_agent(
    bot_id="researcher-bot",           # Target bot (fuzzy-matched)
    prompt="Research the auth system and write findings to your output.md",
    notify_parent=True,                # You get a callback with results (default)
    scheduled_at=None,                 # Optional: "+30m", "+2h", ISO 8601
)
# Returns: {"task_id": "..."}
```

**Key behaviors:**
- `notify_parent=True` (default): When the child completes, you receive a callback message like `[Sub-agent researcher-bot completed]\n\n{result}`
- The child bot runs with its own API key, scopes, and workspace cwd
- Max delegation depth: 3 (controlled by `DELEGATION_MAX_DEPTH`)
- Child gets its own session — it does NOT share your conversation context

## delegate_to_harness — CLI Agent Delegation

Runs an external CLI agent (Claude Code, Cursor) as a subprocess inside the workspace container.

```python
# Synchronous — blocks until complete (up to timeout)
delegate_to_harness(
    harness="claude-code",
    prompt="Fix the authentication bug in /workspace/common/app/auth.py",
    working_directory="/workspace/common/app",
    mode="sync",
)

# Asynchronous — returns task_id immediately
delegate_to_harness(
    harness="claude-code",
    prompt="Refactor the database layer",
    working_directory="/workspace/bots/my-bot/project",
    mode="deferred",
    notify_parent=True,
)
```

**Harness selection:**

| Harness | Best For | Timeout |
|---|---|---|
| `claude-code` | Complex multi-file code tasks, refactoring, debugging | 1800s |
| `cursor` | Quick edits, focused changes | 600s |

**Claude Code specifics:**
- Runs with `--dangerously-skip-permissions --output-format json --max-turns 30`
- JSON output includes `session_id`, `result`, `cost_usd`, `num_turns`, `is_error`
- Failed/timed-out runs can be auto-resumed via `session_id`
- Prompt delivered via stdin heredoc (safe for complex prompts with quotes/special chars)

---

## Orchestration Patterns

### 1. Fan-Out / Fan-In

Delegate parallel tasks, then synthesize results.

```
1. Place shared context in /workspace/common/
2. delegate_to_agent → bot A (task 1)
3. delegate_to_agent → bot B (task 2)
4. delegate_to_agent → bot C (task 3)
5. Wait for callbacks (notify_parent=true)
6. Read each bot's output from /workspace/bots/{bot_id}/
7. Synthesize into final deliverable
```

### 2. Pipeline

Sequential processing where each stage feeds the next.

```
1. delegate_to_agent → researcher (gather data)
2. On callback: review output, place in /workspace/common/research-output/
3. delegate_to_agent → analyst (process data from common/)
4. On callback: review, delegate next stage
```

### 3. Harness + Bot Hybrid

Use Claude Code for code changes, then a bot for review/testing.

```
1. delegate_to_harness(harness="claude-code", prompt="implement feature X", mode="sync")
2. Review the result
3. delegate_to_agent → tester-bot ("run test suite and report failures")
4. On callback: if failures, delegate_to_harness again with fix instructions
```

### 4. Scheduled Maintenance

Use `scheduled_at` for recurring or delayed operations.

```python
delegate_to_agent(
    bot_id="monitor-bot",
    prompt="Check system health and report anomalies",
    scheduled_at="+2h",
    notify_parent=True,
)
```

---

## Common Delegation Mistakes

| Mistake | Why It's Wrong | Do This Instead |
|---|---|---|
| Doing domain work yourself | You lack the member bot's skills, persona, and specialization | Delegate to the right bot |
| Sending vague prompts | Member bots have no shared context with you | Include all necessary context in the prompt, or place it in `/workspace/common/` and reference the path |
| Fire-and-forget without `notify_parent` | You lose track of completion and results | Default to `notify_parent=true` unless truly fire-and-forget |
| Assuming member bots see your context | Each bot has its own session and memory | Explicitly pass context via prompt or shared files |
| Ignoring harness cost/turns | Claude Code runs accrue real API costs | Set `--max-turns`, check `cost_usd` in results |
| Polling tasks in tight loops | Wastes resources, may hit rate limits | Use `agent tasks wait` (5s interval) or `notify_parent=true` |
