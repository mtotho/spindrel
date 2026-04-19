---
tags: [agent-server, completed, reference]
status: monitor
---
# Completed Tracks

Reference doc for tracks that have shipped and are in monitor-only mode. Compressed from per-track files. For active/in-flight work, see [[Roadmap]]. For load-bearing decisions, see [[Architecture Decisions]].

## Chat State Rehydration
**Shipped**: April 18, 2026 (single day, three phases).

Unified the web-chat UI on server-persisted rows so refresh / mobile tab-wake / background-originated approvals all produce the same inline UI as a live SSE stream. One write path; two read paths (SSE for deltas, snapshot endpoint for baseline).

- **Phase 1** — `GET /api/v1/approvals?channel_id=…` + `useChannelPendingApprovals` + `ChannelPendingApprovals` component that dedupes against live-turn approvals; `ApprovalToast` scoped-out the current channel to avoid double-signal. Phase 1 validated the pattern.
- **Phase 2** — migration 207 added `tool_calls.status` (TEXT NOT NULL DEFAULT 'running'), `tool_calls.completed_at`, `tool_approvals.tool_call_id` (FK) + `tool_approvals.approval_metadata` (JSONB). `recording.py` split into `_start_tool_call` / `_complete_tool_call` / `_record_tool_call`; `tool_dispatch.py` upserts a 'running' row at dispatch entry (or reuses `existing_record_id` on post-approval re-dispatch); decide endpoint flips the linked ToolCall on approve/deny; capability `extra_metadata` persisted to `approval_metadata` so orphan capability cards render the friendly label.
- **Phase 3** — `GET /api/v1/channels/{id}/state` returning `{active_turns, pending_approvals}`. Active turn = correlation_id with ToolCall/skill_index TraceEvent in last 10 min AND no terminal assistant Message. `useChannelState` + `rehydrateTurn` store action seed the store on mount before SSE connects; `replay_lapsed` invalidates the snapshot so reconnect reseeds. The 256-event replay buffer no longer holds correctness.

**Decision**: streaming assistant text stays ephemeral — the turn-end Message is source of truth. Tool calls, approvals, auto-injected skills all rehydrate; mid-stream text is reconstructed by the next delta or, if the stream ended, by the persisted Message.

**Tests**: `test_tool_call_status_lifecycle.py` (5), `test_channel_state_snapshot.py` (8), plus 85 adjacent (approval system/pin/suggestions, dispatch core gaps/envelope/timeout, tool policies, parallel tool execution, channel events).

**Closed loose ends**: D2 (streaming refresh / mobile tab-wake), "Tool approval prompt is non-inline in web UI".

## Security
**Shipped**: March 28 – April 6, 2026.

