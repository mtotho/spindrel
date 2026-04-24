---
tags: [testing, audit, refactor]
status: reference
updated: 2026-04-23
---

# Test Audit — Mock Session Refactor

Merged successor to the old `Test Audit - Inventory` (mechanical E.13 snapshot) and `Test Audit - Deep Review` (top-5 offender playbook). Both retired 2026-04-23 — the 2026-04-17 inventory numbers were stale after Phases 1a–1e rewrote the five headline offenders, and the Deep Review's per-file before/after sections described code that has already shipped. This file keeps the refactor **playbook** (still useful) and refreshes the **top-20** against today's suite.

For completed rewrites, see [[Track - Test Quality]] "Shipped phases" table.

## Smell codes

Match `~/personal/dotfiles/claude/skills/testing-python/SKILL.md`:

- **E.13** — mocked `AsyncSession`/`Session` instead of real in-memory SQLite. Headline issue.
- **E.9 / H.1** — `patch("httpx…")`, `patch("datetime…")`, `patch("time.…")`, `patch("asyncio.sleep")` instead of `respx` / `freezegun`.
- **A.13** — flat-structure violations inside `test_` bodies (`try / except / print / for / while` at statement scope).

Weighting for ranking: E.13 = 5, E.9/H.1 = 3, A.13 = 3.

## Summary totals (regenerated 2026-04-23)

| Metric | 2026-04-17 baseline | 2026-04-23 | Δ |
|---|---:|---:|---|
| Files scanned | 320 | 401 | +81 |
| Tests found (by `def test_` scan) | 5681 | 4060 | — (different heuristic; not directly comparable) |
| E.13 — mocked-session hits | 1643 | 2159 | +516 |
| E.9 / H.1 — stdlib patch hits | 37 | 58 | +21 |
| A.13 — flat-structure violations | 194 | 671 | +477 |
| Files that import Mock and never touch `db_session`/`AsyncSession` | 151 | 173 | +22 |

**Reading**: absolute E.13 went UP despite five headline offenders being rewritten. New test files (Phases 2, 3, 4, and drift-seam sweeps) landed with legitimate external-client mocks and some mocked-session patterns in mid-tier modules. Top-20 has rotated completely — only one file (`test_tasks.py`) survives from the old top-20.

## Top 20 offenders (weighted, 2026-04-23)

| # | File | Score | E.13 | E.9/H.1 | A.13 | Tests |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `tests/unit/test_workflow_recovery.py` | 616 | 122 | 0 | 2 | 12 |
| 2 | `tests/unit/test_workflow_improvements.py` | 445 | 89 | 0 | 0 | 3 |
| 3 | `tests/unit/test_tasks.py` | 395 | 79 | 0 | 0 | — |
| 4 | `tests/unit/test_sandbox.py` | 380 | 76 | 0 | 0 | 6 |
| 5 | `tests/unit/test_bluebubbles_wake_word.py` | 340 | 68 | 0 | 0 | 32 |
| 6 | `tests/unit/test_tool_schema_backfill_tier1.py` | 310 | 62 | 0 | 0 | — |
| 7 | `tests/unit/test_backfill_sections.py` | 304 | 59 | 0 | 3 | 4 |
| 8 | `tests/unit/test_mcp_servers.py` | 284 | 55 | 3 | 0 | 4 |
| 9 | `tests/unit/test_workflow_tool.py` | 275 | 55 | 0 | 0 | — |
| 10 | `tests/unit/test_attachment_service.py` | 273 | 54 | 1 | 0 | 7 |
| 11 | `tests/unit/test_workflows.py` | 255 | 51 | 0 | 0 | 41 |
| 12 | `tests/unit/test_history_tool_search.py` | 250 | 50 | 0 | 0 | 8 |
| 13 | `tests/unit/test_heartbeat_workflow.py` | 245 | 49 | 0 | 0 | — |
| 14 | `tests/unit/test_docker_stacks.py` | 239 | 46 | 0 | 3 | 39 |
| 15 | `tests/unit/test_section_retention.py` | 226 | 44 | 0 | 2 | 4 |
| 16 | `tests/unit/test_get_skill.py` | 223 | 41 | 0 | 6 | 2 |
| 17 | `tests/unit/test_tool_discovery.py` | 215 | 34 | 0 | 15 | 16 |
| 18 | `tests/unit/test_step_executor.py` | 206 | 40 | 0 | 2 | 88 |
| 19 | `tests/unit/test_task_title.py` | 200 | 40 | 0 | 0 | 5 |
| 20 | `tests/unit/test_read_conversation_history.py` | 190 | 38 | 0 | 0 | 3 |

**The former top-5 (multi_bot_channels, manage_bot_skill, task_tools, workflow_advancement, memory_hygiene) all dropped out of the top-20** — Phases 1a–1e did their job. `test_tasks.py` at #3 is the only survivor.

### False-positive warnings

