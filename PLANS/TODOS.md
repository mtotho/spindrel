# TODOs
_Simple running list of active work items. Updated every heartbeat._
_Last updated: 2026-03-22_

1. Build `search_history` tool + API — search/list historical messages in a channel by date range or keyword, backed by the DB. Useful for agent self-directed compaction.
2. Build a proper `todo` tool (DB-backed) — create/list/complete/delete todos per bot or channel. Replaces this markdown file. Any bot can use it regardless of filesystem access.
3. Build backup system — Phase 1: Postgres dump on a schedule, offload to third-party (Google Drive, S3, etc). Phase 2: filesystem/integration state backup (indexed files, vector store, etc).
4. Merge PR #16 (Priority 2 API tests) then implement Priority 3 — agent loop + services tests
5. Wire all tests (unit + integration + ingestion) into Dockerfile.test so CI covers everything
6. Revisit GitHub Slack app thread replies — bot currently can't see them
7. Resume GitHub webhook integration (`integrations/github/`) when server has a public URL
