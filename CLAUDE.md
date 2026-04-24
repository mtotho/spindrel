# CLAUDE.md

## Project Knowledge

Detailed project knowledge lives in an Obsidian vault at `../vault/Projects/agent-server/`. On session start, read **Tier 1 files**: `Roadmap.md` (current state) and `Loose Ends.md` (open bugs). Read Track files only when touching that area.

**Cleanup is same-edit, not later.** When you fix a bug from Loose Ends → move it to Fix Log in the same edit. When all track phases ship → close the track immediately. See `dotfiles/claude/rules/vault-updates.md` for the full vault organization system (document taxonomy, track lifecycle, cleanup discipline).

## Canonical Guides

Index: [`docs/guides/index.md`](docs/guides/index.md). Read the matching guide before touching these areas — they win against every other doc when they disagree.

- [`docs/guides/context-management.md`](docs/guides/context-management.md) — context admission + history profiles
- [`docs/guides/discovery-and-enrollment.md`](docs/guides/discovery-and-enrollment.md) — tool / skill / MCP residency + enrollment
- [`docs/guides/widget-system.md`](docs/guides/widget-system.md) — widget contracts, origins, presentation, host policy
- [`docs/guides/ui-design.md`](docs/guides/ui-design.md) — UI archetypes, design tokens, anti-patterns
- [`docs/guides/integrations.md`](docs/guides/integrations.md) — integration contract + responsibility boundary
- [`docs/guides/ubiquitous-language.md`](docs/guides/ubiquitous-language.md) — canonical glossary; open when naming a new concept, reviewing UI copy, or resolving a terminology disagreement

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
- **Don't band-aid — keep the broader vision.** If the user reports one symptom, don't fix it by ripping out a canonical / standard pattern and replacing it with an imperative workaround. Diagnose the root cause and match the fix to best practice. A bug in `flex: column-reverse` chat scroll should not become "scroll with JS"; a bug in React Query caching should not become "bypass the cache"; a bug in CSS grid should not become "use absolute positioning". User frustration means the band-aid isn't holding — it does NOT mean apply another band-aid faster. Assume senior-engineer scrutiny on every line.
- **Chat scroll: use `flex-direction: column-reverse` on the OUTER container with messages in a normal-flow inner div.** The browser natively pins the visual bottom — no `scrollTop = scrollHeight` effects, no `ResizeObserver` pin logic, no image-load races. Selection works because the inner wrapper's DOM order matches its visual order. Do NOT reintroduce imperative scroll anchoring. See `ui/app/(app)/channels/[channelId]/ChatMessageArea.tsx`.

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
