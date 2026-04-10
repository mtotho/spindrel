---
name: Carapace Architect
description: >
  Guide for designing effective carapaces — composable expertise bundles that give bots
  instant domain knowledge. Load when creating, refactoring, or reasoning about carapace
  design: system_prompt_fragment writing, tool selection, composition via includes, or
  when a bot needs to become an expert at something new.
---

# Carapace Architecture

A carapace turns a generic bot into a domain expert. The key insight: **the system_prompt_fragment is an index, not an encyclopedia.** It's a concise routing layer that tells the bot what its workflow is, which tools to reach for, and which skills to fetch when it needs depth.

## What a carapace bundles

```
system_prompt_fragment (always in context when active)
  ├── "You are an expert at X. Your workflow is: 1, 2, 3"
  ├── A Deep Knowledge table — "for Y, get_skill('id-y')"
  └── A Tool Quick Reference table — "use tool_a for ..., tool_b for ..."

local_tools / pinned_tools / mcp_tools
  └── Tools the bot gains while this carapace is active

includes
  └── Other carapaces whose fragments + tools merge in
```

**Skills are NOT a carapace concept.** A carapace does not declare a `skills:` field. Skills live in the per-bot working set (`bot_skill_enrollment`) and are surfaced two ways:

1. **The semantic discovery layer** — every turn, the agent loop runs the user's message through skill embeddings and surfaces the top-K unenrolled catalog skills as a system message. If the query is about your domain, the relevant skills will be there for the bot to fetch.
2. **Your fragment's Deep Knowledge table** — the always-injected, always-visible safety net. It tells the bot exactly which `get_skill('id')` to call for each scenario, regardless of whether semantic discovery surfaced it.

When the bot calls `get_skill('id')` and it succeeds, that skill is **auto-promoted into the bot's working set** (`source="fetched"`). On the next turn it appears in the always-visible flat list. The hygiene loop later prunes skills the bot stops using. This is the entire enrollment lifecycle — carapaces don't need to pre-populate it.

## The fragment as index

The system_prompt_fragment should be **50-150 lines**. It defines:

1. **Identity** — what this expert does, in one paragraph
2. **Workflow** — the step-by-step protocol (numbered, concrete)
3. **Scenario routing** — a "user says X → do Y" table that maps queries to tool calls or skill fetches
4. **Tool quick reference** — when to use which tool
5. **Deep Knowledge table** — the canonical `get_skill('id')` index for every deep procedure or reference doc the bot might need
6. **Key rules** — 3-5 non-negotiable behavioral rules

Everything else lives in the catalog as a regular skill. The bot fetches it when the workflow says to.

## Why this works

- **Context budget**: The fragment is injected every turn. At 50-150 lines it costs ~200-600 tokens. Skills only load when fetched — a 400-line guide costs 0 tokens until called.
- **Routing over dumping**: The bot sees the index, recognizes when it needs depth, and fetches it. Mirrors how humans use reference material — you don't memorize the manual, you know where to look.
- **Composability**: Small focused fragments compose cleanly via `includes`. Two 100-line fragments merge better than two 500-line walls of text.
- **Single enrollment surface**: Skills the bot has used live in `bot_skill_enrollment`. Skills it hasn't yet used surface via discovery. Carapaces don't fight either flow — they augment the discovery side with explicit pointers in the fragment.

## Worked example: the orchestrator carapace

The orchestrator's fragment is ~50 lines — identity, workflow, delegation summary, and a Deep Knowledge index. Its skills live in its subfolder:

```
carapaces/orchestrator/
├── carapace.yaml                              # includes: [mission-control], local_tools, system_prompt_fragment
└── skills/
    ├── workspace-orchestrator.md              # Concise core: environment, filesystem, key capabilities
    ├── workspace-delegation.md                # Delegation patterns, Claude Code reference
    ├── workspace-api-reference.md             # Server API endpoints, permissions, call_api/list_api_endpoints
    ├── workspace-management.md                # Channels, memory patterns, base template
    ├── carapace-architect.md                  # This file — carapace design guide
    └── model-efficiency.md                    # Cost optimization, tier selection

integrations/mission_control/
├── carapaces/mission-control.yaml             # Task boards, planning, projects, feeds, integrations
└── skills/
    ├── mission_control.md
    ├── planning.md
    ├── project-management.md
    ├── content_feeds.md
    └── integration-builder.md
```

The orchestrator's fragment Deep Knowledge table maps scenarios to `get_skill()` calls for each of these. When the orchestrator needs to make an API call, it fetches `workspace-api-reference` (~130 lines) — once. From then on, it's in the bot's working set; no fetch needed next time.

Mission control skills come via `includes: [mission-control]`. The MC carapace's fragment merges into the orchestrator's context automatically, so the MC fragment's Deep Knowledge table is also visible to the orchestrator. The MC skills become reachable through the same fetch-and-promote loop.

**The subfolder IS the carapace package.** Skills that belong to a carapace live in its subfolder for organization. They're just normal catalog skills — discovered, embedded, and available to any bot. The carapace doesn't "own" them; the fragment just *points* at them.

## Designing a carapace — step by step

### 1. Define the expertise boundary

