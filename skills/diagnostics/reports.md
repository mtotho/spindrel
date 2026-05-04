---
name: Diagnostics — Reports
description: Wiring a recurring health digest into a channel — heartbeat or pipeline. Use when scheduling nightly/hourly system-health reports, posting deduped findings, or composing L1+L2 tools into a low-token digest.
triggers: heartbeat report, nightly digest, scheduled report, recurring report, system health report, daily summary post, post_heartbeat_to_channel, get_last_heartbeat, automated report, cron report, channel digest
category: operations
---

# Reports

How to wire the diagnostic surface into a recurring job. Two mechanisms
cover the practical use cases:

- **Heartbeat** — a per-channel scheduled tick that runs the bot for one
  short turn. Tool injection makes `post_heartbeat_to_channel` available
  during that turn so the bot can choose to post or stay silent.
- **Pipeline** — multi-step scheduled work with branching, evidence
  collection, and routing. Use when the digest needs to fan out to
  notification targets, not just a single channel.

If the user just wants "post a daily summary in this channel," reach for the
heartbeat. If they want "open a ticket when criticals appear," reach for a
pipeline.

## Heartbeat pattern

The heartbeat fires on schedule and runs your bot for a single turn with
the chat history of the channel as context. When the dispatch mode is
`optional`, **`post_heartbeat_to_channel`** is dynamically injected into
your tool surface — call it only if there's something worth interrupting
the channel for, otherwise stay silent and the run completes without
posting.

The cheapest implementation is one `run_script` call (see
[`programmatic_tool_use`](../programmatic_tool_use.md)) that reads the
persisted summary, decides, and posts in one round trip:

```python
from spindrel import tools
import json

summary = json.loads(tools.get_latest_health_summary(include_findings=True, max_findings=10))

if summary.get("error_count", 0) == 0 and summary.get("critical_count", 0) == 0:
    print("clean")  # nothing to post
else:
    lines = [
        f"**System health** — {summary['period_start']} → {summary['period_end']}",
        f"errors: {summary['error_count']} · critical: {summary['critical_count']} · tool_errors: {summary['tool_error_count']}",
    ]
    for f in summary.get("findings", [])[:5]:
        lines.append(f"- `{f['service']}` × {f['count']}: {f['title']}")
    tools.post_heartbeat_to_channel(message="\n".join(lines))
    print("posted")
```

Why a script and not three separate tool calls: the intermediate JSON stays
inside the script process, so only `print(...)` lands back in your context
— no token cost for the findings array you didn't post.

## Dedupe gotcha

`get_latest_health_summary` returns the **most recent persisted row**, and
the summary regenerates **once per day**. A heartbeat firing more often
than that will see the same row repeatedly.

Two ways to dedupe:

1. **Gate on `generated_at` changing.** Persist the last-posted
   `generated_at` in workspace memory; skip if unchanged.
2. **Gate on `attention_item_id`.** When the canvas attention beacon fires
   for a new finding, the summary row gets a new `attention_item_id`. Track
   that instead — beacon-aligned, no extra state.

For digests that should run more frequently than daily, use [Recent
Errors](recent_errors.md) (`get_recent_server_errors(since="<hb-window>")`)
instead of the daily summary. That tool returns live findings on every
call.

## `get_last_heartbeat` — inspect prior heartbeat outcomes

Scoped to the **current channel**. Returns recent heartbeat runs with their
prompt, result text, status, and timestamps.

```
get_last_heartbeat(limit=1)            # most recent run
get_last_heartbeat(limit=5)            # last five
```

Use this when:
- Debugging a heartbeat that "didn't post" — was it `failed`, `complete`
  with no post call, or did it never fire?
- Building a richer digest that compares this run to the previous one
  ("error count up 30% since yesterday").

It returns `{run_id, status, run_at, completed_at, result, error?}`. For
deeper inspection of what happened during a heartbeat run — which tools
were called, what errors fired — pivot to [Traces](traces.md) using the
heartbeat's correlation_id (heartbeat runs emit traces just like regular
turns).

## Pipeline pattern

When the digest needs branching (route critical findings to one target,
warnings to another, file an issue automatically) or cross-channel fan-out,
use a task pipeline. See [`pipelines/index`](../pipelines/index.md) for the
authoring contract.

Sketch:

```
step 1  call_tool       get_latest_health_summary
step 2  branch_on       counts.critical_count > 0
        ├─ true  →  step 3a  notify  target=ops_pager  template=critical
        └─ false →  step 3b  branch_on  counts.error_count > threshold
                            ├─ true →  notify  target=ops_channel  template=summary
                            └─ false → end (no notification)
```

The summary tool spends no LLM tokens — only the routing/template steps do.
That makes pipeline-driven digests cheap to run hourly.

## Boundaries

- `post_heartbeat_to_channel` only works inside a heartbeat run with
  dispatch mode `optional`. It is **not** a general "send a message"
  tool — calling it from a normal channel turn returns "no channel context
  available" or queues a malformed delivery. For ad-hoc messaging from a
  pipeline, use the configured notification target.
- Heartbeat runs do not have a normal session, so `list_session_traces`
  (which is current-session-scoped) won't show the heartbeat. Use
  `get_last_heartbeat` for run-level data, or `get_trace` list mode by
  `bot_id` for trace-level data.
- The L1 tools — `get_latest_health_summary` in particular — are
  deterministic, persisted, and zero-token-cost to generate. That's what
  makes them the right backbone for recurring reports. Don't compose
  digests from L3-L5 tools unless you specifically need the live data;
  it costs more and gives you the same answer.
