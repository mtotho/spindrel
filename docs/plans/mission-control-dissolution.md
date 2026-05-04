---
title: Mission Control dissolution — implementation plan
summary: Collapse Mission Control / Operator / Attention triage. End state — one Errors tab in /admin/logs that lists actual deduped errors with route-to-channel / clear / ignore-signature actions. Delete the 3000+ LOC of intermediate AI-driven triage that nothing uses.
status: active
tags: [spindrel, plan, mission-control, attention, refactor]
created: 2026-05-03
updated: 2026-05-03
---

# Mission Control dissolution — implementation plan

## North star

There is one place to see the actual list of errors that occurred on the server: an **Errors** tab inside `/admin/logs`. Each row shows the deduped error (signature, count, first/last seen, sample message, trace link). Each row has three actions:

1. **Send to channel.** Pick a channel; the error is posted there as a structured message. Row is marked routed.
2. **Clear.** Marks resolved.
3. **Ignore signature.** Stops surfacing future occurrences of the same signature until un-ignored.

That's it. No "operator finding," no "code fix" tag, no "next action," no AI brief, no Autofix queue, no review history lanes, no sweep, no triage classification.

The 24h Daily Health summary stays and goes at the top of the same tab (it already exists, it works, you like it).

Everything else in the Mission Control / Operator / Attention sprawl gets deleted. The Project Factory absorbed launchable-work intake; this track absorbs error review. There is no third lane.

## Why

The current state has ~3000 LOC of intermediate code building a "triage" experience nobody uses on a single-user instance:

- `app/services/workspace_attention.py` — 2170 LOC
- `app/services/workspace_mission_ai.py` — 596 LOC
- `app/services/workspace_mission_control.py` — 382 LOC
- Plus routers, tools, UI surfaces, spatial overlays, tasks.

Per the 2026-05-01 session log, the Project Factory consolidation explicitly absorbed the launchable-work piece. What remains in Mission Control is a duplicate of the same primitives wrapped in operator-finding/sweep/review framing that doesn't add value.

The user wants a list of errors. The deterministic 24h rollup (`system_health_summary.py` + `/api/v1/system-health/recent-errors`) already produces that data. The job is to expose it cleanly and delete the rest.

## End state

### Backend

**Keep:**
- `app/services/system_health_summary.py` — deduped error rollup.
- `app/services/error_log_parser.py` — log parsing.
- `app/services/log_file.py` — rotating handler.
- `app/services/system_health_preflight.py` — boot-time health.
- `app/routers/api_v1_system_health.py` — `/api/v1/system-health/recent-errors`, `/recent-errors/promote` (gets simplified — see below), `/log-level`.

**Add:**
- `IgnoredErrorSignature` table: `signature: str (pk)`, `ignored_at: datetime`, `ignored_by: user_id`, optional `note: str`.
- `RoutedError` table: `signature: str`, `channel_id: str`, `routed_at: datetime`, `routed_by: user_id`, `posted_message_id: str | None`. (Or fold both into a single `error_state` row keyed by signature with a JSONB column. Keep it small — two columns or two narrow tables, not a system.)
- `POST /api/v1/system-health/errors/{signature}/route` — body: `{channel_id}`. Posts a structured message to the channel, persists the routing row, returns the row.
- `POST /api/v1/system-health/errors/{signature}/clear` — marks signature resolved (clears the rollup row from "current" view).
- `POST /api/v1/system-health/errors/{signature}/ignore` — adds to `IgnoredErrorSignature`.
- `DELETE /api/v1/system-health/errors/{signature}/ignore` — removes (un-ignore).

The routed message format (single source of truth) — a normal channel message with body containing: signature, count over window, first/last seen, sample formatted error, link to the trace if present, link back to the error row. No new widget, no new card type. Plain markdown.

