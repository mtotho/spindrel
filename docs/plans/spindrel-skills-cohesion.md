---
title: Spindrel runtime skills — cohesion cleanup + two track stubs
summary: Mechanical cleanup of runtime-skill drift, including deleted audit pipelines with DB cleanup, stale skill text, missing safety rules, widget wording, and two follow-up track stubs.
status: executed
tags: [spindrel, plan, skills, runtime, cleanup, orchestrator, docs]
created: 2026-05-03
updated: 2026-05-03
executed: 2026-05-03
---

> **Executed 2026-05-03.** Mechanical cleanup steps 1–8 landed as described
> below. Two follow-up tracks were stubbed: [[orchestrator-dissolution]] and
> [[bot-readable-docs]] (rows added to `docs/roadmap.md`). Migration
> `296_drop_demoted_audit_pipelines` deletes the seeded `Task` rows for the
> four removed pipeline slugs on existing instances. Verification: see the
> `## Verification` section — all checks pass except pre-existing test
> collection/fixture failures in `tests/unit/test_get_skill.py`,
> `tests/unit/test_manage_bot_skill.py::TestSkillNudge`,
> `tests/unit/test_tool_discovery.py::TestCoreSkillAutoEnrollment`, and
> `tests/unit/test_tool_schema_backfill_*` that are unrelated to this work
> (they reference missing prompt sections / missing test DB tables / MagicMock
> JSON-serialization issues that pre-date this change).

# Spindrel runtime skills — cohesion cleanup + two track stubs

## Context

A high-level audit of the runtime `skills/` tree against `app/config.py` base prompts and the recently standardized repo-dev workflow (`.spindrel/WORKFLOW.md`, `.agents/skills/agentic-readiness/`) surfaced three classes of issue:

1. **Mechanical defects** — one skill with broken frontmatter (`workspace/notes.md`); a single stale "use workflows" line in `orchestrator/index.md`; an audits skill recommending four pipelines that the roadmap explicitly demoted; a rule that lives in `DEFAULT_SKILL_REVIEW_PROMPT` (config.py:254) but not in the canonical `skill_authoring` skill; "Phase B" wording in the widgets cluster for SDK/handler features that have shipped.
2. **An identity-level decision** — the user wants the "orchestrator" concept retired so any default bot is capable. The `skills/orchestrator/` cluster, the seeded `orchestrator` system bot (`app/data/system_bots/orchestrator.yaml` + `_ensure_orchestrator_bot_exists()` in `app/services/channels.py:514–590` + the `orchestrator:home` channel), and the `orchestrator.*` pipeline-slug prefix all anchor that concept and need coordinated removal — too big for this plan, hence stubbed as a track.
3. **An infrastructure gap** — bots cannot read `/app/docs/` today. `get_skill` reads the skill DB; `file()` is workspace-scoped; `docs/` is copied into the container but exposed nowhere to runtime bots. Until this is closed, demoting reference-manual skills (`widgets/sdk.md` at 639 lines, `widgets/styling.md` at 384, `pipelines/authoring.md` at 540) to docs would strand them. Stubbed as a track.

User decisions captured upfront:

1. Execute the mechanical defects in this plan; stub the orchestrator and wiki tracks as `docs/tracks/<slug>.md` files for later slices.
2. Orchestrator track direction: delete the seeded orchestrator system bot entirely; redistribute the `skills/orchestrator/*` content into peer skills/clusters; rename `orchestrator.analyze_discovery` pipeline slug; drop the orchestrator routing hint from `DEFAULT_GLOBAL_BASE_PROMPT`.
3. Wiki track direction: do not pick the implementation depth now; lay out the three options (cheap mirror, medium `get_doc` tool, deep RAG ingest) and the dependency that demotion of oversized skills is blocked on this track.
4. Demoted audit pipelines: delete them outright, including existing seeded DB rows on this single-user instance. Remove `orchestrator.analyze_skill_quality`, `orchestrator.analyze_memory_quality`, `orchestrator.analyze_tool_usage`, and `orchestrator.analyze_costs`; keep only `orchestrator.analyze_discovery`; redirect the rest of `orchestrator/audits.md` to the configurator skill + `propose_config_change`.

