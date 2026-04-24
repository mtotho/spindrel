---
name: Workspace Delegation
id: shared/orchestrator/workspace-delegation
description: >
  Delegation patterns and orchestration reference for shared-workspace bots. Load
  when choosing between bot delegation, Claude Code, and workflow steps.
triggers: delegate_to_agent, bot delegation, sub-agent, orchestrator delegation, workspace delegation, claude code delegation, fan out, multi-bot coordination
category: core
---

# Workspace Delegation

## `delegate_to_agent`

Use bot delegation for domain work owned by another bot.

```python
delegate_to_agent(
    bot_id="researcher-bot",
    prompt="Research the auth system and write findings to output.md",
    notify_parent=True,
    scheduled_at=None,
)
```

Key properties:

- Child bots do not share your current turn context.
- `notify_parent=True` is the default and usually the right choice.
- Shared files in `/workspace/common/` are the cleanest handoff surface.
- Delegation depth is bounded, so keep chains deliberate.

## `run_claude_code`

Use Claude Code when the work is primarily code editing, debugging, or refactoring.

```python
run_claude_code(
    prompt="Fix the authentication bug in /workspace/common/app/auth.py",
    working_directory="/workspace/common/app",
    max_turns=20,
)
```

Use it for:

- multi-file code edits
- refactors with verification
- debugging loops where shell access and patching matter

## Patterns

### Fan-out / fan-in

1. Put common inputs in `/workspace/common/`.
2. Delegate parallel subtasks.
3. Wait for results or poll task state.
4. Synthesize final output from bot artifacts.

### Pipeline

1. Research or gather facts.
2. Store or normalize outputs in shared files.
3. Run the next stage against those files.

Use a workflow when the same sequence will repeat.

### Claude Code + bot hybrid

1. Use Claude Code for the implementation pass.
2. Delegate testing, review, or product evaluation to a specialist bot.
3. Loop until the output is acceptable.

## Choosing the mechanism

| Need | Best fit |
|---|---|
| Open-ended domain work | `delegate_to_agent` |
| Deterministic repeated sequence | workflow / `schedule_task` |
| Code editing and repo manipulation | `run_claude_code` |
| Simple local coordination | direct tool use |

For workflow design details, fetch `pipeline_creation` or `pipeline_authoring`.

## Common mistakes

| Mistake | Fix |
|---|---|
| Sending vague prompts | Include enough context or point at shared files |
| Assuming other bots see your chat | Treat every delegation as a fresh context |
| Polling too aggressively | Use callbacks or slower polling |
| Doing specialist work yourself | Delegate to the bot that already owns that domain |
