---
tags: [spindrel, track, integrations, architecture]
status: complete
created: 2026-04-11
updated: 2026-04-26
---
# Track — Integration Delivery Layer Refactor

> **Status**: ✅ **COMPLETE 2026-04-11** (session 15). Phases A–G + UI hookup + bus restructure + manual smoke bug sweep + Phase H acceptance + all polish follow-ups landed on `development`. Single-commit build-up; the refactor is monitor-only now. Only manual-smoke gaps and the BB-out-of-scope items remain — neither blocks declaring the migration done.
>
> **Where the design lives**: [[architecture-decisions#Integration Delivery: Bus + Outbox + Renderer Abstraction]] — bus + outbox + renderer model, capability declarations, target boundary, load-bearing facts.
>
> **Where the shipped detail lives**: [[completed-tracks#Integration Delivery Layer Refactor]] — phase summary + commit pointers + test coverage.
>
> **Where the bug-by-bug history lives**: [[fix-log]] — the 9 manual-smoke fixes + the 4 session-11 backend fixes + 11 session-15 polish landings.

> **2026-04-26 monitor follow-up:** `persist_turn` external delivery now filters `hidden` / `suppress_outbox` rows before enqueueing integration outbox records. This closes a Slack leak where scheduled heartbeat prompt/context rows and tool-injected image analysis rows were correctly persisted for internal history but incorrectly mirrored as channel messages. Heartbeat auto-dispatch now suppresses the full turn outbox and explicitly enqueues only the final assistant result; optional heartbeat posting still uses `post_heartbeat_to_channel`.

## Phase H acceptance — ✅ landed session 15

`tests/integration/test_renderer_abstraction_parity.py` — 5 cases covering the contract end-to-end. The original 8-case plan minus BB (out of scope per session 14 user direction) and minus the cases already covered by other suites. Cross-reference table:

| # | Case | Where it lives |
|---|---|---|
| 1 | BB port from scratch | **out of scope** — BB handled separately |
| 2 | Hypothetical text-only integration | `test_renderer_abstraction_parity::TestHypotheticalTextOnlyIntegration` |
| 3 | Capability gating | `test_channel_renderers::TestCapabilityGating` (existing) |
| 4 | Target-type coverage | `test_domain_dispatch_target::Test{Slack,Discord,GitHub,BlueBubbles,Web,Webhook,Internal,None}Target` |
| 5 | Outbox crash recovery | `test_outbox_drainer::TestClaimBatch` + `outbox.reset_stale_in_flight` (session 11) |
| 6 | Two-integration same-channel | `test_renderer_abstraction_parity::TestTwoIntegrationsSameChannel` (2 cases) |
| 7 | Mirror-removal / NEW_MESSAGE single-path | `test_renderer_abstraction_parity::TestNewMessageSinglePathDelivery` (2 cases) |
| 8 | Slack duplicate-edit | `test_slack_end_to_end::test_long_streaming_turn_coalesces_chat_updates` (Phase F) |

## Pending — manual smoke coverage

Session 12 surfaced 6 bugs/hour against the live `/opt/thoth-server/` instance in roughly an hour of basic chat. Don't declare the refactor done until the rest of the surface has been driven by hand. (Don't worry about BlueBubbles — handled separately.)

- [ ] Multi-bot channels — concurrent primary + member turn rendering, mention chains, member-bot identity preservation
- [ ] Cancel mid-stream — both web and Slack origin; ensure `TURN_ENDED(error="cancelled")` lands and the UI flips to idle
- [ ] Tool approval flow — Slack approval buttons (Block Kit), web approval modal, deny path
- [ ] Capability approval flow — same surface set
- [ ] Attachments — image upload, file upload, file-delete capability path
- [ ] Slack threading — reply-in-thread behavior, thread parent recovery
- [ ] Web-UI-originated cross-integration mirrors — typing in a Slack-bound channel from the browser
- [x] Empty assistant turn ghost (`MessageBubble.tsx:98` + `ToolBadges.tsx:53`, 2-line gate fix) — landed session 14, gate now `toolsUsed.length > 0 || (msgToolCalls && msgToolCalls.length > 0)`

## Polish backlog — ✅ all landed (sessions 14 + 15)

1. ~~**`_persist_and_publish_user_message` metadata + actor cleanup.**~~ ✅ Session 14. Slack renderer echo filter now checks `msg.metadata.get("source") == "slack"` first; the `actor.id` prefix check is the legacy fallback. Time-bomb defused.
2. ~~**NEW_MESSAGE single-path delivery.**~~ ✅ Session 15. Added `ChannelEventKind.is_outbox_durable` (NEW_MESSAGE → True). `IntegrationDispatcherTask._dispatch` short-circuits outbox-durable kinds. Migrated 7 non-`persist_turn` publishers (`turn_worker._persist_and_publish_user_message`, `_fanout`, `heartbeat_tools.post_heartbeat_to_channel`, `usage_spike` channel-target, `delegation.post_child_response`, `compaction`, `core_renderers.InternalRenderer`, `workflow_executor._post_workflow_chat_message`, `store_passive_message`) to enqueue outbox rows via the new `outbox_publish.enqueue_new_message_for_channel` helper. Deleted the per-renderer dedup LRU (`_posted_set`/`_posted_order`/`_RECENT_POSTED_CAP`) from `SlackRenderer`. The dual-delivery foot-gun is gone for every current and future integration.
3. ~~**Integration subprocess import smoke test.**~~ ✅ Session 14. `tests/integration/test_integration_subprocess_imports.py`.
4. ~~**Non-Slack dispatch-target round-trip tests.**~~ ✅ Session 15. Added `test_parse_from_message_handlers_shape` for Discord (which uncovered + fixed a real `user_message_id` field-drift bug — `DiscordTarget` was rejecting the dispatch_config the message handler writes, silently dropping all Discord delivery to `NoneTarget`). Added `test_parse_from_router_shape_with_comment_target` for GitHub.
5. ~~**`ApprovalRequestedPayload.turn_id`**~~ ✅ Session 15. Added optional `turn_id: uuid.UUID | None` field. New `current_turn_id` ContextVar set by `turn_worker.run_turn`, read by `tool_dispatch._notify_approval_request`. Snapshot/restore plumbing updated. UI `useChannelEvents.ts:approval_requested` handler now prefers the explicit `payload.turn_id` over "most recent in-flight turn", with the legacy fallback preserved for script-driven admin approvals.
6. ~~**Renderer scaffold tool.**~~ ✅ Session 15. `admin_integrations._scaffold_integration` now accepts a `renderer` feature that lays down `target.py` + `renderer.py` boilerplate using the ChannelRenderer protocol. CamelCase class names derived from `integration_id`. New `_handle_new_message` and `_handle_turn_ended` stubs.
7. ~~**Module-level `httpx.AsyncClient`.**~~ ✅ Session 15. `app/main.py` lifespan shutdown reflectively closes every renderer's module-level `_http` client (looks up the module via `type(renderer).__module__` so adding a new integration requires no changes here).
8. ~~**`session_locks` no TTL.**~~ ✅ Session 15. New `sweep_stale(ttl_seconds=7200)` helper in `app/services/session_locks.py`. Wired into the existing `_session_cleanup_worker` loop in `app/main.py` (every 10 minutes). Locks store monotonic acquired-at timestamps; sweeper releases anything older than 2 hours. New `tests/unit/test_session_locks.py` (11 tests).
9. ~~**Outbox enqueue failures during `persist_turn`.**~~ ✅ Session 15. The legacy try/except that swallowed enqueue failures and let the message commit proceed is gone. Enqueue errors now propagate, the same DB transaction rolls back the message inserts, and the caller surfaces the error. Atomic outbox semantics restored.
10. **store_dispatch_echo not in BB renderer** — out of scope per user (BB handled separately).

## Future idea

**Integration / Spindrel SDK** — create once, reference on any integration. Easily hit any of the APIs needed for implementing integrations. Replaces bespoke API calls scattered across each integration's code.

## Cross-references

- [[architecture-decisions#Integration Delivery: Bus + Outbox + Renderer Abstraction]] — design + invariants
- [[completed-tracks#Integration Delivery Layer Refactor]] — phase-by-phase shipped detail
- [[fix-log]] — bug-by-bug history (sessions 11 + 12)
- [[loose-ends]] — open follow-ups
- [[streaming-architecture]] — Phase 2 ("collapse the dual paths") was folded into Phase E of this track
- Plan files (archived): `~/.claude/plans/gleaming-rolling-valiant.md` (umbrella), `~/.claude/plans/eager-frolicking-kahan.md` (UI), `~/.claude/plans/twinkling-floating-flame.md` (Phase G), `~/.claude/plans/frolicking-moseying-dongarra.md` (Phase E/F), `~/.claude/plans/keen-hugging-mitten.md` (Phase E)
