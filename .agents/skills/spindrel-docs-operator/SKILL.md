---
name: spindrel-docs-operator
description: "Use when editing Spindrel documentation or project state: canonical guides, guide index entries, roadmap rows, track notes, terminology, and docs drift tests. Repo-dev skill — not a Spindrel runtime skill. Works in both local-CLI and in-spindrel modes."
---

# Spindrel Docs Operator

Repo-dev skill for agents editing Spindrel docs and project state. Works for any
agent on this checkout — local CLI on the operator's box, in-app Spindrel agent
on the server, or a Project coding run.

This is **not** a Spindrel runtime skill and must not be imported into app skill
tables.

## Start Here

1. Read `AGENTS.md` (and its symlink `CLAUDE.md`).
2. Read `.spindrel/WORKFLOW.md` — the canonical contract for what belongs in
   `docs/inbox.md`, `docs/tracks/`, `docs/plans/`, `docs/audits/`, Project
   receipts, and `.spindrel/runs/`.
3. Read `docs/guides/index.md` and `docs/guides/tracks.md` before touching any
   guide or track.
4. Read `docs/guides/ubiquitous-language.md` before naming a new concept.

## Do

- Update the canonical guide in the same pass as behavior it owns.
- Keep roadmap rows short and put implementation detail in the owning track.
- Keep tracks as current-state summaries; long dated execution history goes to
  `docs/audits/`, `docs/plans/`, `.spindrel/audits/`, Project receipts, or
  `.spindrel/runs/`.
- Same-edit doc updates per `AGENTS.md`: bug from inbox → fix-log entry; track
  phase shipped → status table updated; load-bearing decision → architecture
  decisions; architectural change → matching guide.

## Avoid

- Do not write to the operator's vault, `~/.claude/`, `~/personal/`, or any
  path outside the repo. The vault is operator-private and not part of project
  state.
- Do not create duplicate planning documents when Roadmap, Inbox, a track, a
  plan, an audit, or a run receipt already owns the information.
- Do not paste session logs or run transcripts into track files.
- Do not mark living tracks complete when a phase ships.
- Do not document `.agents/skills/` as Spindrel runtime bot skills.
- Do not reference the deleted `agent-server/project-notes/` mirror.

## Completion Standard

Run docs drift tests when canonical guide structure changes. Run a
conflict-marker and trailing-whitespace scan over touched files.
