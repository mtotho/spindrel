---
name: Carapace Architect
description: >
  Guide for designing effective carapaces — composable expertise bundles that give bots
  instant domain knowledge. Load when creating, refactoring, or reasoning about carapace
  design: skill organization, system_prompt_fragment writing, tool selection, composition
  via includes, or when a bot needs to become an expert at something new.
---

# Carapace Architecture

A carapace turns a generic bot into a domain expert. The key insight: **the system_prompt_fragment is an index, not an encyclopedia.** It's a concise routing layer that tells the bot what it knows and where to find depth.

## The Index Pattern

```
system_prompt_fragment (always in context)
  ├── "You are an expert at X. Your workflow is: 1, 2, 3"
  ├── "For Y details, call get_skill('deep-guide-y')"
  ├── "For Z reference, call get_skill('reference-z')"
  └── "Use tool_a for ..., tool_b for ..."

skills (on_demand = indexed but not loaded until requested)
  ├── deep-guide-y.md    ← 500+ lines of detailed procedures
  ├── reference-z.md     ← lookup tables, API docs, recipes
  └── ...

pinned skills (always in context — use sparingly)
  └── core-context.md    ← only if the bot literally needs it every turn

tools (wired up and ready)
  ├── tool_a              ← pinned (always offered to LLM)
  └── tool_b, tool_c      ← available via tool RAG
```

The system_prompt_fragment should be **50-150 lines**. It defines:
1. **Identity** — what this expert does, in one paragraph
2. **Workflow** — the step-by-step protocol (numbered, concrete)
3. **Skill pointers** — explicit `get_skill('id')` callouts for each deep-knowledge area
4. **Tool guidance** — when to use which tool, in a quick reference table
5. **Key rules** — 3-5 non-negotiable behavioral rules

Everything else goes in on_demand skills that the bot fetches when needed.

## Why This Works

- **Context budget**: The system_prompt_fragment is injected every turn. At 50-150 lines it costs ~200-600 tokens. On_demand skills only load when relevant — a 400-line guide costs 0 tokens until called.
- **Routing over dumping**: The bot sees the index, recognizes when it needs depth, and fetches it. This mirrors how humans use reference material — you don't memorize the manual, you know where to look.
- **Composability**: Small, focused fragments compose cleanly via `includes`. Two 100-line fragments merge better than two 500-line walls of text.

## Worked Example: The Orchestrator Carapace

The orchestrator carapace itself follows this pattern. Its fragment is ~50 lines — identity, workflow, delegation summary, and an index table. Its deep knowledge lives in on_demand skills organized in its subfolder:

```
carapaces/orchestrator/
├── carapace.yaml                              # includes: [mission-control]
└── skills/
    ├── workspace-orchestrator.md   (pinned)   # Concise core: environment, filesystem, key capabilities
    ├── workspace-delegation.md     (on_demand) # Delegation patterns, Claude Code reference
    ├── workspace-api-reference.md  (on_demand) # Server API endpoints, permissions, agent CLI
    ├── workspace-management.md     (on_demand) # Channels, memory patterns, workspace skills
    ├── carapace-architect.md       (on_demand) # This file — carapace design guide
    └── model-efficiency.md         (on_demand) # Cost optimization, tier selection

integrations/mission_control/
├── carapaces/mission-control.yaml             # Task boards, planning, projects, feeds, integrations
└── skills/
    ├── mission_control.md          (on_demand) # Kanban board format, status.md
    ├── planning.md                 (on_demand) # Plan workflow — draft, approve, execute
    ├── project-management.md       (on_demand) # Cross-channel portfolio tracking
    ├── content_feeds.md            (on_demand) # Email/RSS feed content in data/
    └── integration-builder.md      (on_demand) # Connecting external services
```

The fragment's index table maps scenarios to skills. Mission control skills come via `includes: [mission-control]` — the MC carapace's fragment and skills merge into the orchestrator's context automatically.

The bot sees ~600 tokens of orchestrator routing + ~200 tokens of MC routing every turn. When it needs to make an API call, it fetches the API reference (~130 lines). When it needs to set up an integration, it fetches integration-builder (~440 lines). The deep knowledge is there but costs nothing until needed.

**The subfolder IS the carapace package.** Skills that belong to a carapace live in its subfolder. They're discovered by ID path (`carapaces/orchestrator/workspace-delegation`), registered in the carapace.yaml skills list, and pointed to from the fragment's index table. Everything related stays together.

**Composition via `includes`** keeps ownership clear. The orchestrator doesn't own project management skills — mission-control does. The orchestrator just includes mission-control, gaining access to all its skills and fragment. When mission-control adds new skills, the orchestrator automatically gets them.

## Designing a Carapace — Step by Step

### 1. Define the Expertise Boundary

One carapace = one area of expertise. Ask: "What does this expert do that a general bot can't?"

Good boundaries:
- "Bug triage and systematic debugging"
- "Code review with severity ratings"
- "Cross-channel project management"

Bad boundaries (too broad):
- "Software engineering" — that's multiple carapaces
- "Everything about the project" — put that in workspace skills

### 2. Write the System Prompt Fragment

Start with this skeleton:

```markdown
## [Expert Name] Protocol

You are [one sentence identity].

### Workflow
1. [First step — concrete action]
2. [Second step]
3. ...

### Deep Knowledge
- **[Topic A]**: Call `get_skill('[skill-id-a]')` for [what it contains]
- **[Topic B]**: Call `get_skill('[skill-id-b]')` for [what it contains]

### Tool Quick Reference
| Tool | When to Use |
|------|-------------|
| `tool_a` | [scenario] |
| `tool_b` | [scenario] |

### Key Rules
- [Rule 1]
- [Rule 2]
- [Rule 3]
```

