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