## Out of scope (handled by the stubbed tracks)

- Redistribution of `skills/orchestrator/*` content into `delegation.md`, `context_mastery.md`, `configurator/integration.md`, `workspace/api_reference.md` (new), etc. — orchestrator track.
- Deletion of `app/data/system_bots/orchestrator.yaml`, removal of `_ensure_orchestrator_bot_exists()`, removal of the `orchestrator:home` channel auto-creation, renaming `orchestrator.analyze_discovery`, updating `docs/setup.md` / `docs/guides/delegation.md` orchestrator language, updating `app/config.py:383–384` to drop the orchestrator routing hint — orchestrator track.
- Picking the wiki implementation depth (mirror vs `get_doc` tool vs RAG ingest), demoting oversized reference-manual skills, designing read-only protections — wiki track.
- Cluster-index "open with a first action" rewrites for `planning/`, `history_and_memory/`, `agent_readiness/`, `widgets/` — folded into the orchestrator track because most of the worst offenders are orchestrator-cluster indices that the dissolution will touch anyway.

## Approach

### 1. Fix `skills/workspace/notes.md` frontmatter

The file uses doc-frontmatter (`title`/`summary`/`status`/`tags`) instead of skill-frontmatter (`name`/`description`/`triggers`/`category`). It will not RAG-index correctly, will not surface from `get_skill`, will not render in the catalog UI like its siblings. Replace lines 1–6 with the standard skill schema. Description should lead with "Use when…". Triggers comma-separated per `skill_authoring.md`.

**File:** `skills/workspace/notes.md`

### 2. Strike the "use workflows" line in `skills/orchestrator/index.md`

Workflows are deprecated per `docs/roadmap.md` ("**DEPRECATED** — superseded by task pipelines. UI hidden, backend dormant"). The orchestrator index still says "Use workflows for repeatable multi-step operations" at line 35; the same file's Tool Selection table already correctly recommends `define_pipeline`. Delete line 35 outright; the routing concern is already covered by `pipelines/creation`.

**File:** `skills/orchestrator/index.md:35`

### 3. Delete the demoted audit pipelines and rewrite `audits.md`

The roadmap states "Bot Audit Pipelines | demoted 2026-04-20 | Only `analyze_discovery` featured; configurator skill + `propose_config_change` replaces ambient config-fix." Delete the four demoted pipeline YAMLs from `app/data/system_pipelines/`:

- `orchestrator.analyze_skill_quality.yaml`
- `orchestrator.analyze_memory_quality.yaml`
- `orchestrator.analyze_tool_usage.yaml`
- `orchestrator.analyze_costs.yaml`

Deleting YAML is not enough on an existing install: `app/services/task_seeding.py` inserts and refreshes YAML-backed `Task` rows, but it does not delete rows when a YAML file disappears. Add an explicit DB cleanup step in this slice:

- Delete `tasks` rows whose deterministic IDs are `pipeline_uuid(<slug>)` for the four deleted slugs above.
- Let existing `channel_pipeline_subscriptions` rows cascade via their `task_id` FK, or delete them first if the target DB requires it.
- Keep historical child runs if FK constraints allow that cleanly; if not, document the chosen cascade behavior in the migration/script.

Preferred implementation for repo safety: add a tiny Alembic migration that deletes the four system pipeline definition rows by UUID. This makes fresh deploys and this existing single-user DB converge. If the executor chooses a one-off admin cleanup instead, record the command in the run receipt and still add a unit/integration test that the deleted slugs are unavailable.

Also update the LLM-facing pipeline tool text. `app/tools/local/pipelines.py` currently hardcodes example system pipeline names in the `list_pipelines` tool description. That text is only help text for the model, not the source of truth, but stale examples cause bots to ask for deleted pipelines. Remove the four deleted names from that description, or better, replace the named list with generic wording that says to call `list_pipelines(source="system")`.

Update stale durable docs in the same pass:

- `docs/tracks/automations.md` currently says the demoted YAMLs stay on disk. Replace that sentence with a short note that they were later deleted by this cleanup because the single-user operator no longer wants them runnable.

Rewrite `skills/orchestrator/audits.md`:

- Keep only the `analyze_discovery` row in the decision table.
- Replace the other four rows with a single pointer: *"For 'skills feel stale' / 'context is bloated' / 'tool X never used' / 'this is too expensive' → use the configurator skill (`propose_config_change`)."*
- Update the body so audit pipelines are no longer presented as the primary path.

**Files:** the four YAMLs + DB cleanup migration/script + `app/tools/local/pipelines.py` + `skills/orchestrator/audits.md` + `docs/tracks/automations.md` + any registry/test that names the deleted slugs.

### 4. Add the catalog-skill-deletion rule to `skill_authoring.md`

`DEFAULT_SKILL_REVIEW_PROMPT` (config.py:254) tells the bot: *"Do not call `manage_bot_skill(action=\"delete\")` on catalog skills you don't own — that archives the skill itself, not just your enrollment."* The canonical `skills/skill_authoring.md` does not carry this rule. The prompt only fires during scheduled skill-review tasks; a bot reading just the skill won't see it.

Add a row to "Common Mistakes" (around line 184) and a `### Pruning vs deletion` subsection in the Lifecycle area (around line 117–129). Cite the prompt's exact phrasing so the two stay aligned.

**File:** `skills/skill_authoring.md`

### 5. Strip "Phase B" / "coming soon" framing in widgets cluster

The Widget SDK roadmap row says "A + B.0–B.6 shipped" — Phase B is shipped. But `widgets/index.md:29` still says "(Phase B — see `handlers.md`)". Sweep with `rg -n "Phase [A-Z]|Phase \d|coming soon|planned|future|not yet|TODO" skills/widgets/`; remove parenthetical phase markers and "future work" framing for shipped capabilities. Don't touch genuine future-work mentions (if any remain).

**Files:** `skills/widgets/*.md` — confirmed at `widgets/index.md:29`; sweep the rest.

### 6. Mirror `STARTER_SKILL_IDS` in `skills/index.md`

`STARTER_SKILL_IDS` at `app/config.py:484–496` is the list of 11 skills every bot starts with. `skills/index.md:42–48` mentions a "Starter set" but doesn't list the IDs and doesn't reference the constant — a bot reading the catalog can't tell what it already has. Add a short section listing the 11 IDs and pointing at the constant.

**File:** `skills/index.md`

### 7. Stub `docs/tracks/orchestrator-dissolution.md` (track stub, not execution)

Frontmatter `status: active`. Goal: any default bot is capable; no special system bot owns coordination.

**Decision recorded at top:** delete the seeded orchestrator entirely.

Phase table (stub only — execution comes in later slices):

1. **Skill content redistribution.** Map every section of `skills/orchestrator/{index,audits,integration_builder,model_efficiency,workspace_api_reference,workspace_delegation,workspace_management}.md` to a destination, using the inventory captured during the audit:
   - `index.md` — tool-selection table → `delegation.md`; persistence model → `context_mastery.md`; scheduling → `delegation.md` or `automation/`.
   - `audits.md` — after step 3 above only has `analyze_discovery`. Move that row to `diagnostics/audits.md` (new) or fold into `diagnostics/index.md`.
   - `integration_builder.md` → `configurator/integration.md` (extend) or new `skills/integration_authoring.md`.
   - `model_efficiency.md` → new section in `delegation.md`.
   - `workspace_api_reference.md` → new `skills/workspace/api_reference.md`.
   - `workspace_delegation.md` → merge into `delegation.md` (`run_claude_code`, fan-out patterns, common mistakes table).
   - `workspace_management.md` — channels → `workspace/channel_workspaces.md`; memory writes → `context_mastery.md`; secrets → `prompt_injection_and_security.md` or new skill.
