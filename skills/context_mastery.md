---
name: Context Mastery
description: The four persistence tiers (auto-injected, reference files, bot-authored skills, core skills), how they relate, and how to move content between them
triggers: context window, persistence, where does this go, memory vs skill, reference file, working set, four tiers, hot warm cold, archive content
category: core
---

# Context Mastery — The Four Persistence Tiers

You operate against a platform with **four distinct persistence layers**. Knowing which tier a piece of information belongs to is the single highest-leverage skill you can develop.

---

## The Four Tiers

| Tier | Where | Cost | Discovery | Scope |
|---|---|---|---|---|
| **1. Auto-injected** | `MEMORY.md`, today's log, channel workspace `*.md` | Tokens every turn | Always present | Per-bot, per-channel |
| **2. Reference files** | `memory/reference/*.md` | Free until fetched | Directory listing visible; you fetch by name | Bot-private |
| **3. Bot-authored skills** | `bots/{your_id}/...` via `manage_bot_skill` | Free until surfaced | RAG-indexed, semantic discovery | Visible to all bots (you own the namespace) |
| **4. Core skills** | `skills/*.md` (operator-curated) | Free until enrolled | Working set (always-injected) + discovery layer (semantic) | Shared across all bots |

**The decision tree:**

```
Is this information...
├── Operational state for THIS channel? → Tier 1 (workspace file)
├── Cross-session persistent for ME alone? → Tier 1 (MEMORY.md) or Tier 2 (reference)
├── A reusable pattern other bots would benefit from? → Tier 3 (author a skill)
└── Already published as core documentation? → Tier 4 (it's there, get_skill if needed)
```

When in doubt: **Tier 3.** Skills are RAG-indexed, so even if you guess wrong about whether others need them, the discovery layer will only surface them when relevant.

---

## How Discovery Works

The skill system has TWO injection paths working together:

1. **Working set** — your persistent enrolled skills (the starter pack plus anything you've fetched, authored, or been manually assigned). Always present in your context as a flat list. Bounded — the hygiene loop prunes stale ones.

2. **Discovery layer** — semantic retrieval over the *unenrolled* catalog. Each turn, the user's message is matched against skill triggers and the top candidates surface as suggestions. If you `get_skill()` one of them, it gets promoted into your working set automatically.

This is why `manage_bot_skill` matters so much. Every skill you author enters the discovery pool. Future bots in unrelated channels will find it the moment a user phrases a relevant question.

---

## Tier 1 — Auto-Injected (Always Costs Tokens)

These are present in your context every turn. Treat them as expensive real estate.

| Source | What |
|---|---|
| `memory/MEMORY.md` | Persistent cross-session memory |
| `memory/logs/{today}.md` | Today's activity log |
| `memory/logs/{yesterday}.md` | Yesterday's log |
| Channel workspace root `*.md` | Active operational state for this channel |
| Working set skills | Flat list of enrolled skills |

**Budget tips:**
- One concern per workspace file — small focused files compress better
- Split at ~100 lines or archive
- Channel workspace files cost the most — every root `.md` is injected every turn

## Tier 2 — Reference Files (Bot-Private)

`memory/reference/*.md` is your personal scratch space. The directory **listing** is visible in your context (so you know what exists), but file contents are NOT injected — you fetch them by name when relevant.

**When to use:**
- Personal context only YOU need (specific client preferences, session-spanning notes)
- Things you don't want polluting the skill catalog
- Drafts before deciding whether to promote to a skill

**Anti-pattern:** Treating reference files as "cheap skills". They're not. They have no RAG, no triggers, no visibility to other bots. If a future bot might need it, author a skill instead.

### Template
```markdown
# Topic Name

## When to Use This
- Trigger conditions

## Quick Reference
| Situation | Action |
|---|---|
| X happens | Do Y |

## Detailed Process
Step-by-step when the quick reference isn't enough.
```

## Tier 3 — Bot-Authored Skills (Visible to All Bots)

Use `manage_bot_skill(action="create", ...)` to author. See the **skill_authoring** skill (you have it auto-enrolled) for the full schema and trigger-writing guidance.

**The key insight:** authoring a skill is the only way to make a learned pattern auto-surface for future bots. Reference files do not. MEMORY.md does not. Workspace files do not. Only RAG-indexed skills.

## Tier 4 — Core Skills (Operator-Curated)

The catalog under `skills/` (this file is one of them). You don't author these — operators do. But you can fetch them via `get_skill("skill_id")`, and successful fetches automatically promote the skill into your working set.

The discovery layer's job is to surface the right ones when you need them.

---

## Moving Content Between Tiers

Sometimes a piece of information starts in one tier and needs to graduate.

### Tier 1 → Tier 2 (active topic going dormant)
```
file(read, "active-topic.md")
file(write, "memory/reference/topic-name.md", content)
file(delete, "active-topic.md")
file(edit, "memory/MEMORY.md", find="...", replace="...→ see reference/topic-name.md")
```

### Tier 2 → Tier 3 (private learning that all bots should benefit from)
Read your reference file, then call `manage_bot_skill(action="create", ...)`. Delete the reference file once the skill exists.

### Tier 1 → Cold (concern fully resolved)
```
file(read, "resolved-item.md")
file(write, "archive/resolved-item.md", content)
file(delete, "resolved-item.md")
file(append, "archive_index.md", "| resolved-item.md | 2026-04-10 | Summary |\n")
```

Archived files are searchable via `search_channel_archive(query)` — gone from your turn-by-turn cost, retrievable on demand.
