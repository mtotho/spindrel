---
tags: [spindrel, track, testing, e2e]
status: in-progress
updated: 2026-04-11-eod
---
# E2E Testing Roadmap

> Session 18 (2026-04-10) — verified cron coverage was actually broken (running 14 of 24 files = 146 tests). Session 17's glob fix was uncommitted. Manual full-suite run with the on-disk fix: 311 tests, 300 pass, 10 fail. Added Ollama provider to e2e instance — now has Gemini + OpenAI + Ollama (real 3-provider matrix). gemma4:e4b smoke 6/6 pass. Real bug found: `test_carapace_resolve` 500 due to dead `resolved.skills` reference (post migration 187), fixed in source.
>
> Session 17 (2026-04-11) — closed the 3 actionable EOD audit remaining failures. Only `test_presenter_fetches_slides_skill_before_creating` still open (tracked under Skill loading drift, container has no browser for Marp).

## Current State
**308+ tests across 23 files**, runs every 6h on the dedicated E2E instance via cron. Full triage of remaining failures lives in [[loose-ends]] — they're tracked there alongside the rest of the bug surface.

| Tier | Tests | What | Model needed? |
|---|---|---|---|
| API Contract | ~95 | Deterministic HTTP: CRUD, shapes, error codes | No |
| Server Behavior | ~40 | Streaming, tool dispatch, memory, multi-bot | Yes (gemini-2.5-flash-lite) |
| Model Smoke | ~6 | Per-model basic chat/stream/tools | Yes (per-model) |
| Multibot | ~17 | Channel members, routing, identity | Mixed |

## Dedicated E2E Instance
A separate Spindrel install at `~/spindrel-e2e/` on the test server (`thothbot@spindrel`). Lets Claude deploy/test freely without touching the user's production at `/opt/thoth-server/`.

