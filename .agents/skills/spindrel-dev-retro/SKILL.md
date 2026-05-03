---
name: spindrel-dev-retro
description: "Use when the user asks for a retrospective on the Spindrel project itself — 'how is the work going?', 'weekly retro', 'sprint retro', 'what should we improve', 'look at the last N days'. Strategic synthesis across recent commits, fix-log, inbox, tracks, and Project coding-run outcomes. Per-run failure investigation is delegated to `spindrel-project-run-review`. Repo-dev skill — not a Spindrel runtime skill."
---

# Spindrel Dev Retro

Repo-dev retrospective for the Spindrel project itself. Synthesizes signals across the recent window into themed findings the operator can act on. Pairs with `spindrel-project-run-review`, which owns per-run failure classification — this skill consumes that skill's output instead of duplicating it.

The retro is a deliberate "stop and look back" — not a cron, not auto-fired, not part of any other loop. The operator invokes it at end-of-week or when something feels off.

## What this skill produces

A single markdown file at `docs/audits/dev-retro-<YYYYMMDD>.md` with sections:

1. **Process health** — what slowed us down, got dropped, or accreted churn.
2. **Product health** — what real users keep struggling with (manifested as repeated inbox/fix-log entries).
3. **Run-loop effectiveness** — Project run outcomes in the window: succeeded vs blocked vs needs_review vs failed, themed by lineage.
4. **Track + skill drift** — stale tracks, recurring re-suggestion of completed deepenings/security findings, skill specs that misroute.

Each finding is classified by **owner**: `repo-dev skill | runtime skill | runtime tool/api | UX surface | docs | infra`. Each has a one-line **what** and a one-line **next slice** — concrete enough to action, not a vibe.

## Inputs (read-only, repo + API only)

This skill must work from any agent — local CLI on the operator's box, in-app Spindrel agent on the server, or an overnight Project run. It does **not** read the operator's vault, personal Claude memory, or assume a particular docker container name.

| Input | Source |
|---|---|
| Project coding runs in window | `GET /api/v1/projects/{id}/coding-runs?limit=200` (filter by `created_at`) |
| Run receipts + `loop_decision` | `GET /api/v1/projects/{id}/run-receipts` |
| Per-run failure classification | invoke `spindrel-project-run-review` for the same window; consume its findings |
| Fix-log adds in window | `git log --since=<window> -- docs/fix-log.md` |
| Inbox adds in window | `git log --since=<window> -- docs/inbox.md` |
| Stale active tracks | `docs/tracks/*.md` frontmatter — `status: active` AND `updated:` more than 30 days ago |
| Commit volume + scope | `git log --since=<window> --pretty=format:'%h %s' --shortstat` |
| Architecture-deepening drift | `docs/deepening-log.md` entries vs current code |
| Security-track drift | `docs/tracks/security.md` shipped items vs current audit signals |
| Recurring screenshot churn | `git log --since=<window> --name-only -- 'docs/images/**' 'scratch/agent-e2e/**' | sort | uniq -c | sort -rn` |

See [`../_shared/api-access.md`](../_shared/api-access.md) for the canonical
`$SPINDREL_API_URL` / `$SPINDREL_API_KEY` env-var contract and
[`../_shared/mcp-bridge-tools.md`](../_shared/mcp-bridge-tools.md) for the
runtime tool catalog.

## Procedure

1. **Resolve the window.** Default 14 days; accept `--since 7d`, `--since 30d`, or an absolute date. Convert to absolute dates internally.
2. **Resolve the project.** For single-Project deployments, pick the one project; for multi, ask. Same convention as `spindrel-project-run-review`.
3. **Walk every input.** Build a flat list of raw observations. Do NOT classify yet.
4. **Pull run-loop themes** from `spindrel-project-run-review` (run it for the same window, consume its findings as a sub-step). Do not re-classify per-run failures here.
5. **Group by theme.** Multiple observations pointing at the same underlying problem collapse into one finding. Single-incident observations are dropped unless severe.
6. **Classify each finding by owner** (per the agentic-readiness audit shape). For each finding, write the one-line **what** and one-line **next slice**.
7. **Render** `docs/audits/dev-retro-<YYYYMMDD>.md` with proper frontmatter.
8. **Print the report path** on stdout. The operator decides whether to commit it.

## Heuristics worth firing

- **Recurring failure mode** — same kind of fix-log entry appears 2+ times in window → flag as candidate for a deeper structural fix or a runtime-skill clarification.
- **Loop dropout** — receipts ending `loop_decision.reason == "missing_loop_decision"` or `"loop_budget_exhausted"` more than once → budget or instruction issue with the loop's child skill.
- **Skill that needs tightening** — a runtime skill referenced in run prompts whose runs end `needs_review` more than 1/3 of the time → the spec is too vague or misroutes.
- **Stale track** — `docs/tracks/<x>.md` with `status: active` and `updated:` more than 30 days ago → either ship it, supersede it, or flip to `complete`.
- **Inbox stagnation** — items added to `docs/inbox.md` more than 7 days ago with no matching `docs/fix-log.md` entry and no commit touching the named file → operator queue is backing up.
- **God-function smell** — a function/file appearing in 4+ recent commits → flag for extraction (per `AGENTS.md` "god functions are the #1 bug source").
- **Deepening-log drift** — an entry in `docs/deepening-log.md` whose seam has been bypassed by recent commits → flag for a deepening drift-sweep run.
- **Security audit-signal regression** — a signal that flipped from pass→fail in window without a corresponding `docs/tracks/security.md` entry → flag for the security skill.
- **Screenshot churn** — same UI surface re-captured in 3+ different sessions in window → flag the surface for stabilization.
- **Scope-creep commit** — a single commit touching 8+ files across unrelated areas → flag for review (often a session that committed someone else's parallel work).

## What this skill does NOT do

- Auto-edit other skills, AGENTS.md, or any track. Recommendations only; the operator (or a follow-up turn) actions them.
- Hit external trackers (Linear, GitHub Issues). Spindrel's internal record is enough.
- Comment on individual contributors.
- Call itself part of a loop. The retro fires when the operator asks. Period.
- Re-classify per-run Project failures. That work lives in `spindrel-project-run-review`; this skill consumes its output.
- Read the operator's vault, personal memory, or any path under `~/personal/`. Repo + API only.

## Output shape (template)

```markdown
---
title: Spindrel dev retro — <date>
summary: <N> findings across process / product / run-loop / drift.
status: complete
tags: [spindrel, retro]
created: YYYY-MM-DD
updated: YYYY-MM-DD
window: 14d
---

# Dev retro — <date>

## Process health

### Owner: repo-dev skill
- **What**: <one line>
- **Next slice**: <one line>

### Owner: docs
- ...

## Product health

### Owner: runtime skill
- ...

### Owner: UX surface
- ...

## Run-loop effectiveness

### Owner: runtime tool/api
- ...

(themed summary; per-run details live in the `spindrel-project-run-review` output for the same window)

## Track + skill drift

### Owner: docs
- ...
```

## Pairing with sibling skills

- **`spindrel-project-run-review`** — consumed by this skill for the run-loop section. Run it first for the same window, then synthesize.
- **`improve-codebase-architecture`** — receives recurring-pattern findings as deepening candidates.
- **`spindrel-security-audit`** — receives audit-signal regressions or recurring boundary findings.

When in doubt, this skill writes the doc; it does not invoke the sibling skills' fix loops itself.
