---
name: Standing Orders
id: standing_orders
description: Plant live, cancellable dashboard tiles that tick on a schedule and ping back when a condition fires
triggers: watch this, poll until, wait for, remind me when, keep an eye on, standing order, reminder, monitor this
category: automation
---

# Standing Orders

A Standing Order is a live tile you pin to the channel's dashboard that **keeps working after the conversation ends**. It ticks on a schedule, holds its own state, and posts a chat message when it finishes. The user sees the tile the whole time and can pause, edit, or cancel it with one click.

Use a Standing Order when the user asks you to *watch*, *poll*, *wait for*, *remind them when*, or *keep an eye on* something — anything where the right answer is "I'll notice later, not now."

## When NOT to use

- If the work needs reasoning per tick → that's a **sub-session**, not a Standing Order.
- If the user wants a one-time tool call right now → just call the tool.
- If the condition isn't expressible as one of the four completion kinds → don't use a Standing Order.
- If the user wants something run at a specific time once (e.g. "at 3pm tomorrow"), that's still a Standing Order — use `timer` + `deadline_passed`.

## Spawning

Call `spawn_standing_order` with:

| Arg | What it is |
|---|---|
| `goal` | Human-readable goal shown on the tile ("Watch the staging deploy"). |
| `strategy` | `poll_url` (HTTP GET each tick) or `timer` (does nothing per tick). |
| `strategy_args` | `poll_url`: `{url, expect_status?, body_contains?}`. `timer`: `{}`. |
| `interval_seconds` | Cadence. Minimum 10. Typical 30–300. |
| `completion` | See the four kinds below. |
| `message_on_complete` | Optional. What to post in chat when the order finishes. |
| `max_iterations` | Optional hard cap (default 1000). |

### Completion kinds

- `{"kind": "after_n_iterations", "n": 10}` — stop after N ticks.
- `{"kind": "state_field_equals", "path": "strategy_state.last_status_code", "value": 200}` — stop when a field in state matches.
- `{"kind": "deadline_passed", "at": "2026-04-24T19:00:00+00:00"}` — stop when the deadline has passed.

Completion is checked **after** each tick runs.

## Examples

**"Watch my deploy."**
```
spawn_standing_order(
  goal="Watch staging deploy",
  strategy="poll_url",
  strategy_args={"url": "https://deploy.example.com/status", "body_contains": "SUCCEEDED"},
  interval_seconds=30,
  completion={"kind": "state_field_equals", "path": "strategy_state.last_matched_body", "value": true},
  message_on_complete="Staging deploy finished — build succeeded."
)
```

**"Remind me in two hours to take the laundry out."**
```
spawn_standing_order(
  goal="Laundry reminder",
  strategy="timer",
  strategy_args={},
  interval_seconds=60,
  completion={"kind": "deadline_passed", "at": "<ISO timestamp 2h from now>"},
  message_on_complete="Laundry reminder: take it out of the dryer."
)
```

**"Tell me if the health endpoint goes down."**
```
spawn_standing_order(
  goal="Watch health endpoint",
  strategy="poll_url",
  strategy_args={"url": "https://api.example.com/healthz"},
  interval_seconds=60,
  completion={"kind": "state_field_equals", "path": "strategy_state.last_status_code", "value": 500},
  message_on_complete="Health endpoint just returned 500 — something is down."
)
```

## Caps (enforced server-side)

- **5 active per bot** — cancel one before spawning a sixth.
- **>= 10s interval** — no faster polling than that.
- **<= 1000 iterations** — anything longer is the wrong primitive.
- **2s per tick wall time** — strategies that exceed this log a warning and continue.

## Lifecycle

1. You spawn a Standing Order → it appears on the channel dashboard as a live tile.
2. Every `interval_seconds` the scheduler fires one tick. The strategy updates state.
3. After each tick the explicit completion condition is evaluated.
4. When terminal, the tile's status flips (`done` / `failed` / `cancelled`) and the `message_on_complete` is posted in chat.
5. The user can click cancel at any time — cancellation is terminal.

## Context export

Pinned Standing Orders show up in your context export as one-liners like:

```
"Watch staging deploy" — running; 14 ticks; last: GET https://... -> 200 (~2m ago)
```

You will know mid-conversation what you're watching without being told. If the user asks "did my deploy go through?", check your context export first — the answer may already be there.