**Delete:**
- `app/services/workspace_attention.py`
- `app/services/workspace_mission_ai.py`
- `app/services/workspace_mission_control.py`
- `app/services/workspace_missions.py` — confirm no Project Factory imports first; if anything load-bears, narrow the deletion.
- `app/routers/api_v1_workspace_attention.py`
- `app/routers/api_v1_workspace_mission_control.py`
- `app/routers/api_v1_workspace_missions.py`
- `app/tools/local/workspace_attention.py`
- `app/tools/local/workspace_missions.py`
- `app/tools/local/capture_project_intake.py` — superseded by repo-resident source artifacts (per 2026-05-03 commits).
- `app/tools/local/propose_run_packs.py` — same.
- `report_attention_triage_batch`, `report_issue`, `publish_issue_intake`, `request_agent_repair`, `preflight_agent_repair` tools.
- `attention_triage` task type.
- DB tables: `attention_items`, `attention_signals`, `operator_findings`, `operator_runs`, `issue_work_packs` (if still present), and any auxiliary triage/review tables behind these services. One migration drops them all. Single user — no data preservation needed.
- `/recent-errors/promote` endpoint and the daily-health "promote to attention" path (Attention is gone).

### UI

**Add (one new view):**
- `ui/app/(app)/admin/logs/errors.tsx` — the Errors tab. Layout:
  - Top: `SummaryPanel` (the Daily Health 24h rollup, embedded — same component already used at `/hub/daily-health`).
  - Below: deduped errors list, filterable by status (open / cleared / ignored / routed). Each row: signature snippet, count, first/last seen, source area, three buttons (Send to channel, Clear, Ignore).
  - Send-to-channel = a popover with the existing channel picker; on submit, calls the route endpoint and shows a toast with a link to the posted message.
- Add the tab to `LogsTabBar` (`ui/src/components/logs/LogsTabBar.tsx`) as the **first** tab. Make it the default landing for `/admin/logs` (current `/admin/logs` index = Agent Logs becomes the second tab).
- Optionally redirect `/hub/daily-health` → `/admin/logs/errors`. Or keep the hub page as-is (it already shows the summary; users who land there from the home dashboard still get value). My pick: keep `/hub/daily-health` as the embed surface for the home dashboard / mobile hub / spatial canvas landmark, but make `/admin/logs/errors` the canonical actionable surface. They share `SummaryPanel`.

**Delete (UI):**
- `ui/app/(app)/hub/attention.tsx`
- `ui/app/(app)/hub/command-center.tsx`
- `ui/src/components/attention/AttentionCommandDeck.tsx` and the entire `attention/` folder
- `ui/src/components/spatial-canvas/SpatialAttentionLayer.tsx`, `SpatialAttentionModel.ts`, `SpatialMissionLayer.tsx` and all attention-rim / mission-tether visual state on world tiles
- `ui/src/api/hooks/useWorkspaceAttention.ts`, `useWorkspaceAttention.test.ts`
- `ui/src/lib/actionInbox.ts`, `actionInbox.test.ts`
- `ui/src/lib/hubRoutes.ts` — delete `ATTENTION_COMMAND_DECK_HREF`, `attentionDeckHref`, `attentionHubHref`, `attentionItemHref`. Keep `DAILY_HEALTH_HREF`.
- Mission Control board / Starboard "Attention station" / Mission Control AI panel chrome inside `CommandCenter.tsx` and Starboard.
- `Send this issue to a bot` accordion in current Mission Control Review (the screenshot you posted) — replaced by Send-to-channel on the new Errors tab.

**Spatial canvas:** keep the `DailyHealthLandmark`. Delete every other attention/mission/operator overlay. Object tiles get plain state (online/offline/last-active); no red rims, no finding tethers, no operator badges, no autofix counts.

### Skills

- Delete `skills/diagnostics/health_triage.md` (it teaches bots how to use the now-deleted promotion / attention flow).
- Update `skills/diagnostics/index.md` to point at the new errors endpoints if there's a runtime use case (probably none — bots don't route errors; humans do).
- Update `docs/guides/discovery-and-enrollment.md` if it references the attention manifest fields.

### Tracks

- `docs/tracks/mission-control-vision.md` → `status: superseded`. Add a one-paragraph note pointing at this plan + the Project Factory track. Keep the file as historical record.
- `docs/tracks/orchestrator-dissolution.md` — no change here, this track is parallel.
- `docs/tracks/projects.md` — note the Project Factory absorbed Issue Intake; remove any cross-references to Mission Control Review as a triage surface.

## Phases

### Phase 1 — Build the Errors tab (additive, no deletes)

