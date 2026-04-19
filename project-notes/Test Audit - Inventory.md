---
status: reference
updated: 2026-04-17
tags: [testing, audit]
---

# Test Audit — Inventory

Mechanical (grep-based) inventory of test quality smells across `tests/unit/` and `tests/integration/`. Weighted ranking highlights the worst offenders to target in a refactor pass. Generated 2026-04-17.

Smell codes match `dotfiles/claude/skills/testing-python/SKILL.md`:

- **E.13** — mocked `AsyncSession`/`Session` instead of real in-memory SQLite. Headline issue.
- **E.9 / H.1** — `patch("httpx…")`, `patch("datetime…")`, `patch("time.…")`, `patch("asyncio.sleep")` instead of `respx` / `freezegun`.
- **A.13** — flat-structure violations in `test_` bodies (`try` / `except` / `print(` / `for ` / `while `).
- **A.1** — cosmetic: `test_` name missing `_when_` / `_then_`.
- **B.3** — ≥3 magic literals (UUIDs / emails / long digits) inside `assert` that never appear in the same function body outside the assert.

Weighting for overall ranking: E.13 = 5, E.9/H.1 = 3, A.13 = 3, B.3 = 2, A.1 = 1.

## Summary totals

Files scanned: **320**. Tests found: **5681**.

| Smell | Total hits |
|---|---:|
| E.13 — Mock near session tokens | 1643 |
| E.9 / H.1 — patch stdlib/httpx/datetime | 37 |
| A.13 — flat-structure violations inside `test_` bodies | 194 |
| A.1 — title not `_when_…_then_…` | 5411 |
| B.3 — test functions with ≥3 unexplained magic literals in asserts | 0 |

Additional signal: **151** files import `MagicMock`/`AsyncMock` and never reference `db_session` or `AsyncSession` — strong candidates for full rewrite against the real DB fixture.

## Top 20 offenders (weighted overall)

| # | File | Score | E.13 | E.9/H.1 | A.13 | A.1 | B.3 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `tests/unit/test_manage_bot_skill.py` | 1036 | 180 | 0 | 1 | 133 | 0 |
| 2 | `tests/unit/test_multi_bot_channels.py` | 1008 | 183 | 1 | 0 | 90 | 0 |
| 3 | `tests/unit/test_task_tools.py` | 452 | 87 | 0 | 0 | 17 | 0 |
| 4 | `tests/unit/test_workflow_advancement.py` | 399 | 72 | 0 | 0 | 39 | 0 |
| 5 | `tests/unit/test_memory_hygiene.py` | 396 | 64 | 0 | 2 | 70 | 0 |
| 6 | `tests/unit/test_tasks.py` | 390 | 75 | 0 | 0 | 15 | 0 |
| 7 | `tests/unit/test_bluebubbles_wake_word.py` | 369 | 61 | 0 | 0 | 64 | 0 |
| 8 | `tests/unit/test_mcp_servers.py` | 273 | 52 | 0 | 0 | 13 | 0 |
| 9 | `tests/unit/test_workflow_tool.py` | 248 | 46 | 0 | 0 | 18 | 0 |
| 10 | `tests/unit/test_tool_discovery.py` | 242 | 34 | 0 | 12 | 36 | 0 |
| 11 | `tests/unit/test_backfill_sections.py` | 209 | 38 | 0 | 2 | 13 | 0 |
| 12 | `tests/unit/test_capability_rag.py` | 188 | 34 | 0 | 1 | 15 | 0 |
| 13 | `tests/unit/test_webhook_execution_config.py` | 183 | 32 | 0 | 0 | 23 | 0 |
| 14 | `tests/unit/test_file_ops.py` | 176 | 0 | 0 | 0 | 176 | 0 |
| 15 | `tests/unit/test_bluebubbles_sender_metadata.py` | 172 | 30 | 0 | 1 | 19 | 0 |
| 16 | `tests/unit/test_workflows.py` | 155 | 22 | 0 | 0 | 45 | 0 |
| 17 | `tests/unit/test_docker_stacks.py` | 153 | 19 | 0 | 0 | 58 | 0 |
| 18 | `tests/unit/test_history_tool_search.py` | 152 | 28 | 0 | 0 | 12 | 0 |
| 19 | `tests/unit/test_read_conversation_history.py` | 151 | 27 | 0 | 0 | 16 | 0 |
| 20 | `tests/unit/test_compaction_comprehensive.py` | 134 | 9 | 0 | 12 | 53 | 0 |

## Top 10 E.13 (mocked session) — the headline refactor list

