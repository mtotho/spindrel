# Spindrel — Agent Instructions

Canonical entry point for any agent (Codex, Claude Code, etc.) working in this repo. **`CLAUDE.md` is a symlink to this file** — both agents read the same rules.

This file is the index, the rule book, and the retrieval contract. Drill into `docs/` for project state and canonical guides. Personal session notes and cross-project context live in the user's vault (`~/personal/vault/Sessions/spindrel/`, etc.) — referenced from here, not duplicated.

## Reading order at session start

**Tier 0 — always read:**
1. This file (`AGENTS.md`).
2. `docs/roadmap.md` — what's actively in flight.
3. The most recent file in `~/personal/vault/Sessions/spindrel/` — last session's notes (vault-private; skip if vault is unavailable).

**Tier 1 — read when relevant to the current task:**
- `docs/inbox.md` — open bugs / ideas / tech debt / questions. Light schema (`## <date> <time> <slug>` + `**kind:** · **area:** · **status:**` tag line). Replaces the prior `loose-ends.md`.
- `docs/guides/index.md` — canonical guides; open the matching guide for the area you're touching.
- The relevant `docs/tracks/<slug>.md` for multi-phase work.

**Tier 2 — drill in via this file's "Where to look" table on demand:**
- `docs/architecture-decisions.md`, `docs/architecture.md`, `docs/fix-log.md`, `docs/how-discovery-works.md`, `docs/integration-depth-playbook.md`, `docs/audits/`, etc.

## Right now

- **Phase:** Active Product Buildout. Feature work, structural cleanup, bug fixing all in scope.
- **Where work is happening:** see `docs/roadmap.md` for the active list with 1-line summaries; open the named track for detail.
- **Server:** test server is at `10.10.30.208` (SSH alias `spindrel-bot`). Tests, cron, scripts run *on the server* in `/opt/thoth-server/`. Ephemeral instance for personal work is `~/spindrel-e2e/`. See vault `Test Server Operations.md` for credentials and details.

## Where to look for what