| Component | Main | E2E |
|---|---|---|
| Path | `/opt/thoth-server/` | `~/spindrel-e2e/` |
| API port | 8000 | 18000 |
| UI port | 8081 | 18081 |
| Postgres port | 5432 | 15432 |
| Stack | systemd uvicorn + docker postgres | Full Docker Compose |
| Provider | (user's config) | Gemini 2.5 Flash + OpenAI gpt-5-nano |
| API key | (user's) | `e2e-dedicated-instance-key-2026` |

**Cron wrapper** (`~/bin/run-e2e-cron.sh`, lives outside the repo so `git pull` can't overwrite):
```
cd ~/spindrel-e2e && git pull --ff-only
docker compose up -d --build spindrel
wait healthy (max 180s, poll every 6s)
./scripts/run_e2e_scheduled.sh --quiet
```

Crontab: `0 */6 * * *  E2E_WORKSPACE_DIR=/home/thothbot/.agent-workspaces/shared/70aae325-... /home/thothbot/bin/run-e2e-cron.sh --quiet`

`E2E_WORKSPACE_DIR` makes `conftest.py` mirror `e2e-results.json` + `e2e-history/` to the agent workspace dir at session end. Logs in `~/logs/e2e/`. Cost tracking via `_ResultCollector.fetch_usage()` querying `/api/v1/admin/usage/summary` — `usage` block in `e2e-results.json` (~$0.06 per full run).

**Setup automation**: `scripts/setup.py` supports `SPINDREL_HEADLESS=1` (no prompts). `scripts/setup-e2e-instance.sh` bootstraps a fresh instance end-to-end.

## How to Run
**Always target the dedicated E2E instance.**

```bash
# Full scheduled suite:
ssh spindrel "cd ~/spindrel-e2e && /opt/thoth-server/.venv/bin/pytest tests/e2e/ -v"

# Specific file:
ssh spindrel "cd ~/spindrel-e2e && \
  E2E_MODE=external E2E_HOST=localhost E2E_PORT=18000 \
  E2E_API_KEY=e2e-dedicated-instance-key-2026 \
  E2E_BOT_ID=e2e E2E_DEFAULT_MODEL=gemini-2.5-flash E2E_REQUEST_TIMEOUT=120 \
  /opt/thoth-server/.venv/bin/pytest tests/e2e/scenarios/test_X.py -v"
```

**WHILE TESTS RUN**: watch logs in parallel and kill on repeating LLM errors — every failed call costs real $.
```bash
ssh spindrel "cd ~/spindrel-e2e && docker compose logs -f spindrel"
```

## Environment Variables
| Var | Default | Notes |
|---|---|---|
| `E2E_MODE` | `compose` | `compose` or `external` |
| `E2E_HOST` | `localhost` | Server hostname |
| `E2E_PORT` | `18000` | E2E instance port |
| `E2E_API_KEY` | `e2e-test-key-12345` | E2E uses `e2e-dedicated-instance-key-2026` |
| `E2E_BOT_ID` | `e2e` | Default bot for Tier 2 |
| `E2E_DEFAULT_MODEL` | `gemini-2.5-flash-lite` | Bare name, no `gemini/` prefix |
| `E2E_SMOKE_MODELS` | JSON array | Tier 3 models |
| `E2E_WORKSPACE_SUMMARY` | `~/logs/e2e/e2e-results.json` | Tiered results with `usage` block |
| `E2E_REQUEST_TIMEOUT` | `60` | Per-request seconds |
| `E2E_KEEP_RUNNING` | `0` | Keep compose stack after tests |

## Test Files
| File | Tests | Tier | What |
|---|---|---|---|
| `test_api_contract.py` | 13 | API contract | Bot/channel CRUD, field persistence |
| `test_regressions.py` | 7 | API contract | Specific bug regressions |
| `test_settings_config.py` | 9 | API contract | Settings, status, model config |
| `test_providers_models.py` | 8 | API contract | Provider/model reads |
| `test_channel_details.py` | 12 | API contract | Channel sub-endpoints |
| `test_carapaces_crud.py` | 14 | API contract | Capability CRUD lifecycle |
| `test_search_indexing.py` | 20 | API contract | Search, indexing, diagnostics |
| `test_tool_policies.py` | 19 | API contract | Policies, calls, approvals |
| `test_multibot_channels.py` | 17 | Mixed | Multi-bot channel behavior |
| `test_server_behavior.py` | 8 | Server behavior | Streaming, tools, context |
| `test_workspace_memory.py` | 9 | Server behavior | File ops, memory round-trips |
| `test_memory_behavior.py` | 8 | Server behavior | Cross-channel, persistence, API |
| `test_model_smoke.py` | 3×N | Model smoke | Per-model chat/stream/tools |
| `test_chat_basic.py` | 4 | Server behavior | Basic chat |
| `test_chat_stream.py` | 5 | Server behavior | Basic streaming |
| `test_workflows.py` | 22 | Server behavior | Workflow CRUD, runs, gates, LLM |
| `test_tool_approval_flow.py` | 8 | Server behavior | Full approval lifecycle, deny, priority |
| `test_context_discovery.py` | 14 | Mixed | Context blocks, token math, breakdown |
| `test_skill_loading.py` | 14 | Server behavior | Skill CRUD, embedding, capability resolve |
| `test_memory_search_depth.py` | 3 | Server behavior | Write→search round-trip, curation |
| `test_sessions_plans.py` | 13 | API contract | Session CRUD, message inject, context |
| `test_subagents.py` | 10 | Server behavior | spawn_subagents, presets, parallel |
| `test_bot_hooks.py` | 27 | API contract | Lifecycle hooks, conditions, cooldowns |
| `test_openai_native_smoke.py` | 4 | Provider smoke | OpenAI gpt-5-nano (catches OpenAIDriver-specific bugs) |

## Coverage Map
| Area | Status | Notes |
|---|---|---|
| Chat & streaming | ✅ solid | Basic, streaming, session_id, errors, multi-turn. Gaps: audio input, attachments, SSE observer |
| Tool dispatch | ✅ solid | Single+multi tool, full approval lifecycle, deny rules, priority. Gaps: tool chaining, pinned tools used |
| Memory system | ⚠️ basic | Round-trips + dispatch shape covered. Gaps: curation actually running, dedup, search relevance ranking |
| Search & indexing | ✅ solid | Diagnostics, embedding health, search returns scored results. Gaps: behavioral reindex, section search |
| Tool policies & approvals | ✅ solid (re-verified 2026-04-10 fresh DB) | Full CRUD, dry-run, approval flow, priority, create_rule. The mid-day "regression" was state pollution from yesterday's schema churn — 8/8 pass on a clean volume. Gaps: conditional rules with arg conditions |
| Tool call history | ✅ solid | List, filter, stats, group, detail. Gaps: error_only filter, date range |
| Bot admin | ✅ solid | Full CRUD, field persistence, defaults. Gaps: custom workspace config, provider override |
| Channel admin | ✅ solid | List, create-via-chat, settings, sub-endpoints. Gaps: delete + verify gone, custom history_mode |
| Multi-bot channels | ✅ solid | Creation, CRUD, validation, routing, isolation. Gaps: concurrent member messages, member tool dispatch |
| Capabilities CRUD | ✅ solid | Full CRUD, resolve, usage, export YAML. Gaps: behavioral activation changes LLM behavior |
| Providers & models | ✅ read-only covered | All read endpoints |
| Settings & config | ✅ covered | Status, settings, deviations, defaults |
| Workflows | ✅ solid (22) | CRUD, runs, gates, multi-step, error cases, LLM via manage_workflow. Gaps: tool/exec step types, conditionals, on_failure policies |
| Sessions & plans | ✅ solid (13) | CRUD, messages, context, plans 404. Gaps: summarize (LLM), plan creation via tool |
| API keys | ❌ zero | Security-critical CRUD untested. **[touched 2026-04-11 by `5acb0220` — `app/services/api_keys.py` +19 LOC, still zero e2e coverage]** |
| Auth | ❌ zero | Login, refresh, token lifecycle untested |
| Workspace REST | ❌ zero | List/read/write/delete/move/upload via admin API untested (LLM tool path is tested). **[touched 2026-04-11 by `5acb0220` — `app/routers/api_v1_workspaces.py` +96 LOC, still zero e2e coverage]** |
| Integrations admin | ❌ blocked | Needs active Slack/GitHub — defer |

## Known Quirks
- Channel throttle blocks rapid requests without `sender_type: "human"` — client sets this
- `/bots` returns `{"bots": [...]}`, `/channels` returns `{"channels": [...], "page": N}`
- Health check must verify bot registry loaded (startup race fix in harness)
- Memory search index has 300s cooldown — test dispatch, not freshness
- Small models hallucinate tool names — system prompt must list tool names explicitly

## Next Up
0. **Fix `run_e2e_scheduled.sh` to enumerate all `tests/e2e/scenarios/test_*.py` files** — currently hard-codes 14 of 24 files, omitting `test_tool_approval_flow.py`, `test_workflows.py`, `test_chat_basic.py`, `test_chat_stream.py`, `test_context_discovery.py`, `test_skill_loading.py`, `test_memory_search_depth.py`, `test_sessions_plans.py`, `test_subagents.py`, `test_bot_hooks.py`. The 308-test runs in `e2e-history/` were manual ad-hoc, not cron. ~10 hours of refactoring landed today entirely uncovered by automation.
1. **API Keys + Auth** (~10 tests) — security-critical zero coverage
2. **Cross-provider matrix** (proposed, not built) — every behavioral test runs against Gemini Flash, so the OpenAIDriver / anthropic_adapter / Ollama paths only get smoked. The session-8 tool-name concat bug lived in `llm.py` for weeks because Gemini's OpenAI-compat sends full names every chunk and OpenAI doesn't. Proposed: `test_provider_smoke.py` parameterized across OpenAI, Gemini, Anthropic, Ollama. Recorded-chunk replay unit tests as a cheap layer below. `E2E_PROVIDER_MATRIX` env var. ~$0.25 per matrix run, nightly.
3. **Behavioral verification depth** — skill discovery actually surfaces the right skill, capability activation actually changes effective tools, search relevance ranking, context budget overflow triggers compaction.
