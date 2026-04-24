---
tags: [testing, quality, refactor]
status: active
updated: 2026-04-24 (Q-MACH shipped; Q-SEC/Q-CONC/Q-CHURN backlog still queued from 3-agent audit)
next-up: Phase Q-SEC (widget-token scope-ceiling + SSRF horizontal coverage + webhook replay drift) or Q-CONC (loop_dispatch gather isolation + tokenization cascade + SSE back-pressure + rerank pathological + bus publisher isolation) — pick one next session
last-shipped: Phase Q-MACH (admin `/machines` router + `local_companion` WS handshake drift — 36 new tests, 1 pre-existing broken test revived) 2026-04-24
last-shipped: Phase P2 (stale unit-test cleanup — 12 flips across `test_model_params_llm` + `test_dashboard_pins_service`, the two pre-existing broken-test entries from Loose Ends 2026-04-23 closed) 2026-04-24
last-shipped: Phase O (Machine Control drift sweep — `validate_current_execution_policy` gates + lease lifecycle + provider cache + multi-session lease sync) 2026-04-23
last-shipped: Phase P (Loose Ends closure — L.1 heartbeat recovery + J.5 JWT jti + I.5 attribution regex + N.3 cache invalidation) 2026-04-23
last-shipped: Phase N (N.1 widget preset 7 + N.2 envelope 5 + N.2 FIX + N.3 channel-skill 9 + N.4 session_plan 13 + N.4 FIX + N.5 rerank 9 + N.6 approval lifecycle 12 + N.6 FIX x2 + N.7 context-assembly bot cache 11 + N.8 outbox drainer 13 + broken-neighbors revived) 2026-04-23
last-shipped: Phase M (OpenAI Responses adapter 27 tests + widget_packages_seeder 13 tests) 2026-04-19
last-shipped: Phases I–L (60 tests — ingest contract, widget-auth scope ceiling, dashboard pin drift, background-task ordering — 3 REAL BUGS pinned) 2026-04-19
totals: ~1137+ tests across Phases 0–Q-MACH; 13 real bugs fixed in code (Phase P closed the 4 drift-pinned Loose Ends; P2 reclaimed 12 pre-existing broken unit tests; Q-MACH reclaimed 1 pre-existing broken test and added 36 drift pins — no new production bugs); 0 open drift-pinned bugs
---

# Track — Test Quality

## North Star

Stop mock-theatre tests. Close critical coverage gaps. Every test either runs against a real SQLite-in-memory DB or has no DB surface at all. Skill `testing-python` is the rule source.

## Why this matters (state as of 2026-04-23)

- The five 2026-04-17 headline E.13 offenders were retired by Phases 1a–1e; the top-20 has rotated completely.
- 25/25 critical service symbols + 67/60 critical admin routes now covered (Phases 2 + 3).
- Drift-pin cycles (Phases D, E–L) found + pinned 5 real bugs; 2 fixed in same commit, 3 live in [[Loose Ends]].
- Absolute E.13 went **up** (1643 → ~2200) as new test files kept the mock-session pattern. Top-20 entirely changed shape — refactor backlog has rotated, not shrunk.
- New surfaces shipped after Phase M (widget presets, native envelope repair, channel-skill injection, session plan SSE, rerank header contract) are **entirely unaudited** — Phase N queues the next cycle.

## Shipped phases

