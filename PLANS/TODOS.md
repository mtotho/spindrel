# TODOs
_Active work items. Updated manually or by heartbeat._
_Last updated: 2026-03-22_

## Active

1. **Thoth CLI Phase 3** — Rewrite shell dispatcher as Python Click app with `thoth install` wizard. (PLANS/THOTH_CLI.md)
2. **Media server integrations** — Sonarr, Radarr, Jellyfin, Jellyseerr. Plan each as a self-contained integration under `integrations/`.
3. **GitHub webhook integration** — Resume `integrations/github/` when server has a public URL. (PLANS/GITHUB_INTEGRATION.md)
4. **Review direct DB access in agent tools** — Decide if a service layer is warranted for todos.py, search_history.py, plans.py vs current `async_session()` usage.
5. **Home Assistant + Frigate integrations** — HAOS MCP tools exist; Frigate sends events via MQTT. Brainstorm useful agent integrations.
6. **Slack thread visibility** — Bot currently can't see GitHub Slack app thread replies.
7. **Integration layer debt paydown** — Consolidate Slack API calls, separate orchestration from delivery, dispatcher registry. (docs/integrations/DEBT.md)
8. **Ingestion pipeline** — 4-layer security pipeline for external content. (PLANS/INGESTION_PIPELINE.md)

## Recently Completed

- **Loop refactor** — All 4 phases landed (tracing, llm, tool_dispatch, context_assembly). (PLANS/LOOP_REFACTOR.md)
- **Backup system** — scripts/backup.sh + restore.sh with S3 via rclone. (PLANS/BACKUP_SYSTEM.md)
- **delegate_to_exec** — Generic async exec primitive in app/tools/local/exec_tool.py. (PLANS/DELEGATE_EXEC.md)
- **Thoth CLI Phase 1** — Shell dispatcher + systemd unit + install script.
- **Heartbeat quiet hours** — Configurable quiet window with interval override.
- **LLM resilience** — Retry logic for transient errors + model fallback.
- **Compaction tests** — 71 new tests, 94% coverage.
