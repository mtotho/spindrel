---
name: Skills Catalog
id: skills_catalog
description: Fleet-wide directory of the built-in skill library. Describes each thematic cluster and points at the cluster index, so a bot can quickly find the right skill before fetching its body.
triggers: skills catalog, skill library, available skills, skill directory, skill tree, skill clusters, what skills are available, skill index
category: core
---

# Skills Catalog

The built-in skill library is clustered by theme. Each cluster has its own `index` skill that routes to the right sub-skill — fetch the cluster index first when the topic is unclear, then drill into the specific skill.

## Clusters

- **[workspace](workspace/index.md)** — file tool, channel files, knowledge bases, attachments, docker stacks, container operations.
- **[project](project/index.md)** — Project Factory: setup, planning, intake, Run Packs, coding runs, review, follow-up. Routes by Project state, not user phrasing.
- **[history_and_memory](history_and_memory/index.md)** — chat history, session model, memory hygiene, cross-session search.
- **[widgets](widgets/index.md)** — all three widget kinds (tool, HTML, native), dashboards, SDK, handlers, styling, manifest.
- **[pipelines](pipelines/index.md)** — task pipelines (authoring + creation), step types, scheduling.
- **[automation](automation/index.md)** — standing orders, machine control, bounded machine probes.
- **[configurator](configurator/index.md)** — bot / channel / integration config changes via `propose_config_change`.
- **[orchestrator](orchestrator/index.md)** — shared-workspace multi-bot coordination, audits, model efficiency, delegation reference.
- **[diagnostics](diagnostics/index.md)** — investigate server failures: health summary, recent errors, structured traces, raw container logs. Cheapest-first L1→L5 procedure plus the heartbeat / nightly digest pattern.
- **[agent_readiness](agent_readiness/index.md)** — capability manifest, Doctor findings, preflighted readiness repairs, and approval-gated repair requests.
- **[planning](planning/index.md)** — native session plan mode: structured questions, publish, approval-gated execution, progress recording, replan, and adherence review.

## Standalone core skills

Not every skill fits a cluster. These sit at the top level:

- `context_mastery` — where durable information should live.
- `delegation` — delegating to sub-agents and readonly sidecars.
- `grill_me` — when to ask the user clarifying questions first.
- `prompt_injection_and_security` — defense posture against prompt injection.
- `skill_authoring` — how to capture patterns as a skill, frontmatter schema, lifecycle.
- `programmatic_tool_use` — `run_script` for chaining tool calls in one pass.
- `generate_image` — image generation with attachments.

## How skill IDs work

A skill's ID is either its filesystem path (default) or a value declared in its frontmatter `id:` field (override). The override exists so files can move between clusters without breaking enrollment records or hardcoded references. Always reference a skill by the ID shown in its row — not the filesystem path if they differ.

## Starter set

Every bot starts with a curated minimum set defined in `STARTER_SKILL_IDS` (see `app/config.py`). The 11 IDs:

- `workspace/attachments`
- `workspace/files`
- `workspace/member`
- `workspace/channel_workspaces`
- `workspace/docker_stacks`
- `delegation`
- `grill_me`
- `context_mastery`
- `history_and_memory`
- `prompt_injection_and_security`
- `skill_authoring`

Treat that list as the canonical baseline. If you need to know whether a baseline ID is already in your working set, consult `app/config.py:STARTER_SKILL_IDS` — that constant is the source of truth and is silently skipped for any ID missing from the catalog at enrollment time. Additional skills are enrolled on demand when a bot calls `get_skill` or `manage_bot_skill`.

Runtime agents can call `list_agent_capabilities` to see `skills.recommended_now`, which points at existing built-in skills to load before procedural work. `skills.creation_candidates` is an operator/developer signal for missing built-in runtime skill coverage; it is not an instruction for the bot to create a personal skill with `manage_bot_skill` unless the user explicitly asks for that.

The runtime prompt includes a compact self-inspection rule for these baseline tools: use `list_agent_capabilities` before broad API/config/integration/widget/Project/harness/readiness work, use `run_agent_doctor` when blocked, and follow `skills.recommended_now[*].first_action` before procedural work. This is prompt guidance, not automatic every-turn tool use.
