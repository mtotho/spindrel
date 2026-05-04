---
name: Diagnostics — Health Summary
description: L1 orientation tier. Read the daily health summary and fleet snapshot before drilling deeper. Cheapest entry point for "what was wrong overnight?" / "is anything broken?". Confirms the named bot/integration exists.
triggers: health summary, daily summary, system health, what broke overnight, fleet snapshot, system status, list bots, list channels, list integrations, is anything wrong, attention beacon
category: operations
---

# Health Summary (L1)

Cheapest possible orientation tier. Two tools, ~one round trip, and you know
which subsystem to drill into next — or whether to drill at all.

## When to fetch this skill

- The user's prompt is open-ended ("what broke last night?", "is anything
  wrong?", "give me a health check").
- You're about to investigate something but want to confirm the named
  bot / channel / integration actually exists first.
- A heartbeat or scheduled report needs persisted counts to act on.

## `get_latest_health_summary`

Returns the most recent daily system-health summary as JSON.

```
get_latest_health_summary(include_findings=true, max_findings=20)
```

**Schema highlights:**
- `generated_at`, `period_start`, `period_end` — when the summary covers.
- `error_count`, `critical_count`, `trace_event_count`, `tool_error_count` —
  totals for the window.
- `source_counts` — per-service finding counts.
- `findings` — top deduped `LogFinding` rows: `{service, severity, signature,
  dedupe_key, title, sample, first_seen, last_seen, count}`.
- `attention_item_id` — set if the canvas-side attention beacon fired for
  this summary; cross-reference if you need the workspace marker.

**Important property: no LLM tokens were spent generating it.** It's produced
deterministically by `app/services/system_health_summary.py` once per day. So
this is the right tool to wire into a recurring report — see
[Reports](reports.md).

**Staleness check:** if `generated_at` is null, the summary hasn't run yet —
fall through to [Recent Errors](recent_errors.md). If it's older than 24h,
treat it as historical and use Recent Errors for live state.

## `get_system_status`

Returns a cheap fleet snapshot: bots, channels, integrations, providers,
system config, fresh-install flag.

```
get_system_status()
```

**Use this to:**
- Disambiguate the user's reference ("which bot is `crumb`?").
- Confirm an integration the user named is actually configured before you go
  hunting for failures in it.
- Detect fresh installs (`is_fresh_install: true`) — different diagnostic
  posture (nothing's broken, nothing's set up either).

**Don't use it to:** count things globally for an audit. It returns the live
list, not historical state. For trends, use [Traces](traces.md) list mode
with timestamps.

## What this tier won't tell you

- **Per-turn failures** — the summary is window-aggregated; one bad turn
  rarely makes it into the rollup. Use [Traces](traces.md).
- **Live errors after the last summary ran** — by definition the summary is
  stale relative to "right now". Use [Recent Errors](recent_errors.md).
- **Raw stderr context** — findings include a `sample` field (one line of
  context) but not the surrounding log lines. If you need those, [Raw
  Logs](raw_logs.md) is the L5 tool — but only after this tier gave you a
  service name and a signature substring to grep.

## Reading findings well

Don't dump the full findings array into your response. Pick the one or two
whose `severity` is `critical` OR whose `count` is anomalously high relative
to the others, and report those by `service` + `signature` + `count`.

The `signature` is the same normalized key the 60-second
`WorkspaceAttentionItem` detector uses, so a finding here will tie back to
the canvas attention beacon if one fired. Don't roll your own dedupe.