2. **System bot deletion.** Remove `app/data/system_bots/orchestrator.yaml`. Remove `_ensure_orchestrator_bot_exists()` and its call site in `app/services/channels.py:514–590`. Remove the `orchestrator:home` channel auto-creation. Add a one-shot migration to soft-delete the seeded bot row on existing instances (or document that the orphaned row is harmless).
3. **Pipeline-slug rename.** Rename `orchestrator.analyze_discovery` → `audit.analyze_discovery` (or `bot.analyze_discovery`) in `app/data/system_pipelines/`, in `skills/diagnostics/traces.md:4`, and any other call site. Update slug-prefix logic in `app/tools/local/pipelines.py` if present.
4. **Base-prompt rewrite.** Update `app/config.py:383–384` from "If something is outside your scope, suggest the user ask the orchestrator" to a generic surface-it-to-the-user phrasing. Update `docs/setup.md` and `docs/guides/delegation.md` to drop "orchestrator" as a named role.
5. **Cluster-index polish.** While the dissolution touches several index files anyway, fold in the "open with a first action" rewrite for `planning/index.md`, `history_and_memory/index.md`, `agent_readiness/index.md`, `widgets/index.md` — adopt the `configurator/index.md` and `project/index.md` shape.
6. **Catalog cleanup.** Delete `skills/orchestrator/` directory. Update `skills/index.md:22` to drop the orchestrator cluster row.

**Risks:** orchestrator bot may be referenced in user data (channels, tasks, traces) on existing instances — phase 2 handles that gracefully.

Add an `Active` row to `docs/roadmap.md`:

> | Orchestrator dissolution | started 2026-05-03 | Retire the orchestrator system bot and `skills/orchestrator/` cluster so any default bot is capable. Pipelines, base prompt, and seeded bot all need coordinated removal. | [[orchestrator-dissolution]] |

**Files:** `docs/tracks/orchestrator-dissolution.md` (new), `docs/roadmap.md`.

### 8. Stub `docs/tracks/bot-readable-docs.md` (track stub, not execution)

Frontmatter `status: active`. Goal: give runtime bots a way to read repo docs (`/app/docs/` in container) so canonical contributor guides are reachable from a bot turn — currently they are not.

Phase table (stub only):

1. **Pick depth.** Three options identified during audit:
   - **Cheap** — mirror `/app/docs/` into `/workspace/common/docs/` at boot, reuse the existing `file()` tool. ~10 lines in entrypoint.
   - **Medium** — new `get_doc(path)` + `list_docs(area)` tool pair, ~100 lines, mirroring `get_skill` (read pipeline at `app/agent/skills.py:17–146` and `app/tools/local/skills.py:63–142`). Read-only by design.
   - **Deep** — ingest `docs/` into RAG via a new scope in `app/services/bot_indexing.py:53–76` so docs surface in semantic discovery alongside skills.
   - Recommend medium as the default — read-only by design, namespaced separately, no RAG cost. Defer the actual choice to the track's first slice.
2. **Implement chosen mechanism.** Add tool(s); register in the tool catalog; add unit tests; advertise via the runtime base prompt or a small new skill (`skills/internal_docs.md`).
3. **Demote oversized reference-manual skills.** Once the mechanism exists, demote: `widgets/sdk.md` (639 lines, SDK reference), `widgets/styling.md` (384, CSS class catalog), `widgets/html.md` (353, bundle layout reference), `pipelines/authoring.md` (540, schema reference), `orchestrator/workspace_api_reference.md` (90, API reference; will already be moved by orchestrator track). Each demotion: move the body to `docs/reference/<area>-<topic>.md`, leave a 30–50 line procedural skill that links to the doc using the new mechanism.
4. **Sweep widget descriptions.** Twelve widget skills have frontmatter `description` over 280 chars (worst: `widgets/errors.md` at 553). Trim to ~200; push detail to body. Independent of the wiki mechanism — could land earlier.

**Constraint:** demotion phase is blocked on phase 1+2. Without the mechanism, demoting strands content. The track row should make this dependency explicit.

Add an `Active` row to `docs/roadmap.md`:

> | Bot-readable internal docs | started 2026-05-03 | Give runtime bots a way to read `/app/docs/` so canonical guides are reachable. Unblocks demoting oversized reference skills (`widgets/sdk`, `pipelines/authoring`, etc.) without stranding content. | [[bot-readable-docs]] |

**Files:** `docs/tracks/bot-readable-docs.md` (new), `docs/roadmap.md`.

## Critical files (execute-now)

