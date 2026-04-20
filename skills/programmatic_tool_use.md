---
name: Programmatic Tool Use
description: When to use run_script to chain or filter tool calls in Python instead of one-by-one
triggers: chain tool calls, programmatic, script, run_script, batch, filter and map, for each, list_tool_signatures, compose tools, multi-step, aggregate, join results
category: tool-use
---

# Programmatic Tool Use — When to Reach for `run_script`

You have an exec-capable tool, `run_script`, that runs a short Python script in your
workspace. From inside the script you call any tool you're authorized for as
`tools.NAME(**kwargs)` — the call routes back through the same policy and tier gate
the LLM-side dispatch uses, with your per-bot scoped API key.

The point: collapse 5–50 round trips into one. Intermediate data stays in the
script process — only what you `print()` lands back in your context.

## When to reach for it

| Pattern | Without `run_script` | With `run_script` |
|---|---|---|
| "For each X, get Y" | one tool call per X (10×, 50× chains) | one script with a `for` loop |
| Filter a list down to a few entries | dump the whole list into context, eyeball it | filter in Python, print only matches |
| Join two tools' output | call A, manually thread fields into B | `for a in A(): b = B(id=a["id"])` |
| Aggregate counts / stats | impossible without dumping data | `sum`, `Counter`, etc. inline |

Heuristic: **3+ expected tool calls of the same shape, OR any "for each" intent → use `run_script`.**

For one-off lookups, just call the tool directly. The overhead of writing a script
isn't worth it for a single call.

## How to discover what you can compose

Before writing a script, find the tools you want and their return shapes:

- `list_tool_signatures()` — compact catalog of tools that declare a return schema. Filter with `category="..."` (matches name or integration). Cheap to call repeatedly.
- `get_tool_info(tool_name="...")` — full input + output JSON Schema for one tool. Use when you need exact field names.

Call these directly from the chat turn *before* writing your script — that's
cheaper than embedding catalog lookups inside the script.

## Writing a script

The script auto-imports `from spindrel import tools`. Keep it short and focused on
the question you're answering — debug elsewhere.

```python
from spindrel import tools

# Filter pipelines by source, then show titles only.
data = tools.list_pipelines(source="user")
for p in data["pipelines"]:
    print(f"{p['title']} ({p['id'][:8]})")
```

`tools.NAME(**kwargs)` returns the same parsed JSON shape the LLM-driven call
would (so `data["pipelines"]` not `data.pipelines`). On a policy denial,
approval-required, or unknown tool, it raises `ToolError(status, detail)` —
catch it if you want to skip and continue:

```python
from spindrel import tools, ToolError

ok, skipped = [], []
for ch_id in candidate_channel_ids:
    try:
        msgs = tools.search_history(query="incident", limit=5)
        if msgs["count"] > 0:
            ok.append(ch_id)
    except ToolError as e:
        skipped.append((ch_id, e.status))

print(f"matched: {ok}\nskipped: {skipped}")
```

## What returns to your context

Only `stdout`, `stderr`, `exit_code`, and timing. The intermediate JSON the script
fetched stays inside the workspace process. So `print` only what the user (or your
next decision) actually needs — a count, a list of IDs, a table summary — not the
raw tool dumps.

If the script exits non-zero the scratch dir is preserved; the `script_dir` field
in the result tells you where to look. Otherwise it's cleaned up.

## Tools without a declared return schema (MCP, legacy tools)

Many tools — every MCP tool, plus the long tail of local tools that haven't been
backfilled with a `returns` schema yet — are still callable from scripts but
their return shape isn't documented. Run a two-line probe script first:

```python
from spindrel import tools
import json

result = tools.some_unschematized_tool(arg1="...", limit=1)
print(json.dumps(result, indent=2)[:2000])
```

You'll see the real shape, then write the composing script against it.

Tools that DO declare a return schema are always preferred for composition —
check `list_tool_signatures()` first.

## Limits

- Client (browser-side) tools aren't reachable from scripts. Use them at the
  LLM-call layer.
- Default 60s timeout, max 300s. For genuinely long work, use a task or pipeline.
- Approval-required tools raise `ToolError(409, ...)` — you can't auto-wait inside
  a script. Surface it back, or call something that doesn't require approval.
- The script's Python is plain stdlib (no `requests`, no project imports). Use
  `tools.NAME(...)` for everything that needs the agent — don't try to call the
  internal HTTP endpoints directly. For arbitrary API access, go through the
  `call_api` tool: `tools.call_api(method="GET", path="/api/v1/...")`.

## What this is NOT

- It is not a general code interpreter for the user. It's *your* tool — for
  composing your other tools more efficiently. Don't use it to "run code for the
  user" unless that's specifically what they asked.
- It is not a replacement for tasks/pipelines for long-running, scheduled, or
  multi-turn work. Use those when the work needs to outlive a single turn.