- **Tool policy + approval system** (March 28) — `ToolPolicyRule` + `ToolApproval` models, three actions (deny / require_approval / allow), tier-based defaults (readonly, mutating, exec_capable, control_plane), evaluated before every dispatch in `tool_dispatch.py`. Fail-closed: policy exceptions deny.
- **Command injection / SSRF / path traversal** (March 31) — `shlex.quote()` on shell paths, `realpath()` validation on exec stream-to paths, `app/utils/url_validation.py` blocks RFC1918/loopback/metadata IPs, applied to web search + webhook dispatcher + frigate. GitHub webhook validation made fail-secure. 24 regression tests.
- **API hardening** (April 2) — CORS tightening, login rate limit (5/15min/IP), task creation rate limit, env var name validation, startup script path validation.
- **Secret detection + redaction** — `app/services/secret_registry.py`, applied to chat responses + logging.
- **Security audit service** — `app/services/security_audit.py`, 18 checks, scored 0-100, `GET /api/v1/admin/security-audit`.
- **Scoped API keys** (April 5-6) — `app/services/api_keys.py`, `ask_` prefix, SHA-256 hashed, 40+ scopes, hierarchical (write implies read, parent covers child, wildcard), per-bot/per-integration/per-user.
- **All routes scoped + auto-generated endpoint catalog** (April 6) — `require_scopes()` on all ~237 previously unscoped routes across 30+ files. 12 new scope pairs. Replaced 800-line static `ENDPOINT_CATALOG` with `app/services/endpoint_catalog.py` — built at startup via FastAPI route introspection, extracts scopes from `require_scopes()` closures. ~370 entries, >90% scoped, validated by `test_endpoint_catalog.py`.
- **Capability approval system** — `CAPABILITY_APPROVAL` (required/optional/off), session tracking via `approve()` / `is_approved()`, approval gate in `tool_dispatch.py`, SSE enrichment for approval cards. Pinned in bot config bypasses. `skip_tool_approval` on channel_heartbeats.
- **API access tools** — `list_api_endpoints` + `call_api` replace old `api_docs_mode`. In-process ASGI transport (no network). Tool-restricted capabilities: bot-authored capabilities CANNOT specify local_tools/pinned_tools/mcp_tools/delegates.
- **XML tool-call suppression** — `ToolCallXmlFilter` in `app/agent/llm.py`, stateful streaming parser, suppresses XML tool calls some providers (MiniMax) emit alongside proper tool_use blocks.
- **Tier gating fix** (April 7) — tier gating only applies when `default_action != "allow"` — explicit allow-all means allow-all.

**Test coverage**: `test_security_hardening.py` (12 classes, 70+ assertions), `test_security_fixes.py`, `test_security_audit.py`, `test_security.py`, `test_api_keys.py` (28 tests), `test_api_access_tools.py` (10 tests), `test_endpoint_catalog.py` (10 tests), `test_capability_*` suites.

**Config**: `TOOL_POLICY_ENABLED=True`, `TOOL_POLICY_DEFAULT_ACTION=deny`, `TOOL_POLICY_TIER_GATING=True`, `RATE_LIMIT_ENABLED=True`, `SECRET_REDACTION_ENABLED=True`, `CAPABILITY_APPROVAL=required`.

## Auto-Discovery
**Shipped**: April 5-6 (Phases 1, 2, 2.5, A-D), April 7 (Phase 3 — skill index RAG).

End state: bot needs only `model` + `system_prompt`. Optionally pin capabilities for guaranteed domain expertise. Everything else automatic.

