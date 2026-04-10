# CLAUDE.md

## Project Knowledge

Detailed project knowledge lives in an Obsidian vault at `../vault/Projects/agent-server/`. Start with `Roadmap.md` for current state and priorities.

**Keep the vault updated as you work** — mark items done, add loose ends, record decisions, note anything a future session would benefit from knowing. Don't wait until session end. See global CLAUDE.md for full vault update guidelines.

## Commands

```bash
# Tests (SQLite in-memory, no postgres needed)
docker build -f Dockerfile.test -t agent-server-test . && docker run --rm agent-server-test
pytest tests/ integrations/ -v          # full suite
pytest tests/unit/test_foo.py -v -s     # single file
# Do NOT use `docker compose run` for tests

# UI typecheck (REQUIRED after UI changes — also enforced by hook)
cd ui && npx tsc --noEmit

# Dev
docker compose up                       # all services
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
alembic upgrade head                    # migrations (auto on startup)
```

## Rules

- **Test-first bug fixing**: write failing test, verify it fails, fix code, verify it passes
- **Never leave tests failing**
- **Split UI files at 1000 lines** — extract into sibling files
- **No integration-specific code in `app/`** — must live in `integrations/{name}/`
- **Production runs in Docker** — debug by reading code, not querying DB

## DB Gotchas

- `schema_` is the ORM attribute for the `schema` column in `tool_embeddings` (PostgreSQL reserved word)
- Core-level `sqlalchemy.dialects.postgresql.insert`: use `**{"schema": value}` — Core doesn't translate ORM attribute names
- JSONB `server_default`: use `sa.text("'{}'::jsonb")` not bare string
- JSONB mutation tracking: use `copy.deepcopy()` + `flag_modified()` (see `_set_step_states()` pattern)

## Conventions

- UI says "Capabilities", code says "carapace" — accepted debt
- Bot YAML seeds DB, then UI edits — YAML is not user-facing config
- `memory_scheme: "workspace-files"` and `history_mode: "file"` are the only active options
- DB `memories` and `bot_knowledge` tables are DEPRECATED — do not use
- **Single-workspace mode**: every bot is a permanent member of the default workspace via `ensure_all_bots_enrolled` (`app/services/workspace_bootstrap.py`). There is no "non-workspace bot" — the workspace is the container environment, not a property of the bot. The `POST`/`DELETE` workspace-bot endpoints are 410'd; membership is owned by the bootstrap loop.