1. Add the two endpoints (`/route`, `/clear`, `/ignore`) and the storage rows.
2. Add `/admin/logs/errors` page with `SummaryPanel` + the actionable deduped list.
3. Add the tab to `LogsTabBar` and make it the default for `/admin/logs`.
4. Verify: post a fake error, see it appear, route it to a channel, confirm the channel message arrived, clear it, ignore the signature, see future occurrences stay quiet.

You can use the new page immediately. Nothing has been deleted.

### Phase 2 — Delete dead UI

After phase 1 is in your hands and working.

- Delete `/hub/attention`, `/hub/command-center`, `/hub/mission-control` routes and components.
- Delete `AttentionCommandDeck`, attention/mission/operator spatial overlays, `useWorkspaceAttention`, `actionInbox`.
- Strip Mission Control AI / Starboard Attention station chrome from `CommandCenter.tsx` and Starboard.
- Update `hubRoutes.ts`, `HomeDashboard.tsx`, `HubSections.tsx`, `MobileHub.tsx`, `SpatialCanvas.tsx` to drop attention navigation.
- UI typecheck pass. Manual sweep — boot, click everywhere, find dead links.

### Phase 3 — Delete dead backend

After phase 2.

- Delete the workspace_mission_*, workspace_attention services + routers.
- Delete the tools: `report_attention_triage_batch`, `report_issue`, `publish_issue_intake`, `capture_project_intake`, `propose_run_packs`, `request_agent_repair`, `preflight_agent_repair`, `workspace_missions`, `workspace_attention`.
- Delete the `attention_triage` task type and any sweep launcher.
- One migration drops the dead tables.
- Strip `agent_capabilities.py` of mission/attention/autofix manifest fields.
- Run the full pytest suite. Find references this plan missed; either delete or migrate.

### Phase 4 — Cleanup

- Mark `mission-control-vision.md` superseded; one-paragraph supersession note.
- Update `docs/roadmap.md` rows: drop Mission Control Vision row from Active, drop the Issue Work Pack mentions in the Projects row.
- Delete `skills/diagnostics/health_triage.md`.
- Grep `rg -i 'mission control|operator finding|attention item|autofix' app/ ui/ skills/ docs/` — should be empty (or only historical migration filenames + this plan).

## Risks

- **`workspace_attention` is huge (2170 LOC) — something might load-bear.** Before phase 3, grep for imports across `app/`, `tests/`, `integrations/`, `app/agent/`. If the Project Factory or any active integration depends on it, narrow the deletion. My read of recent commits says no — Project Factory moved to repo-resident artifacts and explicitly stopped using the IssueWorkPack DB state. Verify before deleting.
- **Spatial canvas red alerts come from `SpatialAttentionLayer`.** Confirm no other surface still expects the layer's data after deletion. Replace with a single `DailyHealthLandmark` badge sourcing from `system-health/recent-errors`.
- **`agent_capabilities` manifest exposes `attention`, `autofix_queue`, `pending_repair_requests`, `work_state.assigned_attention`, etc.** Phase 3 strips these. Any runtime skill that recommended consuming them gets deleted (`agent_readiness/operator`, `health_triage`).
- **Channel message format for routed errors.** Keep it plain markdown. Don't ship a new "error widget" — that's the same trap as `OPERATOR FINDING / NEEDS REVIEW / CODE FIX` chrome. The receiving bot reads markdown, the human sees markdown.

## Out of scope

- Anonymous-bot / model-only channels — parking-lot.
- Auto-routing rules per source — stays manual per error. Don't pre-build "send all `jellyfin` errors to channel X" automation; if you find yourself wanting it after living with manual routing, add it then.
- Spatial canvas redesign beyond pruning attention overlays — that's a separate question (the canvas without operator overlays may or may not be earning its keep, but that's its own track).

## References

- 24h rollup source: `app/services/system_health_summary.py`, `app/routers/api_v1_system_health.py`.
- Existing summary UI: `ui/app/(app)/hub/daily-health.tsx`, `ui/src/components/system-health/SummaryPanel.tsx`.
- Logs tab anchor: `ui/src/components/logs/LogsTabBar.tsx`.
- Project Factory consolidation context: 2026-05-01 session log; `docs/tracks/projects.md` "Project Factory Vision" + invariants.
- Track to mark superseded: `docs/tracks/mission-control-vision.md`.
- Sibling plan: [`docs/plans/orchestrator-dissolution.md`](orchestrator-dissolution.md).
