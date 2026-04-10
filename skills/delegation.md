---
name: Delegation & Sub-Agents
description: When and how to delegate work to other bots or spawn sub-agents for parallel grunt work
triggers: delegate, delegation, fan-out, escalate, parallel, model tier, cheap scan, scanner, sub-agent, subagent, spawn
category: core
---

# Delegation & Sub-Agents

## Two Tools, Two Purposes

| Tool | Purpose | Result |
|------|---------|--------|
| `delegate_to_agent` | Send work to a **named bot** (image bot, QA bot, etc.) | Posted to channel — the user sees it |
| `spawn_subagents` | Run **anonymous workers** for grunt work in parallel | Returned to you only — the user sees your synthesis |

**Rule of thumb:** If the user should see the result from a specific bot → `delegate_to_agent`. If you need help thinking or gathering information → `spawn_subagents`.

## spawn_subagents — Parallel Grunt Work

Use for file scanning, summarizing, research, data extraction. Sub-agents run on cheaper models with minimal context.

**When to use:**
- You have 2+ independent tasks to parallelize
- You're on an expensive model and the task is simple grunt work
- You need to scan/summarize/extract before synthesizing a response

**When NOT to use:**
- Single simple task you can handle directly in one step
- The result should be posted to the channel under another bot's name

**Built-in presets:**

| Preset | Tier | Tools | Use For |
|--------|------|-------|---------|
| `file-scanner` | fast | file, exec_command | Bulk file reading, pattern extraction |
| `summarizer` | fast | (none) | Compress large text inputs |
| `researcher` | standard | web_search | Web research with sources |
| `code-reviewer` | standard | file, exec_command | Code review, bug detection |
| `data-extractor` | fast | file, exec_command | Structured data extraction |

**Examples:**
```python
# Parallel file scanning
spawn_subagents(agents=[
  {"preset": "file-scanner", "prompt": "List all API endpoints in app/routers/"},
  {"preset": "file-scanner", "prompt": "Find all auth middleware usage in app/"},
])

# Custom sub-agent (no preset)
spawn_subagents(agents=[
  {"tools": ["web_search"], "system_prompt": "You are a fact-checker.", "prompt": "Verify: ...", "model_tier": "fast"},
])
```

## delegate_to_agent — Named Bot Delegation

Use when you need a specific bot to do its job and post the result publicly.

**Important — deferred Task semantics:** `delegate_to_agent` creates a deferred Task. Your stream completes BEFORE the child bot runs. You will not see the child's output as an inline tool return — it lands in the channel as a separate message later. If your response depends on the child's output, plan for an asynchronous reply (e.g., end your turn, let the child post, react on the next user turn).

**When to use:**
- Task needs a specialized bot (image generation, QA review, writing)
- Result should appear in the channel under that bot's identity
- Task is too complex for a sub-agent (needs full bot context, tools, persona)

**Available tiers** (for delegate_to_agent):

| Tier | Cost | Best For |
|------|------|----------|
| `fast` | Cheapest | Simple extraction, formatting |
| `standard` | Moderate | Research, code review, analysis |
| `capable` | Higher | Complex debugging, polished writing |

## Common Patterns

### Cheap Scan → Your Synthesis (use spawn_subagents)
```python
spawn_subagents(agents=[
  {"preset": "file-scanner", "prompt": "Read all test files and list untested functions"},
  {"preset": "file-scanner", "prompt": "Read all router files and list API endpoints"},
])
# -> You get both results back, synthesize a coverage report
```

### Named Bot Work (use delegate_to_agent)
```python
delegate_to_agent(bot_id="image-bot", prompt="Create a hero image for the blog post about...")
# -> Image bot generates and posts the image to the channel
```

### Escalation
Start with a sub-agent. If the result needs deeper work, delegate to a specialized bot:
```python
spawn_subagents(agents=[{"preset": "code-reviewer", "prompt": "Quick scan of auth.py for issues"}])
# If issues found:
delegate_to_agent(bot_id="bug-fix-bot", prompt="Fix the auth bypass found in auth.py line 42")
```
