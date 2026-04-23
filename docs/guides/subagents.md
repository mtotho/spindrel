# Sub-Agents

`spawn_subagents` is an experimental tool for **bounded, parallel, read-only side work**.

It is not a default orchestration primitive, not a replacement for normal tool use, and not a generic "help me think" escape hatch.

## What It Is Good For

Use sub-agents only when all of these are true:

- You have **2+ independent side tasks**.
- Each task is **read-only**.
- Each task is **narrow and self-contained**.
- The parent bot can continue to own the real answer and synthesis.

Good examples:

- scan two different directories in parallel
- summarize several long texts in parallel
- run lightweight web research on separate questions
- extract structured facts from multiple documents

## What It Is Not For

Do not use sub-agents for:

- single simple work you can do directly
- critical-path reasoning the parent should do itself
- tasks that need the full conversation context
- mutating, exec-capable, or control-plane work
- anything the user should see under another bot's identity

If the work belongs to a specific named bot, use `delegate_to_agent` instead.

## Current Safety Contract

Sub-agents now run under a deliberately narrow contract:

- minimal context only: system prompt + task prompt
- no recursive subagent spawning
- no bot delegation from inside a sub-agent
- only **readonly** tools are allowed
- mutating, exec-capable, control-plane, and unknown tools are dropped
- tool policy is still enforced; sub-agents do **not** bypass approvals
- each child run records trace events for start/finish plus tool usage metadata

This is intentionally conservative. If you need richer orchestration, that is a separate future phase.

## Presets

Current built-in presets:

| Preset | Default Tier | Tools | Best For |
|---|---|---|---|
| `file-scanner` | fast | `file` | Bulk file reading and pattern extraction |
| `summarizer` | fast | none | Compressing long text |
| `researcher` | standard | `web_search` | Source-backed web research |
| `code-reviewer` | standard | `file` | Read-only code review |
| `data-extractor` | fast | `file` | Structured extraction from files |

## Example

```json
{
  "agents": [
    {"preset": "file-scanner", "prompt": "Read README.md and extract the main product claim."},
    {"preset": "researcher", "prompt": "Find recent browser support notes for WebTransport."}
  ]
}
```

## Operational Guidance

- Keep prompts concrete.
- Keep tasks independent.
- Prefer fewer, sharper child tasks over a swarm.
- Treat subagents as disposable helpers, not mini-workers with ownership.
- If you are unsure whether subagents help, do the work directly.
