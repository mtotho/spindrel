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

1. Start with `machine_status()`.
2. Confirm whether the session already has a lease and which target it points at.
3. If no lease exists, let the user grant one through the inline machine-access card or session controls.
4. Prefer `machine_inspect_command()` for discovery.
5. Use `machine_exec_command()` only when you actually need mutation or real execution.
6. If `machine_exec_command()` returns or triggers an approval state, stop and wait for the user to approve or deny it.

The lease and the approval are separate gates. A lease says this session may use this target. Tool approval says this specific exec-capable command may run.

## Provider choice

- Local Companion: use for the user's workstation or laptop. It runs a paired outbound process on the target machine and can reconnect as a user service.
- SSH: use for headless or LAN machines that already have key-based SSH and known_hosts trust material. It does not need a companion process.

## When to use each tool

### `machine_status`

Use first. It tells you:

- which targets are enrolled
- which are ready
- whether the current session already has a lease
- which provider owns the selected target

### `machine_inspect_command`

Use for readonly discovery:

- `pwd`
- `ls`
- `find`
- `git status`
- `git rev-parse --show-toplevel`
- process inspection

Treat it as the default shell tool until you know you need more.

### `machine_exec_command`

Use only when the task needs real execution on the leased machine:

- running tests in the user's local checkout
- invoking project CLIs installed only on that machine
- editing/building against local state that does not exist on the server

Be explicit about `working_dir` whenever it matters.

## Good habits

- State which machine you are acting on if multiple targets could exist.
- Confirm the working directory before running project-sensitive commands.
- Prefer small inspection steps over one giant shell command.
- Surface lease/readiness blockers plainly instead of pretending the tool is broken.

## `run_script`

Only use `run_script` for machine-control loops after a lease already exists, and only when batching repeated local-tool calls materially helps.

Do not use `run_script` to try to bypass lease gating. The same execution policy still applies.
