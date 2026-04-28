# Programmatic Tool Calling

`run_script` lets a bot write a short Python script that orchestrates many tool calls in one turn.

This is not a replacement for simple tool calls. It is the expected path for jobs that are mostly mechanical orchestration:

- loop over many items
- filter or transform tool results before the next call
- avoid burning context on long intermediate JSON blobs
- keep multi-step tool work inside one controlled round-trip

## When to use it

Use `run_script` when the bot needs to do real tool orchestration, not just one or two tool calls.

Rule of thumb:

- Use normal tool calls for 1-2 direct checks.
- Emit independent direct tool calls together in one assistant turn when the model can do that safely.
- Use `run_script` for 3+ related calls when there is fan-out, looping, filtering, joining, or compact intermediate state.
- Prefer a purpose-built aggregate tool over either direct calls or `run_script` when one exists.

Good fits:

- "Search ten repos, then summarize only the ones that mention OAuth"
- "List all tasks, keep the overdue ones, then send a push notification if any exist"
- "Call the same tool for each device and build one compact result"

Bad fits:

- a single tool call
- a normal pipeline step where `tool` or `foreach` is already clearer
- general shell access on the host when `exec_tool` is the real need

## What it does

The script runs in a controlled Python environment and can dispatch registered tools programmatically.

At a high level:

1. The bot inspects available tool signatures
2. It writes a short Python script
3. The script calls tools, loops, filters, and builds a final result
4. Spindrel returns the final output to the conversation

The point is to move repetitive orchestration out of the token stream and into a structured execution step.

## Why it exists

Without `run_script`, an agent doing multi-step tool work has to:

- call one tool
- read the result in-chat
- reason about the next step
- call the next tool
- repeat

That is expensive and noisy when the work is mostly mechanical.

`run_script` compresses that pattern into one tool call while still using the same tool registry, policy system, and bot context rules.

## Relationship to other mechanisms

| Mechanism | Best for | Why |
|---|---|---|
| Normal tool calls | 1-2 direct calls | Simplest and easiest to inspect |
| `run_script` | Dense tool orchestration inside one turn | Loops, filtering, batching, compact intermediate state |
| Pipelines | Reusable multi-step automation across time | Scheduling, approvals, user prompts, persistent run history |
| `exec_tool` | Host command execution | Shell commands, scripts, file operations on the server host |

## Current readiness

`run_script` is real and useful, but it is still a power-user surface.

- It is best when the task is obviously tool-heavy
- It is not yet something to present as a beginner-first feature
- Budgeting and guardrails matter more here than in plain chat
- Repeated executable workflows should become a bot-authored skill or stored script so future runs do not spend context rediscovering the same loop

See [Feature Status](feature-status.md) for the current readiness/confidence snapshot.

## Related guides

- [Pipelines](pipelines.md)
- [Command Execution](command-execution.md)
- [Custom Tools & Extensions](custom-tools.md)
- [Developer API](api.md)
