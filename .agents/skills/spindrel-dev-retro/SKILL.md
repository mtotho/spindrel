---
name: Spindrel Dev Retro
description: >
  Repo-dev retrospective for the Spindrel project itself — both how the
  development process is going and how the product is shaping up. Reads the
  last N days of project_coding_runs, fix-log, inbox, recent commits, recent
  receipts, recent screenshots, and recent vault session logs; emits a
  candid retro doc with concrete improvement candidates classified per the
  agentic-readiness audit shape.
triggers: dev retro, weekly retro, sprint retro, what should we improve, look at the last N days
category: repo-dev
---

# Spindrel Dev Retro

This is a **repo-dev** skill, not a runtime project skill. It is consumed by
Codex/Claude when the user — working in the Spindrel repo, either locally or
in a Spindrel Project channel — wants to step back and ask "how is the work
going?" It is independent of any specific feature, including the harness
parity loop.

The retro is a deliberate "stop and look back" — not a cron, not auto-fired,
not part of any other loop. The user invokes it at end-of-week, after a long
sprint, or when something feels off.

## What this skill produces

A single markdown file at `docs/audits/dev-retro-<YYYYMMDD>.md` with sections:

1. **Process health** — what slowed us down or got dropped.
2. **Product health** — what real users (you) keep struggling with.
3. **Skill effectiveness** — which runtime skills actually fired well.
4. **Memory health** — entries that have aged out or contradict the code.

Each finding is classified by **owner** per the agentic-readiness audit shape:
`repo-dev skill | runtime skill | runtime tool/api | UX surface | memory | docs`.
Each finding has a one-line **what** and a one-line **next slice** — concrete
enough to action, not a vibe.

## Inputs (read-only)

- **Project coding-run history**: `GET /api/v1/projects/{id}/coding-runs?limit=200`
  on the live server (use the operator API key from
  `docker exec agent-server-agent-server-1 printenv API_KEY` when running on
  spindrel-bot, or `--api-key` locally). Filter to runs with `created_at >=
  now - <window>`.
- **Receipt loop decisions**: each run's receipts via
  `GET /api/v1/projects/{id}/coding-runs/{run_id}/receipts`. Pull
  `metadata.loop_decision` when present so loop dropouts surface.
- **Repo state**:
  - `docs/fix-log.md` and `docs/inbox.md` adds since `<window>` ago via
    `git log --since=<window> -- docs/fix-log.md docs/inbox.md`.
  - `docs/tracks/*.md` `status:` and `updated:` frontmatter for tracks
    older than 30 days still `active`.
  - `git log --since=<window> --pretty=format:'%h %s' --shortstat` for
    commit volume + scope-creep heuristics (8+ files in one commit is a
    smell).
- **Vault session logs** at `~/personal/vault/Sessions/spindrel/` for the
  same window — the user's own notes about what felt slow or got lost.
- **Memory rules** at
  `~/.claude/projects/-home-mtoth-personal-agent-server/memory/MEMORY.md`
  and the linked feedback files. Compare against `AGENTS.md` + `docs/guides/`
  to spot drift.
- **Screenshot artifacts** under `scratch/agent-e2e/harness-parity-runs/`
  and `docs/images/` for re-screenshot frequency (a UI surface captured
  many times in one window suggests visual instability).

## Procedure

1. Resolve the window. Default 14 days; accept `--since 7d`, `--since 30d`,
   or an absolute date in the user's prompt.
2. Resolve the project id from `/api/v1/projects` (Spindrel canonical
   project; the audit helper also uses this).
3. Walk every input above, building a flat list of raw observations. Do
   NOT classify yet.
4. Classify each observation by owner (per the agentic-readiness shape).
5. Group within each owner by *theme* — multiple observations pointing at
   the same underlying problem collapse into one finding. Single-incident
   observations are dropped unless they are severe.
6. For each finding, write the one-line **what** and one-line **next slice**.
7. Render `docs/audits/dev-retro-<YYYYMMDD>.md` with frontmatter
   (`title`, `summary`, `status: complete`, `tags: [spindrel, retro]`,
   `created`, `updated`).
8. Print the report path on stdout.

## Heuristics worth firing

- **Recurring failure mode**: same kind of fix-log entry shows up 2+ times
  → flag as candidate for a deeper structural fix or a runtime-skill
  clarification.
- **Loop dropout**: receipts ending `loop_decision.reason ==
  "missing_loop_decision"` or `"loop_budget_exhausted"` more than once
  → budget or instruction issue with the loop's child skill.
- **Skill that needs tightening**: a runtime skill referenced in run
  prompts whose runs end `needs_review` more than 1/3 of the time → the
  spec is too vague or the skill misroutes.
- **Stale track**: `docs/tracks/<x>.md` with `status: active` and
  `updated:` more than 30 days ago → either ship it, supersede it, or
  flip it to `complete`.
- **Inbox stagnation**: items added to `docs/inbox.md` more than 7 days
  ago with no matching `docs/fix-log.md` entry and no commit touching the
  named file → operator queue is backing up.
- **God-function smell**: a function/file appearing in 4+ recent commits
  → flag for extraction (per AGENTS.md's "god functions are the #1 bug
  source" rule).
- **Screenshot churn**: same UI surface re-captured in 3+ different
  sessions in the window → flag the surface for stabilization.
- **Memory drift**: a memory entry that names a file/function/flag that
  no longer exists in the code → mark stale; suggest delete or update.

## What this skill does NOT do

- Auto-edit other skills, memory entries, AGENTS.md, or any track.
  Recommendations only; the human (or a follow-up turn) actions them.
- Hit external trackers (Linear, GitHub Issues). Spindrel's internal record
  is enough for a retro.
- Re-derive observations the user already wrote in the vault — quote them
  with file:line so the retro is auditable.
- Comment on individual contributors. There is one contributor; that is
  not the retro's lens.
- Call itself part of a loop. The retro fires when the user asks. Period.

## Output shape (template)

```markdown
---
title: Spindrel dev retro — <date>
summary: <N> findings across process / product / skills / memory.
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

## Skill effectiveness

### Owner: runtime skill
- ...

## Memory health

### Owner: memory
- ...
```
