---
name: Machine Control
description: How to inspect or run commands on a leased machine target through local machine control
triggers: local machine, my computer, local companion, machine target, local exec, remote execution on my machine
category: tool-use
---

# Machine Control

Use this when the task is about the user's actual machine rather than the server workspace.

## Core rule

Do not assume server execution and local-machine execution are interchangeable.

- Server tools act on the server.
- Machine-control tools act on the leased machine target for the current session.

Always make that distinction explicit in your reasoning and wording.

## Default workflow

1. Start with `local_status()`.
2. Confirm whether the session already has a lease and which target it points at.
3. If no lease exists, let the user grant one through the inline machine-access card or session controls.
4. Prefer `local_inspect_command()` for discovery.
5. Use `local_exec_command()` only when you actually need mutation or real execution.

## When to use each tool

### `local_status`

Use first. It tells you:

- which targets are enrolled
- which are connected
- whether the current session already has a lease

### `local_inspect_command`

Use for readonly discovery:

- `pwd`
- `ls`
- `find`
- `git status`
- `git rev-parse --show-toplevel`
- process inspection

Treat it as the default shell tool until you know you need more.

### `local_exec_command`

Use only when the task needs real execution on the leased machine:

- running tests in the user's local checkout
- invoking project CLIs installed only on that machine
- editing/building against local state that does not exist on the server

Be explicit about `working_dir` whenever it matters.

## Good habits

- State which machine you are acting on if multiple targets could exist.
- Confirm the working directory before running project-sensitive commands.
- Prefer small inspection steps over one giant shell command.
- Surface lease/connection blockers plainly instead of pretending the tool is broken.

## `run_script`

Only use `run_script` for machine-control loops after a lease already exists, and only when batching repeated local-tool calls materially helps.

Do not use `run_script` to try to bypass lease gating. The same execution policy still applies.