**The skill pointers are critical.** Without them, the bot won't know the deep knowledge exists. The on_demand index shows skill names and descriptions, but the system_prompt_fragment is where you tell the bot *when* and *why* to fetch each one.

### 3. Write the Skills

Each skill is a standalone markdown document. Think of them as chapters the bot pulls off the shelf when needed.

**Skill modes:**
| Mode | Injection | Cost | Use For |
|------|-----------|------|---------|
| `pinned` | Every turn, full content | High | Core context the bot needs on literally every message (rare — most things don't qualify) |
| `on_demand` | Index entry only; full content via `get_skill()` | Zero until fetched | Reference material, detailed procedures, recipes, API docs |
| `rag` | Semantic match against user message | Variable | Background knowledge that should surface when topically relevant |

**Default to `on_demand`.** Only use `pinned` for context that's needed on >80% of turns. Only use `rag` when the bot shouldn't need to explicitly decide to fetch it.

### 4. Select Tools

```yaml
local_tools:          # Available for tool RAG matching
  - file              # Read/write/edit workspace files (preferred for most bots)
  - web_search
  - exec_command      # Shell access (orchestrators, workspace bots with containers)

pinned_tools:         # Always offered to the LLM (bypass tool RAG)
  - file              # Only pin tools the workflow depends on every turn
```

**`file` is the default file tool** for most bots — it reads, writes, and edits workspace files without shell access. Only use `exec_command` for bots that need shell capabilities (orchestrators, workspace container bots, sandbox profiles). Pin sparingly — every pinned tool consumes context tokens on every turn.

### 5. Compose via Includes

Build on existing carapaces instead of duplicating:

```yaml
includes:
  - code-review      # Gets all of code-review's skills, tools, and fragment
```

The included carapace's `system_prompt_fragment` is concatenated after yours. Its skills and tools merge into yours. Resolution is depth-first with cycle detection (max 5 levels).

**Composition tips:**
- Include for shared foundations (code-review includes in qa, bug-fix includes in code-review)
- Don't include carapaces just for one skill — reference the skill directly instead
- Keep the include chain shallow (2-3 levels max in practice)

## Creating a Carapace

Use the `manage_capability` tool:

```
manage_capability(
  action="create",
  id="bug-triage",
  name="Bug Triage Expert",
  skills='[{"id": "debugging-guide", "mode": "on_demand"}, {"id": "test-patterns", "mode": "on_demand"}]',
  local_tools="file,web_search,exec_command",
  pinned_tools="file",
  system_prompt_fragment="## Bug Triage Protocol\n\n..."
)
```

Or place a YAML file in `carapaces/` (or `integrations/*/carapaces/`):

```yaml
id: bug-triage
name: Bug Triage Expert
description: Systematic debugging and bug resolution
tags: [debugging, qa]

skills:
  - id: debugging-guide
    mode: on_demand
  - id: test-patterns
    mode: on_demand

local_tools:
  - file
  - web_search
  - exec_command

pinned_tools:
  - file

system_prompt_fragment: |
  ## Bug Triage Protocol

  You are a systematic debugger. Every bug follows: reproduce, isolate, fix, verify.

  ### Workflow
  1. Reproduce the bug (get exact steps and error output)
  2. Isolate the root cause (bisect, trace, inspect state)
  3. Assess blast radius (what else could this affect?)
  4. Write a failing test that captures the bug
  5. Implement the minimal fix
  6. Verify the test passes and no regressions

  ### Deep Knowledge
  - **Debugging techniques**: Call `get_skill('debugging-guide')` for systematic isolation methods, logging strategies, and common root cause patterns
  - **Test patterns**: Call `get_skill('test-patterns')` for test-first methodology, edge case identification, and coverage strategies

  ### Key Rules
  - Never fix without reproducing first
  - Write the failing test BEFORE the fix
  - Minimal fix — don't refactor adjacent code
```

## Anti-Patterns

| Anti-Pattern | Why It Fails | Fix |
|---|---|---|
| 500-line system_prompt_fragment | Burns context budget every turn; bot ignores most of it | Move depth to on_demand skills, keep fragment as index |
| No skill pointers in fragment | Bot doesn't know deep knowledge exists; never calls `get_skill` | Add explicit "call `get_skill('x')` for ..." lines |
| Everything pinned | Massive context, slow responses, high cost | Default to on_demand; pin only what's needed every turn |
| Carapace per project | Wrong abstraction — projects are channels, not expertise | Use channel workspace + channel prompt for project context |
| Duplicating skills across carapaces | Drift, maintenance burden | Use `includes` or reference shared skills by ID |
| Vague system_prompt_fragment | "You are helpful and knowledgeable" — useless | Concrete workflow steps, specific tool/skill references |

## Applying Carapaces

Three ways to activate a carapace:

| Method | Scope | Use When |
|---|---|---|
| Bot config: `carapaces: [qa]` | All channels for this bot | Bot IS this expert |
| Channel override: `carapaces_extra: [qa]` | One channel only | Temporary or channel-specific expertise |
| Delegation: `execution_config.carapaces: ["qa"]` | Single task | One-off delegated task needs expertise |

Remove via `carapaces_disabled: [qa]` on the channel to suppress a bot-level carapace for specific channels.
