---
title: Orchestrator Dissolution
summary: Retire the orchestrator system bot, the skills/orchestrator/ cluster, and the orchestrator.* pipeline-slug prefix so any default bot is capable of coordination work.
status: active
tags: [spindrel, track, orchestrator, skills, refactor]
created: 2026-05-03
updated: 2026-05-03
---

# Orchestrator Dissolution

## North Star

**Any default bot is capable.** No special "orchestrator" system bot owns
coordination, scheduling, audits, or workspace tooling. The
`skills/orchestrator/` cluster, the seeded orchestrator system bot, the
`orchestrator:home` channel, and the `orchestrator.*` pipeline-slug prefix
all anchor the obsolete identity-level concept and need coordinated
removal.

User decision recorded 2026-05-03: **delete the seeded orchestrator
entirely.** Do not leave an empty shell. Redistribute its skill content
into peer skills/clusters and rename pipelines/slugs that imply an
orchestrator owner.

## Status

| Phase | State | Updated |
|---|---|---|
| 1. Skill content redistribution | not started | — |
| 2. System bot deletion | not started | — |
| 3. Pipeline-slug rename | not started | — |
| 4. Base-prompt rewrite | not started | — |
| 5. Cluster-index polish | not started | — |
| 6. Catalog cleanup | not started | — |

## Phase Detail

### 1. Skill content redistribution

Map every section of `skills/orchestrator/{index,audits,integration_builder,model_efficiency,workspace_api_reference,workspace_delegation,workspace_management}.md` to a destination. Inventory captured during the 2026-05-03 audit:

- `index.md` — tool-selection table → `delegation.md`; persistence model → `context_mastery.md`; scheduling → `delegation.md` or `automation/`.
- `audits.md` — after the 2026-05-03 cleanup only `analyze_discovery` remains; move that row to `diagnostics/audits.md` (new) or fold into `diagnostics/index.md`.
- `integration_builder.md` → `configurator/integration.md` (extend) or new `skills/integration_authoring.md`.
- `model_efficiency.md` → new section in `delegation.md`.
- `workspace_api_reference.md` → new `skills/workspace/api_reference.md`.
- `workspace_delegation.md` → merge into `delegation.md` (`run_claude_code`, fan-out patterns, common-mistakes table).
- `workspace_management.md` — channels → `workspace/channel_workspaces.md`; memory writes → `context_mastery.md`; secrets → `prompt_injection_and_security.md` or new skill.

### 2. System bot deletion

- Remove `app/data/system_bots/orchestrator.yaml`.
- Remove `_ensure_orchestrator_bot_exists()` and its call site (`app/services/channels.py:514–590`).
- Remove the `orchestrator:home` channel auto-creation.
- Add a one-shot migration to soft-delete the seeded bot row on existing instances, or document that the orphaned row is harmless.

### 3. Pipeline-slug rename

- Rename `orchestrator.analyze_discovery` → `audit.analyze_discovery` (or `bot.analyze_discovery`) in `app/data/system_pipelines/`, in `skills/diagnostics/traces.md:4`, and any other call site.
- Update slug-prefix logic in `app/tools/local/pipelines.py` if present.
- Coordinate with the four `orchestrator.analyze_*` slugs already deleted on 2026-05-03 (see `automations.md`) — those do **not** get reintroduced under the new prefix.

### 4. Base-prompt rewrite

- Update `app/config.py:383–384` from "If something is outside your scope, suggest the user ask the orchestrator" to a generic surface-it-to-the-user phrasing.
- Update `docs/setup.md` and `docs/guides/delegation.md` to drop "orchestrator" as a named role.

### 5. Cluster-index polish

While the dissolution touches several index files anyway, fold in the "open with a first action" rewrite for `planning/index.md`, `history_and_memory/index.md`, `agent_readiness/index.md`, and `widgets/index.md` — adopt the `configurator/index.md` and `project/index.md` shape.

### 6. Catalog cleanup

- Delete `skills/orchestrator/` directory.
- Update `skills/index.md` to drop the orchestrator cluster row.

## Key Invariants

- Existing instances may have orchestrator-bot references in user data (channels, tasks, traces). Phase 2 must handle that gracefully — either soft-delete with cascade-friendly behavior or document the orphaned row as harmless.
- The 2026-05-03 cleanup (`docs/plans/spindrel-skills-cohesion.md`) explicitly avoids touching the seeded orchestrator bot, the `analyze_discovery` rename, and the `skills/orchestrator/` directory. Those moves belong to this track.
- The orchestrator dissolution is allowed to delete `skills/orchestrator/`; the wiki track ([[Bot-readable internal docs]]) is *not* a prerequisite because nothing in the orchestrator cluster is large enough to warrant docs-demotion (the lone exception, `workspace_api_reference.md` at 90 lines, is being moved into a peer skill anyway).

## References

- Plan: `docs/plans/spindrel-skills-cohesion.md` — the parent plan that stubs this track.
- Roadmap row: see "Orchestrator dissolution" entry in `docs/roadmap.md`.
- Companion track: [[Bot-readable internal docs]] — required for demoting oversized reference skills, independent of this track.
- Source files: `skills/orchestrator/*.md`, `app/data/system_bots/orchestrator.yaml`, `app/services/channels.py`, `app/config.py`, `app/data/system_pipelines/orchestrator.analyze_discovery.yaml`.
