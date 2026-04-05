---
name: Context Mastery
description: Advanced context window management, reference file authoring, and research delegation patterns
triggers: context window, reference file, cold start, tier management, hot warm cold, archive content, research delegation
category: core
---

# Context Mastery — Extended Patterns

Your base memory instructions define the temperature tiers (hot/warm/cold) and
self-improvement basics. This skill provides the detailed HOW — concrete patterns
for managing content, authoring reference files, and delegating efficiently.

---

## Your Context Map

### Auto-Injected Every Turn (Token Cost)

| Source | What |
|---|---|
| `memory/MEMORY.md` | Persistent cross-session memory |
| `memory/logs/{today}.md` | Today's activity log |
| `memory/logs/{yesterday}.md` | Yesterday's activity log |
| `memory/reference/` | **Directory listing only** — not file contents |
| Channel workspace root `*.md` | Active operational state (if workspace enabled) |
| Pinned skills | Always present in full |

### Available On Demand (Free Until Fetched)

| Source | How to Access |
|---|---|
| `memory/reference/*.md` contents | `file(read, "memory/reference/topic.md")` or `get_memory_file("topic")` |
| `archive/` files | `search_channel_archive(query)` |
| `data/` files | `search_channel_workspace(query)` |
| On-demand skills | `get_skill("skill-id")` (index shown in context) |

---

## Moving Content Between Tiers

### Hot -> Warm (topic no longer actively changing)
```
file(read, "active-topic.md")
file(write, "memory/reference/topic-name.md", content)
file(delete, "active-topic.md")
file(edit, "memory/MEMORY.md", find="...", replace="...-> see reference/topic-name.md")
```

### Warm -> Hot (reference topic becomes active again)
```
file(read, "memory/reference/topic-name.md")
file(write, "active-topic.md", content)
```

### Hot -> Cold (concern fully resolved)
```
file(read, "resolved-item.md")
file(write, "archive/resolved-item.md", content)
file(delete, "resolved-item.md")
file(append, "archive_index.md", "| resolved-item.md | 2026-03-31 | Summary |\n")
```

### Context Budget Tips

- **One concern per workspace file** — small focused files are cheaper than one giant file
- **Split at ~100 lines** — archive old sections or split into focused files
- **Archive after 3+ sessions unused** — you can always search it back
- **Channel workspace files cost the most** — every root `.md` is injected every turn

---

## Authoring Reference Files (Pseudo-Skills)

Your `memory/reference/` directory is your personal skill library. Write files that
your future self can fetch and immediately use — like on-demand skills you author yourself.

### Template

```markdown
# Topic Name

## When to Use This
- Trigger conditions / situations where this is relevant

## Quick Reference
| Situation | Action |
|---|---|
| X happens | Do Y |
| Z appears | Check A, then B |

## Detailed Process
Step-by-step when the quick reference isn't enough.

## Lessons Learned
- What worked, what didn't, edge cases discovered
```

### What Makes a Good Reference File

| Quality | Good | Bad |
|---|---|---|
| Scope | One topic per file | Catch-all dump of everything |
| Format | Headers, tables, actionable steps | Wall of prose |
| Content | "When X, do Y" patterns | Abstract theory |
| Maintenance | Updated when you learn more | Written once, never touched |

### What to Capture

| Discovery | Where |
|---|---|
| Solution to a recurring problem | `memory/reference/solutions-{topic}.md` |
| Domain knowledge you researched | `memory/reference/{domain}.md` |
| Process that worked well | `memory/reference/processes.md` |
| Tool trick or usage pattern | `memory/reference/tool-patterns.md` |
| User preferences (brief) | `memory/MEMORY.md` — one line, not a file |
| Decision rationale | Daily log + MEMORY.md pointer |

---

## Research Delegation

When you need to gather information from many sources, don't burn your context on raw
data. Use `schedule_task` with a cheap model for the gathering, then analyze the results
yourself.

**Note**: This is different from `delegate_to_agent` (bot-to-bot collaboration covered
in your base instructions). Use `schedule_task` specifically for cost-effective research
subtasks where you control the model.

### Pattern: Workspace/Archive Search

```python
schedule_task(
    prompt="Search the channel workspace and archive for all mentions of [topic]. "
           "Compile a summary with: key findings, relevant dates, and source file paths.",
    execution_config={
        "model_override": "gemini/gemini-2.5-flash",
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

### Pattern: Web Research

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

| Situation | Self | Delegate |
|---|---|---|
| Quick lookup in 1-2 files | Yes | — |
| Searching across many files/channels | — | Yes |
| Synthesizing complex analysis | Yes | — |
| Gathering raw data for analysis | — | Yes (gather cheap, analyze yourself) |
| Routine status checks | — | Yes |
| Single web search | Yes | — |
| Multi-source research compilation | — | Yes |

**Key insight**: Delegate the gathering, keep the thinking.

---

## Cold Start Sequence

When you start a new session with no prior messages:

1. **Orient** — MEMORY.md is already injected; scan it for cross-session context
2. **Check reference listing** — see what's in `memory/reference/` (titles are visible)
3. **Fetch what's relevant** — if today's topic relates to a reference file, load it early
4. **Check active workspace** — review any channel workspace `.md` files for current state
5. **Greet with context** — show the user you remember what's going on

Fetch reference files as topics come up, not preemptively. The directory listing tells
you what exists — that's enough to know what to fetch when needed.
