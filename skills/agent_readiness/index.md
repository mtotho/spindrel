---
name: Agent Readiness
description: >
  Runtime skill family for inspecting a bot's own readiness surface, Doctor
  findings, proposed repairs, and approval-gated Agent Readiness requests.
triggers: agent readiness, run agent doctor, list agent capabilities, missing tools, missing scopes, readiness repair, autofix request, blocked agent
category: core
---

# Agent Readiness

Use this family when you need to understand what the current Spindrel bot can
do, why it is blocked, or how to route a readiness repair without asking a
human to inspect settings manually.

## Start Here

Fetch [Agent Readiness Operator](operator.md) before acting on Doctor findings,
pending readiness repair requests, missing API scopes, empty tool working sets,
or widget skill enrollment gaps.

Do not import repo-local `.agents` skills, author personal bot skills, write
secrets, start processes, or bypass approval paths to fix readiness.