| Phase | Scope | Date | Tests | Notable finding |
|---|---|---|---:|---|
| 0 | Shared infra: factories, `db_session`, `patched_async_sessions`, `agent_context` | 2026-04-17 | 6 | tz-aware SQLite DATETIME wrapper shipped via `tests/conftest.py` |
| 1a | `test_memory_hygiene.py` rewrite | 2026-04-17 | 87 | SQL-string-inspection anti-pattern replaced with behavioral test |
| 1b | `test_task_tools.py` rewrite | 2026-04-17 | 18 | `TestHeartbeatPatchNull` deleted outright (tested the wrong thing) |
| 1c | `test_multi_bot_channels.py` rewrite | 2026-04-17 | 78 | `bot_registry` fixture introduced |
| 1d | `test_manage_bot_skill.py` rewrite | 2026-04-17 | 134 | identity-map bypass via `select(.id)` cross-session pattern |
| 1e | `test_workflow_advancement.py` rewrite | 2026-04-17 | 38 | **BUG FIXED**: `tasks.py:1532` shallow-copy `step_states` JSONB silently skipped PG UPDATE |
| 2 | 25 critical service symbols (`bot_hooks`, `outbox*`, `server_config`, `integration_manifests`, others) | 2026-04-17/18 | ~150 | **BUG FIXED**: `integration_manifests` cache corruption via `**data`-last spread ordering |
| 3 | 67/60 critical admin routes (bots, providers, webhooks, mcp_servers, attachments, limits, secret_values, settings, operations, docker_stacks) | 2026-04-18 | ~200 | **BUG FIXED**: `admin_delete_mcp_server` checked bot-usage before existence → 400 instead of 404 on stale references |
| 4 | 8 mock-only services rewritten for real-DB | 2026-04-17 | 69 | 2 false positives cleared; `turn_worker.run_turn` full-persistence 2 tests deferred |
| A | Core gap audit — ranked top-30 behaviors across 8 runtime-frequent modules | 2026-04-18 | — | plan: `~/.claude/plans/gentle-spinning-bird.md` |
| B.1–B.10 | Top-30 module sweeps (sessions, step_executor, llm, tool_dispatch, loop, file_sync, context_assembly, compaction, tasks×2) | 2026-04-18 | 131 | **BUG FIXED**: `file_sync.py:686` `rows2` NameError on deleted prompt/carapace/workflow files |
| C | Dispatch→recording seam (running/done/error/denied/approval) | 2026-04-18 | 9 | `asyncio.sleep(0)*5 + db_session.expire_all()` pattern for fire-and-forget flushes |
| D | Recently-churned surface — deliberate read-for-drift on `decide_approval`, `recording`, `snapshot` | 2026-04-18 | 36 | Silent DB drifts pinned: ToolApproval orphan card undecidable; deny while not awaiting overwrites silently |
| E.1–E.10 | Drift-seam sweep (silent-UPDATE, multi-row sync, orphan pointer, multi-actor, partial-commit, ordering) | 2026-04-18 | 63 | `outbox.enqueue` idempotency docstring was stale (migration 188 dropped unique constraint) |
| F.1–F.7 | Multi-row sync + partial-commit sweep | 2026-04-18 | 49 | `workspace_bootstrap` cross-workspace conflict silently swallowed; `slack/uploads` partial-commit drift |
| G.1–G.6 | Cascade + cross-cache isolation | 2026-04-18 | 44 | Pipeline UUID bypass; dashboard bulk cross-isolation; context_assembly core/integration DB contracts |
| H.1–H.3 | Auth refresh + skill enrollment cache | 2026-04-18 | 19 | Silent 0-row DELETE on refresh-token path pinned |
| I.2–I.8 | Integration ingest contract (`_apply_user_attribution`, pipeline order, `IngestMessageMetadata`) | 2026-04-19 | 18 | **REAL BUG (I.5)**: display-name drift produces double attribution |
| J.1,3,5–7 | Widget-auth scope ceiling + key rotation + TTL boundary | 2026-04-19 | 9 | **REAL BUG (J.5)**: same-second mints produce identical JWT (no `jti` nonce) |
| K.2–K.5,7,9 | Dashboard pin migration idempotency + JSONB round-trip + FK cascade | 2026-04-19 | 12 | SQLite FK pragma limitations pinned at schema level |
| L.1,3–6 | Background-task ordering (heartbeat, session_locks, modal_waiter, sub_session_bus, bot_hooks) | 2026-04-19 | 15 | **REAL BUG (L.1)**: heartbeat has no `reset_stale_running_runs` startup recovery |
| M.1–M.12 | OpenAI Responses adapter (translate, extract, finish, usage, exc-map, response-to-completion) + widget_packages_seeder (idempotency, orphan sweep, sample-payload sync) | 2026-04-19 | 40 | SQLite constraint-ordering limitation on active-transfer orphan sweep — deferred to Postgres fixture |
| N.1 | Widget preset binding + pin persistence (per-source error isolation, tool_family binding_sources lane, shallow-merge contract, fail-loud listing, orphan-pointer JSONB snapshot across manifest reload, cross-dashboard pin isolation) | 2026-04-23 | 7 | `widget_origin.preset_id` is a durable JSONB snapshot — survives full removal from manifest, so pins are not breakable by integration reloads |
| N.2 | Native widget envelope repair on dashboard reload — `_sync_native_pin_envelopes` (idempotency across back-to-back reloads, state-mutation → envelope propagation, orphan widget_instance tolerance, cross-kind isolation of non-native pins, removed-widget_ref graceful-skip contract) | 2026-04-23 | 5 | **REAL BUG FIXED same-commit**: removed widget_ref from `_REGISTRY` crashed `list_pins`; now wrapped in `try/except HTTPException: continue` mirroring the orphan-instance branch. Also repaired the pre-existing broken `test_delete_pinned_files_pin_clears_widget_state` neighbor test by seeding `build_channel()`. See [[Fix Log]] 2026-04-23. |
| N.3 | `channel_skill_enrollment.py` drift seams — cross-channel cache isolation, empty-list + falsy-id no-op, double-enroll idempotency, unenroll-non-existent contract, orphan-pointer cache staleness after out-of-band row delete | 2026-04-23 | 9 | **NEW DRIFT-PIN**: module cache (5-min TTL) not invalidated by FK cascade or admin DELETEs. Pinned as bug-shaped; flip assertion when a channel-delete hook lands. Also extended `_MODULE_LEVEL_ALIASES` + `patched_async_sessions` to cover `app.services.channel_skill_enrollment.async_session`. |
| N.4 | `session_plan_mode.py` drift seams — `_normalize_planning_state` shape-coercion, `_dedupe_recent_items` case-insensitive last-wins + empty-filter + limit, `_PLANNING_STATE_LIST_LIMIT` cap under runaway appends, `flag_modified` on mutation, `_clear_pending_turn_outcome` match/no-match/malformed cases, `list_session_plan_revisions` orphan-snapshot tolerance | 2026-04-23 | 13 | **REAL BUG FIXED same-commit**: `_dedupe_recent_items` fallback chain `item.get(key) or item.get("label") or item` stringified the whole dict when both keys were empty, so `{"text": ""}` survived dedupe as `"{'text': ''}"`. Replaced `or item` with `or ""` — empty-text items now correctly drop. See [[Fix Log]] 2026-04-23. |
| N.5 | `reranking._identify_rag_messages` + `rerank_rag_context` rebuild path — `RERANKABLE_RAG_PREFIXES` order contract, memory-header no-double-newline silent-drop, empty-body zero-chunks contract, non-memory bare-prefix capture for round-trip, non-string content graceful-ignore, `CONVERSATION_SECTIONS_RAG_PREFIX` embedded `:\n\n` terminator, prefix-preservation + reverse-index message removal under partial/full filter | 2026-04-23 | 9 | All invariants held — no new bugs. Pins the fresh header-prefix surface in `app/agent/rag_formatting.py` so future additions to the constant list can't silently reclassify sources or break the rebuild round-trip. |
| N.6 | `_create_approval_state` + `_resolve_approval_verdict` drift seams — `extra_metadata={}→NULL` shape, `channel_id=None` skips notification fan-out, dispatch ContextVars propagate (or default to `None` unset), `policy_rule_id` str→UUID casting, terminal ToolCall preserved on timeout (running/denied/completed never rewound), pending approval with `tool_call_id=None` expires cleanly, malformed UUID raises ValueError (caller-catch contract) | 2026-04-23 | 12 | **TWO REAL PRODUCTION-BREAKING BUGS FIXED same-commit**: (1) `_create_approval_state` referenced `ToolCall` without importing it → every approval-gated tool call NameError'd; caller swallowed the Exception and returned "approval state could not be created", silently breaking 100% of approval gates since the 2a4ce9f0 extraction. (2) Same function referenced `datetime` without importing — same failure mode. Added `ToolCall` + `datetime, timezone` imports. Also **revived** the pre-existing silently-broken `test_approval_orphan_pointers::test_when_creation_succeeds_then_both_rows_exist_and_linked` — it had been failing on HEAD for the same two NameErrors. Extended `_MODULE_LEVEL_ALIASES` + `patched_async_sessions` with `app.agent.tool_dispatch.async_session`; refactored the fixture to use `ExitStack` (hit Python's 20-block nested-`with` limit). See [[Fix Log]] 2026-04-23. |
| N.7 | `context_assembly._get_bot_authored_skill_ids` DB filter shape + bot cache multi-actor drift — `source_type='tool'` + `archived_at IS NULL` + `bots/<id>/` prefix isolation (cross-prefix contamination from `skills/core/` / `integrations/*` ruled out), empty-result caching to block thundering-herd on no-skills bots, multi-bot isolation on cache hits, invalidate-one-bot leaves siblings intact, invalidate-missing-bot is no-op, `invalidate_skill_auto_enroll_cache` try/except silently swallows downstream `invalidate_enrolled_cache` exceptions so file-sync invalidation can't wedge on a broken enrollment cache | 2026-04-23 | 11 | All invariants hold — no new bugs. Companion to Phase G.6 (`test_context_assembly_cache_ttl_drift.py`): G.6 pinned TTL asymmetry + cross-cache invalidation isolation; N.7 pins the DB filter shape + empty-result caching + silent-swallow contract that G.6 skipped. |
| N.8 | `outbox_drainer.py` fire-and-forget + silent-skip + state-vanished seams — `_persist_delivery_metadata` swallow (hook raise does NOT un-deliver) + skip paths (non-NEW_MESSAGE / no msg_id / no IntegrationMeta / no Message row / no `receipt.external_id`), repeated retryable (attempts=9 → 10) escalates to DEAD_LETTER + publishes DELIVERY_FAILED, `_publish_delivery_failed` swallow (broken channel-events bus doesn't wedge drainer), row-vanishes-mid-session (all three `_*_in_session` helpers return DELIVERED sentinel when `db.get` → None), `fetch_pending` FIFO by `created_at` contract, `reconstitute_event` failure → non-retryable mark_failed (no infinite retry on corrupt JSONB) | 2026-04-23 | 13 | All invariants hold — no new bugs. Companion to Phase D (`test_outbox_drainer.py`), which covered the happy path + loop-isolation contracts; N.8 pins the fire-and-forget seams + retryable→dead-letter escalation + row-vanishes contracts the Phase D sweep skipped. Hook-side and bus-side failure modes each proven non-blocking. |
| P | Close the 4 Phase N drift-pinned Loose Ends — J.5 widget-auth JWT `jti` nonce (1 line in `app/services/auth.py`), N.3 channel-delete cache invalidation (2 lines in `app/routers/api_v1_channels.py`), I.5 generic-regex attribution idempotency guard replacing the single-name `legacy_prefix` check (`app/routers/chat/_context.py` — first attribution wins), L.1 heartbeat `reset_stale_running_runs` startup recovery mirroring `outbox.reset_stale_in_flight` (`app/services/heartbeat.py` + `app/main.py` lifespan) | 2026-04-23 | 4 regression tests flipped + 4 new assertion tests | All 4 drift-pinned bugs closed same-session. Each regression test was already pinning the buggy behavior from Phase N; the flips turn them into positive contracts. Neighbor sweep ran 165 tests with zero collateral breakage. See [[Fix Log]] 2026-04-23 for per-bug details. |
| O | `machine_control.py` drift seams — `validate_current_execution_policy` autonomous-origin bypass (heartbeat/task/subagent/hygiene always deny even with valid lease) + admin-only gate + lease user-mismatch (multi-actor) + expired-lease denial (silent time-UPDATE) + disconnected-target denial (orphan); `get_session_lease` shape-coercion on malformed JSONB (missing required fields → None; absent provider_id falls back to `LEGACY_PROVIDER_ID`); `build_session_machine_target_payload` auto-clears expired leases (fire-and-forget cleanup); `_find_conflicting_lease` respects expiration + `exclude_session_id` (own-renewal OK); `delete_machine_target` clears matching leases across all sessions (multi-row sync); `_PROVIDER_CACHE` instance reuse | 2026-04-23 | 19 | All invariants hold — no new bugs. Companion to `test_machine_target_sessions.py` (happy-path grant + single-conflict shape) which used a mocked DB; Phase O widens coverage to the policy gates + multi-session sweep + shape-coercion seams the happy-path sweep skipped. Autonomous-origin denial is parametrized across all four origin kinds to prevent a future refactor from silently pruning one. |
| P2 | Stale unit-test cleanup — closed both pre-existing broken-test entries from [[Loose Ends]] 2026-04-23. `tests/unit/test_model_params_llm.py`: patched `_start_tool_call`/`_complete_tool_call` on the tool-loop iteration test (newer recording seams the original `_record_tool_call`-only mock missed — real `async_session` commit tripped "no such table: tool_calls"); mocked `supports_reasoning=True` on the reasoning-effort passthrough test (Phase 2 Provider Refactor now drops `reasoning_effort` for non-reasoning-marked models). `tests/unit/test_dashboard_pins_service.py`: 6 `HTTPException` → `ValidationError`/`NotFoundError`/`DomainError` flips (services migrated to `app.domain.errors`); 3 `core/context_tracker` pins now pass `channel:<uuid>` scope (`supported_scopes=("channel",)` tightened); `test_create_pin_seeds_chip_preset_into_header_chip_layout` monkeypatches `get_widget_preset` since integration manifests don't auto-load in unit-test env; `test_serialize_pin_backfills_missing_provenance` flipped to `html_widget` (unregistered tools no longer fall back to `tool_widget`) | 2026-04-24 | 12 | No new bugs. All drift was test-side staleness against tightened service contracts that had already been backfilled with fresh drift-pin coverage in earlier phases. |
| Q-MACH | Admin `/machines` router + `local_companion` WS handshake drift. **File 1** `tests/unit/test_machine_admin_routes_drift.py` (22 tests): exception-to-HTTP mapping at each endpoint (`KeyError`→404, `ValueError`→400, `RuntimeError`→409 on enroll/probe/delete), `delete_machine_target` returning False→404 (not silent 200) + success envelope shape, scope gate (`integrations:read` vs `integrations:write` — read-only scope blocked from enroll/probe/delete; empty-scopes blocked from list; umbrella `admin` still passes), no-body POST /enroll accepted + null-body + extra-field tolerated, body passthrough (`label`+`config` verbatim), URL-path `provider_id` wins over smuggled body field, probe-disconnected returns 200 envelope (not 5xx), `server_base_url` passthrough from request. **File 2** `tests/unit/test_local_companion_ws_drift.py` (14 tests + 3 provider-impl extensions): unknown `target_id`→close(4404) with no bridge/provider side effects, wrong token→close(4401), empty-registered-token short-circuits to 4404 (no `compare_digest` call), malformed hello frame→close(4400) across three variants (non-dict JSON, wrong `type`, case-sensitive "HELLO"), successful hello registers target + bridge exactly once with hello-frame metadata, empty `capabilities`→defaults to `["shell"]` on BOTH provider and bridge calls, clean disconnect unregisters the bridge connection in the `finally` block, multi-connect contention shows two separate bridge registrations with fresh `connection_id` per handshake (last-writer-wins contract pinned), provider-impl extensions: `register_connected_target` is a no-op on unknown target_id (no save), `probe_target` raises `ValueError` on unknown (router maps to 400), `probe_target` returns offline envelope (not raise) when known target has no bridge connection. | 2026-04-24 | 36 | **No new production bugs** — all invariants hold. Revived **1 pre-existing broken test**: `test_local_machine_control_phase5a.py::test_machine_status_returns_refreshable_semantic_envelope` had been failing silently because its fixture set only `connected=True` on the target stub, but `machine_status` counts `target.get("ready")` (both fields are normally filled from the same `normalized["ready"]` in `_public_target_payload`, so they're equivalent in prod — the hand-rolled fixture just drifted). One-line fix: add `"ready": True`. Companion to Phase O (service layer) — O stopped at router/WS/provider-impl boundaries; Q-MACH closes all three in one session. |

**Detail lives in the tests themselves.** File names map 1:1 to phases (`test_<module>_core_gaps.py` for B; `test_<specific_seam>.py` for D–M). When reading archaeology is needed, open the test file and the production file side-by-side — the Track only holds the index.

## Open seams (unshipped rows from queued phases)

| # | Seam | File:line | Drift class | Why deferred |
|--:|---|---|---|---|
| I.1 | Raw-content preservation end-to-end across Slack/Discord/BB → persist_turn | `app/routers/chat/_context.py:272-358` | invariant | Requires full HTTP integration fixture — scope deferred |
| J.4 | `source_bot_id` tampering | `app/routers/api_v1_widget_auth.py:39,79` | multi-actor | MOOT — no endpoint surfaces this directly |
| J.8 | Mint for archived bot | `app/routers/api_v1_widget_auth.py:79` | silent-default | MOOT — Bot model has no `archived_at` field |
| K.1 | Rail-zone boundary (x=col-1 in, x=col overflow) | `app/services/dashboard_pins.py`, `ui/src/lib/dashboardGrid.ts` | invariant/boundary | PLANNED |
| K.6 | `apply_layout_bulk` mid-commit visibility race | `app/services/dashboard_pins.py::apply_layout_bulk` | multi-actor | PLANNED (may need Postgres fixture) |
| K.8 | Widget config reserved-key collision (`config.x` shadows `grid_layout.x`) | widget render path | template-shadow | PLANNED |
| L.2 | `_resume_pipeline_background` mid-step crash visibility | `app/routers/api_v1_admin/tasks.py:877-879` | fire-and-forget | DEFERRED (needs complex task fixture) |
| L.7 | PUT heartbeat config vs `_safe_fire_heartbeat` read ordering | `app/routers/api_v1_admin/channels.py:1169` | background-task ordering | DEFERRED |
| L.8 | `_drain_backfill` FK pre-commit race | `app/routers/api_v1_admin/channels.py:1463-1466` | partial-commit | DEFERRED |

## Open drift-pinned bugs

All four Phase N-era drift-pinned bugs (L.1, J.5, I.5, N.3) were closed in Phase P on 2026-04-23. See Shipped Phases row "Phase P" below and [[Fix Log]] 2026-04-23 for per-bug fix details. No drift-pinned bugs currently open.

## Phase N — shipped 2026-04-23

Both surfaces shipped after Phase M with zero dedicated coverage. Both went in as drift-pin sweeps (not coverage sweeps) following the Phases E–L orientation.

### N.1 — Widget preset binding + pin persistence ✅ shipped 2026-04-23

- **File**: `tests/unit/test_widget_preset_drift.py` (7 tests, all green on first run).
- **Surface**: `app/services/widget_presets.py`, `app/services/dashboard_pins.py` preset-pinned rows.
- **Drift classes hit**: per-source error isolation (HTTPException + generic Exception), tool_family contract via `binding_sources` lane, shallow-merge `resolve_preset_config`, fail-loud `list_widget_presets`, orphan-pointer JSONB `widget_origin` snapshot across manifest reload, cross-dashboard pin isolation.
- **Findings**: no bugs — all invariants hold. The `widget_origin.preset_id` durability against manifest removal is the load-bearing discovery: existing pins stay readable/serializable even when their originating preset is dropped from the manifest. A future refactor that hard-validates `preset_id` against the live manifest would break every pre-existing pin; the test catches it.
- **Deliberately NOT covered** (drift-pin orientation): happy-path options parsing (already in `test_widget_presets.py`), preview round-trip, pin-from-preset layout seeding (already in `test_dashboard_pins_service.py`).

- **File**: `tests/unit/test_native_envelope_repair_drift.py` (5 tests, all green after a one-line fixture fix for the channel-pin case).
- **Real surface**: the plan named `_repair_envelope_on_reload` in the seeder — that path does not exist. The actual envelope-repair-on-reload hook is `_sync_native_pin_envelopes` in `app/services/dashboard_pins.py:269-314`, triggered on every `list_pins` call. This is the load-bearing helper that keeps cached pin envelopes consistent with the authoritative `widget_instances` state.
- **Drift classes hit**: idempotency (repeat reloads don't churn), state-mutation propagation, orphan `widget_instance` tolerance, cross-kind isolation (non-native pins untouched), schema-upgrade mid-flight (removed widget_ref).
- **Findings fixed same-commit**: (1) removed widget_ref from `_REGISTRY` crashed `list_pins` entirely — wrapped `build_envelope_for_native_instance` in `try/except HTTPException: continue` mirroring the orphan-instance branch; (2) surfaced that `test_dashboard_pins_service.py::test_delete_pinned_files_pin_clears_widget_state` had been silently broken since `ensure_channel_dashboard` was hardened to require a real Channel row — seeded via `build_channel()`. Both in [[Fix Log]] 2026-04-23. Tests flipped to assert the graceful-skip contract.
- **Deliberately NOT covered**: the `widget_packages_seeder.py` orphan sweep itself (already covered by Phase M.10, with documented SQLite limitation).

### N.3 — `channel_skill_enrollment.py` drift seams ✅ shipped 2026-04-23

- **File**: `tests/unit/test_channel_skill_enrollment_drift.py` (9 tests, all green).
- **Surface**: `app/services/channel_skill_enrollment.py` — per-channel skill membership with 5-min module cache.
- **Drift classes hit**: cross-channel cache isolation (mutating A doesn't leak into B's cached list), empty-list + falsy-id no-op contracts, unenroll-non-existent returns False, double-enroll idempotency under ON CONFLICT DO NOTHING, orphan-pointer cache staleness on out-of-band DELETE (bug-shaped, flip when channel-delete hook lands).
- **Findings**: 1 new drift-pin — module cache is not invalidated by FK cascade or admin DELETEs. Logged to [[Loose Ends]] alongside L.1/J.5/I.5. Low severity: UUID4 channel IDs are not reused, so stale cache entries are dead weight rather than misrouted data. Fix is a one-line `invalidate_enrolled_cache(channel_id)` in the channel-delete path; deferred because the bug shape carries no incident pressure.
- **Infra touched**: extended `_MODULE_LEVEL_ALIASES` + `patched_async_sessions` with `app.services.channel_skill_enrollment.async_session` so real-DB tests cover function-local `async_session()` calls.
- **Deliberately NOT covered**: capability/skill-resolution integration with `app/agent/context_assembly.py` (multi-actor "bot A enrolls, channel filters by bot B" seam named in the backlog) — that lives upstream of this service and belongs in a context-assembly drift cycle, not here.

### N.4 — `session_plan_mode.py` drift seams ✅ shipped 2026-04-23

- **File**: `tests/unit/test_session_plan_mode_drift.py` (13 tests, all green after the same-commit fix).
- **Surface**: `app/services/session_plan_mode.py` — pure-python helpers that coerce, dedupe, clip, and advance JSONB plan/adherence capsules on `Session.metadata_`.
- **Drift classes hit**: silent-default (`_normalize_planning_state` / `_normalize_adherence` default-recovery on corrupt input), multi-row bound (`_PLANNING_STATE_LIST_LIMIT = 12` cap enforcement), silent-UPDATE (`flag_modified` on metadata_ mutation), multi-actor (`_clear_pending_turn_outcome` turn_id vs correlation_id match/no-match/malformed cases), orphan pointer (`list_session_plan_revisions` with externally-deleted snapshot file).
- **Finding fixed same-commit**: `_dedupe_recent_items` fallback chain bug — when `item.get("text")` was falsy *and* `item.get("label")` was missing, it stringified the *whole dict* as the dedupe key, so `{"text": ""}` entries survived as unique-seeming keys like `"{'text': ''}"` and bypassed the empty-filter guard. Replaced `or item` with `or ""`. Only bit corrupt JSONB round-trips because `update_planning_state` filters empties at input, but the service's own normalize + re-dedupe loop could surface it.
- **Deliberately NOT covered**: `record_plan_progress_outcome` end-to-end (complex fixture chain — `load_session_plan` + `get_session_plan_mode` + `_ensure_plan_is_approved_for_execution`), SSE `publish_session_plan_event` wiring (covered upstream by typed-bus end-to-end tests; drift here would be bus-contract, not plan-service), revision diff semantics (happy-path already in existing `test_build_plan_revision_diff_uses_snapshot_content`).

### N.5 — Reranker header-prefix drift ✅ shipped 2026-04-23

- **File**: `tests/unit/test_reranking_drift.py` (9 tests, all green on first run).
- **Surface**: `app/agent/rag_formatting.py` constants + `app/services/reranking.py::_identify_rag_messages` + `rerank_rag_context` rebuild path.
- **Drift classes hit**: prefix-order priority (shorter-before-longer same-source grouping pinned), memory-header no-double-newline silent-drop, empty-body zero-chunks contract, non-memory bare-prefix capture for lossless round-trip on rebuild, non-string system content graceful-ignore, `CONVERSATION_SECTIONS_RAG_PREFIX` embedded `:\n\n` terminator pinned, prefix-preservation + reverse-index message pop under partial/full filter.
- **Findings**: no bugs — existing `test_reranking.py` already covered the happy-path identify flow, so N.5 adds seam-focused coverage: the fresh header contract (bot KB, channel index segments, workspace-excerpt, memory bootstrap/log/yesterday/reference exclusions) is now locked against silent reclassification. The rebuild-path tests stub the cross-encoder to assert the exact content round-trip rather than behavior of the real ONNX model.
- **Deliberately NOT covered**: LLM-backend path (already covered end-to-end in `TestRerankRagContextLLM`), cross-encoder scoring curve (existing `TestSigmoid` pins math), settings-gated skip (`RAG_RERANK_ENABLED=False` and below-threshold both covered).

### N.6 — Approval lifecycle extraction drift ✅ shipped 2026-04-23

- **File**: `tests/unit/test_approval_lifecycle_drift.py` (12 tests, all green after the same-commit fix).
- **Surface**: `app/agent/tool_dispatch.py::_create_approval_state` (atomic ToolCall+ToolApproval insert + fire-and-forget APPROVAL_REQUESTED publish) + `app/agent/loop_dispatch.py::_resolve_approval_verdict` (timeout path, already-resolved DB-truth path).
- **Drift classes hit**: silent-default (`extra_metadata={}→NULL`), silent-skip (`channel_id=None` → no notification task), ContextVar propagation + default-unset, type-coercion (`policy_rule_id` str→UUID), terminal-state preservation on timeout, orphan-approval-with-no-tool_call_id, contract-pin on malformed UUID raise.
- **Findings fixed same-commit**: **Two production-breaking NameErrors** in `_create_approval_state`. The commit `2a4ce9f0` extraction imported `ToolApproval` but missed both `ToolCall` and `datetime`/`timezone`. Every approval-gated tool call since that commit has been NameError'ing inside the helper; `dispatch_tool_call`'s outer `except Exception` handler silently converted the crash into a "Tool call denied: approval state could not be created" result to users. 100% of approval gates were broken. Added both imports. The silently-broken `test_approval_orphan_pointers::test_when_creation_succeeds_then_both_rows_exist_and_linked` had been failing on HEAD for the same two NameErrors — revived by the same two-line fix.
- **Infra touched**: appended `app.agent.tool_dispatch.async_session` to `_MODULE_LEVEL_ALIASES` + `patched_async_sessions`. Refactored the fixture to `contextlib.ExitStack` — the flat nested-`with` chain hit Python's 20-block static-nesting limit on the 21st patch target.

**Phase N yield**: 79 tests (7 + 5 + 9 + 13 + 9 + 12 + 11 + 13), 4 real bugs fixed same-commit (N.2 native envelope crash + N.4 dedupe dict-stringify + N.6 ToolCall import + N.6 datetime import), 1 new drift-pin carried to [[Loose Ends]] (N.3 channel-skill cache staleness), 2 pre-existing broken tests revived (N.2 dashboard-pin channel-seed + N.6 orphan-pointer creation).

### N.7 — Context-assembly bot cache drift ✅ shipped 2026-04-23

- **File**: `tests/unit/test_context_assembly_bot_cache_drift.py` (11 tests, all green on first run).
- **Surface**: `app/agent/context_assembly.py::_get_bot_authored_skill_ids` + `invalidate_bot_skill_cache` + `invalidate_skill_auto_enroll_cache`.
- **Drift classes hit**: DB-filter shape (`source_type='tool'` + `archived_at IS NULL` + `bots/<id>/` prefix scope — a refactor relaxing any one silently widens/narrows the bot-authored set), empty-result caching (thundering-herd prevention — `[]` must be cached so no-skills bots don't re-query every turn), multi-bot cache isolation (bot-A slot never leaks into bot-B lookup; invalidate-one leaves siblings intact; invalidate-missing is no-op), silent-swallow contract on `invalidate_skill_auto_enroll_cache` (downstream `invalidate_enrolled_cache` raises → core + integration caches STILL cleared, so a broken enrollment cache can't wedge file-sync invalidation).
- **Findings**: no bugs — all invariants hold. This is the companion file to Phase G.6's `test_context_assembly_cache_ttl_drift.py`: G.6 pinned the TTL asymmetry (30s bot cache vs 60s core/integration) + cross-cache invalidator isolation; N.7 pins the surface G.6 deliberately skipped (DB filter shape of the bot-authored query, empty-result caching, silent-swallow on the nested invalidator).
- **Deliberately NOT covered**: core/integration cache DB behavior (already in G.6), TTL asymmetry (already in G.6), file-sync → invalidate round-trip end-to-end (bus-contract concern, not cache concern).

### N.8 — Outbox drainer fire-and-forget + state-vanished drift ✅ shipped 2026-04-23

- **File**: `tests/unit/test_outbox_drainer_drift.py` (13 tests, all green on first-pass after a fixture fix — `Message` is session-scoped, not channel-scoped, so `_seed_message_row` also seeds a `Session` row now).
- **Surface**: `app/services/outbox_drainer.py::_deliver_one` + `_persist_delivery_metadata` + `_mark_delivered_in_session` / `_mark_failed_in_session` / `_defer_no_renderer_in_session` + `_publish_delivery_failed` + upstream `outbox.fetch_pending` FIFO contract + `outbox.reconstitute_event` failure path.
- **Drift classes hit**: fire-and-forget (hook-raise does NOT un-deliver row — `mark_delivered` commits before the try/except on `_persist_delivery_metadata`), silent-skip paths (non-NEW_MESSAGE event, missing message id, absent IntegrationMeta, missing Message row, receipt without `external_id` — each short-circuits without raising), retryable-escalation (attempts=9 → 10 flips to DEAD_LETTER + publishes DELIVERY_FAILED — Phase D only covered the immediate non-retryable path), bus-side swallow (`publish_typed` raising on the dead-letter publish doesn't crash the drainer; row stays dead-lettered), row-vanishes-mid-session (all three in-session helpers handle `db.get → None` with a DELIVERED-value sentinel — simulates admin/manual DELETE between `_claim_batch` and commit), FIFO ordering (`fetch_pending` orders by `created_at`, not `id` — renderers pacing against `count_pending_for_target` depend on it), corrupt-payload contract (`reconstitute_event` raising marks the row permanent-failed so it dead-letters without burning the retry budget).
- **Findings**: no bugs — all invariants hold. Companion to Phase D (`test_outbox_drainer.py`), which owned the happy-path + loop-isolation contracts; N.8 pins the fire-and-forget + silent-skip + state-vanished + retryable-escalation seams that Phase D skipped. Hook-side + bus-side failure modes each proven non-blocking for row drainage.
- **Deliberately NOT covered**: multi-worker `SELECT ... FOR UPDATE SKIP LOCKED` contention — SQLite silently ignores `with_for_update`, so a real concurrent-drain test requires Postgres. Phase Z (if scheduled) could pin on `conftest_postgres` when we stand up that fixture. `DEFER_DEAD_LETTER_AFTER=480` accumulation path left unpinned (500 iterations against SQLite is a test-runtime tradeoff; the cutover logic is already covered at the unit level in `test_outbox.py::TestDeferNoRenderer`).

## Candidate next cycles (ranked backlog, not scheduled)

Pick one per Phase N+ cycle. Planned from a 2026-04-24 three-agent audit (security gap / perf-concurrency / recent-churn coverage delta). Q-MACH is queued below in "Planned phases"; Q-SEC / Q-CONC / Q-CHURN remain unscheduled.

| # | Phase | Surface | Why it's high-yield | Blocked on |
|---|---|---|---|---|
| 1 | **Q-SEC** | Widget-token scope-ceiling (`app/services/auth.py::mint_widget_token`) + SSRF horizontal coverage (`assert_public_url` is only called from 2 of 15+ fetch sites) + webhook replay drift (github/slack/bluebubbles/local_companion) | Security pre-empts before internet-exposed deployment; widget token carries frozen scopes with no per-request revalidation | - |
| 2 | **Q-CONC** | `loop_dispatch.py:329-370` parallel-tool semaphore + gather exception isolation (xs); `tokenization.py` Anthropic count_tokens → tiktoken → char/3.5 cascade thundering-herd (s); `api_v1_channels.py` SSE back-pressure + disconnected-client subscription leak (m); `reranking.py::rerank_rag_context` pathological 1000-chunk input (s); `channel_events.py::publish_typed` subscriber exception isolation (m) | Asyncio/concurrency seams with no exception-isolation or boundary tests; `loop_dispatch` gather is a ~xs win with real-bug potential | - |
| 3 | **Q-CHURN** | `loop_dispatch.py` / `loop_helpers.py` / `rag_formatting.py` agent-loop state seams; `integrations/{slack,wyoming,ingestion}/router.py` config endpoints shape-coercion; `app/schemas/binding_suggestions.py` pydantic validation; `app/services/integration_device_status.py` cache + orphan pointer | Recent refactors (`ad96ba2f`, `5a6e7846`) shipped without dedicated drift coverage; highest breadth, lowest per-test yield | - |
| 4 | Postgres-only outbox seams | `SELECT FOR UPDATE SKIP LOCKED` concurrent drain, `reset_stale_in_flight` startup recovery end-to-end, `DEFER_DEAD_LETTER_AFTER` cutover via `_defer_no_renderer` → `_publish_delivery_failed` path | Requires `conftest_postgres`; blocked until that fixture lands | `conftest_postgres` |

## Planned phases (next up)

**Q-MACH shipped 2026-04-24** — see the Shipped Phases row for scope + findings. Q-SEC / Q-CONC / Q-CHURN remain on the ranked backlog above; pick one per next cycle.

## Phase 5 — Mechanical A.13 cleanup (opportunistic, never a dedicated session)

671 flat-structure violations remain across the suite. Biggest current clusters (2026-04-23 regen):

- `test_tool_discovery.py` (15)
- `test_get_skill.py` (6)
- `test_backfill_sections.py` (3)
- `test_docker_stacks.py` (3)

Fix when touching a file for another reason. Don't schedule a session for cosmetic cleanup.

## Key invariants

- Skill `testing-python` (`~/.claude/skills/testing-python/SKILL.md`) is the rule source. Link it in PR descriptions.
- `db_session` fixture (`tests/integration/conftest.py`) is the canonical real-DB fixture. Reuse; do not reinvent.
- `tests/factories/` holds typed factories with sensible defaults. Every new factory re-exports from `tests/factories/__init__.py`.
- `_MODULE_LEVEL_ALIASES` in `tests/unit/conftest.py` tracks known module-level `async_session` offenders. Append when a real-DB test fails with schema-missing despite `patched_async_sessions`.
- Every drift-pin test has a companion "normal lifecycle" test so future hardening distinguishes "noise removal" from "contract change."
- A.1 (test title style) and B.3 (magic literals) are cosmetic — never stand up a dedicated session.
- Phase B yield taught: coverage sweeps pin what's *easy to read* (happy paths). High-yield reads target fire-and-forget UPDATE helpers, multi-row state sync, orphan pointer cases, and multi-actor paths. Phase N+ keeps this orientation.

## References

- [[Test Audit - Coverage Gaps]] — 127 uncovered routes + critical service symbol inventory (still live; next-cycle source)
- [[Test Audit - Mock Session Refactor]] — top-20 E.13 offenders + refactor playbook (merged from old Inventory + Deep Review)
- [[Loose Ends]] — open drift-pinned bugs (L.1, J.5, I.5)
- [[Track - Code Quality]] — partner track for god-function decomposition (Phase B yield analysis lives there)
- Skill: `~/.claude/skills/testing-python/SKILL.md` and `references/`
- Plans: `~/.claude/plans/gentle-spinning-bird.md` (Phase A audit), `~/.claude/plans/drifting-silent-harbor.md` (Phase E), `~/.claude/plans/rippling-giggling-bachman.md` (Phases I–L)

## Out of scope

- E2E tests (`tests/e2e/`) — different concerns, different skill
- UI tests — `ui/` has its own tooling
- Performance / load tests
