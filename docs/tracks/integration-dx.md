---
title: Integration DX Review
summary: Completed integration cleanup pass that removed dispatcher-era docs/code, migrated integrations to YAML, expanded SDK imports, and standardized config patterns.
status: complete
tags: [spindrel, track, integrations, dx]
created: 2026-04-15
updated: 2026-04-15
---

# Integration DX Review

Plan: `~/.claude/plans/jiggly-shimmying-cupcake.md`

## Problem

Integration system evolved through 4 phases, each leaving the previous partially in place. Docs direct authors to deleted dispatcher module, 11/16 integrations on legacy setup.py, three config mechanisms coexist, SDK covers half the imports integrations actually need.

## Phases

### Phase 1: Documentation Emergency + Dead Code -- DONE (2026-04-15)
- [x] Rewrite docs/integrations/index.md — removed dispatchers, added YAML reference, renderer/target quickstart, polling patterns
- [x] Update docs/integrations/design.md — marked dispatcher as historical, added renderer/target/outbox docs
- [x] Update docs/integrations/example.md — removed dispatcher references
- [x] Remove dispatcher.py discovery from integrations/__init__.py
- [x] Clean up UI: remove `has_dispatcher` badge, replace with `has_renderer`

### Phase 2: YAML Migration — Trivial -- DONE (2026-04-15)
- [x] vscode, claude_code, web_search

### Phase 3: YAML Migration — Moderate -- DONE (2026-04-15)
- [x] arr, google_workspace, ingestion, mission_control

### Phase 4: YAML Migration — Complex -- DONE (2026-04-15)
- [x] discord, bluebubbles, frigate, gmail
- Note: bluebubbles/process.py kept — CMD=None with explanation of why Socket.IO is disabled
- Deleted redundant process.py from discord, frigate, mission_control, gmail (declared in YAML)
- 16/16 integrations now on integration.yaml, 0 setup.py remaining

### Phase 5: SDK Surface Expansion -- DONE (2026-04-15)
- [x] Added to sdk.py: async_session, get_db, verify_auth/verify_admin_auth/verify_auth_or_user, resolve_all_channels_by_client_id, ensure_active_session, sanitize_unicode, safe_create_task, get_bot, current_bot_id, current_channel_id
- [x] Migrated top-level imports in all target.py, renderer.py, hooks.py, router.py files
- [x] ~43 direct `from app.` imports eliminated; remaining are lazy/deferred or domain-specific

### Phase 6: Config Pattern Standardization -- DONE (2026-04-15)
- [x] make_settings() factory in sdk.py — generates DB-backed settings class from key/default dict
- [x] Migrated all 9 config.py files: github, arr, frigate, gmail, bluebubbles, claude_code, web_search, google_workspace, mission_control
- [x] Typed properties use subclassing pattern (e.g. `class _Settings(make_settings(...)): ...`)
- Note: wyoming/config.py uses module-level constants from manifests — different pattern, left as-is
- Note: No Pydantic BaseSettings remain in any integration config

### Phase 7: Polish — subsumed (2026-04-17)
- Shared webhook validation utility — covered by the rate-limited HTTP helper pattern in `integrations/slack/web_api.py` (each integration owns a small `web_api.py`-style file now).
- Integration testing harness — covered by the "write a renderer unit test asserting each declared capability has a rendered case" recipe in [[integration-depth-playbook]].
- Google Workspace events — separate track ([[google-workspace]]), not DX scope.
