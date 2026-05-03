---
title: Inbox
summary: Open items - rough captures of bugs, ideas, tech debt, questions. Lightly schemaed for grep-ability. Promoted items become Tracks; resolved items move to fix-log.md; dismissed items are deleted.
status: active
tags: [spindrel, inbox, intake]
created: 2026-05-02
updated: 2026-05-02
---

# Inbox

Replaces the prior `docs/loose-ends.md` (deleted 2026-05-02 as part of Phase 4BD - file-based issue substrate). Plan: `docs/plans/project-factory-issue-substrate.md`. Repo-local skill: `.agents/skills/spindrel-issues/SKILL.md` (lands in 4BD.7).

## Schema

Each item is a level-2 heading with a fixed shape. Keep ceremony low; the structure is for grep-ability, not bureaucracy.

```
## YYYY-MM-DD HH:MM <kebab-slug>
**kind:** bug | idea | tech-debt | question · **area:** <module/path> · **status:** open | → tracks/<slug> | stale
Body. 1-10 lines. Free-form. Repro steps, links, context.
```

- **Heading**: ISO date + 24h time + kebab slug. Natural ordering, scannable, unique-ish.
- **kind**: one of `bug`, `idea`, `tech-debt`, `question`. Grep with `grep '^\*\*kind:\*\* bug'`.
- **area**: free-form module / path / subsystem (e.g., `ui/chat`, `app/services/sessions`, `docs`).
- **status**:
  - `open` - active, untriaged or in-flight.
  - `→ tracks/<slug>` - promoted to a Track; the Track is now the unit of work. Item stays here as a one-line pointer for history.
  - `stale` - no touch in 30+ days; agent will prompt to dismiss/promote/refresh next triage.

## Lifecycle

| Action | Effect |
|---|---|
| Captured | Append a new item to the **Open** section. |
| Promoted to a Track | Status -> `→ tracks/<slug>`. Strip the body; leave a one-line pointer. |
| Dismissed | Delete outright. No archive section. |
| Fixed inline | Delete from inbox; append a one-liner to `docs/fix-log.md`. |
| Goes stale (30+ days) | Status flips to `stale`; agent surfaces in next triage. |

## Open

<!-- New items go below this line. Newest at top within the section. -->

## 2026-05-03 01:37 scheduled-loop-policy-ui-tool-gap
**kind:** tech-debt · **area:** ui/projects, tools/project_runs · **status:** open

Backend/API schedule records can carry `loop_policy`, and one-shot Project
Runs UI exposes bounded-loop controls, but schedule creation UI and the
`schedule_project_coding_run` tool do not expose/pass `loop_policy`. Add
schedule-level loop controls and tool args after the Run Brief workflow
settles.

## 2026-05-02 22:50 thin-run-page-for-loop-iterations
**kind:** ux · **area:** ui/projects · **status:** open

Project coding-run detail page is the heavy Project Factory cockpit. For loop-driven runs the user wants a thin alternative: title + original prompt, current iteration N/M, live transcript feed of the active session, dive-in to the session, artifacts/PRs at end. Probably a `/live` tab on the existing run detail page.

## 2026-05-02 22:48 agent-log-button-routes-wrong
**kind:** bug · **area:** ui/projects · **status:** open

"Agent log" button on a Project Runs row routes to `/admin/projects/{pid}#runs` instead of the iteration's session detail. The session id is on the run record (e.g. `session 648b7cce-...`); deep-link to it.

## 2026-05-02 22:47 loop-policy-max-iterations-capped-to-8
**kind:** bug · **area:** project_runs · **status:** open

Schedule created with `loop_policy.max_iterations=15` renders as "iteration 1/8" on the run page. Either the UI Edit form clamps, or the server caps. Verify `app/services/project_coding_run_loops.py::normalize_project_run_loop_policy` and `CronScheduleModal`.

## 2026-05-02 22:46 orchestration-policy-doesnt-roll-up-blueprint-concurrency
**kind:** bug · **area:** projects/orchestration · **status:** open

`GET /api/v1/projects/{id}/orchestration-policy` returns `concurrency.max_concurrent_runs: null, source: "unset"` even when the applied Blueprint has `max_concurrent_runs=2`. Cap applies at launch (verified); read endpoint should surface it as `source: "blueprint"`.

## 2026-05-02 22:45 claude-code-runtime-capabilities-404
**kind:** bug · **area:** runtimes · **status:** open

`GET /api/v1/runtimes/claude_code/capabilities` returns 404 while `/api/v1/runtimes/codex/capabilities` is 200. Registry name drift. Surfaced by `scripts/spindrel_live_config_audit.py`.
