---
name: spindrel-docs-operator
description: "Use when editing Spindrel documentation or project state: canonical guides, guide index entries, vault roadmap rows, track notes, session logs, terminology, and docs drift tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Docs Operator

This is a repo-dev skill for agents editing Spindrel source and workspace state. It is not a Spindrel runtime skill and must not be imported into app skill tables.

## Start Here

1. Read `CLAUDE.md`, `.spindrel/WORKFLOW.md`, and `docs/guides/index.md`.
2. Read `docs/guides/ubiquitous-language.md` before naming new concepts.
3. Treat `vault/Projects/agent-server/` as live project state.
4. Do not edit `agent-server/project-notes/` as the source of truth.

## Do

- Update the canonical guide in the same pass as behavior it owns.
- Keep roadmap rows short and put implementation detail in the owning track.
- Keep tracks as current-state summaries. Put long dated execution history,
  parity ledgers, and investigation evidence in `docs/audits/`, `docs/plans/`,
  `.spindrel/audits/`, Project receipts, or the private session vault, then
  link from the track.
- Append concise private session bullets for shipped changes, verification, and
  gotchas when the vault is the right continuity surface.
- Preserve the split between repo-dev AX and in-app runtime AX whenever writing
  about agent-first work.

## Avoid

- Do not create duplicate planning documents when Roadmap, Inbox, a track, a
  plan, an audit, or the current session log already owns the information.
- Do not paste session logs into track files.
- Do not mark living tracks complete when a phase ships.
- Do not document `.agents/skills` as Spindrel runtime bot skills.
- Do not mirror vault edits into `project-notes` manually.

## Completion Standard

Run docs drift tests when canonical guide structure changes. For vault-only
state notes, run a conflict-marker and trailing-whitespace scan over touched
vault files.
