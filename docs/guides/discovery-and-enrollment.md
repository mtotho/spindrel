# Discovery and Enrollment

![Bots admin list — enrollment surface](../images/admin-bots-list.png)

This is the canonical document for how Spindrel makes tools and skills available to a bot.

If tool discovery, skill discovery, enrollment, `get_skill`, `get_tool_info`, or residency semantics change, update this file first and then update shorter docs that point at it.

For the canonical guide covering replay policy, context profiles, compaction, and prompt-budget admission, see [Context Management](context-management.md).

---

## What This Guide Covers

This guide explains:

- how tools are discovered
- how skills are discovered
- what enrollment means
- what "loaded" and "resident in context" mean
- which older mechanisms are no longer part of the product model

It is not the place for per-profile prompt-admission policy. That belongs in [Context Management](context-management.md).

---

## Current Product Model

The active product concepts are:

- tools
- skills
- enrollment of each

The app no longer has a first-class capability/carapace model. Do not treat `activate_capability`, capability approval flows, or carapace resolution as part of the current architecture.

---

## Terms

| Term | Meaning |
|---|---|
| discoverable | The runtime can suggest or retrieve it, but it is not yet part of the bot's persistent working set |
| enrolled | Persistently available to that bot or channel as part of the working set / allowed set |
| loaded | The model fetched the full content during the conversation, usually with `get_skill()` or `get_tool_info()` |
| resident | The content is currently in the prompt window for this turn |
| auto-injected | The runtime preloaded the content without the model calling the fetch tool |

Resident is a runtime fact. Enrolled is a persistent configuration fact. Do not confuse them.

---

## Tool Discovery

Tool availability has two layers:

1. **Allowed / enrolled / pinned tools**
2. **Per-turn retrieval over the broader tool pool**

Current behavior:

- tools can be persistently available because they are enabled, enrolled, or pinned
- per-turn tool retrieval ranks tools against the current user message
- `get_tool_info(tool_name="...")` loads the full schema for an available/discovered tool
- once loaded, that schema is callable in the current loop

Pinned tools are the strongest availability signal. They are the tools that must be available every turn.

`get_tool_info` is the fallback when the model knows or suspects the right tool but needs the full schema before calling it.

---

## Skill Discovery

Skill availability also has two layers:

1. **Enrolled working set**
2. **Unenrolled discovery layer**

Current behavior:

- every bot has a persistent enrolled working set
- new bots start from `STARTER_SKILL_IDS`
- successful `get_skill()` calls promote a skill into the working set
- semantic discovery can surface unenrolled skills as suggestions

The discovery layer is for finding skills the bot does not already carry. The working set is for skills the bot should see regularly.

---

## Enrolled Skill Ranking and Auto-Inject

Enrolled skills are ranked per turn against the current user message.

Current defaults:

- `SKILL_ENROLLED_RANKING_ENABLED = True`
- `SKILL_ENROLLED_RELEVANCE_THRESHOLD = 0.40`
- `SKILL_ENROLLED_AUTO_INJECT_THRESHOLD = 0.55`
- `SKILL_ENROLLED_AUTO_INJECT_MAX = 0`

Important consequence:

- the runtime still supports enrolled-skill auto-inject
- it is **disabled by default**
- the current strategy is prompt-first: show the index, let the model call `get_skill()` when it needs the body

So:

- relevant skills may be annotated in the index
- full enrolled-skill auto-injection is not on by default

---

## `get_skill`, Residency, and `refresh=true`

`get_skill(skill_id="...")` loads the full skill body and makes it resident in the conversation.

Current residency rules:

- the runtime tracks a canonical `skills_in_context` residency set
- resident skills are marked as already loaded in the skill index
- duplicate `get_skill()` calls do not paste the full body again by default
- use `refresh=true` only when you intentionally want to reload/reorder the skill

This means:

- enrolled does not imply resident
- resident does not require auto-inject
- `get_skill()` is still the normal path for moving from "suggested" to "actually in prompt context"

---

## Discovery vs Context Admission

Discovery answers:

- what tools/skills can the bot reach?
- which ones are suggested?
- which ones are enrolled?
- which ones are currently resident?

Context admission answers:

- which optional prompt blocks are allowed for this origin/profile?
- which ones fit in budget?

Those are different systems.

Examples:

- a skill can be enrolled but not currently resident
- a tool can be discoverable without its full schema being loaded yet
- a knowledge-base excerpt can be admitted in `chat` but suppressed in `planning`
- a workspace file can be retrievable even when it is not preloaded into context

See [Context Management](context-management.md) for the profile/budget side of that contract.

---

## What Is No Longer Canonical

These are not part of the current canonical discovery story:

- carapace/capability resolution as the main composition pipeline
- `activate_capability`
- capability approval as the main way bots gain expertise
- a default assumption that enrolled skills auto-inject full bodies into context

If older notes or prompts still mention those as the live architecture, they are stale.
