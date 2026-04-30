---
name: agentic-readiness
description: >
  Use this skill when auditing, designing, or improving a project for agent usability — either by external agents (other developers' agents trying to discover, install, and integrate with your project) or for internal agent-first features within an agentic harness application. Trigger whenever the user asks about making their app "agent-friendly", "MCP-ready", improving how agents interact with their platform, writing llms.txt, designing tool schemas, exposing APIs for agents, or adding agent-first UX. Also trigger for any discussion of how to structure skills, tool contracts, context budgets, or mission/task tracking within an agentic harness.
---

# Agentic Readiness

This skill covers two orthogonal dimensions of agentic readiness:

1. **External** — making your project easy for other users' agents to discover, understand, install, and integrate with
2. **Internal** — features and conventions within an agentic harness app that make the agents running inside it more effective

Apply both dimensions unless the user specifies otherwise. Start with an audit of the current state before prescribing changes.

---

## Core Design Principle: Skill-First, Tools as Guardrails

**Default to conventions, files, and structured text. Reach for tools only when convention can't do the job.**

Agents are good at following written instructions. The cheapest, most portable, and most debuggable form of agentic readiness is a well-structured document or convention the agent reads — not an API it has to call. Every tool you add is latency, a failure mode, an integration surface, and a maintenance burden.

Use this decision tree for each capability:

```
Can a well-written convention or static file give the agent 
what it needs with sufficient reliability?
  ├─ Yes → Use a convention/skill/file
  └─ No — Why not?
       ├─ Requires runtime data the agent can't infer → Minimal read tool
       ├─ Requires atomicity or side effects → Minimal write tool
       └─ Convention is being ignored/violated → Guardrail tool (enforces, doesn't replace)
```

Tools that exist to *enforce* conventions are good. Tools that exist to *replace* conventions the agent could just read are waste.

**Signals that you're over-tooling:**
- The tool returns data that could live in a static file updated on deploy
- The tool's only job is to validate something the agent's prompt could constrain
- You're building an API because it "feels more robust" without a specific failure case in mind

### Feature Placement Rubric

When auditing a feature idea, classify it before designing implementation:

| Put it in... | When the feature is... | First output |
|---|---|---|
| Skill | Repeatable procedure, judgment checklist, recovery pattern, examples, or small-model guidance | `SKILL.md` with when-to-use, first action, and boundaries |
| Tool/API | Runtime state, side effects, permissions, atomicity, enforcement, or data too large/stale for text | Minimal typed contract with useful return schema |
| Memory | User/project preference, prior decision, durable local fact, or operating norm | Short durable note with source/date |
| Docs | External install, integration, public API usage, or contributor onboarding | Agent-readable guide or `llms.txt` entry |

Default ambiguous procedural work to **skill candidate**, not tool. This matters
when Spindrel is running non-frontier models: smaller models need explicit,
short procedural cues like `get_skill("diagnostics") before reading raw logs`
more than they need another broad API surface.

**Skill-shaped signals:**
- humans repeatedly explain the same multi-step workflow;
- a tool is used in the wrong order without a checklist;
- success depends on examples, caveats, or "do not do X" rules;
- a smaller model can complete the task if given a short procedure;
- the feature is mostly about deciding *how* to use existing tools.

**Not skill-shaped:**
- the agent needs fresh runtime data;
- the action mutates config, files, external services, or secrets;
- the system must enforce a permission or atomic write;
- the content is public install/API documentation for outside agents;
- the content is a project-specific preference that belongs in memory.

---

## Dimension 1: External Agentic Readiness

The goal: an agent with no prior context should be able to read your project, understand what it does, install it, and call it — without human intervention.

### 1.1 Discovery Layer

These are all **convention/file-based** by nature. No tooling needed.

**`llms.txt`** (priority: high)  
Place at project root and at `https://yourdomain.com/llms.txt`. This is the emerging standard (analogous to `robots.txt`) for telling LLMs what your project is and how to use it. It is a static file. Keep it that way.

```
# ProjectName

> One-sentence description of what this does and who it's for.

## What this is
[2-3 sentences. State the problem, the solution, the primary interface (API/CLI/SDK).]

## Quickstart
[Minimal working example — install + first call. Assume the agent will copy-paste this.]

## Key concepts
- ConceptA: definition
- ConceptB: definition

## Links
- Docs: https://...
- API reference: https://...
- OpenAPI spec: https://...
- Changelog: https://...
```

Write `llms.txt` for an agent reader, not a human one. No marketing language. Prioritize: what it does, how to call it, what it returns.

**Structured README**  
The first 50 lines of your README should answer, in order:
1. What is this? (one sentence)
2. What problem does it solve?
3. How do I install it? (copy-pasteable one-liner)
4. How do I make my first call? (minimal working example with expected output shown)

Agents parse READMEs. Bury context in prose and they miss it.

**OpenAPI / JSON Schema**  
Expose a machine-readable API schema at a stable URL (`/openapi.json`, `/schema`). Generate it from code annotations — not a dynamic resolver. Write `description` fields for agents: say *what the agent should use this for*, not just what it does.

**Inline usage examples in code comments and docstrings**  
Any public function, endpoint, or CLI command an agent might interact with should have an example embedded directly. Agents read source when docs are missing.

### 1.2 Installation — Convention Over Configuration

**One-liner install target**  
Every project should have a single command that works from a clean environment:
```bash
curl -sSL https://get.yourproject.com | sh
npx yourproject@latest init
docker run yourproject/yourproject
```

Document environment assumptions explicitly (`node >= 20`, `docker`, `python >= 3.11`). These belong in `llms.txt` *and* `.env.example` *and* the README — redundancy is fine; an agent reading any one of them should get the full picture.

**`.env.example`**  
Every env var documented with: what it does, where to get it, whether it's required/optional, example value.

```bash
# REQUIRED — your API key. Get it at https://yourproject.com/settings/keys
YOURPROJECT_API_KEY=your_key_here

# OPTIONAL — defaults to https://api.yourproject.com if not set
YOURPROJECT_API_URL=

# OPTIONAL — log level: debug | info | warn | error (default: info)
LOG_LEVEL=info
```

**Idempotent setup commands**  
`init`, `setup`, `migrate` must be safe to run multiple times. This is a code convention, not a tooling problem — design it correctly and you never need to guard against it at the API level.

### 1.3 Integration Surface

**CLI with `--json` output everywhere**  
A formatting convention, not a tool:
```bash
yourproject status --json
yourproject list --json
yourproject run taskname --json
```
Agents cannot reliably parse prose. JSON output is non-negotiable for agent-driven workflows.

**Actionable error responses — convention first**  
The error *shape* is a convention enforced in a shared error formatter in your codebase. Every error must include:

```json
{
  "error": "CONFIG_MISSING",
  "message": "No configuration file found",
  "suggestion": "Run 'yourproject init' to generate a default config",
  "docs": "https://docs.yourproject.com/setup"
}
```

The `suggestion` field is the single highest-ROI addition for agent usability. It converts a dead end into a next step.

**`/health` and `/info` — minimal guardrail tools**  
These are the right place to add runtime tooling because they expose state that can't live in a static file:

```
GET /health   → { status, version, uptime }
GET /info     → { capabilities, config (non-secret), version }
```

Keep them read-only and cheap. An agent should be able to call these before any operation to verify the system is in a known-good state.

**MCP Server exposure** (if applicable)  
Apply the skill-first principle to MCP tool design:

- Tool `description` fields should read like skill instructions: tell the agent *when* to use this vs alternatives, not just what it does
- If a decision the agent commonly makes before calling a tool can be encoded in the description, encode it there — not in a "preflight" tool
- Tool names: verb-noun, unambiguous (`create_task` not `task`)
- Return values: always structured, include enough context that the agent doesn't need to call back for clarification

---

## Dimension 2: Internal Agent-First Features

For agentic harness applications — systems that run, coordinate, or host agents — apply skill-first aggressively. Most of what harness agents need is good written context, not more API surface.

### 2.1 Tool and Skill Discoverability — Skill-Based First

**Prefer injected skill/capability manifests over registry APIs**

The default: inject a capability summary into the agent's system prompt or context at session start. No tool call, no network round-trip, no additional failure mode.

```markdown
## Your Available Tools
- read_file(path) — Read any file in the workspace. Use for: loading configs, reading task state
- write_file(path, content) — Idempotent. Use for: saving task output, updating state files
- post_message(channel, text) — Sends to Slack. Side effects: yes. Use for: user-facing notifications only
```

**Add a registry tool only when:**
- The capability set changes at runtime (dynamic tool registration)
- The agent needs to query capabilities it wasn't initialized with
- You have >20 tools and injecting all of them would bloat the context window

**Self-describing tools**  
Every tool exposed to internal agents needs, in its schema:
- `name`: verb-noun, unambiguous
- `description`: when to use this, what it's for, what side effects it has
- `input_schema`: JSON Schema with descriptions on every field
- `output_schema`: what comes back — agents need this, not just input schemas
- `idempotent`: boolean — agents need to know if retrying is safe

### 2.2 Context Budget Awareness — Convention First

**Start with static token estimates in file metadata, not a live API**

Most context budget decisions can be handled by injecting size metadata alongside file references:

```markdown
## Available Context Files
- MISSION.md (~800 tokens) — current task state and objectives
- CHANGELOG.md (~4,200 tokens) — full history; prefer summary if context is tight
- CHANGELOG_SUMMARY.md (~300 tokens) — last 30 days only
```

The agent makes load/skip decisions from this without calling anything. This handles 80% of context management cases.

**Add a context budget tool only when:**
- The agent is in a long-running session where token count can't be predetermined
- You need to enforce a hard ceiling as a guardrail

If you do add it:
```
GET /agent/context/budget → {
  tokens_used: number,
  tokens_remaining: number,
  recommendation: "continue" | "summarize" | "handoff"
}
```

**Context archival — file convention first**  
Before building an archival API: can the agent write a `SESSION_SUMMARY.md` at end-of-session and read it at the start of the next? For most cases, yes. A simple append-to-file tool is sufficient. A full archival API is warranted only when you need search, indexing, or cross-agent access.

### 2.3 Task and Mission Tracking — File Convention First

**MISSION.md / TASK.md as the primary tracking surface**

Agents are excellent at reading and writing structured markdown. Define a file convention before building an API:

```markdown
# Mission: Audit dependency versions

**Status:** in-progress  
**Started:** 2025-04-30T14:00:00Z  
**Blocking on:** —

## Objective
Check all package.json files for outdated dependencies and file issues.

## Log
- 14:02 — Found 3 packages in /apps/web to check
- 14:05 — axios: current (1.6.0)
- 14:07 — lodash: outdated (4.17.11 → 4.17.21), filed issue #442
```

The agent writes this file. Any other agent or human can read it. No API needed.

**Add mission tracking tools only for:**
- Multi-agent coordination where two agents may write simultaneously → atomic-append tool as guardrail
- Human-facing dashboards that need to query mission state without reading files directly
- Cross-session persistence when the filesystem isn't durable

If you do build mission endpoints, keep them thin wrappers over the same file structure.

### 2.4 Heartbeat and Status — Behavioral Rule First

**Define heartbeat as a behavioral rule in the agent's system prompt**

```
Every 10 tool calls or when switching tasks, post a brief status update 
to #agent-status: current task, last completed step, next step.
Format: "[AgentName] Working on: X | Done: Y | Next: Z"
```

This costs nothing to implement, is immediately visible to humans, and works without any infrastructure. Add a heartbeat endpoint only when you need machine-readable status for automated stuck-agent detection.

**Scheduled tasks — prompt rule first**  
Most scheduling can be expressed as an instruction in the system prompt:
```
At the top of each hour, run summarize_pending_items and post to #digest.
```

Use a cron-style scheduling tool only when the agent isn't running continuously, or when you need guaranteed execution independent of agent state.

### 2.5 Structured Logging — Append Convention First

**Define a log format the agent writes to a shared file**

```
[2025-04-30T14:07:23Z] [pantry-bot] [tool_call] update_item item=eggs quantity=12
[2025-04-30T14:07:25Z] [pantry-bot] [decision] skipped send_message: no user present
[2025-04-30T14:07:30Z] [pantry-bot] [error] read_file failed: path not found — retrying
```

An append-to-file tool with this format is sufficient for most harnesses. Agents can read this file to self-correct and reconstruct context.

**Add a log query API only when:**
- Log volume exceeds what an agent can load in one call
- You need cross-agent log correlation or alerting

### 2.6 Error Recovery — Annotate Conventions, Then Enforce

**Encode retry policy in tool descriptions before relying on error responses**

The agent should know *before* calling a tool whether it's safe to retry:

```
write_file(path, content)
Idempotent — safe to retry on failure.
If you receive LOCK_ERROR, wait 3 seconds and retry once before escalating.
```

Then reinforce in the error response:
```json
{
  "success": false,
  "error_code": "RESOURCE_LOCKED",
  "message": "File is currently being written",
  "retryable": true,
  "retry_after_seconds": 3
}
```

The description handles 90% of cases. The error envelope is the guardrail for the unexpected 10%.

**Dry-run / preflight — add selectively**  
Add `dry_run: true` only on tools with irreversible side effects (send email, delete record, deploy). Skip it for idempotent tools. Don't add it everywhere — it's maintenance overhead without proportional benefit.

### 2.7 Agent Identity and Permissions — Declared First, Enforced Second

**Declare scope in the agent's system prompt**

```
You are pantry-bot. You have access to: read_pantry, update_item, create_shopping_list.
You do NOT have access to user data, messages, or any tool not listed above.
If asked to do something outside this scope, decline and explain your scope.
```

This handles the common case through instruction. Add tool-level enforcement as the guardrail for the cases where agents drift or are manipulated:

```json
{
  "error": "PERMISSION_DENIED",
  "message": "pantry-bot is not authorized to call send_message",
  "suggestion": "This action requires orchestrator-bot. File a handoff request."
}
```

Use identity headers (`X-Agent-Id`, `X-Mission-Id`) for logging and observability, not as the primary permission gate.

---

## Audit Checklist

### External
- [ ] `llms.txt` exists at root and is written for an agent reader (no marketing language)
- [ ] README answers what/why/install/first-call in the first 50 lines
- [ ] OpenAPI or equivalent schema at stable URL; `description` fields written for agents
- [ ] One-liner install command works from a clean environment
- [ ] `.env.example` has every var documented with source, example, required/optional
- [ ] Setup commands are idempotent by design
- [ ] CLI supports `--json` on all commands
- [ ] Error responses include `error_code`, `message`, and `suggestion`
- [ ] `/health` and `/info` exist and are cheap/read-only
- [ ] MCP tool descriptions say *when* to use each tool and what side effects it has

### Internal (harness apps)
- [ ] Agent capability summary is injected in system prompt — no tool call required to discover tools
- [ ] Context files include token size estimates alongside references
- [ ] Summary variants exist for large context files (agent chooses load vs summary)
- [ ] File-based mission/task convention is defined and documented
- [ ] Atomic append tool exists for concurrent log/mission writes (guardrail, not primary)
- [ ] Agent system prompts declare behavioral rules for status reporting
- [ ] Tool descriptions include retry guidance; error envelopes reinforce, not replace
- [ ] Agent scope declared in system prompt; tool-level enforcement is the safety net
- [ ] All tools have output schemas, not just input schemas
- [ ] Side-effect tools with irreversible actions support `dry_run`

---

## Priority Order

Ordered by impact-to-effort, skill/convention items first:

1. **`llms.txt` + README restructure** — zero runtime cost, highest discovery leverage
2. **`.env.example` documentation + idempotent setup** — unblocks autonomous install
3. **Actionable errors (`suggestion` field) + `--json` CLI** — unblocks agent automation
4. **Agent system prompt: capability declaration + behavioral rules** — enables reliable internal agents with no new infrastructure
5. **File-based mission/task convention (MISSION.md)** — externalizes agent state, enables handoffs and recovery
6. **`/health` + `/info` + structured error envelope** — minimal runtime tooling that fills gaps convention can't cover
7. **Token-annotated context manifests** — prevents context degradation in long sessions
8. **Atomic write/append tools for concurrent access** — add when multi-agent contention is observed, not preemptively
9. **MCP server exposure** — highest integration leverage, highest implementation cost; do last
10. **Log query API, mission API, permission enforcement tools** — add when file conventions show their limits under load
