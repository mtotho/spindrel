---
title: Orchestrator dissolution — implementation plan
summary: Delete the orchestrator system bot, the skills/orchestrator/ cluster, and the orchestrator.* pipeline-slug prefix. Single-user instance — straight deletes, no tombstones.
status: active
tags: [spindrel, plan, orchestrator, skills, refactor]
created: 2026-05-03
updated: 2026-05-03
---

# Orchestrator dissolution — implementation plan

This is the narrow track: delete the seeded `orchestrator` bot, redistribute or delete the `skills/orchestrator/` cluster, rename the surviving `orchestrator.analyze_discovery` pipeline slug, and remove the base-prompt routing hint.

The bigger collapse — Mission Control / Operator / Attention triage — is a sibling track. See [`docs/plans/mission-control-dissolution.md`](mission-control-dissolution.md). They run in parallel; nothing here blocks on that one.

## Why

The seeded `orchestrator` bot, the `orchestrator:home` channel, and the `skills/orchestrator/` cluster anchor an obsolete identity-level concept ("a special system bot owns coordination, scheduling, audits, integration scaffolding"). Any default bot is capable. The Project Factory absorbed the launchable-work piece. Mission Control dissolution absorbs the error-review piece. What's left here is the bot/skill/pipeline layer — pure deletion plus a few content moves.

Single-user instance. No soft-delete, no tombstones, no parallel-slug deprecation. Straight deletes, one migration, done.

## Scope

In:

- `skills/orchestrator/` cluster — content redistributed or deleted per the table below; directory removed.
- `app/data/system_bots/orchestrator.yaml` — deleted.
- `_ensure_orchestrator_bot_exists()` and the `orchestrator:home` channel auto-create in `app/services/channels.py:514–590` — deleted.
- `app/data/system_pipelines/orchestrator.analyze_discovery.yaml` — renamed to `audit.analyze_discovery.yaml`.
- `app/config.py:383–384` (base-prompt routing hint) — rewritten.
- `docs/setup.md`, `docs/guides/delegation.md` — orchestrator references removed.

Out:

- Mission Control Review, Operator sweeps, AttentionCommandDeck, `workspace_attention`, `workspace_mission_ai`, `workspace_mission_control`, `attention_triage` tasks, brief-first deck, Autofix queue, spatial attention overlays — all owned by [`mission-control-dissolution`](mission-control-dissolution.md).
- Anonymous-bot / model-only channels — parking-lot, not this track.
- Cluster-index polish for `planning/`, `history_and_memory/`, `agent_readiness/`, `widgets/` — out of scope; revisit only if dissolution edits the index files anyway.

## Skill redistribution table

Each row decides one disposition. No "or" entries — if it has to move, the destination is named.

| Source | Section | Disposition |
|---|---|---|
| `index.md` | Tool-selection table | Move to `delegation.md`. |
| `index.md` | Persistence model | **Delete.** Already covered in `context_mastery.md`. |
| `index.md` | Scheduling rules | Move to `delegation.md`. |
| `audits.md` | `analyze_discovery` row | Fold into `diagnostics/index.md` (single row, no new file). |
| `audits.md` | Configurator pointer | **Delete.** Already in `configurator/index.md`. |
| `integration_builder.md` | Full file | Extend `configurator/integration.md` with the relevant sections. |
| `model_efficiency.md` | Full file | New `## Model efficiency` section in `delegation.md`. |
| `workspace_api_reference.md` | Full file | **Delete.** No default bot operates the workspace admin API. |
| `workspace_delegation.md` | `run_claude_code`, fan-out | **Delete or move to `.agents/skills/`.** Repo-dev guidance, not runtime product. |
| `workspace_delegation.md` | Common-mistakes table | Merge into `delegation.md`. |
| `workspace_management.md` | Channel ops | **Delete.** Operator-only. |
| `workspace_management.md` | Memory writes | **Delete.** Already in `context_mastery.md`. |
| `workspace_management.md` | Secrets | **Delete.** Operator-only. |

## Phases

Land each phase as one PR. Phases 1–3 are independent; phase 4 lands after 1.

### Phase 1 — Skill content redistribution

Per the table. Trim each `skills/orchestrator/<file>.md` to a one-line redirect ("moved to X") so any cached fetches degrade cleanly until phase 6 deletes the directory. Update `skills/index.md` and any cross-references in `delegation.md`, `context_mastery.md`, `diagnostics/index.md`, `configurator/integration.md`.

Verification: `pytest tests/unit/test_skill_*` (skill discovery + frontmatter linting). RAG reseed will happen automatically on next instance start; no manual reindex.

### Phase 2 — Pipeline-slug rename

`orchestrator.analyze_discovery` → `audit.analyze_discovery`.

