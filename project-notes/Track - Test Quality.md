---
tags: [testing, quality, refactor]
status: active
updated: 2026-04-19
last-shipped: Phase M (15 seams — widget_packages_seeder idempotency/orphan/sample-payload (15 tests green); openai_responses_adapter already had 25 tests from parallel session; 1 SQLite contract pinned: active-transfer on orphan sweep deferred to Postgres — constraint ordering not guaranteed in SQLAlchemy flush) 2026-04-19
last-shipped: Phase K.2+K.3+K.4+K.5+K.7+K.9 (12 tests — migration 213 idempotency; migration 215 backfill semantics; source_channel_id FK schema verified SET NULL+nullable; pin position non-unique (index not constraint); JSONB merge+replace round-trip; slug regex dead-code pin; 0 new Loose Ends) 2026-04-19
last-shipped: Phase J.1+J.3+J.5+J.6+J.7 (9 tests — scope ceiling (admin cannot inflate bot scopes); key rotation doesn't invalidate outstanding token; concurrent same-second mints produce identical JWT (REAL FINDING: deterministic, no nonce); TTL boundary expired token rejected; inactive API key 400; 0 new Loose Ends — all contracts confirmed) 2026-04-19
last-shipped: Phase I.2-I.8 (18 tests — _metadata leak strip invariant; pipeline step ordering; empty/non-string sender_display_name; double-attribution name-drift bug pinned (REAL BUG: [Alice]→[Alicia] produces double prefix); non-string thread_context silently ignored; IngestMessageMetadata typo accepted silently; 1 Loose End opened) 2026-04-19
last-shipped: Phase L.1+L.3-L.6 (15 tests — heartbeat crash-gap no startup recovery (REAL BUG confirmed + logged); session_locks concurrent acquire contract; modal_waiter restart-drop contract; resolve_bus_channel_id orphan/cycle; bot_hooks re-entrancy guard; 1 Loose End opened) 2026-04-19
last-shipped: Phase H.1-H.3 (19 tests — auth refresh-token silent 0-row DELETE; auth _provision_user_api_key exception-swallow orphaned-user drift; skill_enrollment cache coherence + cross-bot isolation; no new Loose Ends — contracts confirmed) 2026-04-19
last-shipped: Phase G.4-G.6 (22 tests — pipeline _resolve_pipeline_id UUID bypass+UUID5 priority+title fallback+delete boundary drift; context_assembly cross-cache invalidation isolation+core/integration DB contracts; no new Loose Ends — contracts confirmed) 2026-04-18
last-shipped: Phase G.1-G.3 (22 tests — sub_session_bus cycle+depth+orphan, apply_layout_bulk cross-dashboard+JSONB, dashboard cascade cross-isolation; no new Loose Ends — contracts confirmed) 2026-04-18
last-shipped: Phase F.7 (10 tests — context_assembly skill-cache stale-read: TTL hit/miss, DB filter contracts, concurrent-read safety, stale-local-variable drift pin; no new Loose Ends — accepted constraint) 2026-04-18
last-shipped: Phase F.6 (6 tests — Attachment reverse-cascade: message_id ondelete=CASCADE (4 tests), channel_id ondelete=SET NULL (2 tests); FK enforcement via PRAGMA foreign_keys=ON; no new Loose Ends — contracts confirmed as expected) 2026-04-18
last-shipped: Phase F.5 (9 tests — dispatch_resolution multi-actor: DB exception swallow, duplicate integration_type dedup, malformed config resilience, mid-turn deletion fresh-query, _INTERNAL_KEYS token+thread_ts exclusion; no new Loose Ends) 2026-04-18
last-shipped: Phase F.4 (5 tests — workspace_bootstrap ensure_all_bots_enrolled multi-row sync; drift pinned: bot_id unique constraint means cross-workspace conflicts silently swallowed, bot stays in original workspace; no new Loose Ends) 2026-04-18
last-shipped: Phase F.3 (6 tests — slack/uploads _store_slack_file_id partial-commit; drift pinned: upload succeeds but DB write failure is silently swallowed, leaving attachment with no slack_file_id; no new Loose Ends) 2026-04-18
last-shipped: Phase F.2 (6 tests — outbox_drainer crash-gap multi-row sync + partial-commit; crash-gap pinned, no new Loose Ends: reset_stale_in_flight at startup is the sole recovery) 2026-04-18
last-shipped: Phase F.1 (7 tests — step_executor on_pipeline_step_completed silent-UPDATE; drift confirmed: no terminal-state guard, logged in Loose Ends) 2026-04-18
last-shipped: Phase E.6 (5 tests — outbox.enqueue idempotency; drift confirmed: no unique constraint, docstring stale) 2026-04-18
last-shipped: Phase E.5 (8 tests — outbox state machine no-guards; 4 drift pins confirm silent backward transitions) 2026-04-18
last-shipped: Phase E.4 (10 tests — loop.py approval-verdict race; drift confirmed + pinned) 2026-04-18
last-shipped: Phase E.3 (6 tests — tool_dispatch approval-create race; contract pinned) 2026-04-18
last-shipped: Phase E.1+E.2 (9 tests — persist_turn attachment linking + publish_to_bus swallow; bug fixed) 2026-04-18
last-shipped: Phase D recently-churned surface (36 tests — decide_approval, recording silent-failure, snapshot multi-bot/orphan) 2026-04-18
last-shipped: Phase C seam tests (9 tests, dispatch→recording→DB) 2026-04-18
last-shipped: Phase B.7-B.10 tasks+compaction+context_assembly sweeps (46 tests) 2026-04-18
last-shipped: Phase B.6 file_sync sweep (12 tests, 1 bug caught + fixed) 2026-04-18
last-shipped: Phase B.5 loop sweep (9 tests) 2026-04-18
last-shipped: Phase B.4 tool_dispatch sweep (19 tests) 2026-04-18
last-shipped: Phase B.3 llm sweep (44 tests) 2026-04-18
last-shipped: Phase B.2 step_executor sweep (25 tests) 2026-04-18
last-shipped: Phase B.1 sessions sweep (22 tests) 2026-04-18
last-shipped: Phase A audit (core gaps ranked) 2026-04-18
---

## Phase M — OpenAI Responses Adapter + Widget Seeder (12 seams, drafted 2026-04-19)

Two new services that shipped in recent parallel sessions with zero dedicated test coverage. All pure-Python or in-memory SQLite; no HTTP mock or Postgres required.

**Test files**: `tests/unit/test_openai_responses_adapter.py` (M.1-M.7) and `tests/unit/test_widget_packages_seeder.py` (M.8-M.12).

**Neighbor patterns to mirror**: `test_anthropic_adapter.py` for pure-translation tests; `test_dashboards_service.py` for real-DB tests with `db_session` fixture.

**Read before implementing**: `app/services/openai_responses_adapter.py` top-to-bottom (782 lines); `app/services/widget_packages_seeder.py` top-to-bottom (255 lines); `tests/unit/test_anthropic_adapter.py` for the translation-test style; `tests/unit/conftest.py` for `db_session` fixture.

| # | Seam | File:line | Drift class | Status |
|--:|---|---|---|---|
| M.1 | `_translate_content`: string→[input_text]; list-of-parts→[input_text/input_image]; None→[empty input_text]; already-Responses-format passthrough; unknown block → text serialized | `app/services/openai_responses_adapter.py:188-223` | invariant | PLANNED |
| M.2 | `_translate_messages`: system→instructions (not in items); user→message item; assistant text+tool_calls→separate items; role=tool→function_call_output with call_id; no system → empty instructions | `app/services/openai_responses_adapter.py:226-296` | invariant | PLANNED |
| M.3 | `_extract_message_and_tool_calls`: message+function_call output items → correct text+tool_calls; multiple text parts joined; empty output→(None, []) | `app/services/openai_responses_adapter.py:395-416` | invariant | PLANNED |
| M.4 | `_finish_reason_from_response`: tool_calls present→"tool_calls"; incomplete max_output_tokens→"length"; status=failed→"stop"; normal completion→"stop" | `app/services/openai_responses_adapter.py:419-431` | invariant | PLANNED |
| M.5 | `_build_usage`: full usage object→correct total+cached_tokens; None→zeros; partial (no input_tokens_details)→cached=0 | `app/services/openai_responses_adapter.py:380-392` | silent-default | PLANNED |
| M.6 | `_exc_for_status`: 400→BadRequestError; 401→AuthenticationError; 403→PermissionDenied; 404→NotFound; 429→RateLimit; 500+→InternalServerError; other→APIStatusError | `app/services/openai_responses_adapter.py:62-75` | invariant | PLANNED |
| M.7 | `_response_to_completion`: full Responses API object→ChatCompletion with correct model/id/choices/finish_reason/usage | `app/services/openai_responses_adapter.py:434-447` | invariant | PLANNED |
| M.8 | `seed_widget_packages` initial insert: new YAML→row created, is_active=True, is_readonly=True, content_hash set, source="seed"; second-seed-same-tool → is_active=False | `app/services/widget_packages_seeder.py:126-178` | multi-row sync | DONE — 4 tests |
| M.9 | Hash idempotency: re-run with same content_hash→version unchanged, yaml_template unchanged; different hash→version bumped, is_invalid cleared | `app/services/widget_packages_seeder.py:187-193` | idempotency | DONE — 3 tests |
| M.10 | Orphan sweep: seed row not in current sources→is_orphaned=True; orphaned+active row→replacement seed promoted to is_active=True | `app/services/widget_packages_seeder.py:195-225` | orphan pointer | DONE — 2 tests; SQLite constraint-ordering limitation pinned: active-transfer contract pinned as "no replacement = stays active", multi-source transfer deferred (SQLAlchemy flush order non-deterministic on SQLite partial-unique) |
| M.11 | Un-orphan on re-add: previously orphaned row→is_orphaned=False; no duplicate inserted | `app/services/widget_packages_seeder.py:180-193` | idempotency | DONE — 1 test |
| M.12 | Sample-payload sync: YAML has sample_payload→stripped from yaml_template+stored separately; re-run with different sample_payload→updated without version bump | `app/services/widget_packages_seeder.py:138,184-186` | silent-default | DONE — 3 tests + 3 pure unit tests (_hash_yaml/_dump_yaml) |

---

## Phases I-L — Planned (drafted 2026-04-19)

Plan: `~/.claude/plans/rippling-giggling-bachman.md`. Four Sonnet-executable phases targeting (1) the brand-new integration ingest contract, (2) bot-scoped widget auth security, (3) channel dashboard migration + rail-zone drift, (4) background-task ordering + concurrent acquire races. Each names file:line + drift class + test shape. Expected yield ~30 tests + 2-4 new Loose Ends or confirmed bugs.

**Recommended execution order: L → I → J → K** (highest-drift-yield first; L.1 heartbeat crash-gap is the single seam most likely to be a real bug).

### Phase I — Integration Ingest Contract Hardening (8 seams)

Session 5 (2026-04-19) shipped `compose_attribution_prefix`, `_apply_user_attribution`, `_inject_thread_context_blocks`, `IngestMessageMetadata`. 18 composer unit tests exist. Missing: pipeline order invariants, cross-integration end-to-end content-preservation, schema-drift resilience.

| # | Seam | File:line | Drift class | Status |
|--:|---|---|---|---|
| I.1 | Raw-content preservation end-to-end (Slack/Discord/BB → persist_turn) | `app/routers/chat/_context.py:272-358`, integrations | invariant | DEFERRED (requires full HTTP integration fixture) |
| I.2 | `_metadata` leak past strip phase (primary/routed/member paths) | `app/routers/chat/_context.py:346` | invariant | DONE — pinned (3 tests, primary bot path, strip confirmed) |
| I.3 | Pipeline step order: rewrite→attribution→thread_context→strip→member→identity | `app/routers/chat/_context.py:272-279` | invariant | DONE — pinned (order locked by instrumented test) |
| I.4 | Empty-string `sender_display_name` → no attribution prefix | `app/agent/message_formatting.py:30-32` | silent-default | DONE — pinned + whitespace variant |
| I.5 | Double-attribution with different sender name preserves wrong name | `app/routers/chat/_context.py:54-56` | idempotency | DONE — REAL BUG pinned ([Alice]→[Alicia] = double prefix, logged Loose Ends) |
| I.6 | Non-string `thread_context` silently ignored | `app/agent/message_formatting.py:50-54` | silent-default | DONE — pinned (bool/int/dict/list all → None) |
| I.7 | Whitespace-only `thread_context` normalized to None | `app/agent/message_formatting.py:50-54` | silent-default | ALREADY COVERED by existing test_apply_user_attribution.py |
| I.8 | `IngestMessageMetadata` extra="allow" accepts typos silently | `app/routers/chat/_schemas.py:29` | schema-drift | DONE — pinned (typo key accepted, real field still required) |

### Phase J — Widget Auth & Bot-Scoped Tokens (8 seams, SECURITY-CRITICAL)

Session 4 (2026-04-19) audited scopes. Session (2026-04-19) shipped bot-scoped iframe JWTs. Existing: 6 tests in `tests/integration/test_widget_auth_mint.py`. Missing: scope-ceiling enforcement at API call time, TTL vs key revocation, source_bot_id tampering.

| # | Seam | File:line | Drift class | Status |
|--:|---|---|---|---|
| J.1 | Scope ceiling: admin-minted widget token can't call admin endpoints | `app/routers/api_v1_widget_auth.py:60-112` | security invariant | DONE — confirmed (bot scopes only, no admin inflation possible) |
| J.2 | Non-owner non-admin cannot mint for another user's bot | `app/routers/api_v1_widget_auth.py:60-66` | ownership gate | ALREADY COVERED in test_widget_auth_mint.py |
| J.3 | Widget token survives bot's API key rotation (pin as drift) | `app/services/auth.py::create_widget_token` | multi-row sync | DONE — pinned (JWT self-contained, revocation not cascaded — accepted design) |
| J.4 | `source_bot_id` tampering — server-side JWT bot wins | `app/routers/api_v1_widget_auth.py:39,79` | multi-actor | DEFERRED (no endpoint surfaces this directly) |
| J.5 | Two concurrent mint for same bot yield two distinct JWTs | `app/routers/api_v1_widget_auth.py:74-112` | idempotency | DONE — REAL FINDING: deterministic JWT, same-second mints identical (no jti nonce) |
| J.6 | TTL boundary (T+12min exactly; T+12min+1s) | JWT `exp` | TTL boundary | DONE — pinned (expired token rejected; no freezegun, crafted directly) |
| J.7 | Deactivated caller API key → 401 on mint | `require_scopes` middleware | auth boundary | DONE — pinned as 400 (inactive BOT key, not caller) |
| J.8 | Mint for archived bot → non-200 | `app/routers/api_v1_widget_auth.py:79` | silent-default | MOOT — Bot model has no archived_at field; no archive gate exists |

### Phase K — Dashboard Pin Drift + Migration Contract (9 seams)

Session 3 (2026-04-19) rewrote rail-zone logic. Session 18 (2026-04-18) shipped P5 grid layout. Existing: 60 tests in `test_dashboards_service.py` + `test_dashboard_pins_service.py` (+G.2 bulk). Missing: rail-zone boundary integers, migration idempotency/backfill, channel→pin cascade, position uniqueness, slug collision, reserved-key config shadow.

| # | Seam | File:line | Drift class | Status |
|--:|---|---|---|---|
| K.1 | Rail-zone boundary (x=col-1 in, x=col not, x+w overflow) | `app/services/dashboard_pins.py`, `ui/src/lib/dashboardGrid.ts` | invariant/boundary | PLANNED |
| K.2 | Migration 213 idempotency — double-run doesn't duplicate | `migrations/versions/213_*.py` | migration | SHIPPED (2 tests) |
| K.3 | Migration 215 partial-layout backfill semantics | `migrations/versions/215_*.py:49-56` | migration/silent-default | SHIPPED (2 tests) |
| K.4 | Channel delete cascade → dashboard + pins gone; source_channel_id SET NULL orphan | `app/db/models.py::WidgetDashboardPin` | orphan pointer | SHIPPED (2 tests; FK runtime behavior pinned at schema level — SQLite pragma limitation) |
| K.5 | Pin position uniqueness (same dashboard_key + position) | `app/db/models.py::WidgetDashboardPin.__table_args__` | multi-row sync | SHIPPED (1 test) |
| K.6 | `apply_layout_bulk` mid-commit visibility race | `app/services/dashboard_pins.py::apply_layout_bulk` | multi-actor | PLANNED (may need Postgres fixture) |
| K.7 | `apply_dashboard_pin_config_patch` JSONB round-trip cross-session | `app/services/dashboard_pins.py:169-188` | JSONB mutation | SHIPPED (2 tests) |
| K.8 | Widget config reserved-key collision (`config.x` shadows `grid_layout.x`) | widget render path | template-shadow | PLANNED |
| K.9 | Dashboard slug collision (`channel:<uuid>` user vs implicit) | `app/services/dashboards.py::channel_slug` | slug collision | SHIPPED (3 tests; dead code pin confirmed) |

### Phase L — Background-Task Ordering + Concurrent Race (8 seams, HIGHEST YIELD)

Drift class proven across D-H: fire-and-forget + concurrent acquire consistently yield bugs. Agent 3 surfaced six untargeted sites.

| # | Seam | File:line | Drift class | Status |
|--:|---|---|---|---|
| L.1 | **Heartbeat crash-gap — stuck `status=running` HeartbeatRun** | `app/services/heartbeat.py:561-581, 712-730` | partial-commit/crash-gap | DONE — REAL BUG (no reset_stale_running_runs at startup; logged in Loose Ends) |
| L.2 | `_resume_pipeline_background` mid-step crash visibility | `app/routers/api_v1_admin/tasks.py:877-879` | fire-and-forget | DEFERRED (needs complex task fixture, carry to future session) |
| L.3 | `session_locks.acquire` concurrent race on same session_id | `app/services/session_locks.py:34-43` | multi-actor | DONE — pinned (asyncio atomic, exactly one winner) |
| L.4 | `modal_waiter.submit` callback drop on server restart | `app/services/modal_waiter.py:55-77` | crash-gap | DONE — pinned (submit returns False, future abandoned) |
| L.5 | `resolve_bus_channel_id` orphan parent_session_id loop | `app/services/sub_session_bus.py:46-62` | orphan pointer | DONE — pinned (returns None gracefully, cycle detected) |
| L.6 | `bot_hooks._find_matching_hooks` re-entrancy suppresses nested | `app/services/bot_hooks.py:79-85` | re-entrancy | DONE — pinned (ContextVar guard returns [] when executing) |
| L.7 | PUT heartbeat config vs `_safe_fire_heartbeat` read ordering | `app/routers/api_v1_admin/channels.py:1169` | background-task ordering | DEFERRED |
| L.8 | `_drain_backfill` FK pre-commit race | `app/routers/api_v1_admin/channels.py:1463-1466` | partial-commit | DEFERRED |

**Session-start template** (for each phase): read the plan + target source file top-to-bottom + mirror fixture patterns from the named neighbor test file. TDD red-phase: every drift-pin test must fail against current code OR be docstring-marked "pinning current contract." Log confirmed bugs to [[Loose Ends]]; bump `last-shipped:` frontmatter on phase close.

---

## Phase A — Core Gap Audit — COMPLETE 2026-04-18

Plan: `~/.claude/plans/gentle-spinning-bird.md`. Audit doc: [[Test Audit - Core Gaps]].

Ranked 30 dark/smoke behaviors across the 8 top runtime-frequent core modules (loop, llm, tool_dispatch, context_assembly, compaction, memory_hygiene, sessions, step_executor, tasks, file_sync — ~14,880 prod lines vs ~9,300 existing test lines). Three Explore agents read each cluster + all cross-referencing test files; I synthesized into the audit doc.

**Key findings**:
- `compaction.py` + `memory_hygiene.py` confirmed well-covered (refuted the initial hypothesis that big-module = thin tests). Only small outlier gaps (`repair_section_periods` dark, `maybe_compact` smoke).
- `llm.py` has **no dedicated test file** despite running every turn. Highest-impact greenfield target.
- `sessions.py` has the biggest every-turn dark surface (`persist_turn` outbox loop + `_sanitize_tool_messages` 3-phase state machine).
- `step_executor.py` fresh churn (foreach `when:`, `tool` step, `/resolve` background) is happy-path-only — regression risk highest here.
- `context_assembly.py` unit tests are thin (210 lines vs 2072 prod); integration suite exists but doesn't pin branch logic.

**Phase B ordering** (pick from the top-30 list per sweep):

| Sweep | Module | Primary targets (top-30 #) | Session owner |
|---|---|---|---|
| **B.1** ✅ | `app/services/sessions.py` | #1, #6, #13, #18, #27 | DONE 2026-04-18 — 22 tests, `test_sessions_core_gaps.py`. All 5 entries moved → **pinned**. |
| **B.2** ✅ | `app/services/step_executor.py` | #7, #8, #12, #15, #17, #26 | DONE 2026-04-18 — 25 tests, `test_step_executor_core_gaps.py`. All 6 entries moved → **pinned**. |
| **B.3** ✅ | `app/agent/llm.py` | #2, #14, #19, #20, #21 | DONE 2026-04-18 — 44 tests, `test_llm_core_gaps.py`. All 5 entries moved → **pinned**. |
| **B.4** ✅ | `app/agent/tool_dispatch.py` | #10 | DONE 2026-04-18 — 19 tests, `test_tool_dispatch_core_gaps.py`. Entry moved → **pinned**. |
| **B.5** ✅ | `app/agent/loop.py` | #4, #5, #30 | DONE 2026-04-18 — 9 tests, `test_loop_core_gaps.py`. All 3 entries moved → **pinned**. |
| **B.6** ✅ | `app/services/file_sync.py` | #11, #28 | DONE 2026-04-18 — 12 tests, `test_file_sync_core_gaps.py`. #11 already covered (audit flag was stale — pinned by `test_when_zero_files_on_disk_then_orphan_deletion_skipped`). #28 new: 5 kind branches + deletion + reload cascade. **Bug caught + fixed**: `file_sync.py:686` referenced undefined `rows2` → NameError on deletion of prompt/carapace/workflow files (short-circuited past only when SkillRow hit was truthy). |
| **B.7** ✅ | `app/agent/context_assembly.py` | #24, #25 | DONE 2026-04-18 — 10 tests, `test_context_assembly_core_gaps.py`. Both entries → **pinned**. |
| **B.8** ✅ | `app/services/compaction.py` | #22, #23 | DONE 2026-04-18 — 11 tests, `test_compaction_core_gaps.py`. #22 (repair_section_periods): 5 tests covering message_count==0 skip, no session_id skip, normal repair, multi-section offset. #23 (maybe_compact): 6 tests covering budget threshold, background task scheduling, exception containment. Both entries → **pinned**. |
| **B.9** ✅ | `app/agent/tasks.py` (part 1) | #16, #29 | DONE 2026-04-18 — 18 tests in `test_tasks_core_gaps.py`. #29: _matches_event_filter (7 pure-unit) + _spawn_from_event_trigger (5 real-DB) + fire_event_triggers (4 real-DB). #16 (callback atomicity): covered in B.10 delegation tests instead. All entries → **pinned**. |
| **B.10** ✅ | `app/agent/tasks.py` (part 2) | #3, #9 | DONE 2026-04-18 — 7 tests in same file. #3: run_task cross-bot delegation creates child session with depth+1 + propagates root_session_id (2 tests, real DB + full run_task mocking). #9: recover_stalled_workflow_runs 4 scenarios + fresh-run no-op + exception swallowing (7 tests). **Key gotcha**: scenario 1 on_step_task_completed has no try/except — exception propagates (scenarios 3/4 wrap in try/except). Identity-map bypass needed for scenario 2: use patched_async_sessions() factory fresh session to read committed step_states. All entries → **pinned**. |

---

## Phase C — Seam Tests — COMPLETE 2026-04-18

**9 tests in `tests/unit/test_dispatch_recording_seam.py`. All green.**

Fills the seam between Phase B.4 (`test_tool_dispatch_core_gaps.py`, policy logic isolated) and `test_tool_call_status_lifecycle.py` (`_start_tool_call`/`_complete_tool_call` isolated). Phase C exercises the full `dispatch_tool_call → _start_tool_call (fire-and-forget) → tool execution → _complete_tool_call (fire-and-forget) → ToolCall row in test DB` pipeline.

| Class | Tests | Behaviors pinned |
|---|---:|---|
| `TestNormalDispatchRecordingSeam` | 4 | `done` status after success, `error` status on error-JSON, single row (not two), iteration+bot_id stored |
| `TestDeniedDispatchRecordingSeam` | 2 | `denied` one-shot row on auth check, `denied` one-shot row on policy deny (tool not called) |
| `TestApprovalDispatchRecordingSeam` | 3 | `awaiting_approval` row created, `result.record_id` ↔ ToolCall.id linked, `ToolApproval.tool_call_id` ↔ ToolCall.id wired |

**Key technique**: `await asyncio.sleep(0)` × 5 + `db_session.expire_all()` to flush fire-and-forget `safe_create_task` background tasks before asserting on DB state.

**No bugs found.** The dispatch → recording → DB pipeline worked correctly under all 5 status transitions (running→done, running→error, denied one-shot auth, denied one-shot policy, running→awaiting_approval with ToolApproval linkage).

---

## Phase E — Drift-Seam Sweeps — 2026-04-18 (drafted)

Plan: `~/.claude/plans/drifting-silent-harbor.md`. Ten Sonnet-executable targets organized by drift class (silent-UPDATE, multi-row sync, orphan pointer, multi-actor, partial-commit, background-task ordering). Each names file:line + suspected drift + test shape. Expected yield ~60-80 tests + 3-6 new Loose Ends from drift confirmation.

| # | File | Seam | Status |
|--:|---|---|---|
| E.1 | `sessions.py::persist_turn` attachment link | partial-commit | SHIPPED (5 tests) 2026-04-18 — bug found+fixed: `Message.id` was None when captured (SA callable default not eager); added `id=uuid.uuid4()` in constructor |
| E.2 | `persist_turn::publish_to_bus` swallow | partial-commit | SHIPPED (4 tests) 2026-04-18 — no bugs; per-row swallow and outbox-before-bus ordering confirmed |
| E.3 | `tool_dispatch` approval-create race | background-task ordering | SHIPPED (6 tests) 2026-04-18 — no bugs; contract pinned: ToolApproval commits before ToolCall; ghost `tool_call_id` possible if start raises; both policy-gate + capability-gate paths confirmed |
| E.4 | `loop.py` approval-verdict race | background-task ordering | SHIPPED (10 tests) 2026-04-18 — no bugs; race drift confirmed + pinned: handler guards correctly on `status=="pending"`, but when race wins, local `verdict="expired"` diverges from DB `approved` → TC stuck in "running". Idempotency + exception-swallow also pinned. |
| E.5 | `outbox` state machine no-guards | silent-UPDATE | SHIPPED (8 tests) 2026-04-18 — 4 normal transitions + 4 drift pins: DELIVERED→FAILED_RETRYABLE (re-queues delivered!), DELIVERED→mark_delivered (idempotent), IN_FLIGHT→IN_FLIGHT, FAILED_RETRYABLE→DELIVERED. No bugs; contracts pinned. |
| E.6 | `outbox.enqueue` idempotency | multi-row sync | SHIPPED (5 tests) 2026-04-18 — **drift confirmed**: unique constraint was dropped in migration 188; docstring claiming IntegrityError on duplicate is stale. Re-enqueue silently inserts duplicate rows; no rollback on batch duplicates. Logged in Loose Ends. |
| E.7 | `channel_bot_members.config` JSONB PATCH | silent-UPDATE | SHIPPED (9 tests) 2026-04-18 — no bugs; merge/delete contracts pinned; expire_all cross-session read confirms flag_modified fires; second-PATCH accumulation confirmed |
| E.8 | `channel_events` subscribe + replay | multi-actor | SHIPPED (5 tests) 2026-04-18 — no bugs; overflow isolation confirmed (healthy subscriber never gets lapsed when slow subscriber overflows); two-subscriber independent replay windows confirmed; replay doesn't inject into live subscriber queues |
| E.9 | Multi-bot snapshot + decide non-primary | multi-actor | SHIPPED (5 tests) 2026-04-18 — no bugs; both primary+nonprimary turns surface simultaneously; primary sorts first; non-primary awaiting_approval links approval_id correctly; primary turn completion leaves non-primary active |
| E.10 | Channel integration activate/deactivate | multi-row sync | SHIPPED (12 tests) 2026-04-18 — no bugs; activate creates/reuses/idempotent; real binding client_id preserved on reactivation; includes cascade activates child; deactivate cascades to child; cascade skipped when other parent still active; row preserved as inactive (not deleted) |

Don't parallelize targets that share a module (see Parallel safety in plan).

---

## Phase D — Recently-Churned Surface — 2026-04-18

**Session frame**: user observed that Phase B pinned 131 tests but only caught 1 bug (B.6 `rows2` NameError). Hypothesis: tests were written by reading code, so they pin current behavior rather than challenging it. Retargeted at code that shipped same-week (Chat State Rehydration Phase 2/3) where the audit hadn't reached yet.

**Picks came from reading**, not from the top-30. Three files:

| File | Tests | Behaviors pinned | Finding |
|---|---:|---|---|
| `test_decide_approval_flow.py` | 18 | Approve/deny flips; bot- vs global-rule creation; rule/pin only on approve; capability pin idempotency + no-pin-on-deny; 404/409 guards; tool_call_id=None and orphan pointer; future resolution both ways; no-waiting-future doesn't crash | **Silent DB drift** — deny while ToolCall is no longer `awaiting_approval` flips ToolApproval→`denied` but leaves ToolCall alone. Pinned as current behavior; logged in [[Loose Ends]]. |
| `test_recording_silent_failure.py` | 8 | `_complete_tool_call` on missing row = 0-row no-op; 4000-char truncation default + `store_full_result` bypass; `_set_tool_call_status` has no state-machine guard; duplicate `_start_tool_call` swallowed not raised; terminal-row `_record_tool_call` path | Contract pinned: every helper swallows errors + accepts any transition. Hardening (logging 0-row UPDATEs, raising on missing id) now has a regression surface to move off. |
| `test_channel_state_snapshot.py` (+2) | 2 | Foreign-bot turn → `is_primary=False`; `awaiting_approval` ToolCall with no linked ToolApproval → `approval_id=None` (undecidable card) | Orphan card surfaces but can't be decided — UI stuck until 10-min cutoff. Logged in [[Loose Ends]]. |

**Total: 36 tests, all green (1.77s for decide_approval alone).** No bugs broke during write — the findings above are documented DB inconsistencies the code silently tolerates, not regressions.

**Method**: read the module top-to-bottom, note surprising branches / silent-failure modes / state-sync seams, then write tests that either pin the current behavior OR would fail if the suspicion is a bug. Every silent-failure test has a companion "normal lifecycle" test so future hardening distinguishes "noise removal" from "contract change."

**Key finding for future sessions**: the Phase B yield was low because coverage sweeps pin what's *easy to read* — happy paths + the most obvious branch. The higher-yield reads target:
1. **Fire-and-forget UPDATE helpers** — silent on missing rows.
2. **Multi-row state sync** (ToolApproval ↔ ToolCall) — guards may leave drift behind.
3. **Orphan pointer cases** — FK=SET NULL means both sides can outlive each other.
4. **Multi-actor paths** (foreign-bot, multi-bot channel) — tests default to single-bot.

---

## Phase B Complete — 2026-04-18

All 10 sweeps shipped. Top-30 gap list fully pinned.

**B.7-B.10 session (2026-04-18) — 46 new tests, all green in Docker**

| Sweep | File | Tests | Key findings |
|---|---|---:|---|
| B.7 | `test_context_assembly_core_gaps.py` | 10 | Both #24/#25 pinned. `invalidate_skill_auto_enroll_cache` exception swallow path confirmed. `patch.dict(sys.modules)` pattern for import-fail path. |
| B.8 | `test_compaction_core_gaps.py` | 11 | `repair_section_periods`: message_count==0 silent skip confirmed (documented behavior). `maybe_compact`: budget threshold boundary at 0.85 (exclusive) confirmed. Exception containment verified via captured coroutine. |
| B.9 | `test_tasks_core_gaps.py` | 18 | `_matches_event_filter` pure unit tests. `_spawn_from_event_trigger` real-DB: event_data merged into execution_config correctly. `fire_event_triggers` filter hit/miss/swallow. |
| B.10 | same file | 7 | `run_task` delegation: child session created with depth = parent.depth + 1, root_session_id propagated. `recover_stalled_workflow_runs`: all 4 scenarios covered. **Gotcha**: scenario 1 (on_step_task_completed) has no try/except — exception propagates; scenarios 3/4 DO swallow. Scenario 2 identity-map bypass: use `patched_async_sessions()` fresh session for post-commit reads. |

**Total Phase B: 131 tests across B.1-B.10. All 30 top-30 entries pinned.**

## Phase B Handoff — Per-Session Outlines (for next Sonnet)

Each outline names the entry points, the existing test neighbors to mirror, the fixtures needed, and the success bar. Read **this outline + [[Test Audit - Core Gaps]] top-30 row + the session-13 log** (Phase B.6) for context. Then follow the pattern from `test_file_sync_core_gaps.py` (session 13) or `test_loop_core_gaps.py` (session 12).

### B.7 — `context_assembly.py` cache invalidation (#24, #25)

**Scope**: 2 functions, both ~30 lines each. No DB fixtures needed. Warm-up session.

- **#24 `invalidate_bot_skill_cache`** (`app/agent/context_assembly.py:88`) — 30s TTL cache lives in module dict. Test: cache populated → invalidate by bot_id → next read misses. Extra-mile: invalidate one bot leaves others intact. Add a "invalidate all" branch test if one exists.
- **#25 `invalidate_skill_auto_enroll_cache`** (`app/agent/context_assembly.py:159`) — same pattern + silent exception swallow at 172-173. Test: normal invalidation works; raise inside the inner block → function returns without propagating + next read still returns stale (documented behavior).

**Fixtures**: none special. Use `monkeypatch` to reset the module-level cache dict in setup/teardown (B.28 — leaking state breaks every test after). Mirror `tests/unit/test_file_sync.py::TestClassifyPath` for sync tests, no DB.

**Success bar**: 5–8 tests. Both entries move **dark** → **pinned** in the audit.

---

### B.8 — `compaction.py` one-offs (#22, #23)

**Scope**: 2 unrelated one-offs. #22 is pure offset math (unit-testable without DB). #23 needs to assert the background task actually executed, not just that it was scheduled.

- **#22 `repair_section_periods`** (`app/services/compaction.py:1899`) — **critical**: `section.message_count == 0` path silently skips the section. Read the function, enumerate all sections-array shapes, test:
  - normal 3-section repair updates offsets correctly
  - `message_count == 0` section: assert current behavior (skip) and that downstream sections' offsets are unaffected
  - empty sections list: returns without error
  - boundary: section at index 0 vs mid-array vs last
- **#23 `maybe_compact` background task** (`app/services/compaction.py:1290`) — existing tests assert `safe_create_task` was called but never run the coroutine. Test: let the coroutine execute (await the captured arg) with a stubbed `compact_for_channel`, assert the stub received the right budget + channel_id. Add: exception inside the background task is swallowed + logged (don't crash the turn).

**Fixtures**: `db_session` + `patched_async_sessions` for #22 (compaction reads/writes sections). For #23, mirror the `safe_create_task` patching pattern used in `tests/unit/test_operations_admin.py` (Phase 3 gotcha #2).

**Success bar**: ~8–12 tests. #22 moves **dark** → **pinned**; #23 moves **smoke** → **pinned**.

---

### B.9 — `tasks.py` smaller entries (#16, #29)

**Scope**: Start with the two that don't need a stalled-run DB fixture. Build fixture shape here if #29 needs one, then reuse in B.10.

- **#16 `run_task` callback task creation atomicity** (`app/agent/tasks.py:1242-1253`) — follow-up task creation inside the finalize block. Test: callback succeeds → follow-up task row exists. Callback raises → no orphaned task row. Mirror the partial-failure shape from `tests/unit/test_tasks.py` if present; otherwise build from `tests/factories/tasks.py` (check `ls tests/factories/`).
- **#29 `_spawn_from_event_trigger` + filter matching** (`app/agent/tasks.py:371-445`) — filter matching at 437-438 dark, event_data injection at 388-389 dark. Test:
  - filter hit → spawn fires with the right `ecfg`
  - filter miss → no spawn
  - spawn failure is swallowed silently (this is the current behavior; pin it)
  - event_data merged into ecfg correctly

**Fixtures**: `db_session`, `patched_async_sessions`, `agent_context` (sets the ContextVars for bot_id/channel_id). Existing factories in `tests/factories/` — `build_task`, `build_channel`, `build_bot`. Check first.

**Success bar**: 10–15 tests. Both entries move → **pinned**.

---

### B.10 — `tasks.py` recovery/delegation (#3, #9) — biggest remaining sweep

**Prerequisite**: Phase B.9 completed so the fixture pattern is proven.

- **#3 `run_task` delegation child session linkage** (`app/agent/tasks.py:888-912`) — root_session_id propagation and delegation_depth across cross-bot calls. Test: parent task spawns child → child has correct `root_session_id` + `delegation_depth == parent.depth + 1`. Extra-mile: grand-child (depth 2) + circular delegation guard (if one exists).
- **#9 `recover_stalled_workflow_runs` 4 scenarios** (`app/agent/tasks.py:1411-1542`) — 130 lines, branch coverage <10%. Read the function, enumerate the 4 scenarios (likely: stuck-in-running, heartbeat-expired, no-workflow, already-terminal). One test per scenario asserting the correct terminal state.

**Fixtures**: the big one — stalled-run fixture that seeds a `Task` row with `status=running`, configurable `heartbeat_at`, optional workflow linkage. Add to `tests/factories/tasks.py`. Also needs mocked time (`freezegun` for the 5-min-stalled threshold) — mirror pattern in `tests/unit/test_usage_limits.py`.

**Success bar**: 12–18 tests. Both entries **dark** → **pinned**. This closes the top-30 gap list.

---

### What's out of scope

After B.10 the top-30 is fully pinned. If there's appetite for more:
- **Phase C**: re-run the audit Explore-agent pass on the next tier (modules #11-20 by runtime frequency). [[Test Audit - Inventory]] has the ranked list.
- **Phase D**: integration-layer gaps (mcp, providers, dispatch renderers) — separate audit needed.
- Neither is on the roadmap yet. Start with B.7 → B.10 as queued.

**Session hand-off shape**: each Phase B session begins by reading this track + [[Test Audit - Core Gaps]], running `pytest tests/unit/test_<module>*.py -v` to confirm current-green baseline, then TDD-writing tests for the top-30 entries in scope. As entries move `dark` → `pinned` or smoke → pinned, update the classification column in the audit doc **same edit**.

---

## Phase 2 — COMPLETE 2026-04-18

All 25+ critical service symbols covered. **163 passed, 0 failed** in sibling regression (2026-04-18).

### Final batch (2026-04-18)

| file | new tests | symbols |
|---|---:|---|
| `tests/unit/test_attachment_service.py::TestFindOrphanDuplicate` | 4 | `attachments.find_orphan_duplicate` |
| `tests/unit/test_sessions.py::TestNormalizeStoredContent` | 6 | `sessions.normalize_stored_content` |
| `tests/unit/test_task_run_anchor.py::TestUpdateAnchor` | 4 | `task_run_anchor.update_anchor` |
| `tests/unit/test_usage_limits.py::TestStartRefreshTask` | 3 | `usage_limits.start_refresh_task` |
| `tests/unit/test_usage_spike.py::TestStartSpikeRefreshTask` | 3 | `usage_spike.start_spike_refresh_task` |
| `tests/unit/test_workflow_hooks.py::TestRegisterWorkflowHooks` + `TestOnTaskComplete` | 2 | `workflow_hooks.register_workflow_hooks`, `_on_task_complete` |

**False positives cleared**: `encryption.is_encryption_enabled` + `widget_templates.apply_widget_template` — both already covered by existing tests; audit flags were false positives.

**`conftest.py` extended**: `app.services.task_run_anchor.async_session` added to `_MODULE_LEVEL_ALIASES` + `patched_async_sessions` chain (10 aliases total).

**`asyncio.create_task` gotcha**: patching only `asyncio.create_task` doesn't prevent the coroutine from being created — `patch()` auto-creates `AsyncMock` for `async def` targets, which still creates a coroutine on call. Fix: ALSO patch `_refresh_loop` with an explicit `MagicMock()` (sync mock) to prevent coroutine creation entirely. Applied to both `usage_limits` and `usage_spike` tests.

**Bug found + fixed**: `TestDispatchAlert::test_integration_target_success` + `test_partial_failure` were pre-existing failures. Root cause: `_dispatch_alert` calls `parse_dispatch_target({"type": integration_type, ...})` which looks up the integration type in `target_registry`. In the unit test environment, integration discovery never runs → registry is empty → `ValueError: unknown dispatch target type` raised → caught by `except ValueError` → `continue` skips `renderer.render()`. Fix: patch `app.domain.dispatch_target.parse_dispatch_target` with `return_value=MagicMock()` in both tests.

### First batch (2026-04-18)

| file | new tests | symbols |
|---|---:|---|
| `tests/unit/test_workflows.py::TestCreateWorkflow` | 4 | `workflows.create_workflow` |
| `tests/unit/test_attachment_service.py::TestDeleteAttachment` | 4 | `attachments.delete_attachment` |
| `tests/unit/test_attachment_service.py::TestInferIntegrationFromMetadata` | 3 | `attachments._infer_integration_from_metadata` |
| `tests/unit/test_turn_event_emit.py::TestCoerceToolArguments` | 5 | `turn_event_emit._coerce_tool_arguments` |
| `tests/unit/test_turn_event_emit.py::TestEmitRunStreamEvents` | 7 | `turn_event_emit.emit_run_stream_events` |

**False positive cleared**: `channel_events.publish_message/updated` — no DB surface; 2-test `TestPublishMessage` is correct and sufficient.

## Phase 3 — limits + secret_values + settings + operations + docker_stacks shipped 2026-04-18

69 tests across 5 new files, all green in 60.6s. Sibling regression (bots + providers + webhooks + mcp_servers + attachments): 120 passed. Phase 3 score: **67/60 admin routes — COMPLETE**.

**3 new factories**: `tests/factories/usage_limits.py::build_usage_limit`, `tests/factories/secret_values.py::build_secret_value`, `tests/factories/docker_stacks.py::build_docker_stack`. All re-exported.

### Routes covered

| file | tests | routes |
|---|---:|---|
| `test_limits_admin.py` | 18 | list, status, create, update, delete (5) |
| `test_secret_values_admin.py` | 15 | list, create, get, update, delete (5) |
| `test_settings_admin.py` | 11 | update_settings, reset_setting, update_model_tiers, update_fallback_models (4) |
| `test_operations_admin.py` | 10 | list-ops, pull, restart, get-backup-config, update-backup-config, backup-history, trigger-backup (7) |
| `test_docker_stacks_admin.py` | 15 | list, get, destroy, start, stop, status, logs (7) |

### Bugs found

**Pinned (not a bug, documented as a behavioral gap):** `update_limit` has no guard against an empty body — a `PUT /limits/{id}` with `{}` silently updates the timestamp and reloads the in-memory cache. Contrast with `update_backup_config` which returns 400 on empty. Pinned in `test_when_empty_update_body_then_timestamp_changes_but_values_unchanged`.

**No critical bugs found.** Key validation logic probed and cleared:
1. **`create_limit` uniqueness** — in-code check (not DB constraint) returns 409 correctly.
2. **`destroy_docker_stack` integration guard** — 403 (not 204) when `source=="integration"`. Critical business rule pinned.
3. **`restart_server` confirm guard** — 400 without `{"confirm": true}`. Pinned with two tests (explicit false + missing body).
4. **`update_backup_config` pg_insert** — uses PostgreSQL-specific dialect inline; only the 400 validation case is safe to test against SQLite. Happy path requires a Postgres test DB.
5. **`secret_values` 409 detection** — catches `UNIQUE constraint failed` (SQLite) via `"unique" in str(exc).lower()`. Works correctly.

### Gotchas captured

1. **`pg_insert` inline in `update_backup_config` (operations.py) is not testable with SQLite.** Only the `400 (no fields)` validation branch is safe. The `server_settings.update_settings` / `reset_setting` route counterparts work because those functions are patched at the service level.
2. **`asyncio.create_task(_run())` in `trigger_backup`** — background task is swallowed by `side_effect=lambda coro: (coro.close(), MagicMock())[1]` to prevent "coroutine never awaited" warnings. Route still returns `{status: "started"}` correctly.
3. **`stack_service.start/stop/destroy`** — imported inside handler (local import). Patch at `app.services.docker_stacks.stack_service.{method}` — patches the method on the singleton, not the name binding.
4. **`asyncio.create_subprocess_exec` mocking**: needs `AsyncMock(return_value=mock_proc)` where `mock_proc` has `proc.communicate = AsyncMock(return_value=(b"", b""))`. Plain `MagicMock(return_value=proc)` fails because `await asyncio.create_subprocess_exec(...)` awaits the mock's return value.
5. **`load_limits()` patch target**: `from app.services.usage_limits import load_limits` at the top of the router binds at import time. Patch `app.routers.api_v1_admin.limits.load_limits`, not `app.services.usage_limits.load_limits`.

## Phase 3 — webhooks + mcp_servers + attachments shipped 2026-04-18

`tests/integration/test_webhook_admin.py` — **19 tests** across 5 classes, all green.
`tests/integration/test_mcp_server_admin.py` — **16 tests** across 5 classes, all green.
`tests/integration/test_attachment_admin.py` — **8 tests** across 2 classes, all green.
Sibling regression (bots + providers + admin_scoped_auth): 93 passed. Phase 3 score: **40/60 admin routes**.

**Bug found + fixed**: `admin_delete_mcp_server` checked bot usage BEFORE server existence. A stale bot reference to a non-existent server caused 400 "Cannot delete: referenced by bots X" instead of 404. Fix: moved `db.get(MCPServerRow, server_id)` / 404 guard BEFORE the bot-usage scan. TDD red-phase confirmed (test failed against buggy code; passes after fix). Full entry in Fix Log.

**New factories**: `tests/factories/webhooks.py::build_webhook_endpoint`, `tests/factories/mcp_servers.py::build_mcp_server`, `tests/factories/attachments.py::build_attachment`. All re-exported from `tests/factories/__init__.py`.

### Routes covered

| method + path | handler | tests |
|---|---|---:|
| `POST /webhooks` | `admin_create_webhook` | 6 |
| `PUT /webhooks/{id}` | `admin_update_webhook` | 6 |
| `DELETE /webhooks/{id}` | `admin_delete_webhook` | 3 |
| `POST /webhooks/{id}/rotate-secret` | `admin_rotate_webhook_secret` | 2 |
| `POST /webhooks/{id}/test` | `admin_test_webhook` | 2 |
| `POST /mcp-servers` | `admin_create_mcp_server` | 5 |
| `PUT /mcp-servers/{id}` | `admin_update_mcp_server` | 4 |
| `DELETE /mcp-servers/{id}` | `admin_delete_mcp_server` | 4 |
| `POST /mcp-servers/{id}/test` | `admin_test_mcp_server` | 2 |
| `POST /mcp-servers/test-inline` | `admin_test_mcp_server_inline` | 1 |
| `DELETE /attachments/{id}` | `delete_attachment` | 3 |
| `POST /attachments/purge` | `purge_attachments` | 5 |

### Gotchas captured

1. **`_reload_mcp()` opens its own session via `load_mcp_servers`** — not in the integration conftest's patch set. Patched per-test via `patch("app.routers.api_v1_admin.mcp_servers._reload_mcp", AsyncMock)`. Could be added to conftest if more mcp_server tests land.
2. **`admin_delete_mcp_server` existence-before-usage ordering** — always check existence first, then report "in-use" conflicts. Reversed order lets stale references mask the correct 404.
3. **`respx` not installed** — skip `respx.mock` patterns; patch service-level functions (`send_test_event`, `_test_mcp_connection`) directly instead. Acceptable because the route tests exercise DB interaction + error handling; HTTP transport is the true external being isolated.
4. **`Attachment.metadata_`** is the Python-side attribute (maps to DB column `metadata` — avoiding SQLAlchemy's reserved `MetaData` name). Factory uses `metadata_={}`.

### Next session — start here

Phase 3 continues (~20 more admin routes):
- `api_v1_admin/operations.py` — restart/reload/cache-flush ops
- `api_v1_admin/docker_stacks.py` — stack CRUD
- `api_v1_admin/secret_values.py` — create/update/delete (pattern from `test_secret_values.py`)
- `api_v1_admin/limits.py` — limit CRUD
- `api_v1_admin/settings.py` globals — update/reset

## Phase 3 — admin providers router shipped 2026-04-18

`tests/integration/test_provider_admin.py` — **40 tests** across 12 classes, all green in 31.8s. Sibling regression (`test_bot_admin.py` + `test_admin_scoped_auth.py`): 53 passed. Closes all 11 `api_v1_admin/providers.py` mutating routes the audit flagged uncovered.

**Routes covered** (happy path + at least one error branch per route, F.16 Deliberate Fire on missing provider / invalid type / unsupported capability / driver raise):

| method + path | handler | tests |
|---|---|---:|
| `POST /providers` | `admin_create_provider` | 6 |
| `PUT /providers/{id}` | `admin_update_provider` | 7 |
| `DELETE /providers/{id}` | `admin_delete_provider` | 3 |
| `POST /providers/{id}/test` | `admin_test_provider` | 2 |
| `POST /providers/test-inline` | `admin_test_provider_inline` | 2 |
| `POST /providers/{id}/models` | `admin_add_provider_model` | 4 |
| `DELETE /providers/{id}/models/{pk}` | `admin_delete_provider_model` | 2 |
| `POST /providers/{id}/sync-models` | `admin_sync_provider_models` | 4 |
| `POST /providers/{id}/pull-model` | `admin_pull_model` (SSE) | 3 |
| `DELETE /providers/{id}/remote-models/{name:path}` | `admin_delete_remote_model` | 3 |
| `GET /providers/{id}/remote-models/{name:path}/info` | `admin_remote_model_info` | 2 |
| `GET /providers/{id}/running-models` | `admin_running_models` | 2 |

### Infra delta

`tests/integration/conftest.py` — `client` fixture patches now include `app.services.providers.async_session`. Eight module-level aliases total (workflows, workflow_executor, bot_hooks, attachments, skill_enrollment, tool_enrollment, sandbox, providers). `providers.py:12` imports `async_session` at module level so `load_providers()` + `has_encrypted_secrets()` + `_warm_model_info_cache()` all pick up the test factory when called during a route.

New factory: `tests/factories/providers.py::build_provider_config`, `build_provider_model`. Re-exported.

### Bugs found

**None.** The `providers.py` handlers behaved correctly under real-DB exercise across happy paths, validation failures, cascade deletes, billing-type transitions, and capability gating. Tried specifically to bite on:

1. **`admin_update_provider` plan/usage transition** — traced every combination of `billing_type`, `plan_cost`, `plan_period`, `clear_plan_cost`. Logic is subtle but correct: when switching to "usage", plan fields cleared first; the subsequent `if row.billing_type == "plan"` gate correctly skips the plan-field update block. When switching to "plan" in the same request, the gate fires against the just-updated value and the cost/period both land. Test pinned explicitly in `test_when_billing_switched_to_usage_then_plan_fields_cleared`.
2. **JSONB `config` mutation on update** — `admin_update_provider` does `config = dict(row.config or {})` + mutate + `row.config = config` (new-dict assignment, not mutation). SQLA change-tracking picks up the assignment on both SQLite and PG — no `flag_modified` needed. Pinned by `test_when_management_key_empty_then_removed_from_config` which verifies the `management_key` field is popped **and the sibling `other_key` is preserved** (extra mile I.7).
3. **`admin_test_provider` missing-registry branch** — route returns `ProviderTestResult(ok=False, ...)` as HTTP 200 (not 404) when provider not found. Inconsistent with other routes but pinned as documented contract in `test_when_provider_not_in_registry_even_after_reload_then_ok_false`.
4. **`admin_add_provider_model` registry-reload gating** — only reloads when a flag (no_system_messages / !supports_tools / !supports_vision) is set. Pinned in `test_when_flag_set_then_registry_reloaded`.
5. **`admin_delete_provider` bot-usage blocking** — 400 response names the bot id in the detail string. Pinned in `test_when_provider_in_use_by_bot_then_400_with_bot_id`.

### Minor observations (not bugs, documented for follow-up)

- **No `clear_plan_period` flag** in `ProviderUpdateIn` — asymmetric with `clear_plan_cost`. User must switch billing_type to clear `plan_period` alone.
- **`admin_delete_remote_model` ignores driver return value** — driver returns `bool` per base class, but route always returns `ok=True, message=f"Deleted {model_name}"` unless an exception is raised. If a driver returns `False` on "not found without raise", the route lies. Depends on driver contracts (they actually raise rather than return False), so effectively latent.
- **`admin_test_provider_inline` unknown type path** catches `ValueError` from `get_driver` — but `get_driver` has a fallback to `OpenAICompatibleDriver` that swallows unknown types with a log warning. So the `ValueError` branch is unreachable in production via the current registry. Pinned anyway as a defensive assertion via `side_effect=ValueError` patch.

### Gotchas captured

1. **`app/services/providers.py:12` is the eighth known module-level `async_session` alias.** Routes call `load_providers()` via function-local import, which then opens its own session from `providers.async_session`. Without patching, tests hit an empty engine and log "No DB providers configured". Added to the integration `client` fixture.
2. **`admin_pull_model` returns `StreamingResponse` (SSE)** — `httpx.AsyncClient` collects the full body synchronously (since `ASGITransport` drives the generator to completion), so `resp.text` contains all `data: {...}\n\n` chunks concatenated. String-substring assertions on `'"status": "downloading"'` + `'"status": "success"'` are sufficient; no need to parse the event stream.
3. **Async-generator exception path for `pull_model`**: simulating a driver that raises before first yield requires the generator function shape — `async def _boom(cfg, name): raise ...; yield` (unreachable `yield` makes it an async generator so `async for` dispatches the `__anext__`, which re-raises into the route's `except`).
4. **Driver stub via `AsyncMock`**: `capabilities()` is **sync** per `ProviderDriver.capabilities()`, so assign a lambda (not `AsyncMock`) — otherwise the route gets a coroutine where it expects a `ProviderCapabilities` dataclass and `caps.list_models` attribute access crashes. Exact line: `driver.capabilities = lambda: ProviderCapabilities(...)`.
5. **`sync_models` display-name policy**: enriched `display` only overrides when the row's `display_name` is empty/None — never clobbers user-curated names. Cost + max_tokens fields **always** update from enriched data (per inline comment).

## Phase 3 — admin bots router shipped 2026-04-18

`tests/integration/test_bot_admin.py`: 11 → **37 tests** (26 new), all green in 33.5s. Sibling regression (`test_admin_scoped_auth.py` + `test_admin_skills.py`): 18 passed. Closes all 9 `api_v1_admin/bots.py` mutating routes the audit flagged uncovered.

**Routes covered** (ship each with happy path + at least one error branch; F.16 Deliberate Fire on missing bot / missing skill / duplicate / invalid input):

| method + path | handler | tests |
|---|---|---:|
| `POST /bots` | `admin_bot_create` | 6 |
| `POST /bots/{id}/memory-hygiene/trigger` | `admin_bot_memory_hygiene_trigger` | 4 |
| `POST /bots/{id}/memory-scheme` | `admin_bot_enable_memory_scheme` | 3 |
| `POST /bots/{id}/sandbox/recreate` | `admin_bot_sandbox_recreate` | 2 |
| `POST /bots/{id}/enrolled-skills` | `admin_bot_enrolled_skill_add` | 4 |
| `DELETE /bots/{id}/enrolled-skills/{skill_id}` | `admin_bot_enrolled_skill_remove` | 2 |
| `POST /bots/{id}/enrolled-tools` | `admin_bot_enrolled_tool_add` | 3 |
| `DELETE /bots/{id}/enrolled-tools/{tool_name}` | `admin_bot_enrolled_tool_remove` | 2 |

`DELETE /bots/{id}` was already covered by `TestBotDelete` (6 tests, unchanged).

### Infra delta

`tests/integration/conftest.py` — `client` fixture's `patch.multiple` chain extended with three new `async_session` aliases: `app.services.skill_enrollment.async_session`, `app.services.tool_enrollment.async_session`, `app.services.sandbox.async_session`. Now seven module-level aliases (parallels the unit conftest's `_MODULE_LEVEL_ALIASES` list but scoped to what the admin router handlers touch).

### Bugs found

None. All 9 routes behaved as documented under real-DB + real-router exercise. Minor observations (not bugs, documented for follow-up):

- `admin_bot_create` / `admin_bot_update` silently drop typo'd fields (`if hasattr(row, key): setattr(...)`). Consistent pattern; not regression-worthy.
- `admin_bot_sandbox_recreate` wraps `recreate_bot_local` in bare `except Exception` → 500 with message. Same shape as other sandbox routes.

### Gotchas captured

1. **The integration conftest's `get_bot` side_effect patch doesn't retarget router-local aliases.** `api_v1_admin/bots.py:16` does `from app.agent.bots import get_bot, list_bots`, binding the alias at import time. `patch("app.agent.bots.get_bot", side_effect=_get_test_bot)` doesn't retarget this alias — the real `get_bot` runs. The real `get_bot` reads `app.agent.bots._registry` at call time, and that IS patched (to `_TEST_REGISTRY`). **Implication**: when a handler calls `get_bot(id)` after a DB mutation creates a new bot, pre-seed `_TEST_REGISTRY[id]` with a minimal `BotConfig` so the real `get_bot` resolves it. Surfaced as 404 "Unknown bot: X" (from the `_get_test_bot` fallback path) in `TestMemoryScheme::test_when_bot_exists_*`. Helper `_register_bot_in_test_registry` encapsulates the pattern; tests pop the entry before asserting so no cross-test leakage.
2. **`admin_bot_create` calls `reload_bots()` → real `get_bot(data.id)`** — pattern: patch `app.agent.bots.reload_bots` with an `AsyncMock(side_effect=...)` that inserts a `BotConfig` into `_TEST_REGISTRY[data.id]` before `get_bot` runs. Helper `_register_new_bot_on_reload(bot_id, name, model)` returns the configured AsyncMock.
3. **`skill_enrollment.async_session` / `tool_enrollment.async_session` / `sandbox.async_session` are all module-level aliases** (same offender pattern as Phase 1d/1e). The route handlers (create bot → `enroll_starter_pack` / `enroll_starter_tools`; enrolled-skills add → `enroll()`; sandbox recreate → DB cleanup) each open their own session. The integration conftest now patches all three.
4. **`enroll_starter_pack` / `enroll_starter_tools` swallow exceptions** (bots.py:779-790) and return 0 when the skills table is empty — `POST /bots` happy-path tests don't need a seeded skill row.
5. **Route deep-dependency chain** for `POST /bots/{id}/memory-scheme`: `reload_bots()` → `get_bot()` → `bootstrap_memory_scheme(bot)` → `workspace_service.get_workspace_root()` → filesystem mkdir + MEMORY.md write. Tests patch `workspace_service.get_workspace_root` → `tmp_path` and `index_memory_for_bot` → `AsyncMock`. The "non-fatal indexing" branch is pinned by a dedicated test that sets `side_effect=RuntimeError("disk full")` and asserts the route still returns 200 `status=ok`.

## Phase 4 — mock-only services shipped 2026-04-17

Swept the eight services the audit flagged as mock-only ([[Test Audit - Coverage Gaps]] §"Critical Service Symbols"). Three were lexical-audit false positives (file contained `MagicMock` for unrelated tests; the symbol itself was already real-FS-tested). Four became fully real-DB-backed. One (`turn_worker.run_turn`) has three new real-DB control-flow tests; two full-persistence tests are parked — see Known issue below.

**Files rewritten / added** — **69 new tests, all green in 4.1s** aggregate. Full Phase 0-4 regression: **476 passed in 19.2s**.

| Service symbol | File | Action | Tests |
|---|---|---|---|
| `server_settings.reset_setting`, `update_settings` | `tests/unit/test_server_settings.py` | full rewrite | **29** (was 13 pure + 4 mock-based) |
| `secret_values.create_secret`, `delete_secret` | `tests/unit/test_secret_values.py` | full rewrite | **17** (was 4 mock-based) |
| `file_sync.sync_all_files` | `tests/unit/test_file_sync.py` | append `TestSyncAllFilesSkills` + `TestSyncAllFilesPromptTemplates` | **8** new (no prior coverage of this symbol) |
| `turn_worker.run_turn` | `tests/integration/test_turn_worker_persistence.py` | new sibling file | **3** real-DB control-flow |
| `memory_scheme.bootstrap_memory_scheme` | `tests/unit/test_memory_scheme.py` | **audit false positive** | existing 5 tests already use `tempfile.TemporaryDirectory()` |
| `channel_workspace.delete_workspace_file` | `tests/unit/test_channel_workspace.py` | **audit false positive** | existing 5 tests already use real FS |

All new tests use real SQLite-in-memory `db_session` + factories + `patched_async_sessions` per the skill. No `AsyncSession`/`MagicMock` hybrid. Magic mocks confined to true externals per E.1 (embedding calls, secret_registry rebuild, agent loop `run_stream`, member-bot fanout).

### Infra delta

`tests/unit/conftest.py` — added `app.services.file_sync.async_session` to `_MODULE_LEVEL_ALIASES` + corresponding `patch.multiple` call. Now six module-level aliases. Triggered when `sync_all_files` opened its own `async_session()` blocks and hit an empty engine.

### Gotchas captured

1. **`app/services/file_sync.py:28` imports `async_session` at module level** — the seventh known offender. `_MODULE_LEVEL_ALIASES` in `tests/unit/conftest.py` now covers it.
2. **`persist_turn` propagates outbox-enqueue errors by design** (sessions.py:600–628, "An enqueue failure here propagates…"). In real-DB tests, this means `resolve_targets` **must** find the schema it queries — patching `app.services.dispatch_resolution.async_session` to the test factory is required or the entire turn transaction rolls back and the assistant message is silently lost. This was the "only 'user' in roles" failure mode caught during this session.
3. **`_persist_and_publish_user_message` + `persist_turn` open their own sessions**. For full turn coverage you have to patch `turn_worker.async_session`, `sessions.async_session`, and `dispatch_resolution.async_session` — plus `app.db.engine.async_session` for the outbox-publish fallback path.
4. **`secret_values._rebuild_registry` recurses into `secret_registry.rebuild`** which opens its own `async_session` and rebuilds a process-wide regex pattern. Mock via `patch("app.services.secret_values._rebuild_registry", new_callable=AsyncMock)` — not the nested `secret_registry.rebuild` — so the secret_values.py try/except wrapping stays real.
5. **Fernet passthrough simplifies encryption tests**: when `ENCRYPTION_KEY` is unset, `encrypt()` returns plaintext and `decrypt()` passes through. Real-DB `load_from_db` tests round-trip values literally without any mocks.
6. **In-memory `settings` singleton leaks across tests**: `update_settings` / `reset_setting` / `load_settings_from_db` patch `app.config.settings` in place via `object.__setattr__`. A per-test `settings_snapshot` fixture that snapshots the specific keys touched and restores them in teardown is non-negotiable (B.28). Without it, the first `AGENT_TRACE=True` test flips every subsequent test's behavior.
7. **`sync_all_files` "zero files on disk" safety skips orphan deletion**: when the scan returns 0 skill files but the DB has file-sourced rows, the service logs a warning, appends a "mount issue" string to `counts["errors"]`, and skips orphan cleanup. This is defensive behavior that would be invisible to a mocked suite — the real-DB test now pins it.

### Known issue — deferred

Attempted two additional `turn_worker.run_turn` tests that assert on persisted `Message` rows after a full turn (user + assistant, or cancellation's `[STOP]` markers). Intermittent visibility — `persist_turn` commits the row within its own session/connection, `SELECT` from `db_session` on the same engine returns only the pre-persisted user row even after `db_session.rollback()`. Suspect a cross-connection SQLite `:memory:` isolation quirk (NullPool default splits connections; StaticPool would share) but the existing unit-test machinery sidesteps this because `patched_async_sessions` routes everything through one factory bound to the same engine. The three remaining tests pass and cover the observable bus contract + session-lock release; the two deferred tests would pin the exact DB-rows-in contract. Retry when we revisit the test infrastructure pool config. Documented in the test file docstring.

### Phase 4 status

**6/8 symbols ship as fully real-DB** (server_settings ×2, secret_values ×2, file_sync, turn_worker control-flow). Two items were false positives (already real-FS-tested). Net: **Phase 4 done** per the track scope. `turn_worker.run_turn` full persistence assertions remain open.

## Phase 2 — integration_manifests shipped 2026-04-17

`tests/unit/test_integration_manifests.py`: 8 mock-based `_CapturingSession` tests → **48 real-DB + accessor tests**, all green in 2.3s. Full Phase 0/1/2 regression: **486 passed in 19.5s**.

Closes `integration_manifests.py` — previously at 0/6 public symbol coverage with a mock-only `seed_manifests` block. After this session: full coverage of `seed_manifests`, `load_manifests`, `update_manifest`, `get_yaml_content`, `get_manifest`, `get_all_manifests`, `get_capabilities`, `set_detected_provides`, `check_file_drift`, `collect_integration_mcp_servers`, `validate_capabilities`, `validate_provides`, `parse_integration_yaml`, `_file_hash`.

Phase 2 status: **6/25 → 8/25** critical-uncovered services covered. Two symbols crossed off [[Test Audit - Coverage Gaps]] §"Critical Service Symbols" (`update_manifest`, `set_detected_provides`) — and four high-tier symbols in the same file flipped covered as a side-effect (`check_file_drift`, `get_all_manifests`, `get_capabilities`, `get_yaml_content`). This is also a Phase 4 flip: the existing `seed_manifests` tests were mock-only and are now fully real-DB.

### Bug found + fixed

**Integration manifest cache corrupted by user-pasted YAML internals.** `update_manifest` and `load_manifests` both built the cache dict with `**data` / `**(row.manifest or {})` spread *last*. Python dict-literal merge semantics meant any top-level YAML key overrode the explicit trusted fields set above — so a YAML containing `content_hash:`, `source:`, `source_path:`, or `is_enabled:` would poison the in-memory cache. `check_file_drift` reads `content_hash` from the cache → poisoned value would silently lie about whether the disk file had drifted since seed. DB columns stayed correct (`update_manifest` only writes name/description/version/icon/manifest/yaml_content), so the divergence was cache-only — hard to spot without a real-DB test. Fix: moved `**data` / `**(row.manifest or {})` to the START of both dict literals so explicit DB-captured fields always win. TDD red-phase verified: pre-fix code failed `cached["content_hash"] == "real-hash-from-seed"` with `'user-pasted-fake-hash'`; post-fix both regression tests green. Full entry in [[Fix Log]].

### Files touched

- `tests/factories/integration_manifests.py` — new `build_integration_manifest(integration_id, **overrides)` factory.
- `tests/factories/__init__.py` — re-export.
- `tests/unit/test_integration_manifests.py` — full rewrite (8 mock tests → 48 real-DB + accessor tests).
- `app/services/integration_manifests.py` — `**data` / `**(row.manifest or {})` moved to start of cache dict literal in `update_manifest` + `load_manifests`.
- `vault/Projects/agent-server/Fix Log.md` — new entry.
- `vault/Projects/agent-server/Track - Test Quality.md` — Phase 2 entry + status table flip.

### Gotchas captured

1. **`_manifests` is a module-level dict — reset per test.** Autouse fixture `_reset_manifest_cache` in the test file clears before + after each test. Without this, cache state leaks across tests and `TestLoadManifests::test_when_rows_present_then_cache_populated` starts passing for the wrong reason (stale entries).
2. **`integration_manifests.py` uses function-local `from app.db.engine import async_session` imports** (not a module-level alias). So `patched_async_sessions`'s existing `patch.multiple("app.db.engine", async_session=factory)` handles it automatically — no new `_MODULE_LEVEL_ALIASES` entry needed.
3. **`**blob`-last in a cache dict literal is a latent corruption hazard.** Python evaluates dict literals left-to-right with later keys overriding earlier ones, so untrusted data (user YAML, request body, etc.) must spread FIRST if you want trusted fields below to win. Worth scanning the codebase for this pattern opportunistically. Grep candidate: `**data,\n    }` as the last line before `}`.
4. **SQLite + `asyncio_mode = "auto"` emits a warning for every sync test in a file with async tests** (pytest-asyncio complains about the auto-mark on non-coroutine functions). Pre-existing suite-wide noise — not a new issue. Per-class `@pytest.mark.asyncio` on the async classes only (no file-level `pytestmark`) doesn't silence it because auto mode marks everything. Skip optimizing.

## Phase 2 — outbox trio + server_config shipped 2026-04-17

20 new tests across 4 files. Full Phase 2 file regression: **77 passed in 4.4s**.

Closes 5 critical-uncovered service symbols in [[Test Audit - Coverage Gaps]] §"Critical Service Symbols":

- `outbox.reset_stale_in_flight` — added 3 tests in `tests/unit/test_outbox.py::TestResetStaleInFlight`. Covers no-op (zero IN_FLIGHT rows), single-row recovery (sets PENDING + last_error + available_at; does NOT increment attempts), and mixed-state recovery (only IN_FLIGHT touched; PENDING/DELIVERED siblings untouched).
- `outbox_publish.enqueue_for_targets` + `enqueue_new_message_for_channel` + `publish_to_bus` — new `tests/unit/test_outbox_publish.py` (7 tests). Exercises the no-target no-op log, real-DB target resolution end-to-end (channel resolves to `[("none", NoneTarget())]` because no integrations bound), the channel-missing silent-skip, and the swallow-on-resolve-targets-raises contract. `publish_to_bus` covered with a real `subscribe()` task.
- `outbox_drainer.outbox_drainer_worker` — added 4 tests in `test_outbox_drainer.py::TestDrainerWorkerLoop`. Drives the actual `while True` loop end-to-end via a `_cancel_after(N)` shim that patches `asyncio.sleep` to raise `CancelledError` on the Nth call. Covers happy-path drain, per-row exception isolation (loop continues, failed row stays IN_FLIGHT — the documented "isolation" contract that motivates `reset_stale_in_flight` at startup), idle sleep cadence, and `_claim_batch` exception → log + IDLE_SLEEP recovery.
- `server_config.update_global_fallback_models` + `update_model_tiers` — rewrote `tests/unit/test_server_config.py` (10 tests). Verified `pg_insert(...).on_conflict_do_update(...)` compiles cleanly against SQLite (both dialects support `ON CONFLICT(col) DO UPDATE`). Tests insert (no row), update (singleton already present + sibling-column non-clobber), empty-payload clear, and cache refresh after each call. Pre-existing mock-based `load_server_config` tests preserved.

### Files touched

- `tests/unit/test_outbox.py` — added `TestResetStaleInFlight` class (3 tests).
- `tests/unit/test_outbox_publish.py` — new file, 7 tests.
- `tests/unit/test_outbox_drainer.py` — added `import asyncio`, `_cancel_after` helper, `TestDrainerWorkerLoop` class (4 tests).
- `tests/unit/test_server_config.py` — full rewrite. Old: 4 mock-based tests. New: 10 tests (6 new real-DB + 4 retained mocks).

### Gotchas captured

1. **`pg_insert(...).on_conflict_do_update(...)` compiles fine on SQLite.** Both PG and SQLite dialects emit `INSERT ... ON CONFLICT(col) DO UPDATE SET ...`. No special-case handling needed for upsert services in unit tests. Confirmed via direct probe before writing tests.
2. **Patching `asyncio.sleep` is process-wide.** `patch("app.services.outbox_drainer.asyncio.sleep", ...)` actually replaces `asyncio.sleep` everywhere because `outbox_drainer.asyncio` IS the global module. The test-helper sleep replacement must NOT call `asyncio.sleep(0)` (infinite recursion via the patched mock); just return without awaiting. Caught after first run hit `RecursionError: maximum recursion depth exceeded`.
3. **Patching a function then calling it from inside the patch is recursion.** `patch("...module._deliver_one", side_effect=lambda r: ... await module._deliver_one(r))` recurses. Capture the original via local-binding before patching: `original = module._deliver_one`, then call `original(r)` from the side-effect.
4. **Drainer per-row exception leaves the row IN_FLIGHT permanently within a single process lifetime.** `_deliver_one` raising is caught at the loop level and logged, but the row is never `mark_failed`'d — it stays IN_FLIGHT until the next process restart calls `reset_stale_in_flight`. This is the documented isolation contract; the test now codifies it explicitly (`first.delivery_state == IN_FLIGHT.value` after the simulated crash).

### Bugs found

None. All 5 services behaved as documented under real-DB exercise.

## Phase 2 — bot_hooks shipped 2026-04-17

`tests/unit/test_bot_hooks.py`: 7 mock-only helper tests → 33 real-DB + helper tests, all green in 1.8s. Full regression across phase 0/1a/1b/1c/1d/1e + Phase 2: 394 passed in 13.9s.

Module `app/services/bot_hooks.py` was at 0/8 critical-symbol coverage in [[Test Audit - Coverage Gaps]]. After this session: full coverage of `create_hook`, `update_hook`, `delete_hook`, `list_hooks`, `load_bot_hooks`, `run_before_access`, `run_after_exec`, `schedule_after_write`, plus the four pure helpers (`_matches_conditions`, `_find_matching_hooks`, `_check_cooldown`, indirect `_execute_hook` via the trigger pathways).

- **Factory added** (`tests/factories/bot_hooks.py`): `build_bot_hook(bot_id, **overrides)` returns a real `BotHook` ORM instance with sensible defaults (uuid `id`, `before_access` trigger, glob `path`, `cooldown_seconds=60`, `on_failure="block"`, enabled). Re-exported from `tests/factories/__init__.py`.
- **Infra added** (`tests/unit/conftest.py`): `app.services.bot_hooks.async_session` added to both `_MODULE_LEVEL_ALIASES` and the `patched_async_sessions` patch chain. Same gotcha as Phase 1d/1e — `bot_hooks.py:14` does `from app.db.engine import async_session` at module level, so the local alias must be patched separately.
- **Test classes**:
  - `TestCreateHook` (4) — happy-path persists row + caches; `before_access` trigger defaults `on_failure="block"`; `after_write` defaults `"warn"`; `enabled=False` skips cache.
  - `TestUpdateHook` (3) — fields persist + cache reload; cross-bot returns None + leaves row untouched; missing id returns None.
  - `TestDeleteHook` (3) — row gone + sibling untouched + cache cleaned + cooldown cleared (extra-mile via `select(BotHook.id)` round-trip — identity-map gotcha from Phase 1d); cross-bot returns False + row preserved; missing id returns False.
  - `TestListHooks` (1) — only target bot's hooks (including disabled).
  - `TestLoadBotHooks` (1) — only enabled hooks loaded, grouped by `bot_id`.
  - `TestMatchesConditions` (4) — glob match / no-match / no-conditions matches all / unknown key falls through to no-match.
  - `TestFindMatchingHooks` (3) — wrong trigger excluded, no hooks empty, re-entrancy guard via `_hook_executing.set(True)`.
  - `TestCheckCooldown` (4) — first call allowed, second blocked, `cooldown_seconds=0` allows consecutive, per-hook independence.
  - `TestRunBeforeAccess` (5) — success returns None, `block` failure returns error string, `warn` failure returns None, no matching hooks no-exec, workspace-disabled triggers the failure path through `_execute_hook`'s early-return.
  - `TestRunAfterExec` (2) — success invokes exec; failure swallowed.
  - `TestScheduleAfterWrite` (3) — no matching hook no timer, no running loop returns silently, rapid calls cancel + replace pending TimerHandle.
- **Cache hygiene**: `_reset_hook_caches` autouse fixture clears `_hooks_by_bot` / `_cooldowns` / `_pending_after_write` (cancelling any leaked TimerHandles) before and after each test (B.28).
- **Mocks**: only `workspace_service.exec` (E.1 — subprocess external) and the `bot_registry` harness (in-memory dict, not a DB lookup; pre-existing fixture from Phase 1c).

### Gotchas captured

1. **`app/services/bot_hooks.py:14` is the next module-level alias** (after `tasks.py`, `workflow_executor.py`, `compaction.py`, `agent.tasks`). `_MODULE_LEVEL_ALIASES` now lists six entries — append the next one when a real-DB test fails with `no such table` despite both `db_session` and `patched_async_sessions` confirming the table exists in the engine.
2. **Identity-map masks cross-session deletion** (still): `delete_hook` opens its own session and commits a `db.delete(row)`. `db_session.get(BotHook, id)` afterwards returns the cached row. Use `db_session.execute(select(BotHook.id).where(...))` to force a round-trip — same fix as Phase 1d's merge-deletion test.
3. **`_execute_hook`'s `bot.workspace.enabled` check is the only path where a `block`-trigger fails without invoking exec**: `bot_registry.register("bot-A", workspace=WorkspaceConfig(enabled=False))` exercises it. `assert_not_awaited()` on the exec mock + presence of the hook name in the returned error string is the smoking gun.

## Phase 1e — shipped 2026-04-17

`tests/unit/test_workflow_advancement.py`: 1652 → ~700 LOC, 35 mock-heavy tests → 38 real-DB tests, all green in 2.9s. Full regression across phase 0/1a/1b/1c/1d/1e: 361 passed in 14s.

- **Bug caught + fixed**: `app/agent/tasks.py:1532-1536` (Scenario 2 recovery path) used the `list(run.step_states)` shallow-copy + `fresh_run.step_states = ss` direct-assign pattern with no `flag_modified`. On PostgreSQL this silently skips the JSONB UPDATE, leaving the stalled run in the same state the recovery was supposed to fix. Swapped to the canonical `copy.deepcopy` + `_set_step_states(...)` pattern (imported from `workflow_executor`). TDD red-phase verified: reverted fix → new behavioral test fails with `'running' != 'failed'`; re-applied → passes.
- **Infra added** (`tests/unit/conftest.py`): `patched_async_sessions` now also patches `app.agent.tasks.async_session`. `tasks.py` imports `from app.db.engine import async_session` at module level (line 14), so patching only the source didn't retarget the local alias — same gotcha pattern as Phase 1d's `app.tools.local.skills.async_session`.
- **Deletions**:
  - `TestOnStepTaskCompletedLocking::test_uses_with_for_update` — B.23. Asserts `db.get` was called with `with_for_update=True`. Implementation detail; the row-lock semantics aren't observable on SQLite anyway (it's a no-op there), and the behavioral contract (no lost updates under concurrent completions) is better exercised by integration tests against real PG.
- **Rewrites** (all other DB-touching classes):
  - `TestFireTaskComplete` (5 tests) — real `Task` rows via factory; external hooks patched per skill E.1.
  - `TestOnStepTaskCompleted` (4) — real `WorkflowRun` + `Workflow` + `Task` rows round-trip; asserts the persisted `step_states[i]["result"]` / `error` / `correlation_id` after `refresh(run)`.
  - `TestRecoveryAllPendingStalls` (3), `TestRecoveryAllTerminalStalls` (2), `TestRecoveryRunningStepNoTask` (1 — regression guard for the bug above).
  - `TestRunTaskWorkflowSession` (1) — real `Channel` + `Task` rows, `session_locks.acquire=False` to defer past the session-resolution check.
  - `TestExecutionCap` (2), `TestCancelWorkflow` (1 — real cascaded UPDATE on pending `Task` rows keyed by `callback_config["workflow_run_id"]`; SQLite's JSON subscript works here).
  - `TestRecoverStuckTasks` (2), `TestFetchDueTasks` (1), `TestAdvancementLock` (1).
  - `TestWorkflowSnapshot` (4) — `trigger_workflow` + `_get_run_definition` + `_advance_workflow_inner` snapshot round-trip.
  - `TestExecStepType` (1), `TestToolStepType` (4) — inline tool execution (`call_local_tool` patched; step state round-tripped via real DB).
  - `TestAtomicTaskCreation` (2), `TestTriggerWorkflowFreshReturn` (1).
  - `TestSetStepStates` (1) — helper invariant kept as-is.
  - `TestNoShallowCopyRegression` (2) — source-code regex guards kept. Note: they scan only `workflow_executor.py`, not `tasks.py` — the Phase 1e bug slipped past. Expanding the guard to walk the whole app tree is a candidate follow-up.

- **Shared helper** (in-file): `_seed_workflow_and_run(db_session, *, steps, step_states, run_status, run_overrides, workflow_overrides)` persists a linked `Workflow` + `WorkflowRun` pair with a default `workflow_snapshot`. Keeps arrange phase under the A.3 10-statement bound across every DB test.

### Gotchas captured

1. **`tasks.py` imports `async_session` at module level** (line 14: `from app.db.engine import async_session`). Patching only `app.db.engine.async_session` doesn't retarget this local alias. Added `app.agent.tasks.async_session` to `patched_async_sessions`; the `_MODULE_LEVEL_ALIASES` tuple now serves as the canonical list of known offenders.
2. **Regression guard scope is file-local**: `TestNoShallowCopyRegression` regex tests in `workflow_executor.py` didn't catch the exact bug pattern inside `tasks.py`. Either broaden the scan (iterate over `app.**`) or write symmetrical per-module guards for each file that holds its own JSONB mutation path.
3. **`cancel_workflow`'s JSONB UPDATE works on SQLite**: `Task.callback_config["workflow_run_id"].as_string()` translates to `json_extract(callback_config, '$.workflow_run_id')` on SQLite. No special-case handling needed in tests.
4. **`_advance_workflow_inner` re-commits inside tool-step loops**: when a workflow mixes tool + agent steps, the executor commits after each tool step (line 613) and again when it pauses on an agent step (line 645). The `_set_step_states` call before each commit makes this safe; without `flag_modified` the second commit would see `old == new` for the JSONB column and no-op.

## Phase 1d — shipped 2026-04-17

`tests/unit/test_manage_bot_skill.py`: 2070 → 1723 LOC, 134 tests green in 4.7s (full file) and 323 tests green across phase 0/1a/1b/1c/1d regression in 11.1s. All DB-touching CRUD classes rewritten end-to-end against the real `db_session` + `patched_async_sessions` + `agent_context` infrastructure.

- **Infra added** (`tests/unit/conftest.py`):
  - `embed_skill_patch` — patches `app.agent.skills.re_embed_skill` (the underlying external) rather than the `_embed_skill_safe` wrapper, so the wrapper's try/except + True/False return stays real code under test.
  - `dedup_patch` — patches `app.tools.local.bot_skills._check_skill_dedup` (pgvector / `halfvec_cosine_distance` — legit E.1 exception). Default returns `None`; duplicate-rejection tests set `.return_value = json.dumps({...})`.
  - `bot_skill_cache_reset` — opt-in teardown fixture that clears the three module-level caches `_invalidate_cache` touches: `app.agent.context_assembly._bot_skill_cache`, `app.agent.rag.invalidate_skill_index_cache()`, `app.agent.repeated_lookup_detection._cache`. Test file opts in via `pytestmark = pytest.mark.usefixtures("bot_skill_cache_reset")` — NOT autouse (would affect 100+ other unit tests).
  - `patched_async_sessions` extended with `app.tools.local.skills.async_session` (module-level alias inside `skills.py`, needed for `TestGetSkillAccess::test_when_get_skill_called_for_*`).

- **Factory added** (`tests/factories/bot_skills.py`):
  - `build_bot_skill(bot_id, name="my-skill", **overrides)` — bot-authored Skill row with `id=f"bots/{bot_id}/{slug(name)}"`, `source_type="tool"`, deterministic `content_hash = sha256(content).hexdigest()`. Distinct from existing `build_skill` (classic skills, `id="skills/{uuid}"`).

- **Rewrites** (16 DB-touching classes — one-line summary each):
  - `TestList` (3) — real rows + filter-by-bot-id assertion.
  - `TestGet` (3) — seeded skill, not-found, missing-name error.
  - `TestGetSkillAccess` (3) — real DB exercise of `app.tools.local.skills.get_skill` for own/other-bot skills.
  - `TestCreate` (8) — happy path (DB row round-trip, `source_type="tool"`, triggers/category/description synced), missing fields, duplicate by-ID, invalid name, dedup-rejected, `force=True` bypasses dedup.
  - `TestUpdate` (6) — content + hash refresh, frontmatter merge preserves category, no-op update error, file-managed rejected.
  - `TestDelete` (6) — archives `target` while siblings untouched (extra-mile), restore, already-archived errors.
  - `TestPatch` (5) — content/hash refresh, triggers column synced, description synced, file-managed rejected.
  - `TestCountWarning` (3) — real count via `_check_count_warning`, plus end-to-end create-near-threshold test.
  - `TestListPagination` (3) — limit/offset round-trip, limit clamp 100, preview truncation 120.
  - `TestEmbeddingStatus` (2) — `re_embed_skill` raises → `"Warning: embedding failed"` in message (exact-string equality on the full result dict — smoking gun).
  - `TestSurfacingStats` (1) — last_surfaced_at + surface_count round-trip.
  - `TestListStaleHints` (4) — stale flag, singular/plural grammar hints, no-hint-when-fresh.
  - `TestMergeAction` (11) — source skills deleted + target persisted via fresh `SELECT Skill.id` query (identity-map bypass), target=one-of-sources allowed, target=other-preexisting rejected, file-managed source rejected.
  - `TestEdgeCases` (7) — offset past end, negative offset clamping, zero-limit clamping, patch size validation, file-managed patch rejected, empty `new_text` rejected.
  - `TestValidation` async tests (3) — rewritten; pure-function tests (5) A.1-renamed in place.

- **Group A A.1 renames** (8 pure-function classes, 35 tests): `TestBotSkillHelpers`, `TestValidation`, `TestFrontmatterSanitization`, `TestIsStale`, `TestUnknownAction`, `TestSecurity`. Bodies untouched.

- **Deletions / scope decisions**:
  - `TestSkillDedup` (3 tests) — deleted outright. Dedup is a branch of the `create` action and is covered by two tests in `TestCreate` (`test_when_dedup_finds_similar_skill_then_create_rejected` + `test_when_force_true_then_dedup_bypassed`). Keeping it separately was pure duplication.
  - `test_cross_bot_rejected` in TestUpdate and `test_delete_rejects_cross_bot` in TestEdgeCases — deleted outright. The cross-bot check at `bot_skills.py:382/437/460/484/561` is structurally unreachable via the public API: `_bot_skill_id(bot_id, name)` either strips this bot's prefix or slug-cleans the slashes away, so the caller can never land on another bot's skill. Defensive guards with no reachable code path.
  - **Off-target classes LEFT ALONE** per scope decision (~35 tests, Group B): `TestCacheInvalidation`, `TestSkillNudge`, `TestCorrectionNudge`, `TestRepeatedLookupDetection`, `TestBroadenedCorrectionRegex`, `TestEmbedSkillSafe`. They assert real behavior of other modules (caches, prompt strings, regex constants) — working coverage in the wrong file, not broken tests. Revisit in a separate organization pass. `_mock_session` helper kept for those classes; `_make_skill_row` + `_parse` deleted (unused).

### Gotchas captured

1. **Identity-map masks merge deletions**: `await db_session.get(Skill, id)` after `manage_bot_skill(action="merge", ...)` returns the still-cached source row even though the merge opened its own session and committed a `db.delete(row)`. `db_session.expire_all()` throws `MissingGreenlet` on AsyncSession mid-test. Fix: assert via a fresh `await db_session.execute(select(Skill.id).where(...))` which always round-trips to the DB.
2. **`app.tools.local.skills.async_session` is a module-level alias**: `from app.db.engine import async_session` at the top of `app/tools/local/skills.py` binds at import time; patching only `app.db.engine.async_session` doesn't retarget it. `patched_async_sessions` now covers five known aliases; append new ones whenever a `get_skill`-style test fails with a real-DB schema-missing error.
3. **`_embed_skill_safe` wraps `re_embed_skill` — patch the outer external**: patching `_embed_skill_safe` itself lets the wrapper's try/except + True/False return go uncovered. Patch `app.agent.skills.re_embed_skill`; set `.side_effect = RuntimeError(...)` to exercise the `False` branch.
4. **`dedup_patch` returns JSON STRING, not dict**: `_check_skill_dedup` returns `json.dumps({...})` or `None`. Tests that exercise the duplicate-rejected path must `m.return_value = json.dumps({...})`, and `manage_bot_skill` will return that string verbatim — the result shape is checked via `json.loads(await manage_bot_skill(...))`.
5. **`bot_skill_cache_reset` must be opt-in**: autouse in `tests/unit/conftest.py` would add teardown cost to every unit test. Scope via `pytestmark = pytest.mark.usefixtures("bot_skill_cache_reset")` at the top of files that touch these caches.

## Phase 1c — shipped 2026-04-17

`tests/unit/test_multi_bot_channels.py`: 88 → 78 tests, all green against real `db_session` + `patched_async_sessions` + `bot_registry` + `agent_context`. Full regression across phase 0/1a/1b/1c files: 189 passed.

- **Infra (`tests/unit/conftest.py`)**: new `bot_registry` fixture snapshots/restores `app.agent.bots._registry`. Yields a helper with `register(bot_id, **overrides)` that constructs a minimal `BotConfig` and inserts it. Solves the "get_bot is an in-memory dict lookup, not a DB query" blocker from the Deep Review. Also extended `patched_async_sessions` to cover `app.services.compaction.async_session` (needed by `_flush_member_bots`).
- **Deletions**: 14 self-validating tests dropped — 4 from `TestContextInjection` (pure-string awareness-message format), 5 from `TestMultiBotIdentity` (class merged into `TestContextInjection`), 4 from `TestAntiLoop` (pure `ContextVar` semantics, not product code), 1 from `TestParallelInvocation`.
- **Rewrites (all DB-touching classes)**:
  - `TestMemberBotRouting` (10) — `_maybe_route_to_member_bot` driven against real `Bot` / `Channel` / `ChannelBotMember` rows. `test_when_member_bot_id_missing_from_registry_then_falls_through` deliberately omits `bot_registry` → real `get_bot()` raise → real fall-through.
  - `TestAntiLoop` (3 surviving) — drives `DelegationService.run_immediate` via `agent_context`.
  - `TestContextInjection` (2) — `_run_member_bot_reply` with real `Channel` row + `bot_registry`; verifies primary bot's system messages are stripped and member persona is injected.
  - `TestMemberBotFlush` (5) — real `Channel` + `ChannelBotMember` rows. `test_when_db_load_fails_then_exception_swallowed_and_no_flush` makes the contract explicit per `compaction.py:358` (DB error is swallowed and logged at debug).
  - `TestDetectMemberMentions` (6) — real DB + `bot_registry`; display-name resolution, case-insensitive matching, deduplication.
  - `TestBotToBotMention` (10) — `_trigger_member_bot_replies` return value is the real observable. `_run_member_bot_reply` patched to no-op AsyncMock to prevent the LLM stack from running.
  - `TestPrimaryBotMentionBack` (3) — consolidated four individual depth-chain asserts into one tuple-equality assertion across depths 0/1/2/3.
  - `TestParallelInvocation` (7) — no `asyncio.create_task` patching; `await asyncio.sleep(0)` to let background tasks land on the patched `_run_member_bot_reply` spy so we can assert on its real `await_args.kwargs["messages_snapshot"]`.
- **Renames**: 31 A.1 renames across the 5 pure-function classes (`TestRewriteHistoryForMemberBot`, `TestInjectMemberConfig`, `TestApplyUserAttribution`, `TestMetadataPreservation`, `TestIsPrimaryRewriting`) — bodies already compliant, just title template.
- **Cleanup**: transitional `_make_member_row` / `_mock_db_with_member_rows` helpers deleted; `MagicMock` import removed (no longer needed).

### Gotchas captured

- `BotConfig` is a non-slotted dataclass → tests needing `memory_scheme` (which is on the `Bot` ORM row, not `BotConfig`) post-set the attribute directly on the registry entry: `_bot_reg["helper"].memory_scheme = "workspace-files"`. Ugly but minimal; a cleaner fix would be to thread `memory_scheme` through `bot_registry.register()`.
- `_trigger_member_bot_replies` tests that assert on captured kwargs need `await asyncio.sleep(0)` after the call — the function schedules a background task via `asyncio.create_task`, and the spy only sees the kwargs after one event-loop turn.
- Module-level `from app.db.engine import async_session as _async_session` inside `_multibot.py`'s function bodies picks up `patched_async_sessions`'s patch of `app.db.engine.async_session` at call time — no extra patching needed for that module.

## Phase 1b — shipped 2026-04-17

- `tests/unit/test_task_tools.py` rewritten. 18 tests green in 2.39s under Docker. Down from 17 mock-heavy tests (including the 4-test `TestHeartbeatPatchNull` re-implementation class, deleted outright per Deep Review).
- `TestResolveTemplate` (3) exercises `_resolve_template` against real `db_session` + seeded `PromptTemplate` rows — covers the existing-template / auto-create-manual / raises-if-missing branches.
- `TestScheduleTask` (2) drives `schedule_task` through `patched_async_sessions` + `agent_context`. Extra-mile assertion verifies the `Task` row actually persisted (bot_id, prompt, status).
- `TestListTasksDetailMode` (4) and `TestListTasksListMode` (2) seed real Task/PromptTemplate rows via factories and assert the JSON payload shape — including the internal-task-type filter (`callback` hidden from default listing).
- `TestUpdateTask` (7) seeds real Task rows and verifies each mutation (scheduled_at, prompt, recurrence add/remove, bot change, no-changes error, wrong-status error). `resolve_bot_id` is the only surface still patched — it's an in-memory registry, not a DB lookup, so patching is legitimate per skill E.1.
- Deleted `TestHeartbeatPatchNull` entirely — the class inlined production loop logic and asserted against the copy. Covered the wrong thing; replacement belongs in a heartbeat endpoint / integration test.

### Infrastructure gotcha captured

`PromptTemplate.id` uses `server_default=text("gen_random_uuid()")` with no Python-side `default=uuid.uuid4`. The engine fixture strips the PG function for SQLite → INSERT fails with NOT NULL violation. Setting `col.default = ColumnDefault(uuid.uuid4)` post-construction does **not** re-register with SA's insert machinery. Fix in `tests/conftest.py`: scan for columns with stripped `gen_random_uuid()` server_defaults on UUID primary keys, and register a `Session.before_flush` listener that fills any missing PK. Uses `sqlalchemy.orm.Session` (the class), so every AsyncSession wrapper picks it up automatically. Verified no regressions across `test_memory_hygiene.py` + `test_phase0_smoke.py` (93 tests green).

## Phase 1a — shipped 2026-04-17

- `tests/unit/test_memory_hygiene.py` rewritten end-to-end. 87 tests, all green in 2.80s under Docker.
- Every DB-touching class now uses the real `db_session` fixture + (where the service opens its own session) the `patched_async_sessions` fixture from `tests/unit/conftest.py`. Real `Bot` / `Channel` / `ChannelBotMember` / `Session` / `Message` rows via `tests/factories`.
- `TestHasActivitySince::test_query_includes_member_channels` — the SKILL.md canonical anti-pattern (asserting on compiled SQL strings) — replaced with a behavioural test: insert a member channel, post a user message in it, assert `_has_activity_since(member_bot.id, ...)` returns True.
- Kept MagicMock usage only in `TestDiscoveryAuditSnapshot` (PG-specific JSONB SQL that doesn't run on SQLite — acceptable per skill rule E.1) and `TestBotChannelFilter` (SQL builder is the unit under test, per the exception in the SQL-string-inspection rule).
- Replaced every `_make_bot_row()` / `_make_bot` MagicMock helper with `build_bot(...)` factory calls.
- Test titles updated to the `test_when_<scenario>_then_<expectation>` template.

### Infrastructure gotcha captured

SQLite dialect substitutes `sqlalchemy.dialects.sqlite.base.DATETIME` for any `DateTime`/`TIMESTAMP` column via `colspecs` — patching `PG_TIMESTAMP.result_processor` has no effect because SQLite's dialect never calls it. Fix lives in `tests/conftest.py`: wrap `_SQLITE_DATETIME.result_processor` to coerce naive results to UTC-aware. Now every TIMESTAMP(timezone=True) column in the real-DB test path round-trips tz info, matching Postgres semantics. Verified no regressions in 64 unit tests spanning `test_compaction*`, `test_session*`.

## Phase 0 — shipped 2026-04-17

- `tests/factories/`: `build_bot`, `build_channel`, `build_channel_bot_member`, `build_skill`, `build_bot_skill_enrollment`, `build_task`, `build_prompt_template`, `build_workflow`, `build_workflow_run` — all return real ORM instances with sensible defaults.
- `tests/unit/conftest.py`: `patched_async_sessions` (points `tasks.py` / `workflow_executor.py` / `app.db.engine.async_session` at the test engine) and `agent_context` (snapshot/restore for 10 ContextVars).
- `tests/unit/test_phase0_smoke.py`: 6 smoke tests covering factory round-trip, JSONB `step_states` persistence, service-owned `async_session()` routed to test DB, ContextVar teardown. All green.
- `db_session` + engine fixtures already live in `tests/conftest.py` (from earlier refactor); re-exported by `tests/integration/conftest.py`.

Gotcha captured: `ContextVar.reset(token)` fails across pytest-asyncio's context boundary. The fixture uses `.set()` snapshot/restore instead of tokens. Delete smoke tests once Phase 1 pilot lands.

# Track — Test Quality

## North Star

Stop mock-theatre tests. Close critical coverage gaps. Every test either runs against a real SQLite-in-memory DB or has no DB surface at all. Skill `testing-python` enforces the rules.

## Why this matters

- **1,643 mocked-session hits** across the unit suite — those tests accept nonsense queries and pass
- **25 critical services** and **60 critical admin routes** are uncovered — mutating paths with zero real exercise
- **151 test files** import `MagicMock`/`AsyncMock` but never touch a real session — pure ceremony
- Integration suite is clean; the problem is almost entirely in `tests/unit/`

See the raw data: [[Test Audit - Inventory]], [[Test Audit - Coverage Gaps]].

## Status

| Phase | Scope | Size | Status |
|---|---|---:|---|
| 0 | **Shared infrastructure** (factories, promoted `db_session`, patched session fixtures, `agent_context` fixture) | 6–8h | done (2026-04-17) |
| 1a | Pilot rewrite — `test_memory_hygiene.py` | ~40 tests, 5–6h | done (2026-04-17) |
| 1b | `test_task_tools.py` (delete 4 tests outright, rewrite rest) | ~25 tests, 3–4h | done (2026-04-17) |
| 1c | `test_multi_bot_channels.py` (delete ~15 re-implementation tests) | ~55 tests, 9–11h | done (2026-04-17) |
| 1d | `test_manage_bot_skill.py` (needs Phase 0 fixtures) | ~60 tests, 10–12h | done (2026-04-17) |
| 1e | `test_workflow_advancement.py` (JSONB `step_states` + `flag_modified`) | 38 tests | done (2026-04-17) |
| 2 | Write tests for 25 critical uncovered services | 25 symbols | **done** (2026-04-18 — all 25+ covered; 2 false positives cleared; pre-existing `TestDispatchAlert` regression fixed) |
| 3 | Write tests for 60 critical uncovered admin routes | 60 endpoints | **done** (67/60 — bots 9 + providers 11 + webhooks 5 + mcp_servers 5 + attachments 2 + limits 5 + secret_values 5 + settings 4 + operations 7 + docker_stacks 7, 2026-04-18) |
| 4 | Replace mock-only coverage for 8 critical services | 8 files | done (2026-04-17 — 6/8 real-DB, 2 were audit false positives, `turn_worker` full-persist deferred) |
| 5 | Mechanical A.13 cleanup (try/except, loops, prints in tests) | 194 hits | opportunistic |

**Corrected ordering (per Deep Review):** ship shared infrastructure first; then the smallest/most regular file (`test_memory_hygiene.py`) as the pilot to validate the patterns; then `test_task_tools.py` (fast, has deletable tests); then the two beasts last. Total: ~230 tests, ~45h + 8h infra ≈ 1.5–2 focused weeks.

## Phase 1 — Refactor the 5 headline offenders

These five files account for ~600 of 1,643 session-mock hits. Fix them first — biggest leverage per unit of effort.

| # | File | E.13 hits | Rewrite size |
|---:|---|---:|---|
| 1 | `tests/unit/test_multi_bot_channels.py` | 183 | large |
| 2 | `tests/unit/test_manage_bot_skill.py` | 180 | large |
| 3 | `tests/unit/test_task_tools.py` | 87 | medium |
| 4 | `tests/unit/test_workflow_advancement.py` | 72 | medium |
| 5 | `tests/unit/test_memory_hygiene.py` | 64 | medium |

**Approach:** per file, swap `MagicMock()` sessions for the real `db_session` fixture (from `tests/integration/conftest.py`), build factories for the dominant model(s), and use the smoking-gun pattern (arrange → act → assert against arranged values). See `skills/testing-python/references/refactoring-recipes.md` Recipe 1.

**Deep-review artifact:** [[Test Audit - Deep Review]] will land here with file:line violation reports and sample before/after for each of the 5.

**Sessions estimated:** 2–3. Each file is its own focused session; don't batch.

## Phase 2 — Write tests for 25 critical uncovered services

Top of the list (full 25 in [[Test Audit - Coverage Gaps]]):

- `bot_hooks.py` — `create_hook`, `update_hook`, `delete_hook`, `run_before_access`, `run_after_exec`, `schedule_after_write` (6 symbols, no tests at all)
- `outbox.py` — `reset_stale_in_flight`
- `outbox_drainer.py` — `outbox_drainer_worker`
- `outbox_publish.py` — `publish_to_bus`
- `server_config.py` — `update_global_fallback_models`, `update_model_tiers`
- `workflows.py` — `create_workflow`
- `attachments.py` — `delete_attachment`
- `channel_events.py` — `publish_message`, `publish_message_updated`
- `turn_event_emit.py` — `emit_run_stream_events`
- `integration_manifests.py` — `update_manifest`, `set_detected_provides`
- others

**Approach:** one test module per service module. Real `db_session`. Factory per model. Cover happy path + one critical error per public entry.

**Sessions estimated:** 2–3.

## Phase 3 — Write tests for 60 critical uncovered admin routes

Concentrated in:

- `api_v1_admin/bots.py` — 9 uncovered mutating routes
- `api_v1_admin/providers.py` — 11 uncovered routes (CRUD + test-inline)
- `api_v1_admin/webhooks.py` — 5 uncovered
- `api_v1_admin/mcp_servers.py` — 5 uncovered
- `api_v1_admin/operations.py`, `docker_stacks.py`, `secret_values.py`, `limits.py`, others

**Approach:** one test module per router. Use the real FastAPI `AsyncClient` + `ASGITransport` pattern from `skills/testing-python/references/fastapi-httpx-testing.md`. For each route: happy path + auth-denied case (Deliberate Fire — viewer role hits admin endpoint → 403).

**Sessions estimated:** 2.

## Phase 4 — Replace mock-only coverage

8 critical services have tests that only use `MagicMock`. Per the skill, that's nearly equivalent to no coverage.

- `channel_workspace.delete_workspace_file`
- `file_sync.sync_all_files`
- `memory_scheme.bootstrap_memory_scheme`
- `secret_values.create_secret`, `delete_secret`
- `server_settings.reset_setting`, `update_settings`
- `turn_worker.run_turn`

**Approach:** keep the existing test titles (they describe the right scenarios) but rewrite the bodies using the real `db_session` pattern. Use this as a calibration exercise — these files should be fast to fix once Phase 1 established the factory patterns.

**Sessions estimated:** 1.

## Phase 5 — Mechanical A.13 cleanup

194 flat-structure violations scattered across the suite. Don't batch. Fix opportunistically when a file is touched for another reason. Biggest clusters:

- `test_assembly_budget.py` (18)
- `test_channel_events.py` (14)
- `test_channel_renderers.py` (14)
- `test_compaction_comprehensive.py` (12)
- `test_tool_discovery.py` (12)

## Key invariants

- The skill `testing-python` is the rule source. Link it in PR descriptions when refactoring tests.
- `db_session` fixture in `tests/integration/conftest.py` is the canonical real-DB fixture. Reuse it — do not reinvent.
- `tests/factories/` doesn't exist yet. Phase 1 creates it. Every new factory goes there, typed, with sensible defaults.
- `A.1` (test title style) is cosmetic — never stand up a dedicated session for it.
- `B.3` (magic literals) came back 0 in the audit; the heuristic was conservative. Re-scan with stricter rules if it becomes a priority.

## References

- [[Test Audit - Inventory]] — raw smell counts per file
- [[Test Audit - Coverage Gaps]] — uncovered / mock-only service & route inventory
- [[Test Audit - Deep Review]] — file-level violation reports + before/after samples (pending)
- Skill: `~/.claude/skills/testing-python/SKILL.md` and its `references/`

## Out of scope

- E2E tests (`tests/e2e/`) — different concerns, different skill
- UI tests — ui/ has its own tooling
- Performance / load tests
