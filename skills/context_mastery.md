---
name: Context Mastery
description: >
  Universal guide for managing your context window, building persistent knowledge,
  and delegating research efficiently. Load when you need to manage active vs
  reference content, create reference documents, optimize your context budget,
  delegate research to cheaper models, or improve your own capabilities over time.
---

# Context Mastery — Managing Your Working Memory

## Your Context Map

### Auto-Injected Every Turn (Costs Tokens Always)

| Source | What |
|---|---|
| `memory/MEMORY.md` | Your persistent cross-session memory |
| `memory/logs/{today}.md` | Today's activity log |
| `memory/logs/{yesterday}.md` | Yesterday's activity log |
| `memory/reference/` | **Directory listing only** — not file contents |
| Channel workspace root `*.md` | Active operational state (if workspace enabled) |
| Pinned skills | Always present in full |

### Available On Demand (Not Injected — You Fetch When Needed)

| Source | How to Access |
|---|---|
| `memory/reference/*.md` contents | `file(read, "memory/reference/topic.md")` |
| `archive/` files | `search_channel_archive(query)` |
| `data/` files | `search_channel_workspace(query)` |
| On-demand skills | `get_skill("skill-id")` (index shown in context) |

Understanding this map is critical. Everything in the first table costs tokens every single turn.
Everything in the second table costs nothing until you ask for it.

---

## Context Budget Rules

1. **Keep MEMORY.md lean** — aim for under ~100 lines. Move detailed knowledge to
   `memory/reference/` files and leave a one-line pointer in MEMORY.md.

2. **One concern per workspace file** — don't create catch-all files. Small focused
   files are cheaper than one giant file with sections you rarely need.

3. **Split growing files** — when an active file exceeds ~100 lines, either archive
   old sections or split into focused files.

4. **Archive aggressively** — if you haven't referenced something in 3+ sessions,
   move it to archive. You can always search it back.

---

## The Temperature Hierarchy

Think of your content in three tiers:

| Tier | Location | Behavior | Use For |
|---|---|---|---|
| **Hot** | Workspace root `.md` files | Auto-injected every turn | Actively changing state, current work |
| **Warm** | `memory/reference/` | Listed (titles visible), fetch on demand | Stable knowledge, reusable patterns, how-tos |
| **Cold** | `archive/` | Not visible, searchable | Resolved items, historical records |

### Moving Content Between Tiers

**Hot → Warm** (topic no longer actively changing):
```
file(read, "active-topic.md")
file(write, "memory/reference/topic-name.md", content)
file(delete, "active-topic.md")
file(edit, "memory/MEMORY.md", find="...", replace="...→ see reference/topic-name.md")
```

**Warm → Hot** (reference topic becomes active again):
```
file(read, "memory/reference/topic-name.md")
file(write, "active-topic.md", content)
```

**Hot → Cold** (concern fully resolved):
```
file(read, "resolved-item.md")
file(write, "archive/resolved-item.md", content)
file(delete, "resolved-item.md")
file(append, "archive_index.md", "| resolved-item.md | 2026-03-31 | One-line summary |\n")
```

---

## Self-Improvement Protocol

You learn things every session. Don't let insights evaporate — persist them so future
sessions start smarter.

### What to Capture

| Discovery | Where | Why |
|---|---|---|
| Solution to a recurring problem | `memory/reference/solutions-{topic}.md` | You'll face it again |
| Domain knowledge you researched | `memory/reference/{domain}.md` | Don't re-research next time |
| User preferences or patterns | `memory/MEMORY.md` (brief line) | Personalization persists |
| Process that worked well | `memory/reference/processes.md` | Repeatable success |
| Tool trick or usage pattern | `memory/reference/tool-patterns.md` | Efficiency compounds |
| Decision and its rationale | Daily log + MEMORY.md pointer | Avoids re-debating |

### Reference Files as Pseudo-Skills

Your `memory/reference/` directory is your personal skill library. The directory listing
is injected every turn, so you always know what's available. Write reference files like
you'd write a skill — structured, actionable, topic-focused:

