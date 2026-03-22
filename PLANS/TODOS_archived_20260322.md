# TODOs
_Simple running list of active work items. Updated every heartbeat._
_Last updated: 2026-03-22_
_Source of truth: DB-backed todo tool. This file is a heartbeat snapshot._

1. Refactor/declutter `app/agent/loop.py` — ~1000 lines, needs cleanup and better separation of concerns.
2. Build backup system — Phase 1: Postgres dump on a schedule, offload to third-party (Google Drive, S3, etc). Phase 2: filesystem/integration state backup (indexed files, vector store, etc).
3. Test Claude Code async/streaming pattern — launch via raw PID + .jsonl so we can tail live output mid-run. Try on next long Claude Code task.
4. Build media server integrations — Sonarr, Radarr, Jellyfin, Jellyseerr. Plan each as a self-contained integration under integrations/.
5. Heartbeat schedule control — ability to slow down or disable heartbeat during a time window (e.g. overnight). Configurable per bot or globally.
6. Review direct DB access pattern in agent tools (todos.py, search_history.py, plans.py) — decide if a service layer is warranted vs current async_session() direct usage.
7. Sketch out Home Assistant + Frigate integrations — HAOS MCP tools already exist, Frigate sends events via MQTT. Brainstorm what useful agent integrations could look like.
8. Revisit GitHub Slack app thread replies — bot currently can't see them.
9. Resume GitHub webhook integration (`integrations/github/`) when server has a public URL.
