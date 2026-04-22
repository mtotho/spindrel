---
tags: [agent-server, track, skills, simplification]
status: complete
updated: 2026-04-22
---
# Track — Skill & Capability Simplification

## North Star
Claude Code's "installed skills" model. Tools are just available; knowledge is files; prompts are CLAUDE.md. Replace the 6+ assignment surfaces (bot YAML, channel overrides, capability resolution, integration activation, session state, auto-enrollment) with two: bot config + channel config.

For the *why*, see [[Architecture Decisions#Per-Bot Persistent Skill Working Set]] and [[Architecture Decisions#Conditional Auto-Enrollment on Workspace Join]].

## Status

| Phase | Status | One-line |
|---|---|---|
| Phase 0 — Audit | ✅ DONE | Classified every skill / capability-skill pair, found 12 redundant |
| Phase 1 — Migrate capability skills → fragment references | ✅ DONE | Removed `skills` field from all 4 core carapace YAMLs (orchestrator, presenter, data-analyst, image-artist) |
| Phase 1.5 — Kill carapace skills end-to-end | ✅ DONE 2026-04-10 | Removed `skills:` from all 7 integration carapace YAMLs (arr, github, gmail-feeds, google-workspace, frigate, mission-control, home-assistant). Dropped runtime merge in `resolve_carapaces()` + `context_assembly.py` + `tasks.py`. Dropped `Carapace.skills` ORM column (migration 187), `ResolvedCarapace.skills`, `_carapace_to_dict` skills key, `manage_capability` skills parameter + `_parse_skills` helper, `CarapaceCreateIn`/`CarapaceUpdateIn`/`CarapaceOut.skills` Pydantic fields, admin + bot-facing route writes, `file_sync.py` carapace-skills assignments, capability_rag embedding inclusion, `activate_capability` `skills_next_turn` response field, `tool_dispatch._capability.skills_count` metadata, UI `Carapace.skills` type + `WorkspaceSkills`/`SkillPreview` rendering + `buildSkillCarapaceMap` + `CapabilityPreviewData.skills` + `CapabilityPreview` skill block + `BotInfoPanel` skillCapMap + `[carapaceId].tsx` Skills FormRow + `index.tsx` skills count + `ToolsOverrideTab` skill provenance. Rewrote `carapaces/orchestrator/skills/carapace-architect.md` to teach the new model (no skills field, fragment-as-index, on-fetch promotion). Updated `integration-builder.md`, `docs/guides/custom-tools.md`, `integrations/arr/README.md` to match. Added `tests/unit/test_carapaces.py::test_legacy_skills_field_silently_ignored` graceful-ignore test. |
| Phase 2 — Kill pinned skill mode | ✅ DONE | Merged 2 pinned skills into fragments. Removed pinned injection from `context_assembly.py`. ~100 lines of access-check code gone |
| Phase 3 — Per-bot working set (sub-phases 3.0–3.8) | ✅ DONE 2026-04-10 | Schema, starter pack, replaced auto-enrollment, get_skill promotion, semantic discovery layer, hygiene curation, bot UI panel |
| Phase 3.9 — Skill content review + self-improvement nudges | ✅ DONE 2026-04-10 | New `skill_authoring.md` + `agent_cli.md`, rewrote `context_mastery.md`, trimmed `prompt_injection_and_security.md`, Self-Improvement section in base prompt, conditional auto-enrollment on workspace join (`source="auto"`) |
| Phase 4 — Workspace half (drop `SharedWorkspace.skills`) | ✅ DONE 2026-04-10 | Migration 185. Live server had zero data in the column. Replacement: conditional auto-enrollment on workspace join |
| Phase 4 — Channel half (drop `skills_extra` / `skills_disabled`) | ✅ DONE 2026-04-14 | Migration 195 drops columns. All backend reads/writes, API schemas, UI types, and tests removed. |
| Phase 5 — Skills removed from bot config | ✅ DONE | `get_skill()` / `get_skill_list()` auto-injected for all bots |
| Phase 6 — Workspace singleton cleanup | ✅ DONE 2026-04-10 | Promoted `workspace_member`/`channel_workspaces`/`docker_stacks` to `STARTER_SKILL_IDS`. Dropped `source="auto"` Literal + tests + UI badge. Retired POST/DELETE workspace-bot endpoints with 410. Removed `bots.workspace_only` (column drop migration 186, ORM/API/UI/tool/schema). UI BotsTab no longer exposes add/remove. Skill copy + carapace + docs + CLAUDE.md updated. 171/171 targeted tests pass; full suite has same 15 pre-existing failures as baseline. See [[Plan - Workspace Singleton Cleanup]] |
| Phase 7 — Enrolled skill ranking + auto-inject | ✅ DONE 2026-04-14 | Per-turn semantic ranking of enrolled skills against user message via `rank_enrolled_skills()`. Two-tier annotation (relevant ↑ / auto-inject). Top match auto-injected as synthetic `get_skill()` tool call/result pairs with `_no_prune` persistence. Budget accounting (`_budget_can_afford`/`_budget_consume`). History-scan dedup. Separate tracking: `auto_inject_count`/`last_auto_injected_at` on enrollment. 5 tests. Trace events: `skills_in_history`, `skipped_in_history`, `skipped_budget`. See [[Architecture Decisions#Enrolled Skill Relevance Ranking + Auto-Inject]] |

## 2026-04-21 follow-on
- Product direction changed again: there is no replacement "capability package" model. Foldered skills are still just skills.
- Runtime `activate_capability`, capability approval handling, capability discovery prompt injection, and channel capability UI started coming out in favor of plain skill/tool enrollment.
- Channel-level skill enrollment was introduced (`channel_skill_enrollment`, migration 236) so channel capability assignment can fold into the existing skills surface instead of inventing a new package abstraction.
- Admin/UI direction now is: remove capability pages/sections, make `/admin/skills` folder-aware (`index.md` roots + child skills), and let bots/channels show enrolled skills/tools only.
- Remaining cleanup is mostly deletion of dormant carapace CRUD/routes/docs/workflow fields; the runtime path is the important cut.
- Follow-up removal pass deleted the public/admin carapace routers and local management tools, removed approval pinning, removed workflow/pipeline/delegation `carapaces` execution config, and removed the admin capability pages/hooks/types from the UI.
- Integration activation summaries now expose only tools + system prompt presence on the active channel UI path; they no longer resolve carapaces for tool summaries.
- Targeted verification after the removal pass: `pytest tests/unit/test_file_sync_skills.py -q` passed, `pytest tests/unit/test_tool_dispatch_core_gaps.py -q -k approval` passed after deleting obsolete `activate_capability` approval tests, `pytest tests/unit/test_workflow_tool.py -q -k step` reported `1 skipped, 17 deselected`, and `timeout 30s npx tsc --noEmit` exited cleanly.
- Next destructive cleanup pass removed the remaining live file-sync/admin helper callers that still pulled carapaces into active behavior: `app/services/file_sync.py` no longer watches or syncs carapace YAML, admin channel context preview no longer shows carapace prompt fragments, the channel-creation integration manifest summary no longer resolves carapaces for tool lists, bot-scoped direct tool execution no longer augments allowed tools through `bot.carapaces`, and the `workspace_bot` API-key preset dropped the dead `carapaces:*` scopes.
- Verification for that pass: `python -c "import importlib; ..."` successfully imported `app.services.file_sync`, `app.routers.api_v1_admin.channels`, `app.routers.api_v1_admin.tools`, and `app.services.api_keys`; `python -m py_compile app/services/file_sync.py app/routers/api_v1_admin/channels.py app/routers/api_v1_admin/tools.py app/services/api_keys.py` passed; `pytest tests/unit/test_file_sync_skills.py -q` still passed (`9 passed`).
- Follow-up service cleanup removed the remaining carapace-aware behavior from `feature_validation` and old admin helpers: feature validation now checks only static bot features plus integration-manifest `tools`, `manage_integration` no longer scaffolds/reloads `carapaces`, `manage_channel` no longer advertises or writes `carapaces_extra` / `carapaces_disabled`, and the admin integration activation comments were rewritten around skills/prompts/workflows instead of carapaces.
- Verification for that pass: `pytest tests/unit/test_feature_validation.py -q` passed (`8 passed`) and `python -m py_compile app/services/feature_validation.py app/tools/local/admin_integrations.py app/tools/local/admin_channels.py app/routers/api_v1_admin/integrations.py` passed.
- Bot/admin cleanup removed the remaining public bot `carapaces` API shape from the active admin path: `BotConfig`, bot admin schemas/helpers, and bot create/update payloads no longer expose `carapaces`, and stale scaffold tests were rewritten to the current integration contract (`integration.yaml`, no scaffolded `carapaces/`, no reload-time carapace registry call).
- Direct obsolete capability/carapace test files were deleted in the same pass so the remaining test blast area is concentrated in mixed approval/file-sync/context/delegation coverage rather than standalone preservation suites.
- Verification for that pass: `python -m py_compile app/agent/bots.py app/routers/api_v1_admin/_schemas.py app/routers/api_v1_admin/_helpers.py app/routers/api_v1_admin/bots.py app/agent/context.py app/agent/context_assembly.py app/services/workflows.py tests/unit/test_integration_reload.py` passed and `pytest tests/unit/test_integration_reload.py -q` passed (`22 passed`).
- Follow-up unit-tail cleanup removed more stale mixed-test coverage: `tests/unit/test_integration_activation.py` was deleted, `test_model_tiers.py` was rewritten around plain bot-to-bot delegation model tiers, `test_auto_injections.py` dropped `activate_capability`, `test_decide_approval_flow.py` dropped capability pinning, `test_approval_orphan_pointers.py` dropped capability-gate orphan cases, `test_tool_schema_backfill_tier2.py` dropped `manage_capability` schema coverage, and file-sync tests stopped patching/expecting carapace reload paths.
- Verification for that pass: `pytest tests/unit/test_model_tiers.py -q -x` passed (`6 passed`), `pytest tests/unit/test_auto_injections.py -q` passed (`15 passed`), and `python -m py_compile` across the edited unit files passed. The remaining DB-heavy unit suites (`test_decide_approval_flow.py`, `test_file_sync.py`, `test_file_sync_core_gaps.py`, `test_approval_orphan_pointers.py`) hit the 30s timeout ceiling in this environment without surfacing new assertion failures, so they still need a calmer run.
- Remaining backend blast area is now mostly dormant/internal code: `app.agent.carapaces`, file-sync carapace loading, bot/channel ORM fields, admin helper previews, integration admin metadata, and legacy docs/tests. Those still need a dedicated deletion pass before storage/migration cleanup.
- Follow-up deletion pass removed the dead agent stack outright: `app/agent/carapaces.py`, `app/agent/capability_rag.py`, and `app/agent/capability_session.py` were deleted after rewriting `tests/integration/test_context_assembly.py` to drop obsolete capability assertions and stale patch points.
- The same pass deleted pure-carapace e2e/unit surfaces (`tests/e2e/scenarios/test_carapaces_crud.py`, `tests/unit/test_effective_tools_activation.py`) and trimmed mixed e2e/API/workflow tests so they no longer assert `/admin/carapaces`, `activate_capability`, or `execution_config.carapaces`.
- Verification for that pass: `pytest tests/unit/test_step_executor.py -q -k execution_config` passed (`1 passed`), `pytest tests/unit/test_workflow_tool.py -q -k include_definitions` returned `2 skipped, 16 deselected`, `python -m py_compile` across the edited test files passed after fixing an indentation slip in `test_context_assembly.py`, and `rg` now returns no remaining `app.agent.carapaces` / `capability_rag` / `capability_session` imports in `app/` or `tests/`.
- The remaining tail is now storage- and contract-oriented rather than runtime-oriented: `Bot.carapaces`, `Channel.carapaces_extra` / `carapaces_disabled`, the `carapaces` ORM/table, stale e2e cleanup hooks, and several old tests that still encode carapace IDs as data or schema fields.

## Phase 4 channel half — DONE 2026-04-14
Dropped `skills_disabled` and `skills_extra` columns (migration 195). Remaining channel-level overrides (`local_tools_disabled`, `mcp_servers_disabled`, `client_tools_disabled`, `carapaces_disabled`, `carapaces_extra`) are still active — they control tool/carapace availability, not skills.

## Key invariants (current state)
- **Skills table** is a managed document store: name + description + content + triggers
- **Bot-authored skills may carry named `run_script` snippets** — stored separately in `skills.scripts`, managed via `manage_bot_skill` script CRUD, executed through `run_script(skill_name=..., script_name=...)`
- **Bot-authored skills** stay (agents writing reference docs for themselves is good)
- **`get_skill()` / `get_skill_list()`** are auto-injected for all bots
- **Enrolled skills are ranked per-turn** — RAG as ranker, not filter (all enrolled stay visible)
- **Top-match auto-inject** — highest-confidence enrolled skill injected as synthetic tool call/result pairs with `_no_prune`
- **Auto-inject tracking is separate from fetch tracking** — `auto_inject_count` vs `surface_count`/`fetch_count`
- **Capability RAG discovery is being removed** — do not build new product behavior on top of it
- **`activate_capability` is being removed** — use skill/tool discovery + enrollment only
- **Tool RAG + tool enrollment** — semantic tool discovery + persistent working set (mirrors skill enrollment)
- **Per-bot working set** is the canonical assignment surface — manual prune via UI, hygiene loop curation, on-fetch promotion via `get_skill()`
- **Channel `skills_extra` / `skills_disabled` are dead** — UI doesn't read them; do not add new code that does
- **Channel capability UI is dead** — replace it with channel-level skill enrollment, not a new package layer

## What we killed
- Pinned skill mode (Phase 2)
- Skills as a carapace YAML field — both core + integration carapaces (Phase 1 + Phase 1.5)
- The runtime merge that flowed `carapace.skills` into `bot.skills` per turn (Phase 1.5)
- The `Carapace.skills` DB column (migration 187, Phase 1.5)
- Skills as a bot config field (Phase 5)
- Per-turn ephemeral auto-enrollment of core + integration skills (Phase 3 — replaced by persistent `bot_skill_enrollment`)
- `SharedWorkspace.skills` JSONB column (Phase 4 workspace half)
- `retrieve_context()` chunk-injection (Phase 3.0 — orphaned by `45721f47`, then removed)
- `source_type` branching in context assembly (Phase 4 — keep field for provenance, stop branching)

## References
- [[Architecture Decisions#Per-Bot Persistent Skill Working Set]] — the design and the reasoning
- [[Architecture Decisions#Conditional Auto-Enrollment on Workspace Join]] — workspace bot pattern
- [[Architecture Decisions#Self-Improvement Awareness in Base Prompt]] — why bots author skills
- [[How Discovery Works]] — runtime discovery pipeline
- `app/services/skill_enrollment.py` — service layer
- `app/db/models.py` — `BotSkillEnrollment` ORM
- `migrations/versions/184_add_bot_skill_enrollment.py` — schema + backfill
- `migrations/versions/185_drop_shared_workspace_skills.py` — workspace half cleanup