- **`test_bluebubbles_wake_word.py`** (#5, 68 E.13) — mocks the BlueBubbles API client, not `AsyncSession`. Largely legitimate external-client isolation. Triage before rewriting.
- **`test_mcp_servers.py`** (#8) — mocks MCP transport; same caveat.
- **`test_attachment_service.py`** (#10) — partially rewritten in Phase 2; residual hits are in classes that stub Slack/file-store clients.
- **`test_docker_stacks.py`** (#14) — mocks `asyncio.create_subprocess_exec`; legitimate external.

True rewrite candidates (mocked `AsyncSession` as primary pattern): `test_workflow_recovery.py`, `test_workflow_improvements.py`, `test_tasks.py`, `test_sandbox.py`, `test_tool_schema_backfill_tier1.py`, `test_backfill_sections.py`, `test_workflow_tool.py`, `test_workflows.py`, `test_history_tool_search.py`, `test_heartbeat_workflow.py`, `test_section_retention.py`, `test_get_skill.py`, `test_step_executor.py`.

## Refactor playbook (distilled from the old Deep Review)

These patterns recur across every rewrite candidate. Each is a candidate for shared infra ahead of per-file cleanup, but most of the shared infra now exists (Phase 0) — the work is mostly file-by-file application.

### 1. Existing shared infra (do not reinvent)

- **`tests/factories/`** — `build_bot`, `build_channel`, `build_channel_bot_member`, `build_skill`, `build_bot_skill`, `build_task`, `build_prompt_template`, `build_workflow`, `build_workflow_run`, `build_bot_hook`, `build_integration_manifest`, `build_usage_limit`, `build_secret_value`, `build_docker_stack`, `build_provider_config`, `build_webhook_endpoint`, `build_mcp_server`, `build_attachment`. Re-exported from `tests/factories/__init__.py`.
- **`db_session`** — canonical real-DB fixture in `tests/integration/conftest.py` (re-exported by `tests/unit/conftest.py`).
- **`patched_async_sessions`** — patches every known module-level `async_session` alias (`_MODULE_LEVEL_ALIASES` in `tests/unit/conftest.py`). Append when a new test fails with "no such table" despite the engine being seeded.
- **`agent_context`** — snapshots/restores the eight agent ContextVars (`current_bot_id`, `current_session_id`, `current_channel_id`, `current_client_id`, `current_dispatch_type`, `current_dispatch_config`, `current_correlation_id`, `current_turn_responded_bots`).
- **`bot_registry`** — snapshots/restores `app.agent.bots._registry`; `.register(bot_id, **overrides)` seeds a minimal `BotConfig`.

### 2. Patterns to rip out when you see them

| Smell | Replace with |
|---|---|
| `AsyncMock()` session with `scalars.return_value.all.return_value = [...]` | Real `db_session` + factory rows |
| `db.execute = AsyncMock(side_effect=[result_a, result_b])` (call-order coupling) | Real queries — refactors don't break behavior |
| `db.add.assert_called_once(); task = db.add.call_args[0][0]` (reaching into pre-flush ORM state) | `select()` after commit; assert on persisted row |
| `patch("app.module.settings") as mock_settings; mock_settings.FOO = bar` | `monkeypatch.setenv("FOO", "bar")` + reload, or session-scoped `test_settings` fixture |
| Compiling SQLAlchemy statement + `"channel_bot_members" in str(stmt)` | Seed real data + assert on returned rows (the B.23 anti-pattern) |
| Inline re-implementation of production logic in Arrange + assert on the copy | **Delete the test.** Replace with one behavioral test that exercises real code path. |
| `_mock_db_session` helper that every DB test routes through | Remove; use `db_session` directly |
| Six+ nested `patch()` context managers (A.3 violation — > 10 statements) | Push internal patches into fixtures; keep test body ≤ 10 statements |

### 3. Ordering rule

For each rewrite candidate:

1. **Delete first** — re-implementation tests, "no assertion = success" tests, call-order-coupled sequential-execute tests. These can't catch bugs at any effort level.
2. **Rewrite with real DB** — DB-touching classes, one per session. Keep existing test titles (they name the right scenarios); swap bodies to use `db_session` + factory + `select()` round-trip.
3. **Leave alone** — pure-function test classes (no DB surface); external-client mock classes where the mocked object is the legitimate isolation boundary (BlueBubbles SDK, Slack client, MCP transport, HTTPX response).
4. **Don't rename** (A.1) — cosmetic; fix opportunistically in the same edit only.

### 4. Known SQLite / fixture gotchas

- **SQLite tz-aware DATETIME**: `tests/conftest.py` wraps `_SQLITE_DATETIME.result_processor` to coerce naive results to UTC-aware, matching Postgres semantics. New `TIMESTAMP(timezone=True)` columns automatically round-trip tz info.
- **UUID PKs with `gen_random_uuid()` server_default**: engine fixture strips the PG function for SQLite; `Session.before_flush` listener in `tests/conftest.py` fills any missing PK.
- **`pg_insert().on_conflict_do_update()`** compiles fine on SQLite; no special-case needed.
- **Identity-map masks cross-session deletions**: `db_session.get(Model, id)` returns the cached row even after a commit in another session. Force a round-trip via `db_session.execute(select(Model.id).where(Model.id == id))`.
- **JSONB mutation tracking**: `copy.deepcopy()` + `flag_modified()` or SA won't persist the UPDATE on PG (no-op on SQLite, silently breaks on PG).
- **Fire-and-forget flush**: `await asyncio.sleep(0)` × 5 + `db_session.expire_all()` before asserting on DB state written by `safe_create_task()` background tasks.
- **`from app.db.engine import async_session` at module top** is the canonical offender — binds at import time, so patching only `app.db.engine.async_session` misses the alias. `_MODULE_LEVEL_ALIASES` is the canonical running list.

## Related docs

- [[Track - Test Quality]] — active track, shipped phases, open seams, Phase N
- [[Test Audit - Coverage Gaps]] — 127 uncovered routes + critical service symbols (orthogonal axis; still live)
- `~/.claude/skills/testing-python/SKILL.md` — canonical rule source
- `~/.claude/skills/testing-python/references/sqlalchemy-real-db.md` — the anti-pattern catalog