| # | File | E.13 hits | Uses real `db_session`? |
|---:|---|---:|:---:|
| 1 | `tests/unit/test_multi_bot_channels.py` | 183 | no |
| 2 | `tests/unit/test_manage_bot_skill.py` | 180 | no |
| 3 | `tests/unit/test_task_tools.py` | 87 | no |
| 4 | `tests/unit/test_tasks.py` | 75 | no |
| 5 | `tests/unit/test_workflow_advancement.py` | 72 | no |
| 6 | `tests/unit/test_memory_hygiene.py` | 64 | no |
| 7 | `tests/unit/test_bluebubbles_wake_word.py` | 61 | no |
| 8 | `tests/unit/test_mcp_servers.py` | 52 | no |
| 9 | `tests/unit/test_workflow_tool.py` | 46 | no |
| 10 | `tests/unit/test_backfill_sections.py` | 38 | no |

## Top 10 A.13 (flat-structure violations) — mechanical fix candidates

Usually: `for`-loops building expected lists, `try/except` around the Act phase, or leftover `print(` from debugging.

| # | File | A.13 hits | Total tests |
|---:|---|---:|---:|
| 1 | `tests/unit/test_assembly_budget.py` | 18 | 7 |
| 2 | `tests/unit/test_channel_events.py` | 14 | 20 |
| 3 | `tests/unit/test_channel_renderers.py` | 14 | 15 |
| 4 | `tests/unit/test_compaction_comprehensive.py` | 12 | 54 |
| 5 | `tests/unit/test_tool_discovery.py` | 12 | 36 |
| 6 | `tests/integration/test_context_assembly.py` | 6 | 23 |
| 7 | `tests/unit/test_model_params_llm.py` | 5 | 33 |
| 8 | `tests/unit/test_tool_execute_api.py` | 5 | 10 |
| 9 | `tests/unit/test_channel_events_subscribe_all.py` | 5 | 5 |
| 10 | `tests/unit/test_web_search_optional.py` | 5 | 17 |

## Notes & false-positive risks

These caveats apply when reading the counts — don't bulk-fix without eyeballing first.

- **E.13 over-counts legitimate external-client mocks.** The regex flags any `MagicMock(` / `AsyncMock(` within 5 lines of tokens like `session`, `db`, `execute`. That catches the anti-pattern (`MagicMock()` standing in for `AsyncSession`) but also catches legitimate mocks of Slack SDK clients, BlueBubbles API, Discord adapter, Anthropic SDK, MCP server transports, HTTPX response objects, etc. Files whose subject matter is an *external* adapter (e.g. `test_slack_renderer.py`, `test_bluebubbles_*`, `test_discord_renderer.py`, `test_anthropic_adapter.py`, `test_mcp_servers.py`, `test_provider_drivers.py`) will always score high on E.13 but may be legitimate. Triage by opening the file and checking whether the mocked object is an `AsyncSession` or a third-party client.
- **"Never touches real DB" heuristic is sharper.** The `imports Mock + no db_session + no AsyncSession` check is a better signal for "this file is pure mock theatre" than raw E.13 counts. 151 of 320 files fall into this bucket — but again, many are legitimate adapter-only unit tests with no DB surface at all.
- **A.13 under-counts.** The regex only catches `try/except/print/for/while` at line-start inside a `def test_…` body. Multi-line constructs, comprehensions that should be factory calls, and nested helper functions all slip through. Treat the count as a lower bound.
- **A.1 is cosmetic noise.** 5k+ hits means nearly every test name in the codebase predates the `test_when_…_then_…` convention. Don't prioritize — fix opportunistically when touching a file for another reason.
- **B.3 came back zero.** The heuristic (UUID/email/long-digit in `assert` that doesn't appear elsewhere in the function) is conservative — it misses short string literals, integer IDs, dict-key magic strings, and cases where the literal is duplicated in the arrange phase (which is *also* a smoking-gun violation — they should reference the variable, not re-type the constant). Re-run with a stricter heuristic if B.3 is a priority.
- **Integration tests score deceptively low.** Only 12 integration files have any Mock usage at all — good news — but the integration suite is small (≈20 files) so absolute counts aren't comparable with unit. The refactor opportunity is almost entirely in `tests/unit/`.
- **`test_memory_hygiene.py`, `test_task_tools.py`, `test_multi_bot_channels.py`, `test_workflow_*`, `test_tasks.py`** recur across the top-20 and the E.13 top-10. These are the best compound-refactor targets — fixing the session-mock pattern in one of these files will touch many tests at once.