- Rename `app/data/system_pipelines/orchestrator.analyze_discovery.yaml`.
- Update `skills/diagnostics/traces.md:4` and the example in `app/tools/local/pipelines.py::_resolve_pipeline_id`.
- Add migration `<next>_rename_orchestrator_analyze_discovery_pipeline.py`: re-key the seeded `Task` row's deterministic UUID. `app/services/task_seeding.py:36` derives `pipeline_uuid()` from the slug, so the new slug produces a new UUID. Migration: update the existing row's id (preserves all `ChannelPipelineSubscription.task_id` references) **or** delete the old row and let the seeder re-create under the new slug; migrate `ChannelPipelineSubscription.task_id` in the same migration if going the delete path. Pick id-update — fewer downstream writes.

Verification: `pytest tests/unit/test_pipelines.py tests/unit/test_task_seeding.py`. Boot the local instance and confirm `analyze_discovery` still resolves from the bot tool and from a scheduled subscription.

### Phase 3 — Base-prompt rewrite

- Rewrite `app/config.py:383–384` (`DEFAULT_GLOBAL_BASE_PROMPT`): drop "If something is outside your scope, suggest the user ask the orchestrator." Replace with a generic surface-it-to-the-user phrasing. Pass: "If something is outside what you can do, say so to the user and stop — don't pretend or hand off."
- Drop "orchestrator" mentions from `docs/setup.md` and `docs/guides/delegation.md`.

Verification: `pytest tests/unit/test_config.py`. Grep `rg -i 'orchestrator' docs/ skills/ app/config.py` — only the migration name and `audit.analyze_discovery` slug history (if any) should remain.

### Phase 4 — System bot + channel deletion

After phase 1.

- Delete `app/data/system_bots/orchestrator.yaml`.
- Delete `_ensure_orchestrator_bot_exists()` and its call site (`app/services/channels.py:514–590`).
- Delete `orchestrator:home` channel auto-creation logic in the same area.
- Migration `<next>_drop_orchestrator_bot_and_channel.py`: hard delete the `bots` row (`id="orchestrator"`), hard delete the `channels` row(s) where `name="orchestrator:home"`, hard delete dependent `ChannelMember` / `ChannelPipelineSubscription` / `ChannelHeartbeat` rows referencing them. `Task.bot_id` rows pointing at `"orchestrator"` get re-bound to NULL or deleted (decide based on whether any non-orchestrator task references survive — likely none on the single-user instance; just delete).

Verification: `pytest tests/unit/test_channels.py tests/unit/test_system_bots.py`. Boot fresh DB, confirm no `orchestrator:home` channel auto-creates.

### Phase 6 — Catalog cleanup

After phases 1–4 ship.

- Delete `skills/orchestrator/` directory (the redirect stubs from phase 1).
- Drop the orchestrator cluster row from `skills/index.md`.
- Delete the migration name from any roadmap row that points at this track; mark the [[orchestrator-dissolution]] track `status: complete`.

Verification: `pytest tests/unit/test_skill_catalog.py`. Grep `rg -i 'orchestrator' app/ ui/ skills/ docs/` — should be empty (or only historical migration filenames).

(Phase 5 from the seed plan — cluster-index polish — is dropped as scope creep.)

## Coordination with `mission-control-dissolution`

These two tracks share zero code-level dependencies but share one logical one: the Mission Control track deletes everything that referenced `bot_id="orchestrator"` indirectly (Operator findings, attention items targeting the orchestrator bot, etc.). If MC dissolution lands first, this track's phase 4 is cleaner. If this track lands first, MC dissolution still works — orphaned attention rows pointing at the deleted bot get cleaned up in MC's deletion sweep.

Land in either order. No file-level conflicts expected.

## Risks

- **Pipeline UUID re-key vs subscription FK.** Phase 2 migration must preserve `ChannelPipelineSubscription.task_id` references. Going id-update (not delete-and-reseed) keeps all subscriptions valid.
- **Skill discovery cache drift.** RAG-indexed skill IDs change after phase 1. Confirm `skills.recommended_now` for representative test prompts after phase 1 (one quick spot-check, not a regression suite).
- **Latent bot references in user data.** On a single-user instance you can answer this directly: `select count(*) from channels where name like 'orchestrator%';`, `select count(*) from tasks where bot_id='orchestrator';`. Verify before phase 4; expect 1 channel + the seeded `analyze_discovery` task only.

## What's already true

- Four demoted audit pipelines are gone (migration `296_drop_demoted_audit_pipelines`).
- `skills/orchestrator/audits.md` already redirects to configurator except for `analyze_discovery`.
- The "use workflows" line in `skills/orchestrator/index.md:35` is gone.

## References

- Track: [[orchestrator-dissolution]]
- Sibling plan: [`docs/plans/mission-control-dissolution.md`](mission-control-dissolution.md)
- Companion plan: [`docs/plans/bot-readable-docs.md`](bot-readable-docs.md)
- Source files: `skills/orchestrator/*.md`, `app/data/system_bots/orchestrator.yaml`, `app/services/channels.py`, `app/config.py`, `app/data/system_pipelines/orchestrator.analyze_discovery.yaml`, `app/services/task_seeding.py`.
