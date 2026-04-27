# CLAUDE.md

## Entry Point

For repo-wide work: start with this file, then open [`docs/guides/index.md`](docs/guides/index.md) and the matching canonical guide for the area you're touching. For project state (active tracks, bugs, decisions), see the project's `INDEX.md` and `AGENTS.md` in the workspace's vault.

Keep public, reusable process in `docs/guides/`. Local workspace state and private session workflow belong in workspace-level agent instructions, not in this public repo file.

## Canonical Guides

Index: [`docs/guides/index.md`](docs/guides/index.md). Read the matching guide before touching these areas — they win against every other doc when they disagree.

- [`docs/guides/development-process.md`](docs/guides/development-process.md) — review triage, Agent Briefs, contract/red-line review, out-of-scope decisions
- [`docs/guides/context-management.md`](docs/guides/context-management.md) — context admission + history profiles
- [`docs/guides/discovery-and-enrollment.md`](docs/guides/discovery-and-enrollment.md) — tool / skill / MCP residency + enrollment
- [`docs/guides/widget-system.md`](docs/guides/widget-system.md) — widget contracts, origins, presentation, host policy
- [`docs/guides/ui-design.md`](docs/guides/ui-design.md) — UI archetypes, design tokens, anti-patterns
- [`docs/guides/ui-components.md`](docs/guides/ui-components.md) — shared dropdowns, prompt editors, settings rows, component usage catalog
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
- **Cross-integration helpers live in `integrations/sdk.py`** — before adding a private helper to any `integrations/<id>/`, grep `integrations/sdk.py` for an existing one. Same helper appearing in 2+ integrations is a smell, gated by `tests/unit/test_integration_no_duplicate_helpers.py`.
- **Production runs in Docker** — debug by reading code, not querying DB
- **Don't band-aid — keep the broader vision.** If the user reports one symptom, don't fix it by ripping out a canonical / standard pattern and replacing it with an imperative workaround. Diagnose the root cause and match the fix to best practice. A bug in `flex: column-reverse` chat scroll should not become "scroll with JS"; a bug in React Query caching should not become "bypass the cache"; a bug in CSS grid should not become "use absolute positioning". User frustration means the band-aid isn't holding — it does NOT mean apply another band-aid faster. Assume senior-engineer scrutiny on every line.
- **Chat scroll: use `flex-direction: column-reverse` on the OUTER container with messages in a normal-flow inner div.** The browser natively pins the visual bottom — no `scrollTop = scrollHeight` effects, no `ResizeObserver` pin logic, no image-load races. Selection works because the inner wrapper's DOM order matches its visual order. Do NOT reintroduce imperative scroll anchoring. See `ui/app/(app)/channels/[channelId]/ChatMessageArea.tsx`.


## Conventions

- Bot YAML seeds DB, then UI edits — YAML is not user-facing config
- `memory_scheme: "workspace-files"` and `history_mode: "file"` are the only active options