One carapace = one area of expertise. Ask: "What does this expert do that a general bot can't?"

Good boundaries:
- "Bug triage and systematic debugging"
- "Code review with severity ratings"
- "Cross-channel project management"

Bad boundaries (too broad):
- "Software engineering" — that's multiple carapaces
- "Everything about the project" — that's a bot's system prompt, not a carapace

### 2. Write the system prompt fragment

Start with this skeleton:

```markdown
## [Expert Name] Protocol

You are [one sentence identity].

### Workflow
1. [First step — concrete action]
2. [Second step]
3. ...

### Scenario Routing
| User says... | What to do |
|---|---|
| "[example query]" | → [tool call or `get_skill('id')`] |

### Tool Quick Reference
| Tool | When to Use |
|------|-------------|
| `tool_a` | [scenario] |
| `tool_b` | [scenario] |

### Deep Knowledge
| When you need... | Fetch this skill |
|---|---|
| [topic A] | `get_skill('[skill-id-a]')` |
| [topic B] | `get_skill('[skill-id-b]')` |

### Key Rules
- [Rule 1]
- [Rule 2]
- [Rule 3]
```

**The Deep Knowledge table is your safety net.** Semantic discovery may or may not surface a borderline-relevant skill on any given turn. The table ensures the bot can always fetch what it needs, regardless of discovery noise.

### 3. Write the skills (as normal catalog entries)

Skills are standalone markdown documents with frontmatter. They live in the catalog, not on the carapace. Every skill should have:

```markdown
---
name: Human-readable name
description: One-line description used by the discovery embedding
triggers: comma, separated, keywords
category: core | integration | bot
---

# Content...
```

The bot finds them three ways:
1. Discovery layer surfaces the top-K unenrolled skills semantically each turn
2. The fragment's Deep Knowledge table tells the bot exactly which to fetch
3. The bot can also call `get_skill_list()` to enumerate everything

A skill becomes "enrolled" the first time the bot calls `get_skill()` on it. From then on it's in the always-visible working-set flat list.

### 4. Select tools

```yaml
local_tools:          # Available for tool RAG matching
  - file              # Read/write/edit workspace files (preferred for most bots)
  - web_search
  - exec_command      # Shell access (orchestrators or any bot needing shell capabilities)

pinned_tools:         # Always offered to the LLM (bypass tool RAG)
  - file              # Only pin tools the workflow depends on every turn
```

**`file` is the default file tool** for most bots — it reads, writes, and edits workspace files without shell access. Only use `exec_command` for bots that need shell capabilities. Pin sparingly — every pinned tool consumes context tokens on every turn.

### 5. Compose via includes

Build on existing carapaces instead of duplicating:

```yaml
includes:
  - code-review      # Gets all of code-review's tools and fragment
```

The included carapace's `system_prompt_fragment` is concatenated after yours. Its tools merge into yours. Resolution is depth-first with cycle detection (max 5 levels).

**Composition tips:**
- Include for shared foundations (code-review includes in qa, bug-fix includes in code-review)
- Don't include carapaces just for one fragment line — write the line yourself
- Keep the include chain shallow (2-3 levels max in practice)

## Creating a carapace

Use the `manage_capability` tool:

```
manage_capability(
  action="create",
  id="bug-triage",
  name="Bug Triage Expert",
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
  | When you need... | Fetch this skill |
  |---|---|
  | Systematic isolation methods, logging strategies, root cause patterns | `get_skill('debugging-guide')` |
  | Test-first methodology, edge cases, coverage strategies | `get_skill('test-patterns')` |

  ### Key Rules
  - Never fix without reproducing first
  - Write the failing test BEFORE the fix
  - Minimal fix — don't refactor adjacent code
```

Notice: **no `skills:` field**. The bot will fetch `debugging-guide` and `test-patterns` from the catalog the first time the workflow demands them, and they'll auto-enroll into the working set from that point on.

## Anti-patterns

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| `skills:` field on the carapace | Dead — the field is no longer read at runtime | Delete it; add a Deep Knowledge table to the fragment instead |
| 500-line system_prompt_fragment | Burns context budget every turn; bot ignores most of it | Move depth to catalog skills, keep fragment as index |
| Fragment with no Deep Knowledge table | Bot relies entirely on discovery; borderline-relevant skills won't be reached | Add explicit `get_skill('id')` lines for every procedure the workflow depends on |
| Fragment dumping skill content inline | Wastes tokens on every turn for content the bot needs once | Keep the procedure in a skill; reference it from the fragment |
| Carapace per project | Wrong abstraction — projects are channels, not expertise | Use channel workspace + channel prompt for project context |
| Vague fragment ("You are helpful and knowledgeable") | Useless — no behavior change | Concrete workflow steps, specific tool and skill references |

## Applying carapaces

Three ways to activate a carapace:

| Method | Scope | Use When |
|---|---|---|
| Bot config: `carapaces: [qa]` | All channels for this bot | Bot IS this expert |
| Channel override: `carapaces_extra: [qa]` | One channel only | Temporary or channel-specific expertise |
| Delegation: `execution_config.carapaces: ["qa"]` | Single task | One-off delegated task needs expertise |