**Structure them for quick retrieval:**
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

## Lessons Learned
- What worked, what didn't, edge cases
```

**Example**: After debugging a sourdough overproofing problem through research and
experimentation, write `memory/reference/proofing-troubleshooting.md` with the diagnostic
signs, fixes, and temperature adjustments. Next time the user describes a flat loaf,
you see "proofing-troubleshooting.md" in your reference listing and fetch it instantly
instead of re-researching.

### The Growth Loop

After each significant interaction, ask yourself:

1. **Did I learn something reusable?** → Write a reference file or update an existing one
2. **Did I find an approach that works?** → Document the pattern with concrete steps
3. **Did I discover a user preference?** → Note in MEMORY.md
4. **Did I wish I had knowledge I didn't?** → Research it NOW, then write the reference file
5. **Is a reference file getting stale or wrong?** → Update it with what you now know

Don't wait for a perfect moment. Write rough notes immediately, refine later. A messy
reference file is infinitely better than lost knowledge.

---

## Efficient Research Delegation

When you need to gather information from many sources or scour files for context,
don't burn your entire context window on raw data gathering. Delegate the grunt work
to a cheaper model via `schedule_task`.

### Pattern: Research Sub-Task

```python
schedule_task(
    prompt="Search the channel workspace and archive for all mentions of [topic]. "
           "Compile a summary with: key findings, relevant dates, and source file paths.",
    execution_config={
        "model_override": "gemini/gemini-2.5-flash",  # cheap + fast for extraction
    }
)
```

### Pattern: Multi-File Digest

```python
schedule_task(
    prompt="Read these workspace files and extract [specific data]: "
           "file1.md, file2.md, file3.md. Return a structured summary.",
    execution_config={
        "model_override": "gemini/gemini-2.5-flash",
    }
)
```

### Pattern: Web Research Gather

```python
schedule_task(
    prompt="Research [topic] using web_search. Find 3-5 authoritative sources "
           "(prefer .edu, established publications). Summarize key findings with URLs.",
    execution_config={
        "model_override": "gemini/gemini-2.5-flash",
    }
)
```

### When to Self-Handle vs Delegate

| Situation | Do It Yourself | Delegate |
|---|---|---|
| Quick lookup in 1-2 files | Yes | — |
| Searching across many files/channels | — | Yes |
| Synthesizing complex analysis | Yes | — |
| Gathering raw data for later analysis | — | Yes (gather cheap, analyze yourself) |
| Routine status checks | — | Yes |
| Single web search | Yes | — |
| Multi-source research compilation | — | Yes |

The key insight: **delegate the gathering, keep the thinking.** Cheap models are great
at extraction and summarization. Save your context budget for reasoning, synthesis, and
decisions that need your full capabilities.

---

## Cold Start Checklist

When you start a new session with no prior messages:

1. **Orient** — read MEMORY.md (already injected) for cross-session context
2. **Check reference listing** — scan the `memory/reference/` directory for relevant files
3. **Fetch what you need** — if today's work relates to a reference file, load it early
4. **Check active workspace** — review any active `.md` files for current state
5. **Greet with context** — show the user you remember and know what's going on

Don't front-load everything. Fetch reference files as topics come up, not preemptively.
The directory listing tells you what exists — that's enough to know what to fetch when.

---

## Quick Decision Guide

| Situation | Action |
|---|---|
| Learned a durable fact | `memory/reference/` file |
| Noted a transient status | Active workspace `.md` file |
| Discovered a user preference | `memory/MEMORY.md` (one line) |
| Resolved an active concern | Archive the workspace file |
| Need context from old work | `search_channel_archive` |
| Need info from another channel | `list_workspace_channels` → `search_channel_workspace` |
| Building up expertise in a domain | Create/update a reference file (pseudo-skill) |
| Large research task ahead | Delegate gathering to cheap model |
| MEMORY.md getting long | Move detailed sections to reference files, leave pointers |
| Reference file outdated | Read it, update it, note the revision in daily log |
