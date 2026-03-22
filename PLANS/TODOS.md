# TODOs
_Simple running list of active work items. Updated every heartbeat._
_Last updated: 2026-03-22_

1. Refactor/declutter `app/agent/loop.py` — ~1000 lines, needs cleanup and better separation of concerns.
2. Build `search_history` tool + API — search/list historical messages in a channel by date range or keyword, backed by the DB. Useful for agent self-directed compaction.
3. Build backup system — Phase 1: Postgres dump on a schedule, offload to third-party (Google Drive, S3, etc). Phase 2: filesystem/integration state backup (indexed files, vector store, etc).
4. Test Claude Code async/streaming pattern — launch via raw PID + .jsonl so we can tail live output mid-run. Try on next long Claude Code task.
5. Wire all tests (unit + integration + ingestion) into Dockerfile.test so CI runs the full 301.
6. Build media server integrations — Sonarr, Jellyseerr, Radarr, Jellyfin. Plan each as a self-contained integration under integrations/.
7. Revisit GitHub Slack app thread replies — bot currently can't see them.
8. Resume GitHub webhook integration (`integrations/github/`) when server has a public URL.
