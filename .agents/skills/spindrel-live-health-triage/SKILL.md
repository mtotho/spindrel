---
name: spindrel-live-health-triage
description: Repo-dev workflow for coding agents to inspect a live Spindrel instance's recent health findings, promote actionable errors into Attention, resolve only clear benign/recovered duplicates, and turn likely code bugs into repo work.
---

# Spindrel Live Health Triage

This is a repo-dev skill for agents working inside this Git repository. It is
not a Spindrel runtime skill and must not be imported into app skill tables.
Runtime agents use runtime tools and the `skills/diagnostics/health_triage.md`
skill instead.

Use this when asked to dogfood daily health, inspect latest persisted errors,
or triage live server issues before or after backend/runtime work.

## Setup

1. Determine the live API base URL from local env or project docs. Prefer the
   currently running backend; do not start a Vite dev server for this skill.
2. Use the local API key from env/config without printing it, writing it to
   files, or committing it.
3. If no live backend or key is available, stop the live portion and report the
   missing prerequisite. Still inspect code for likely bugs if the error
   payload was supplied.

## Fetch Current Findings

Call:

```
GET /api/v1/system-health/recent-errors?since=24h&limit=50&include_attention=true
```

For active investigation, also check a shorter window:

```
GET /api/v1/system-health/recent-errors?since=2h&limit=50&include_attention=true
```

Read findings by severity, count, freshness, service, signature, and existing
Attention state. Do not treat a stale daily summary as current truth when the
recent-errors endpoint is available.

The response should include `review_state` on each finding. If it does not,
the server is still on the pre-overlay build; do not call `promote` because old
promotion can re-surface duplicates that were already resolved.

Useful focused views:

```
GET /api/v1/system-health/recent-errors?since=24h&review_state=open&include_attention=true
GET /api/v1/system-health/recent-errors?since=24h&review_state=stale_resolved_reappeared&include_attention=true
GET /api/v1/system-health/recent-errors?since=24h&exclude_review_state=resolved_duplicate&include_attention=true
```

## Promote Review-Worthy Errors

Promote only findings that deserve durable review:

```
POST /api/v1/system-health/recent-errors/promote
{
  "since": "24h",
  "limit": 20,
  "min_severity": "error"
}
```

Use `dedupe_keys` when only a subset should enter Attention. Promotion reuses
existing open or acknowledged items with the same dedupe key. By default, it
skips findings already reviewed as `resolved_duplicate`; pass that exact
`dedupe_key` or `include_resolved=true` only when you intentionally want to
re-open or re-promote it.

## Classify Each Promoted Finding

Use these labels in your notes:

- `benign` — expected or harmless and evidence is specific.
- `duplicate` — another open item already covers the same root cause.
- `already_recovered` — absent from the short live window or clearly fixed.
- `external` — caused by a dependency/service outside this repo.
- `likely_code_bug` — points to code in this repo and needs a patch/test.
- `unknown` — not enough evidence yet.

Resolve only `benign`, `duplicate`, `already_recovered`, `external`, or `stale`
findings with evidence. Never resolve `likely_code_bug` or `unknown` just to
make the queue quiet.

## Resolve With Notes

Call:

```
POST /api/v1/workspace/attention/{id}/resolve
{
  "resolution": "duplicate",
  "duplicate_of": "open-root-attention-item-id",
  "note": "Covered by the root finding; keeping that item open."
}
```

Allowed `resolution` values: `fixed`, `benign`, `duplicate`,
`not_reproducible`, `external`, `stale`, `already_recovered`, `other`.

`GET /recent-errors?include_attention=true` returns `review_state`. A
`resolved_duplicate` finding can still be a recent log event; it is simply not
new work. Keep the root item open and avoid spending review time on the wrapper
signature unless it reappears without a valid `duplicate_of` target.

## Convert Code Bugs Into Repo Work

For `likely_code_bug`:

1. Leave the Attention item open.
2. Search the repo for the signature, tool name, route, model, or service path.
3. Identify the smallest failing test or add one before changing logic.
4. In the final report, include the Attention id, dedupe key, suspected files,
   and verification command.

Use this skill at the start of long backend/runtime work and before final
handoff when your changes could affect server health.
