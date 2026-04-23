---
name: Delegation & Sub-Agents
description: When to use named-bot delegation versus experimental readonly sub-agents
triggers: delegate, delegation, fan-out, escalate, parallel, sub-agent, subagent, spawn
category: core
---

# Delegation & Sub-Agents

## Two Tools, Two Different Contracts

| Tool | Purpose | Result |
|---|---|---|
| `delegate_to_agent` | Give work to a **named bot** | Posted to the channel under that bot |
| `spawn_subagents` | Run **anonymous readonly sidecars** | Returned only to you |

Use `delegate_to_agent` when the work belongs to a specific bot and the user should see that bot's output.

Use `spawn_subagents` only for narrow, parallel, read-only side work that helps you gather input before you answer.

## `spawn_subagents`

Treat sub-agents as an experimental bounded helper.

Use them when:

- there are 2+ independent side tasks
- the work is read-only
- the tasks are tightly scoped
- you still own the synthesis and final answer

Do not use them for:

- single simple work
- critical-path reasoning
- anything needing the full conversation
- mutating or exec-capable work
- "help me think" as a default reflex

Current presets:

| Preset | Tier | Tools | Use For |
|---|---|---|---|
| `file-scanner` | fast | `file` | Bulk reading and extraction |
| `summarizer` | fast | none | Text compression |
| `researcher` | standard | `web_search` | Web research |
| `code-reviewer` | standard | `file` | Read-only code review |
| `data-extractor` | fast | `file` | Structured extraction |

Example:

```python
spawn_subagents(agents=[
  {"preset": "file-scanner", "prompt": "Read README.md and extract the main setup steps."},
  {"preset": "researcher", "prompt": "Find recent browser support notes for WebTransport."},
])
```

## `delegate_to_agent`

Use delegation when:

- the task belongs to a specific bot
- the user should see that bot's identity
- the task needs the target bot's fuller context, persona, or toolset

Important: `delegate_to_agent` is deferred task-style work. Your turn can finish before the child bot posts.

## Rule of Thumb

- If the user should see another bot do the work, use `delegate_to_agent`.
- If you need small readonly sidecar help on parallel subproblems, `spawn_subagents` is acceptable.
- If you are unsure, do the work directly instead of spawning sub-agents.
