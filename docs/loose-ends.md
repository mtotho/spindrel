---
tags: [spindrel, loose-ends, todo]
status: active
updated: 2026-05-01 (Logged run_script auto-import gap + list_tool_signatures default-limit problem from heartbeat token-cost trace)
---
# Loose Ends

Active items only. Resolved bugs → [[fix-log]]. Architectural decisions → [[architecture-decisions]]. Track-specific work → `Track - *.md`. Untriaged review findings → [[open-issues]].

## Bugs — Open

### `run_script` description claims auto-import but doesn't auto-import (2026-05-01)
**Surfaced**: Heartbeat trace `e0874e14-…` burning 4 iterations on `provide_either_inline_script_or_stored_script_reference` and `NameError: tools is not defined`.
- The `script` parameter description (`app/tools/local/run_script.py:51`) says: *"Auto-imports `from spindrel import tools`"*. This is false. `app/services/script_runner.py:write_script_files` writes the helper module next to the script but does not prepend any import. Bots that trust the description and skip the import line hit `NameError` on first dispatch.
- The `script` vs `(skill_name + script_name)` mutex at `run_script.py:111` triggers when *either* `skill_name` or `script_name` is set alongside an inline `script`. Bots passing `skill_name="<bot-id>"` (string description metadata) plus an inline `script` get `provide_either_inline_script_or_stored_script_reference` with no hint about which arg was the offender. Mutex should require BOTH `skill_name` AND `script_name` to be set before treating it as stored-script mode, OR ignore one of them when an inline `script` is also provided.
- Fix path: pick one — either implement the auto-import (prepend `from spindrel import tools` to the user's script source in `write_script_files`) and keep the description, or drop the auto-import claim from the description. Tighten the mutex check to `script_name and skill_name` AND emit a clearer error naming the offending arg pair.

### `list_tool_signatures` default limit invites 12K-token catalog dumps (2026-05-01)
**Surfaced**: Same heartbeat trace. Bot called `list_tool_signatures(limit=200)` and burned ~12K tokens enumerating tools that were already in its enrolled working set. Default is `50`, max `200` (`app/tools/local/discovery.py:519-522`). The Phase-1 heartbeat-surface fix (2026-05-01) suppresses this tool from heartbeats entirely so the original failure mode no longer fires there. Open question: whether to also reduce the default to `25` for chat surfaces and add a stronger nudge toward `category=` filtering. Defer until we see whether chat surfaces have the same problem.

### `spatial-checks` Mission Control Review captures time out on deck selector (2026-04-30)
**Surfaced**: Spatial widget stewardship visual-feedback run against
`localhost:5173`. `spatial-checks` staging succeeded and browser capture passed
10/12, but `spatial-check-attention-review-deck` and
`spatial-check-attention-run-log` timed out waiting for
`[data-testid="attention-command-deck-what-now"]`. Existing artifacts show the
Mission Control Review and Sweep history pages visibly populated, so this may be
a stale scenario/action timing issue rather than a product regression. Fix path:
rerun with trace/screenshot debug around the two specs and either restore the
deck test id in the active pane or relax the wait predicate to the current
visible review/run-log contract.

### Harness full-tier live parity sweeps can overload shared channel replay (2026-04-29)
**Surfaced**: Codex/Claude live parity roundup. Running several broad
`run_harness_parity_live.sh --tier ...` sweeps at the same time reuses the same
Codex and Claude harness channels. Focused checks pass, but full sweeps in
parallel can push channel consumers past replay retention and fail with
`ReplayLapsedPayload` / `client_lag`. Fix path: either make the live runner
allocate isolated disposable channels/sessions per sweep, or serialize full
tier sweeps and keep only focused `-k` slices parallel-safe.

### Spatial heartbeat satellites can reuse React keys (2026-04-29)
**Surfaced**: Local Vite run during spatial screenshot capture. React logged
duplicate child keys like `heartbeat:2026-04-30T00:00:00+00:00`, which means
multiple heartbeat satellite items can share the same timestamp-derived key.
Fix path: include the owning channel/bot/task identity in the satellite key so
near-simultaneous heartbeats do not duplicate or disappear during rerenders.

### Project terminal screenshot emits xterm dimensions client error (2026-04-29)
**Surfaced**: Project Workspace Phase 2B screenshot capture. Local Vite console logged `TypeError: Cannot read properties of undefined (reading 'dimensions')` from `@xterm/xterm` while capturing Project terminal artifacts. Capture still passed, but the terminal unmount/viewport path should be checked before relying on this surface for longer visual runs.

### `git stash --keep-index` slips past the no-stash hook (2026-04-27)
**Surfaced**: Phase 2.5 parity-gate session. The PreToolUse hook in
`dotfiles/claude/hooks/block-git-stash.sh` blocks `git stash pop` /
`git stash apply` but `git stash` (and `git stash --keep-index`) is
not blocked at session start — only the recovery commands are. An agent
that mistakenly stashes can't recover via the normal pop path; recovery
required `git stash show -p > patch && git apply patch`. Fix path:
extend the hook matcher to block ALL `git stash …` invocations
including bare `git stash` and `git stash push --keep-index`. Path:
`dotfiles/claude/hooks/block-git-stash.sh`.

### Dashboard tools integration tests have four standalone failures (2026-04-25)
**Surfaced**: Native widget action rollback fix verification.
- `tests/integration/test_dashboard_tools.py::TestPinWidget::test_pins_native_library_widget_and_creates_instance` fails in isolation because `pin_widget(core/notes_native)` returns a payload without `tool_name`.
- `TestPinWidgetLibrary::test_unknown_library_widget_returns_error` and `test_pins_template_tool_renderer_as_adhoc_widget` fail in isolation with `ValidationError: Unknown bot_id 'test-bot'` from `validate_tool_context_requirements`, suggesting the DB-seeded bot fixture no longer satisfies the registry-backed bot-context check used by template renderer instantiation.
- `TestMovePins::test_move_to_header_normalizes_h_to_1` fails in isolation because header-zone move now leaves `grid_layout.h == 2`, while the test expects `1`.
- Verified under `Dockerfile.test` / Python 3.12; local Python 3.14 skips DB-backed async SQLite tests by guard. These are separate from the `MissingGreenlet` regression, whose targeted tests pass.

### file_sync watch handler drops `session_mode` and prompt-template source metadata on update (2026-04-24)
**Surfaced**: Cluster 10 refactor preservation pass.
- **Watch-mode workflow upsert** (`app/services/file_sync.py::_upsert_workflow_row` watch branch) doesn't set `session_mode` on add or update. A YAML edit changing `session_mode: interactive` won't take effect until the next full `sync_all_files()` run. `sync_all_files` sets it correctly.
- **Watch-mode prompt-template update** (`_upsert_prompt_template_row` watch branch) doesn't update `existing.source_path` / `existing.source_type` on hash mismatch. If a prompt template file moves between dirs (e.g. `prompts/` → `integrations/foo/prompts/`) the row's source classification stays stale until the next full sync.
- Both preserved as-is by Cluster 10 (behavior-preservation contract). Fix is a 2-3 line change per branch — drop the `if not is_watch:` guard once the asymmetry is confirmed unintentional.

### UI design debt backlog (updated 2026-04-24)
Canonical spec `spindrel/docs/guides/ui-design.md` §8 enumerates current violations. Not a single fix — rolling cleanup: migrate each entry when its file is touched for another reason. Track progress in [[ui-vision]].

**Migrated 2026-04-23 (Pass 3)**: `settings.tsx` header + tab strip, `ChannelDashboardBreadcrumb.tsx`, `ChannelSettingsSections.tsx` (first-landing sections incl. TagEditor, DangerZone, owner row, metadata footer, DashboardSettingsLink, AgentIdentitySection AlertTriangle), `DashboardConfigForm.tsx`, `DashboardTab.tsx`. All now 0 `useThemeTokens()`, 0 inline hex.

**Migrated 2026-04-24 (Pass 4b)**: guide/skill reset removed the non-canonical gradient/shadow CTA rule; `SettingsControls.ActionButton` primary is now low-chrome transparent accent text instead of a filled blue row button; integration control proof path (`ActivationsSection`, `ActivationCard`, `ActivationConfigFields`, `BindingsSection`, `BindingForm`, `SuggestionsPicker`, `MultiSelectPicker`) is now token/Tailwind, 0 `useThemeTokens()`, with activation add-ons split into Added vs Available plus filter.

**Migrated 2026-04-24 (Pass 4c start)**: `TasksTab`, `TaskCardRow`, `TaskConstants`, and `Spinner` now use grouped control flow, quiet segmented filters, borderless tonal rows, semantic token badges, and no `useThemeTokens()` in the visible task list path. `TaskConstants` no longer carries Bootstrap-blue status/type badge classes.

**Migrated 2026-04-25 (Admin Tasks pass)**: `/admin/tasks`, task detail/create/edit, `TaskStepEditor`, `StepsJsonEditor`, `JsonObjectEditor`, and channel `PipelineRunLive`/`PipelineRunPreRun` are now token/Tailwind, low-chrome, no native selects in refreshed task controls, no Bootstrap-blue/pulse builder states, no hard-coded JSON syntax hex colors, and no colored left rails in refreshed task calendar/schedule rows.

**Still outstanding**: inline hex in `MarkdownContent`, `SystemPauseBanner`, `ApprovalToast`, `MemoryHygieneGroupBanner`, `DelegationCard`, `IndexStatusBadge`, `ToolsInContextPanel`, `ChannelHeader` (chat-view `#f87171`/`#fbbf24` + `animate-pulse`; header visual direction should otherwise be preserved); `useThemeTokens()` callers in `DetailPanel`, `ChatMessageArea` skeleton, and the deeper channel settings tab panels (`HeartbeatTab`, `PipelinesTab`, `AttachmentsTab`, `HistoryTab`, `ChannelWorkspaceTab`, `ChannelFileBrowser`, `ContextTab`, `LogsTab`, `AutomationTabSections`, `AgentTabSections`).

### Streaming tokens use terminal-mode font in non-terminal channels (2026-04-24)
**Surfaced**: Scratch Pad triage. Streaming assistant tokens render in the monospaced/terminal font even when the channel is not in terminal chat mode. Should use the normal chat body font for default-mode channels and reserve mono for terminal mode. Likely in `ChatMessageArea` streaming path — check whether the live-token renderer short-circuits the theme selector that settled messages use.

### UI polish bugs triaged from Scratch Pad (2026-04-21)
- ~~**Providers page lacking padding**~~ — fixed 2026-04-24 during Provider Refactor Phase 5 UI pass; list wraps cards in a `px-6 py-5` / `px-4 py-3` Tailwind container.
- **Streaming shows wrong bot typing sometimes** — still seeing incorrect "typing…" attribution in multi-bot channels. Intermittent; needs repro + SSE event inspection.
- **Wrench icon in chat header — purpose unclear** — affordance is present but action/label not self-evident. Either remove or relabel.
- **Skill tag styling inconsistent in chat** — in chat feed, skill tags don't match the tag styling used elsewhere (admin / library). Unify.
- **Attachment disappears when attached from web** — uploading an attachment in the web composer sometimes drops it before send. Repro + check `useAttachments` / upload state.
- **Model picker in input was supposed to change model for channel, not turn** — currently turn-scoped, user wanted channel-scoped default. Either flip the default or add an explicit channel-override affordance.
- **Can't scroll in Jump tab** — Jump tab inside mobile drawer / command palette unscrollable when list is long.
- **Widgets still draggable outside edit mode** — can drag widgets in non-edit layout mode; things still a bit janky. Gate pointer-events on `layoutEditable`.

### Widget UX small items (2026-04-21)
- **Delete widget from chat feed** — no affordance to dismiss/remove a widget message from the chat feed; currently stays forever. Either per-message hide or per-channel "hide widget results" toggle.

### Webhook replay-contract gaps (surfaced 2026-04-24, Q-SEC-3)
Remaining protocol gap after the 2026-04-28 safety pass:

1. **BlueBubbles webhook — residual sender-protocol freshness limit** (`integrations/bluebubbles/router.py:webhook`). The 2026-04-30 callback hardening pass moved auth to header-first bearer tokens, kept deprecated `?token=` compatibility, and added durable DB-backed `data.guid` replay dedupe before dispatch. Remaining limit: BlueBubbles does not provide a request HMAC/timestamp/nonce contract, so a compromised token still has sender authority and can mint fresh GUIDs. Fix path: switch to HMAC over body + request time if BlueBubbles supports it; otherwise keep this documented as a deployment-tier risk rather than a local code bug.

2. **Slack — NO webhook surface** (`integrations/slack/router.py` has ZERO POST routes; uses Socket Mode via `slack-bolt.AsyncSocketModeHandler`). This is intentional and tracked only so a future migration to the Slack Events API (HTTP POST `/events` with `X-Slack-Signature` + `X-Slack-Request-Timestamp`) forces a fresh drift-pin file for the signature+timestamp+nonce contract.

### Verification items (2026-04-21)
- **Endpoint catalog unit test expects a removed workspace pull route** — surfaced 2026-04-29 during startup-bootstrap boundary verification. `tests/unit/test_endpoint_catalog.py::TestWorkspaceEndpointsCoverage::test_workspace_pull_and_cron` still expects `POST /api/v1/workspaces/{workspace_id}/pull`, but `app/routers/api_v1_workspaces.py` at `HEAD` exposes `GET /{workspace_id}/cron-jobs` and no workspace pull route; pull appears to live under admin operations as `POST /operations/pull`. Decide whether to restore a workspace-scoped pull endpoint or update the catalog coverage to the current route contract.
- **App import logs widget-authoring tool circular-import warning** — surfaced 2026-04-29 while smoke-importing `app.main`. `python -c "from app.main import app; print('ok')"` completes, but tool discovery logs `Failed to import tool file ... app/tools/local/widget_authoring.py` because `app.services.widget_templates` imports `ToolResultEnvelope` from partially initialized `app.agent.tool_dispatch`. This looks pre-existing and non-fatal, but it means the import smoke is not clean and the widget-authoring tool may be missing until the cycle is broken.
- **`test_integration_setup.py` github + ssh tests are test-isolation-sensitive** — surfaced 2026-04-24 during Q-MACH neighbor sweep. Running ANY machine-control-related test file before `test_integration_setup.py` (confirmed reproducible with Phase O's `test_machine_control_drift.py` alone and `test_ssh_provider.py` alone, so pre-existing and not caused by Q-MACH) causes `test_example_integration_discovered` + `test_status_ready_when_env_vars_set` + `test_status_not_configured_when_no_env_vars` + `test_ssh_exposes_machine_control_metadata` to fail — env vars or integration-manifest cache state leaks between files. All four pass in isolation. Root cause likely in `app/services/integration_manifests.py` module-level cache or an earlier test's `os.environ.pop`. Not a product bug; test-infra hygiene item.
- **Token cache looks right?** — paste from user:
  ```
  { "model": "gpt-5.4", "iteration": 1, "channel_id": "d0cb2ce8-...", "provider_id": "chatgpt-subscription",
    "total_tokens": 48562, "cached_tokens": 13824, "prompt_tokens": 48544, "completion_tokens": 18 }
  ```
  `prompt_tokens + completion_tokens = 48562 ≈ total_tokens` ✓, `cached_tokens=13824` on `chatgpt-subscription` provider. Sanity-check that cache-hit math reports the right number in the chat header's context-budget pill — after the Context Estimation Consolidation landing, the surface should already be `api` truth, but verify once with a live run.
- **BlueBubbles wake-word — send a test message, confirm integration enabled in admin UI; close or re-surface with a specific failure.** The `[unknown]` phone-number portion shipped 2026-04-18 (see Fix Log), so the prior symptom may already be resolved.
- **Session-router plan review integration test stalls in local harness** — `timeout 30 pytest tests/integration/test_sessions_router.py -q -k review_adherence` hangs with no pytest output after route setup, while unit coverage for the semantic-review path is green. Need to isolate whether the stall is in the FastAPI test client, session-plan SSE publish path, or broader router teardown for plan endpoints.

## Bugs — Open (pre-existing)

### Harness `harness_workdir` can bypass resolved WorkSurface
**Surfaced**: 2026-04-30 (WorkSurface isolation audit, HIGH). `app/services/agent_harnesses/project.py` prefers Project/instance WorkSurface when available, then falls back to `bot.harness_workdir`. That fallback is operator-target config, not ordinary isolation policy. Fix path: prefer WorkSurface cwd for channel turns; require explicit operator grant/path-within-root proof when `harness_workdir` points outside the resolved WorkSurface.

### Security doc needs deeper threat-model pass
**Surfaced**: 2026-04-19 (security audit); updated 2026-04-30 after first agentic-threat pass. `SECURITY.md` now covers reporting, self-hosted deployment posture, high-risk operator surfaces, deployment tiers, agentic-AI risk classes, and the current audit surface. Still missing inbound-integration untrusted-input rules, per-surface hardening checklist, and concrete green gates before encouraging public internet exposure.

### Codex harness native compact cards repeat and context budget can show 0%
**Surfaced**: 2026-04-27 (harness terminal stop/approval pass). Live Codex harness sessions showed frequent "Native compaction completed" harness cards after ordinary turns, and the harness context popover reported "Context 0% left after native compact" even while turns still executed. This was not fixed in the stop/approval pass. Need to inspect whether native compaction events are being persisted/rendered once per turn replay, whether the UI treats post-compact usage totals as exhausted instead of refreshed, and whether duplicate compact events should be collapsed in terminal mode.

### Dashboard edit mode: viewport-resize while editing needs proper handling
**Surfaced**: 2026-04-19. Today's fix restored drag/resize (`widgets/index.tsx:178`) by dropping the `breakpoint === "lg"` condition from `layoutEditable`. The commit-side gate at `onLayoutChange` (line 410) still prevents narrow-breakpoint coordinates from being written to `grid_layout`, so resizing window while in edit mode is safe today — but the UX is rough: at md/sm/xs the user can still *visually* drag widgets (because `isDraggable=true` whenever `layoutEditable` is true) and nothing persists, which is confusing. Proper handling options: (a) disable gestures when at non-lg breakpoints while still showing an edit-mode indicator, (b) provide per-breakpoint editable layouts so users can customize stacking at md/sm, (c) switch to a single-breakpoint grid and handle narrow viewports with horizontal scroll. Currently (a) is closest to the original intent — needs a "widen window to edit" overlay/banner at narrow breakpoints. Related code: `BREAKPOINTS` (line 61), `stackFor` in layouts memo (line 210).

### Vite dev server appears to not pick up `global.css` changes
**Surfaced**: 2026-04-18 (session 22, widget polish pass). User reported scrollbar styling changes in `ui/global.css` weren't reflecting in the running dev server (`localhost:5173`) even with DevTools open. Specifically: `::-webkit-scrollbar-button { display: none !important }` had no effect — the native ▲▼ scroll arrows were still rendering on dashboard cards. Same with thumb color updates. Multiple consecutive edits to the same `::-webkit-scrollbar-thumb` rule didn't surface in browser. User noted "ive never not had my local dev server not refresh" — atypical for this repo. `global.css` is imported once via `ui/src/main.tsx:1` (`import "../global.css"`). Hypotheses: (a) Vite's CSS HMR is broken for top-level `global.css` (possibly due to the relative-path import from `src/main.tsx`?), (b) browser SW or static asset cache from a prior build is being served, (c) a React StrictMode-driven double-mount is hiding the second style injection. Workaround: hard-refresh + restart Vite. Real fix: investigate whether moving `global.css` into `ui/src/` (so it's covered by `src/**` HMR scope) helps, or add an explicit `?inline` import or `<link>` injection. **Repro**: edit `ui/global.css` line 137 (`::-webkit-scrollbar-thumb` background), save, observe browser doesn't update without hard refresh.

### `on_pipeline_step_completed` has no terminal-state guard
**Surfaced**: 2026-04-18 (test quality Phase F.1). `app/services/step_executor.py:1446-1451` unconditionally writes `state["status"] = "done" if status == "complete" else "failed"` with no pre-check that the step was `running`. A double-callback (generic hook dispatcher double-fires, retry resume, parent restart replays completion) silently overwrites terminal state: an already-`done` step can be rewritten with a different result; an already-`failed` step flips to `done` with the error cleared. Same shape as the `decide_approval` stale-status drift. Pinned by `test_when_already_done_reentered_then_result_silently_overwritten` + `test_when_already_failed_reentered_with_complete_then_flips_to_done` in `tests/unit/test_step_state_transition_guards.py`. Fix options: (a) add `if state.get("status") in {"done", "failed"}: return` guard at line 1446, (b) flip only if `state["status"] == "running"`, (c) log a WARNING when drift detected so we see how often it actually fires before hardening.

### `outbox.enqueue` docstring falsely claims IntegrityError on duplicate tuple
**Surfaced**: 2026-04-18 (test quality Phase E.6). `app/services/outbox.py:222-224` docstring says `(channel_id, seq, target_integration_id)` is unique and re-enqueue raises `IntegrityError`. Migration 188 explicitly omitted this constraint (its comment at lines 18-26 explains why: seq is assigned post-commit by the in-memory bus, making a pre-commit unique constraint unreliable). Actual behavior: re-enqueue silently inserts duplicate rows; a batch containing a duplicate target commits all rows with no rollback. Any caller relying on the docstring's IntegrityError for idempotency protection is not getting it. Pinned by `test_outbox_enqueue_idempotency.py` drift-pin tests. Fix options: (a) correct the docstring only (callers were warned), (b) add the unique constraint to the schema (requires confirming seq is stable enough pre-commit), (c) add an explicit duplicate-check in `enqueue` before insert.

### Slack ordering polish — verify wait-on-outbox holds across load
**Surfaced**: 2026-04-17. Root cause was bus-vs-outbox race: TURN_STARTED rides the fast in-process bus, user's NEW_MESSAGE mirror goes through the slower outbox drainer. For web-originated messages, that lets the "thinking..." placeholder land in Slack before the user-mirror message. Confirmed by user: no issue when the message was typed in Slack; only web→Slack mirror case. Fixed in `integrations/slack/renderer.py` `_handle_turn_started` with `_wait_for_pending_outbox` (polls outbox up to 1.5s for pending Slack-targeted rows before posting the placeholder). Remaining: verify behavior under higher load — the wait might fail to cover cases where the drainer itself is backed up beyond 1.5s, and the poll interval (50ms) could compound with LLM latency on hot channels.

### `thinking_display: append` in Slack only shows "thinking" placeholder + final message
**Surfaced**: 2026-04-17. User reports with `thinking_display=append`, Slack shows a `thinking...` placeholder and the final assistant message but the intermediate streamed tokens never arrive — despite the web UI showing the full stream. Likely lives in the `TURN_STREAM_TOKEN` handler path in `integrations/slack/renderer.py` (update-coalesce → chat.update). Config plumbing is correct; this is a streaming-path bug. Unrelated to new `tool_output_display` setting.

### Forecast turn emits both forecast + current-weather widgets
**Surfaced**: 2026-04-17. When the user asked Rolland for the 7-day forecast, the resulting Slack message posted the forecast table widget AND a stray current-weather widget (Lambertville 69.42°F). Looks like the forecast tool is returning two envelopes — one for forecast, one for current conditions. Fix lives in the OpenWeather integration (probably `integrations/openweather/integration.yaml` widget template or the underlying tool emission), not in rendering.

### Tool discovery not surfacing expected tools — measure after 2026-04-17 prompt fix
**Surfaced**: 2026-04-16. User reports needing to explicitly add tools even with discovery enabled. Partially addressed this session (list_channels and read_conversation_history now auto-injected). But broader discovery effectiveness needs verification — are similarity thresholds too high? Is the stricter threshold for undeclared tools (+0.1, `app/agent/tools.py:359, 413, 449`) filtering out too much?

**2026-04-17 update**: Root cause was prompt-level, not threshold-level. Skill + tool index headers rewritten as imperative ("BEFORE answering, call get_skill/get_tool_info FIRST — these lines are an index, not content"). Auto-inject default flipped to 0 (machinery intact). New `discovery_summary` TraceEvent + UI card in trace detail lets us measure: % of turns where a `↑`-marked skill or discoverable-above-threshold tool got a real fetch call. Revisit after ~1 week of traffic. If fetch rates are healthy (target 60%+), leave auto-inject off; if low, iterate on prompts before re-enabling. Re-enable path: bump `SKILL_ENROLLED_AUTO_INJECT_MAX` env var.

**2026-04-18 update — partial root cause found + fixed**: A distinct bug contributed: **pinned tools whose names weren't also in `bot.local_tools`/`mcp_servers`/`client_tools` were silently dropped at schema-loading time** (`app/agent/message_utils.py:_all_tool_schemas_by_name`). The pin showed in the UI + trace as pinned, but the schema never entered `by_name`, so it was filtered out of `pinned_list` and not authorized. Fixed by loading schemas for any pinned name (local/client/MCP), widening the "has any tools?" guard to include `pinned_tools`, and correcting `discovery_summary.tools.included` to report the actually-loaded set. UI `togglePin` now also adds to `local_tools` to prevent new drift. New `search_tools` LLM-callable added (auto-injected when `tool_discovery=on`) so weak models can semantically search the full pool when the initial retrieval misses. Tool-index header now points at `search_tools` as the next step when the right tool isn't in the index. Tests: `tests/unit/test_pinned_tool_honored.py` + `tests/unit/test_search_tools.py`. **Still open**: second-turn behavior in the original trace (tool retrieved but LLM still refused) — unclear whether it's weak-model stubbornness (`gemma4:e2b`), a downstream `capability_gate` drop, or payload never delivered. Needs targeted trace with the final outbound tool list logged.

### Skill loading drift
`test_presenter_fetches_marp_slides_skill_before_creating` — LLM calls `create_marp_slides` directly instead of fetching skill first.

### Flaky bot-hooks tests
`test_cooldown_suppresses_second_fire` and `test_memory_scheme_tools_callable` — pass alone, flake in full runs. Likely state pollution.

### Channel-targeted tasks don't show output in channel
**Surfaced**: 2026-04-16. Tasks assigned to a channel don't display their output or step progress in the channel UI. Should have a "show output in channel" option (like heartbeat). Also need rich task step rendering in-channel (like scheduled tasks / workflows). Open question: when a task targets a channel, what context does it get — all messages? Per-step? Option to go contextless?

**2026-04-18 proof-pass finding**: `_suppress_channel = _is_pipeline_child(task)` at `app/agent/tasks.py:844` is the SOLE determinant — pipeline children suppress, everything else publishes TURN_STARTED/TURN_ENDED unconditionally if `channel_id` is set. The user-reported "no output" symptom doesn't match the code (non-pipeline tasks SHOULD publish). Either (a) tasks the user means aren't actually channel-bound, (b) the events fire but the UI isn't rendering them visibly, or (c) something else suppresses them. Live trace + UI check needed before designing the opt-in flag — confirm WHICH code path is actually silent. Once confirmed, design adds `Task.show_output_in_channel: bool` + UI wiring + temporal-block gating per the addendum below.

**2026-04-17 addendum — temporal block**: when the "contextless / no channel context" toggle gets implemented, the temporal context block added in `app/agent/context_assembly.py:1770` (`build_current_time_block` call, including Layer-2 resolved-references scan of prior messages) must also be suppressed under that toggle. A task running contextless should not get "Most recent user message: ~3d ago" or "'overnight' has now passed" bullets derived from the channel's conversation — those are channel context leaking back in by the side door. Gate in the same place that suppresses channel history injection. See [[architecture-decisions#Temporal Context Block Fires Unconditionally]].

### Slack image attachment doesn't show up in web UI
**Surfaced**: pre-2026-04-18 (scratch pad). Image uploaded to Slack, sent to a channel and interpreted by the AI, but the attachment doesn't render in the web UI. User suspected an SQL update may have already addressed it. **2026-04-18 proof-pass**: all attachment tests pass; no failing repro found via code reading. Need a live test — upload an image to a Slack-bound channel, confirm `Attachment` row gets created with `message_id` set, then check the web UI's attachment query. If row exists but UI doesn't render, the gap is in the read path; if no row, it's the Slack ingestion side (`integrations/slack/uploads.py`).

### Mobile: keyboard focus scrolls chat feed up
**Surfaced**: pre-2026-04-18 (scratch pad). Focusing the chat input on mobile causes the chat feed to scroll up a bit. Likely the keyboard reveal triggers a layout shift the chat scroll anchor doesn't compensate for. Reproduce on phone web. May interact with `flex-direction: column-reverse` chat scroll model (CLAUDE.md note).

### Mobile: side menu (bottom popup) UX
**Surfaced**: pre-2026-04-18 (scratch pad). Mobile side menu sheet should default to pinned + remember last selection. Sliding it up/down should be smoother. Currently feels janky. Polish pass needed.

## Code Smells (not bugs)

### `_enrolled_cache` is process-local
Multi-worker gap: enrollment on worker A not visible to worker B for 5 min. Acceptable for single-worker.

### Shared SourceFilterDropdown component
Tool selector in `TaskStepEditor.tsx` has source-filter dropdown that should be extracted as shared component. Skills page version uses inline styles — retrofit to shared Tailwind version.

### Usage source filter parity
**Surfaced**: 2026-04-24 (Usage anomaly dashboard). `/admin/usage` exposes a source-type filter because anomaly detection can classify traces as agent/task/heartbeat/maintenance, but the legacy summary/log/timeseries endpoints still ignore `source_type` query params. This means Overview anomaly sections honor the source filter while aggregate stat/timeline/log totals remain broader. Fix: teach the shared usage event query path to classify/filter source type consistently, or split the UI copy so source filtering is clearly scoped to anomalies only.

### Channel settings loading shells still have minor CLS
**Surfaced**: 2026-04-24 UI polish pass. Heartbeat loading was moved away from spinner-only swaps and stale enabled/disabled flashes, but visual review still showed small residual bounce because some placeholders do not exactly match final content size/position. Rule is documented in `docs/guides/ui-design.md`; finish by making loading shells shape-true to final controls before marking the channel-settings sweep done.

### Harness bridge tool labels differ by runtime
**Surfaced**: 2026-04-28 live harness smoke. Codex persists Spindrel bridge calls under canonical local names like `bennie_loggins_health_summary`; Claude Code persists the SDK-native MCP names like `mcp__spindrel__bennie_loggins_health_summary`. The calls work and persist with `tool_calls` / `assistant_turn_body`, but UI labels may look noisy or inconsistent. Decide whether to normalize display labels at persistence/render time while keeping native names in raw metadata.

### Bennie Loggins integration tools not loaded after restart
**Surfaced**: 2026-04-28 live harness parity. After a deployed server restart, `bennie_loggins_health_summary` was absent from configured MCP servers, local tool registry, and `ToolEmbedding`, so both Codex and Claude bridge tests could only prove generic Spindrel tools. Treat this as an external-integration setup/reload/indexing follow-up, not as the generic harness parity fixture. Need to verify whether deployment integrations should auto-load on boot or require an explicit enable/reload step.

### Widget Dev Panel UX debt
**Surfaced**: 2026-04-18 (P3 session). The `/widgets/dev#tools` sandbox is functional but thin. P3 shipped the pin flow + MCP execute; the rest is deferred. Each item is small-to-medium on its own — group them into a P5 polish pass or a new "Dev Panel UX" sub-phase.

- **Args form is minimal** — `ui/app/(app)/widgets/dev/ToolArgsForm.tsx` handles primitives/booleans/enums inline but falls through to a raw JSON textarea for arrays-of-objects and nested-object inputs. For tools like `list_tasks` with complex filters this is friction.
- **No copy / download affordance on the output pane** — raw JSON result + rendered envelope both lack a "Copy JSON" button or "Download envelope" action. Forces right-click inspection.
- **No keyboard shortcut for Run** — Cmd/Ctrl-Enter from inside the args form should trigger Run; currently keyboard users must tab to the button.
- **No in-session run history** — each new Run wipes the previous result. No way to compare two calls of the same tool with different args side-by-side, and no back/forward.
- **Tool metadata not badged** — the left-column tool list shows name + server_name only. Local vs MCP vs client origin, required scopes, and "has widget template" aren't visible. Users select tools blind.
- ~~**Three-pane layout cramped below ~1200px**~~ — addressed 2026-04-18: ToolsSandbox + RecentTab now stack vertically under `md` (<768px); fixed-width panes become full-width with sensible `max-h-[35-45vh]` caps. Tablet range (768-1200px) still tight — that's a separate responsive pass (compressing the middle column) if it matters.
- **"No copy / download affordance" partially addressed** — P4 session 19 added a "Copy envelope JSON" button to the PreviewPane in Templates tab. Tools tab output still lacks one.
- **MCP tool execution is admin-only from `/admin/tools/{name}/execute`** (by design, for now). Bot-scoped keys receive 403 on MCP. Broader MCP permissioning for bot keys is a separate auth story and belongs nowhere near this track.

## Technical Debt

### Skill/tool description audit after discovery telemetry lands
**Surfaced**: 2026-04-17. After the prompt-first discovery fix, the next lever is description quality. Many tool descriptions state *what they do* but not *when to call them*. The discovery_summary trace event will surface which tools/skills were above threshold but not fetched — those are the worst offenders. Tasks:
1. Add an optional `use_when` field to the `Skill` model (fall back to description). Update `_fmt_skill_line` at `app/agent/context_assembly.py:1209` to emit "Use when: {use_when}" when present.
2. Audit ~30 tool descriptions and ~20 skills using trace data — fix the ones with generic descriptions like "Run this", "Get info", etc.
3. Only after this, consider re-enabling auto-inject with a higher threshold.

**2026-04-17 update**: Closed the data-feedback loop into the skill_review hygiene job. The `skill_index` trace now stores ALL ranking scores + per-trace `relevance_threshold`/`auto_inject_threshold`. New `_build_discovery_audit_snapshot()` aggregates the last 14d of traces into "ranked relevant but rarely fetched" and "catalog skills repeatedly suggested but not enrolled" sections, injected into the skill_review prompt. New Step 2.5 in `DEFAULT_SKILL_REVIEW_PROMPT` instructs the bot to rewrite triggers/descriptions or prune based on the audit. Bots now self-correct description quality from real ranker signal — measure on next skill_review cycle. Items 1–3 above remain (use_when field still deferred until we see whether description rewrites alone close the gap; auto-inject re-enable still gated on 60% fetch-rate target).

### Task pipeline test coverage gaps
Task pipelines have 60 unit tests but coverage was noted as thin during scratch pad review. Need audit of edge cases: condition evaluation, step state transitions, error propagation, auto-inject prior results.

### Task → Workflow connection underexposed
Workflow dropdown buried in task creation Configuration section. See [[Ideas & Investigations#Task Execution Without LLM]].

## Cross-references
- [[fix-log]] — resolved bugs
- [[architecture-decisions]] — load-bearing decisions
- [[code-quality]] — god-function splits, duplication