| Path | Action |
|---|---|
| `skills/workspace/notes.md` | Rewrite frontmatter to skill schema |
| `skills/orchestrator/index.md:35` | Delete the "Use workflows" line |
| `skills/orchestrator/audits.md` | Rewrite to keep only `analyze_discovery`; redirect rest to configurator |
| `app/data/system_pipelines/orchestrator.analyze_{skill_quality,memory_quality,tool_usage,costs}.yaml` | Delete |
| Alembic migration or explicit cleanup script | Delete existing DB `tasks` rows for the four removed system pipeline definitions |
| `app/tools/local/pipelines.py` | Remove hardcoded examples for the deleted pipelines from tool descriptions |
| `skills/skill_authoring.md` | Add catalog-skill-deletion rule + Pruning-vs-deletion subsection |
| `skills/widgets/index.md:29` (and any other Phase-B mention) | Strip "Phase B" framing |
| `skills/index.md` | Mirror `STARTER_SKILL_IDS` |
| `docs/tracks/orchestrator-dissolution.md` | Create (track stub, not execution) |
| `docs/tracks/bot-readable-docs.md` | Create (track stub, not execution) |
| `docs/roadmap.md` | Add two `Active` rows linking the new tracks |
| `docs/tracks/automations.md` | Update stale 2026-04-20 note that said demoted YAMLs stay on disk |

## Reuse / no new mechanism

- Skill frontmatter format: existing schema in `skills/skill_authoring.md`.
- Track contract: `docs/guides/tracks.md` — both stubs follow it.
- Plan home and roadmap rules: `.spindrel/WORKFLOW.md`.
- Pipeline catalog source files live in `app/data/system_pipelines/`; existing DB rows need explicit cleanup because the seeder does not tombstone deleted YAML.
- No new runtime mechanism lands in this plan. The only code-like change should be the DB cleanup migration/script and stale tool-description cleanup.

## Verification

After execute-now:

1. **Frontmatter parses** — `python -c "import yaml; print(yaml.safe_load(open('skills/workspace/notes.md').read().split('---')[1]))"` returns a dict with keys `name`, `description`, `triggers`, `category`.
2. **Targeted stale-reference grep is clean** — `rg -n "Use workflows for repeatable multi-step operations|Phase B — see" skills/` returns zero hits. Do not require all historical or genuine future-work "Phase B" mentions to disappear.
3. **Pipeline source removal** — `ls app/data/system_pipelines/ | grep -E "orchestrator\\.analyze_(skill_quality|memory_quality|tool_usage|costs)\\.yaml"` returns empty.
4. **Runtime references to deleted pipelines are gone** — `rg -n "orchestrator\\.analyze_(skill_quality|memory_quality|tool_usage|costs)|analyze_skill_quality|analyze_memory_quality|analyze_tool_usage|analyze_costs" app skills tests --glob '!app/static/**'` returns no live references except tests deliberately asserting deletion behavior.
5. **Skill rule is in the canonical file** — `rg -n "do not.*delete.*catalog|catalog skill.*delete" skills/skill_authoring.md` matches.
6. **Deleted pipelines are unavailable** — add/update tests so `list_pipelines(source="system")` omits the four deleted slugs and `run_pipeline("orchestrator.analyze_memory_quality")` returns "not found" after the cleanup.
7. **Tests still green** — `. .venv/bin/activate && PYTHONPATH=. pytest tests/unit/ -q -k "skill or pipeline"` passes, plus the focused pipeline seeding/listing tests touched by this cleanup.
8. **Track rendering** — `docs/tracks/orchestrator-dissolution.md` and `docs/tracks/bot-readable-docs.md` parse with the standard frontmatter; new roadmap rows resolve to them.
9. **No accidental orchestrator dissolution** — this slice may edit `skills/orchestrator/index.md` and `skills/orchestrator/audits.md`, but must not delete the seeded orchestrator bot, rename `orchestrator.analyze_discovery`, or remove `skills/orchestrator/`; that belongs to the new track.

If any verification step fails, stop and report — do not patch around.

## Related

- `.spindrel/WORKFLOW.md` — durable artifact homes; plans live in `docs/plans/`.
- `docs/guides/tracks.md` — track contract for the two new stubs.
- `app/config.py` — base prompts referenced throughout.
- `skills/skill_authoring.md` — canonical skill-authoring contract.
- `docs/roadmap.md` — two new `Active` rows added in step 7 and 8.