- **Smart defaults** — `RAG_SIMILARITY_THRESHOLD: 0.3 → 0.45`, `TOOL_RETRIEVAL_THRESHOLD: 0.35 → 0.45`, `RAG_RERANK_ENABLED=True` (ONNX cross-encoder, zero API cost).
- **Skill auto-enrollment** — core skills (`source_type='file'`) auto-enrolled as on_demand for all bots; integration skills auto-enrolled when integration activated; both respect channel `skills_disabled`. Now superseded by per-bot working set (see [[Architecture Decisions#Per-Bot Persistent Skill Working Set]]).
- **Tool discovery** — `retrieve_tools()` with `discover_all=True` searches the full local pool, not just declared tools. Discovered tools get stricter threshold (`+0.1`, capped 0.65).
- **Skill metadata standardization** — added description, category, triggers columns (migration 166); standard frontmatter; admin UI shows description + category badges + trigger pills.
- **Enriched on-demand skill index** — shows `id: name — description [triggers]` instead of `id: name`. Zero additional DB queries.
- **Trigger keyword boost** — after cosine retrieval, checks trigger keywords vs user message; injects trigger-matched skills the cosine missed.
- **Hybrid search (BM25 + RRF) for tool retrieval** — BM25 full-text alongside cosine, fused via `reciprocal_rank_fusion()`. GIN index on `tool_embeddings.embed_text` (migration 168).
- **Capability RAG** — `capability_embeddings` table + HNSW index (migration 171). `app/agent/capability_rag.py`. `CAPABILITY_RETRIEVAL_TOP_K=5`, `CAPABILITY_RETRIEVAL_THRESHOLD=0.50`. Replaced flat list injection.
- **Capability approval gate** (Phase 2.5) — `CAPABILITY_APPROVAL=required`, session tracking, SSE enrichment, pinned bypass.
- **Skill config simplification A-D** — killed RAG mode, killed `similarity_threshold`, killed `skills_override`, removed `compatible_templates`, dropped 5 whitelist `_override` columns (migration 174). Only `_disabled` + `_extra` remain.
- **Phase 3 — Skill Index RAG** (April 7) — replaced flat on-demand skill dump with semantic retrieval (`retrieve_skill_index()` in `rag.py`). Hybrid vector+BM25, top-8 per turn (threshold 0.35), 5-min TTL. `get_skill_list` tool as escape hatch. Reuses existing skill embeddings in `documents` table.

Validated through real usage: bots find the right tools, skills surface, minimal config is sufficient.

## Workflows
**Shipped**: complete, monitor only. 186 unit tests, 22 E2E tests.

- **Engine** (`app/services/workflow_executor.py`, 1225 lines) — state machine, condition evaluation (pure dict-based, no eval()), prompt template rendering (`{{param}}`, `{{steps.id.result}}`), three step types (`agent` LLM task, `exec` shell, `tool` inline), approval gates (`requires_approval` → `awaiting_approval`), step actions (approve / skip / retry), execution cap (`WORKFLOW_MAX_TASK_EXECUTIONS`), error handling (`on_failure: abort | continue | retry:N`), session modes (`isolated` vs `shared`), workflow snapshots at trigger time, integration event dispatch, recovery for stalled runs (row locks).
- **Tool**: `manage_workflow` — list, get, trigger, get_run, list_runs, create.
- **API**: full admin CRUD, trigger with params, step approve/skip/retry, cancel, export YAML.
- **UI**: 21 TSX files, well-split. List page with search + recent runs feed. Detail editor: definition + runs tabs, step editor, run viewer. Approval buttons when status=awaiting_approval. Condition builder, YAML editor, trigger modal, param editor.
- **Tests**: 5087 lines across 6 files. `test_workflows.py` (conditions/rendering/validation), `test_workflow_advancement.py` (38 tests — completion, gates, types, snapshots), `test_workflow_recovery.py` (34 tests — idempotency, stalled recovery, dispatch), `test_workflow_improvements.py`, `test_workflow_step_types.py`, `test_workflow_tool.py`. Integration tests: 20 tests (DB schema fixture issue, not code).
- **Examples**: research-and-report.yaml, channel-setup.yaml, system-diagnostics.yaml.
- **Orchestrator integration**: `manage_workflow` in pinned tools; on-demand skills `workflows.md` + `workflow-compiler.md`.

**Optional polish**: fix integration test DB schema fixture, approval discoverability toast, session mode UI note in trigger modal. All backlog.

## Memory Hygiene
**Shipped**: complete. 66 unit tests.

Periodic background scheduler creates agent tasks to curate workspace-files memory across all channels. The bot reviews cross-channel memory, promotes stable facts to MEMORY.md, prunes stale entries, detects contradictions, generates reflections, consolidates skills.

**Architecture**: `task_worker → check_memory_hygiene → find workspace-files bots → resolve config (bot > global > built-in) → check next_hygiene_run_at → activity gate → dedup → create_hygiene_task` → agent runs with hygiene prompt.

**Config hierarchy** (bot override > global > built-in):

| Setting | Global key | Bot column | Default |
|---|---|---|---|
| Enabled | `MEMORY_HYGIENE_ENABLED` | `memory_hygiene_enabled` | `false` |
| Interval (hours) | `MEMORY_HYGIENE_INTERVAL_HOURS` | `memory_hygiene_interval_hours` | `24` |
| Only if active | `MEMORY_HYGIENE_ONLY_IF_ACTIVE` | `memory_hygiene_only_if_active` | `true` |
| Prompt | `MEMORY_HYGIENE_PROMPT` | `memory_hygiene_prompt` | built-in 8-step prompt |
| Model | `MEMORY_HYGIENE_MODEL` | `memory_hygiene_model` | bot's default |
| Target hour | `MEMORY_HYGIENE_TARGET_HOUR` | `memory_hygiene_target_hour` | `-1` (disabled) |

**Stagger**: without target hour, deterministic `hash(bot_id) % (interval_hours * 60)` minutes from bootstrap. With target hour (`0-23`), 60-min window around target hour. Uses `zoneinfo.ZoneInfo(settings.TIMEZONE)`.

**Skill curation hook** (Phase 3.6 of Skill Simplification): hygiene prompt Step 6 split into "(a) bot-authored skills you wrote" and "(b) your enrolled working set". `create_hygiene_task` injects a live `## Working set` snapshot with surface counts. New `prune_enrolled_skills` tool.

**Key files**: `app/services/memory_hygiene.py`, `app/config.py` (`DEFAULT_MEMORY_HYGIENE_PROMPT`), `app/routers/api_v1_admin/bots.py` (admin API), `ui/app/(app)/admin/bots/[botId]/MemoryKnowledgeSections.tsx`.

## Mission Control
**Status**: working, DB-backed, frozen. Make what's there work, don't extend.

Separate integration (`integrations/mission_control/`) providing kanban + timeline + structured plans. NOT core app code.

- **Own SQLite DB** at `~/.agent-workspaces/mission_control/mc.db`. Models: `McKanbanColumn`, `McKanbanCard`, `McTimelineEvent`, `McPlan`, `McPlanStep`.
- **Write-through markdown rendering**: every DB mutation regenerates `tasks.md` (kanban), `timeline.md` (activity), `plans.md` (structured plans). Workspace .md files auto-injected into context. Bot reads markdown, mutations go through tools → DB → re-render.
- **Tools**: `create_task_card`, `move_task_card`, `append_timeline_event`, `draft_plan`, `update_plan_step`, `update_plan_status`.
- **Plan execution engine** (`plan_executor.py`): when plan approved, creates core Tasks to execute steps. `hooks.py` advances plan on task completion. Approval gates on certain steps.
- **Skills**: `mission_control.md`, `planning.md`, `project-management.md`, `content_feeds.md`, `integration-builder.md`.
- **Dashboard**: React/Vite app at `:9100`. Read-only access to workspace files.
- **Activation flow**: `channel_integrations.activated=true` → context assembly injects `mission-control` capability → capability pulls in MC tools + skills + system prompt fragment.

**Router migrated out of core** (1765-line monolith deleted). **Template step removed from channel creation**. **MC capability extended with workspace file organization guidance**.

**Known issue**: dashboard container restarts (~172 silent restarts since March 31). Crash handlers added (`uncaughtException` + `unhandledRejection` in `server.ts`, auto-restart loop with backoff in `container.py`). Pending: rebuild MC image and deploy to capture root cause.

**Frozen**: dashboard enhancements, MC as separate product, multi-workspace for MC. `app/services/task_board.py` may be dead code now that MC has its own services — not worth moving.

## Multi-Bot Channels
**Status**: stabilized, structural rewrite complete. 5+ rounds of identity/routing bug fixes culminated in the unified pipeline + post-marker reinforcement.

**Architecture**: a channel has one **primary bot** (`Channel.bot_id`) and zero or more **member bots** (`ChannelBotMember` rows). Users `@`-mention bots to direct messages. All bots share one Session; each message tagged with `_metadata.sender_id` for attribution. History rewriting (`_rewrite_history_for_member_bot`) converts other bots' assistant messages to `[Bot Name]: ...` user messages and drops their tool calls.

### Key files
| File | What it does |
|---|---|
| `app/routers/chat/_context.py` | `prepare_bot_context()` — unified 8-step pipeline for all paths |
| `app/routers/chat/_multibot.py` | Routing, mention detection, member bot execution |
| `app/routers/chat/_routes.py` | Route handlers |
| `app/agent/tags.py` | `_TAG_RE` regex, tag parsing/resolution |
| `app/agent/context.py` | `current_invoked_member_bots` ContextVar for dedup |
| `ui/src/stores/chat.ts` | `memberStreams` state keyed by stream_id |

### Pipeline order (invariant, all paths)
swap system prompt → save raw snapshot → extract user prompt → rewrite history → apply attribution → strip metadata → inject member config → build identity preamble.

### Dedup mechanisms
1. `current_invoked_member_bots` ContextVar — prevents `invoke_member_bot` from re-firing auto-invoked bots
2. `_MEMBER_MENTION_MAX_DEPTH = 3` — prevents cascading mention chains
3. `_channel_throttled()` — rate-limits bot-to-bot replies
4. `already_invoked` param on `_trigger_member_bot_replies()` — post-response dedup
5. Turn-level set tracking in `current_turn_responded_bots`

### Critical invariants
See [[Architecture Decisions#Multi-Bot Shared Session Model]] and [[Architecture Decisions#Bot system_prompt Reinforcement (Position is Load-Bearing)]] for the load-bearing rules.

- After any routing change, `messages[0]` MUST be rebuilt for the bot about to run
- Routed non-primary bots MUST get a `system_preamble` injected right before user message — `messages[0]` alone is insufficient because workspace files + history drown it out
- Snapshots for member bots MUST be captured BEFORE rewrite/strip — `messages` is mutated in place for the primary
- The raw snapshot (`_raw_messages_for_members`) MUST include the current user message (appended later by `assemble_context`)
- Member bots get ALL assistant messages rewritten to user role — including their "own" — to break the poisoned-history feedback loop
- Member bots SKIP channel `carapaces_extra` (those are for the primary bot's role)
- The user's current message MUST be at the END (passed as `prompt`/`user_message`)
- `finishStreaming` MUST NOT clear `memberStreams` — member bots finish independently
- `startStreaming` SHOULD clear `memberStreams` — fresh request, fresh state
- Cancel and error paths must explicitly finish each remaining member stream

### Why preamble fixes alone always failed (session 13 diagnosis)
5+ sessions "fixed" identity confusion by strengthening the preamble. Every time it failed again. The preamble approach is fundamentally wrong: the model has no examples of its own voice and overwhelming examples of the primary bot's voice in the rewritten history. No amount of preamble overcomes the dominant voice.

The actual fix is structural: clean context (own system prompt + own memories + only the user's messages, no rewritten bot history) — which is what the rewrite-all-assistant-to-user + skip-channel-carapaces + post-marker reinforcement together produce. Do not attempt another preamble fix. The problem is what goes INTO the context, not what text describes it.

### Known remaining issues
- **UI member stream visibility gaps** — SSE observer reconnect can miss `stream_start` events. User may not see typing indicator until `stream_end` triggers DB refetch. Potential fix: heartbeat or initial-state sync on observer reconnect.
- **Concurrent filesystem operations** — multiple bots writing to the same workspace files can produce confusing partial-read output. Potential fix: per-bot working dirs or file-level locking.
- **Message ordering on persist** — `created_at` should order correctly, but near-simultaneous finishes can interleave oddly in the UI.

## Skill & Capability Simplification
**Shipped**: March 28 – April 14, 2026 (7 phases + 4 sub-phases).

End state: per-bot persistent working set with enrolled skill ranking + auto-inject. Two assignment surfaces: bot config + channel config. All legacy surfaces killed (pinned mode, carapace skills, workspace skills, channel skills_extra/disabled).

Full detail: [[Track - Skill Simplification]].

## Workspace Singleton Cleanup
**Shipped**: 2026-04-10 (session 14, single pass).

Single-workspace mode: every bot is a permanent member via `ensure_all_bots_enrolled`. POST/DELETE workspace-bot endpoints 410'd. `bots.workspace_only` dropped (migration 186). Starter skills auto-enrolled. Full detail: [[Plan - Workspace Singleton Cleanup]].

## Workspace Container Collapse
**Shipped**: 2026-04-14.

`exec_tool` uses `subprocess.run()` instead of `docker exec`. Deleted `Dockerfile.workspace`, workspace editor, container lifecycle endpoints/UI. Migration 196 drops 16 container columns. Docker socket stays for integration sidecars.

## Sub-Agent System
**Status**: core done (April 9). 25 unit + 10 E2E tests, all passing.

- `app/agent/subagents.py` — presets, `run_subagent`, `run_subagents`
- `app/tools/local/subagents.py` — tool registration
- 5 built-in presets: `file-scanner`, `summarizer`, `researcher`, `code-reviewer`, `data-extractor`
- Parallel execution via `asyncio.gather`, depth enforcement (sub-agents can't spawn sub-agents), rate limit (10/call)
- Base prompt auto-injection when `spawn_subagents` in bot tools
- Orchestrator bot has `spawn_subagents` in `local_tools`
- `skills/delegation.md` rewritten to cover both delegation and sub-agents
- Model Tiers UI card in Settings > Global (maps tier names → concrete models)
- Docs: `docs/guides/subagents.md` + mkdocs nav entry

**Design decision**: sub-agents are NOT bots (no persona, memory, sessions) and NOT capabilities — they're orthogonal to the capability simplification track.

**Pending polish** (in [[Roadmap]] active list): admin UI for managing presets, tracing/observability, cost tracking. User-defined presets via YAML/DB deferred — not needed yet.

## Integration Delivery Layer Refactor
**Shipped**: April 11, 2026 (single-commit build-up across ~12 sessions). 8 phases A–G + UI hookup + bus restructure + manual smoke bug sweep all in `development`. Commits: `5acb0220` (umbrella refactor), `68af8ec4` (smoke + IN_FLIGHT recovery), `5af9d381`/`75182b6c`/`426b7289`/`f53d4bd8` (manual smoke fixes). Phase H acceptance test still pending — see [[Track - Integration Delivery]].

End state: every integration is a `ChannelRenderer` subscribed to the channel-events bus. POST `/chat` returns 202. Outbox + drainer provide durability. Renderers run in the main process; Slack/Discord subprocesses handle inbound only. Adding a new integration is zero `app/` changes — drop `target.py` + `renderer.py` into `integrations/{name}/` and the discovery loop wires both registries automatically. See [[Architecture Decisions#Integration Delivery: Bus + Outbox + Renderer Abstraction]] for the full design + invariants.

**What landed (compressed phase summary)**:

- **Phase A — Domain types.** 8 frozen dataclasses under `app/domain/`: `ActorRef`, `Capability`, `DeliveryState`, `DispatchTarget`, `Message`, `OutboundAction`, `ChannelEvent` + 16 `ChannelEventKind` variants, `payload` discriminated union of 16 typed payloads. `MessageOut.from_domain()` parallel to `from_orm()`. 51 unit tests.
- **Phase B — Renderer abstraction.** `ChannelRenderer` Protocol + `DeliveryReceipt` (`app/integrations/renderer.py`), `renderer_registry`, `IntegrationDispatcherTask` + `RenderContext` (`app/services/channel_renderers.py`), `subscribe_all()` global subscriber API on the bus. **Silent-drop bug fix**: on subscriber-queue overflow the publisher drains the queue and pushes a `replay_lapsed` sentinel; consumers reconnect with `since=last_seq`.
- **Phase C1 — Migrate non-mirror dispatcher call sites.** 13 of 14 sites moved to `publish_typed`, gated under `USE_RENDERER_PIPELINE` flag. 4 core renderers (`NoneRenderer`/`WebRenderer`/`WebhookRenderer`/`InternalRenderer` in `app/integrations/core_renderers.py`) self-register at import.
- **Phase D — Outbox + drainer.** Migration `188_add_outbox.py`. New `app/services/outbox.py` (CRUD + payload serializer using `__type__` discriminators), `dispatch_resolution.py` (multi-target resolver replacing `_resolve_mirror_target`'s `.limit(1)` bug), `outbox_publish.py`, `outbox_drainer.py` (claim batches via `mark_in_flight` under `FOR UPDATE SKIP LOCKED`, deliver per-row in isolated sessions, exponential backoff capped at 300s + 10-attempt dead-letter, capability gating before invoking renderer). `persist_turn` writes outbox rows in the same transaction as message inserts. **`reset_stale_in_flight()` runs in lifespan startup** to recover rows stranded between IN_FLIGHT commit and renderer ack (does NOT increment `attempts`).
- **Phase E — POST /chat → 202.** `_mirror.py` deleted. `event_generator` (250-line SSE long-poll body) deleted. `/chat` and `/chat/stream` both return 202 `{session_id, channel_id, turn_id}`. New `app/services/turns.py` (`start_turn` → `TurnHandle`, acquires per-session lock via `session_locks`, raises `SessionBusyError` → translated to queued 202). New `app/services/turn_worker.py` (~340 lines extracted from `event_generator`: owns its own DB session, sets agent ContextVars per-task, pre-persists user message, drives `run_stream` via `emit_run_stream_events`, calls `persist_turn`, publishes `TURN_ENDED`, runs `maybe_compact`, triggers member-bot fanout, releases lock; exception handler publishes `TURN_ENDED` with `error` set). `USE_RENDERER_PIPELINE` flag DELETED — pipeline is unconditional. **Drainer no-renderer behavior**: row goes back to PENDING with 30s deferral capped at 480 defers (~4h), `defer_count` column added; cutover publishes `DELIVERY_FAILED`. Cancellation markers persisted (the `if not was_cancelled:` guard was deleted; legacy unconditional behavior restored).
- **Phase F — Slack + Discord renderers.** `SlackRenderer` (~700 LOC across `integrations/slack/{renderer.py, render_context.py, rate_limit.py}`) + `DiscordRenderer` (~440 LOC). Both self-register at import. Capabilities declared explicitly. Subprocess long-poll + `SlackStreamBuffer` + `DiscordStreamBuffer` deleted (~1500 LOC). `stream_chat` deleted from both `agent_client.py` files. **Original "Slack mobile sometimes never refreshes" bug fixed by 0.8s `chat.update` coalesce window + safety pass for in-flight tokens.** Single shared `SlackRateLimiter` (per-method token bucket, 429-aware). `tests/integration/test_slack_end_to_end.py` (3 tests) drives a 50-token streaming sequence and asserts <30 `chat.update` calls + final edit carries complete text.
- **Phase G — BlueBubbles + GitHub renderers + target boundary refactor + dispatchers.py deletion.** `BlueBubblesRenderer` (~290 LOC, ports legacy 1:1 with echo-tracker wired BEFORE every send), `GitHubRenderer` (~210 LOC). **`app/agent/dispatchers.py` DELETED (157 LOC).** `integrations/{bluebubbles,github}/dispatcher.py` deleted. **Target registry refactor**: `SlackTarget`/`DiscordTarget`/`BlueBubblesTarget`/`GitHubTarget` moved into `integrations/{name}/target.py`, `parse_dispatch_target` consults `target_registry`. `DispatchTarget` is now a type alias for `_BaseTarget`, not a discriminated union. `_load_single_integration` auto-imports `target.py` BEFORE `renderer.py`. **Phase F boundary regression cleaned**: explicit `import integrations.slack.renderer` lines deleted from `app/main.py`. `_fanout` was NOT deleted (the original track doc was wrong; it's still called by `inject_message(notify=True)` from non-BB integrations).
- **UI + Bus restructure (no legacy preservation).** `services.ChannelEvent` legacy envelope DELETED. `publish_typed(channel_id, event)` is the only publish path. `event_to_sse_dict` helper produces JSON-safe wire format. `useChatStream` (legacy SSE long-poll) → `useSubmitChat` (fire-and-forget POST returning 202). Chat store collapsed: dropped `streamingContent`/`thinkingContent`/`toolCalls`/`memberStreams`/`isLocalStream` etc., replaced with one `turns: Record<turn_id, TurnState>`. `ChatMessageArea` renders one `StreamingIndicator` per turn. `_run_member_bot_reply` migrated to `publish_typed` via shared `emit_run_stream_events` helper (~100 LOC of inlined translation switches deleted from both `turn_worker` and `_multibot`). `stream_id` removed everywhere — `turn_id` is the sole demux key.
- **Smoke + manual UI bug sweep.** Surfaced + fixed 9 distinct bugs: tool-call args JSON-string-vs-dict (`_coerce_tool_arguments`); SSE handler `aclose()` race against suspended generator (cancel + `await pending` BEFORE `aclose`); E2E harness still speaking legacy synchronous response shape (rewrote around `_post_and_consume_turn` SSE bus consumer); outbox missing IN_FLIGHT crash recovery; `SlackTarget` missing `message_ts` field (parse_dispatch_target throwing → NoneTarget fall-through → silent delivery loss); tool-role JSON content posted to Slack as APP messages; bot-reply duplication (TURN_ENDED + NEW_MESSAGE both delivered, compounded by NEW_MESSAGE on two paths); web UI synthetic-message permanent duplicate (timestamp dedup failed on browser/server clock skew, replaced with content-prefix match); Slack subprocess crash loop since Phase F (`/ask` slash command importing the deleted `stream_chat`); Slack-origin user messages echoed back as APP posts. Each is a one-line entry in [[Fix Log]].

**Test coverage**: ~5253 unit + integration passing across the touched surface (test_channel_events 24 tests, test_outbox 26, test_outbox_drainer 6, test_dispatch_resolution 9, test_slack_renderer 24, test_discord_renderer 14, test_bluebubbles_renderer 23, test_slack_rate_limit 7, test_domain_dispatch_target round-trips, test_slack_end_to_end 3 integration tests).

**Files notable for future work**: `app/integrations/renderer.py`, `app/integrations/renderer_registry.py`, `app/services/channel_renderers.py`, `app/services/channel_events.py`, `app/services/turn_event_emit.py`, `app/services/turn_worker.py`, `app/services/turns.py`, `app/services/outbox*.py`, `app/services/dispatch_resolution.py`, `integrations/{slack,discord,bluebubbles,github}/{target,renderer}.py`.

## Web-Native Conversion
**Status**: chat + sidebar + app shell DONE. Admin pages NOT started — folded into UI Polish track.

Goal: convert React Native UI from RN abstractions (View, Text, Pressable) to web-first HTML on the web path.

**Done**: MessageBubble, Avatar, StreamingIndicator, WebChatList, ChannelHeader, MessageInput, file browser polish, HudInputBar, HudFloatingAction, ChatBanners, HudStatusStrip, HudSidePanel, ActiveBadgeBar, ActiveWorkflowStrip, SidebarFooter, AdminNav, ChannelList, Sidebar, AppShell.

**Conversion patterns**:
- `Link asChild` + `Pressable` → `<Link><div className="...">` (renders as `<a>` on web)
- RN transform arrays → CSS transform strings
- NativeWind classes → inline styles with `useThemeTokens()`
- `ScrollView` → `<div style={{ overflowY: "auto" }}>`
- `numberOfLines={1}` → `overflow: hidden; textOverflow: ellipsis; whiteSpace: nowrap`

CSS classes in `ui/global.css` (Chat, Sidebar, HUD, Utility categories).