| Need | File |
|---|---|
| Current active work, status of named tracks | `docs/roadmap.md` |
| Open bugs, tech debt, things to verify | `docs/inbox.md` |
| Why does it work this way? | `docs/architecture-decisions.md` |
| Subsystem map, request flow | `docs/architecture.md` |
| Resolved bug history (one-liners) | `docs/fix-log.md` |
| Multi-session work efforts | `docs/tracks/*.md` |
| Test coverage gaps and audits | `docs/audits/*.md` |
| Track contract — when to create, format, lifecycle | `docs/guides/tracks.md` |
| Public-facing docs / mkdocs landing | `docs/index.md` (don't confuse with this file) |
| Canonical contributor guides | `docs/guides/index.md` |
| Future ideas, parking lot (private) | `~/personal/vault/Projects/spindrel/Ideas & Investigations.md` |
| Test server credentials, SSH (private) | `~/personal/vault/Projects/spindrel/Test Server Operations.md` |
| Recent session context (private) | `~/personal/vault/Sessions/spindrel/` |
| Hot-path memory rules (Claude Code only) | `~/.claude/projects/.../memory/MEMORY.md` |

## Canonical guides — `docs/guides/`

Read the matching guide before touching these areas. **Guides win against every other doc when they disagree.** Update the matching guide in the same pass as any architectural change.

- [`docs/guides/development-process.md`](docs/guides/development-process.md) — review triage, Agent Briefs, contract/red-line review, out-of-scope decisions
- [`docs/guides/context-management.md`](docs/guides/context-management.md) — context admission + history profiles
- [`docs/guides/discovery-and-enrollment.md`](docs/guides/discovery-and-enrollment.md) — tool / skill / MCP residency + enrollment
- [`docs/guides/widget-system.md`](docs/guides/widget-system.md) — widget contracts, origins, presentation, host policy
- [`docs/guides/ui-design.md`](docs/guides/ui-design.md) — UI archetypes, design tokens, anti-patterns
- [`docs/guides/ui-components.md`](docs/guides/ui-components.md) — shared dropdowns, prompt editors, settings rows, component usage catalog
- [`docs/guides/integrations.md`](docs/guides/integrations.md) — integration contract + responsibility boundary
- [`docs/guides/ubiquitous-language.md`](docs/guides/ubiquitous-language.md) — canonical glossary; open when naming a new concept, reviewing UI copy, or resolving a terminology disagreement
- [`docs/guides/tracks.md`](docs/guides/tracks.md) — Track contract: when to create, format, lifecycle, pruning

## Commands

```bash
# Tests (agent default: native venv, SQLite in-memory, no postgres needed)
. .venv/bin/activate
PYTHONPATH=. pytest tests/unit/test_foo.py -q
PYTHONPATH=. pytest tests/ integrations/ -v
# Do NOT wrap unit tests in Docker, Dockerfile.test, or docker compose.
# If DB-backed tests need Python 3.12 and the venv is not Python 3.12,
# report the environment blocker instead of switching to Docker.

# UI typecheck (REQUIRED after UI changes — also enforced by hook)
cd ui && npx tsc --noEmit

# Regenerate UI API types after changing any FastAPI response model
# (CI's api-type-drift job fails if ui/openapi.json or
# ui/src/types/api.generated.ts is out of date)
bash scripts/generate-api-types.sh

# Dev
docker compose up                       # all services
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
alembic upgrade head                    # migrations (auto on startup)
```

Use port 5173 if a UI dev server is already running locally rather than starting another.

## Retrieval discipline

Reading the project docs is the dominant cost of every session. **Use the cheapest primitive that answers the question; escalate only when needed.**

| Need | Primitive | Cost |
|---|---|---|
| Does file exist? Title / tags / status? | `ls`; `grep '^summary:\|^status:\|^tags:' <file>` | Cheapest |
| 1–2 sentence preview | Read the `summary:` frontmatter field only | Cheap |
| A specific claim or section | `grep -A 10 -B 2 "<term>" <file>` | Medium |
| Whole-file content | `Read <file>` | Expensive — last resort |
| Cross-doc relationships | `grep "\[\[.*?\]\]"` then walk wikilinks | Case-by-case |

A 500-line file opened to read 15 lines is 485 lines of wasted context. If `summary:` answers the question, don't read the body. If a grepped section answers, don't read the file.

## Frontmatter contract

Every file under `docs/` (Tracks, Architecture Decisions, Roadmap, Loose Ends, Audits, etc.) carries this frontmatter:

```yaml
---
title: Human-readable title
summary: One or two sentences, ≤200 chars, what this file is about. Drives cheap retrieval.
status: active | complete | superseded | reference | permanent
tags: [spindrel, <area>, ...]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

`summary:` is required on Tracks, Architecture Decisions, Roadmap, Loose Ends, Fix Log, Audits, INDEX-style files. Soft-required elsewhere.

## Rules

- **Test-first bug fixing.** Write the failing test, verify it fails, fix the code, verify it passes. **Never leave tests failing.**
- **Untested code changes are suspect.** If you modify logic and no existing tests break, that's not a green light — it means the path has no coverage. Either fix existing tests to match new behavior, or write new tests as part of the change.
- **God functions are the #1 bug source.** `context_assembly`, `loop`, `tasks`, etc. — when working in those files, look for sub-functions to extract; treat decomposition as part of the task, not a separate cleanup.
- **Understand the system before writing tests.** Read the code first; reason about actual behavior. Don't write tests from assumptions.
- **Use hooks for enforcement, not memory rewrites.** When the same mistake happens twice, add a deterministic hook in `~/personal/dotfiles/claude/hooks/`. Memory-based rules get skipped during "task completion" mode; hooks don't.
- **Split UI files at 1000 lines** — extract into sibling files.
- **No integration-specific code in `app/`** — must live in `integrations/{name}/`.
- **Cross-integration helpers live in `integrations/sdk.py`** — before adding a private helper to any `integrations/<id>/`, grep `integrations/sdk.py` for an existing one. Same helper appearing in 2+ integrations is a smell, gated by `tests/unit/test_integration_no_duplicate_helpers.py`.
- **Production runs in Docker** — debug by reading code, not querying DB.
- **Don't band-aid — keep the broader vision.** If the user reports one symptom, don't fix it by ripping out a canonical / standard pattern and replacing it with an imperative workaround. Diagnose the root cause and match the fix to best practice. A bug in `flex: column-reverse` chat scroll should not become "scroll with JS"; a bug in React Query caching should not become "bypass the cache"; a bug in CSS grid should not become "use absolute positioning". User frustration means the band-aid isn't holding — it does NOT mean apply another band-aid faster. Assume senior-engineer scrutiny on every line.
- **Chat scroll: use `flex-direction: column-reverse` on the OUTER container with messages in a normal-flow inner div.** The browser natively pins the visual bottom — no `scrollTop = scrollHeight` effects, no `ResizeObserver` pin logic, no image-load races. Selection works because the inner wrapper's DOM order matches its visual order. Do NOT reintroduce imperative scroll anchoring. See `ui/app/(app)/channels/[channelId]/ChatMessageArea.tsx`.

## Same-edit doc updates

- Fixing a bug from `docs/inbox.md`: remove it there and add a one-line entry to `docs/fix-log.md` in the **same edit**.
- Completing a track phase: update the track's `## Status` table immediately. Compress phase prose in place when work ships. See `docs/guides/tracks.md` for the full lifecycle (when to flip `status: complete`, when to supersede, when to split).
- Making a load-bearing decision: add to `docs/architecture-decisions.md`.
- Discovering a bug or gotcha: add to `docs/inbox.md`. Ideas / speculation go to vault `Ideas & Investigations.md` instead.
- Architectural change: update the matching `docs/guides/<area>.md` in the same pass.

## Worktree safety

- Do not run `git stash`, `git reset`, `git checkout`, `git switch`, `git clean`, or any equivalent worktree-rewriting command to make room for your own task unless the user explicitly asks for that operation in the current turn. If the current checkout is too dirty or conflicting, **stop and ask**, or create/use a separate worktree after explicit approval.
- Before any commit, stash, reset, branch switch, pull/rebase, or worktree-level cleanup, inspect `git status --short` and protect unrelated user/agent edits. Never hide or move another session's uncommitted changes as a convenience step.

## Conventions

- Bot YAML seeds DB, then UI edits — YAML is not user-facing config.
- `memory_scheme: "workspace-files"` and `history_mode: "file"` are the only active options.

## Principles

- **If the user has to choose, we failed.** Explain by showing, not by labeling.
- **Composition over configuration.**
- **Trust the pipeline — fix mechanisms, don't add config knobs.**
