---
name: Delegation & Model Tiers
description: >
  Compact guide for using delegate_to_agent effectively with model tiers.
  For any bot with delegates — teaches when and how to delegate cost-effectively.
---

# Delegation & Model Tiers

## When to Delegate vs Do It Yourself

**Delegate when:**
- The task needs 3+ tool calls to gather information (delegate to a scanner)
- The task is outside your core expertise (e.g., you're a QA bot and need web research)
- The task can run in parallel with your other work
- You need a different cost tier than your own (cheap scan, or expensive polish)

**Do it yourself when:**
- You already have the information needed
- It's a single tool call or simple synthesis
- The overhead of delegation (context assembly, task creation) isn't worth it

## Available Tiers

| Tier | Cost | Best For |
|------|------|----------|
| `fast` | Cheapest | Scanning files, summarizing, extracting data |
| `standard` | Moderate | Research, code review, structured analysis |
| `capable` | Higher | Complex debugging, polished writing, architecture |

## How Tiers Work

When you call `delegate_to_agent`, the model tier is resolved automatically:

1. **Your carapace's delegate entry** defines the default tier for each delegate
2. **Explicit `model_tier` param** overrides the default (use sparingly)
3. **Bot's own model** is the final fallback

```python
# Default tier from your delegate config (usually correct)
delegate_to_agent(bot_id="scanner", prompt="Find all API endpoints in app/routers/")

# Override for an unusually complex scanning task
delegate_to_agent(bot_id="scanner", prompt="...", model_tier="standard")
```

## Common Delegation Patterns

### Cheap Scan → Your Synthesis
Delegate the grunt work, synthesize the results yourself:
```python
delegate_to_agent(bot_id="scanner", prompt="Read all test files and list untested functions")
# → You get back a structured list, then decide what to do with it
```

### Parallel Fan-Out
Break a task into independent pieces and delegate each:
```python
delegate_to_agent(bot_id="scanner", prompt="Scan backend for auth patterns")
delegate_to_agent(bot_id="scanner", prompt="Scan frontend for auth patterns")
# → Collect both results, synthesize
```

### Escalation
Start cheap. If the result is insufficient, escalate:
```python
delegate_to_agent(bot_id="scanner", prompt="...")  # fast tier
# If too shallow:
delegate_to_agent(bot_id="researcher", prompt="...", model_tier="capable")  # upgrade
```
