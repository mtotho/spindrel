---
tags: [agent-server, track, skills, simplification]
status: complete
updated: 2026-04-21
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
- **Capability RAG discovery** continues — semantic matching to suggest capabilities
- **`activate_capability`** runtime activation with approval continues
- **Tool RAG + tool enrollment** — semantic tool discovery + persistent working set (mirrors skill enrollment)
- **Capability composition** (`includes`) — reusable bundles
- **Per-bot working set** is the canonical assignment surface — manual prune via UI, hygiene loop curation, on-fetch promotion via `get_skill()`
- **Channel `skills_extra` / `skills_disabled` are dead** — UI doesn't read them; do not add new code that does

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
