# E2E Testing Guide

End-to-end tests exercise the full Spindrel server pipeline against a real instance: user message → context assembly → LLM call → tool selection → tool execution → streamed response. Unlike unit tests (which mock the LLM), these validate that the whole system works together.

## Quick Start

### Run from the command line

```bash
# Run all E2E tests (starts compose stack, runs tests, tears down)
pytest tests/e2e/ -v

# Run specific scenario files
pytest tests/e2e/ -k "test_health"
pytest tests/e2e/ -k "test_tool_usage"
pytest tests/e2e/ -k "delegation"

# Keep the stack running after tests (for debugging)
E2E_KEEP_RUNNING=1 pytest tests/e2e/ -v
```

### Run via the agent tool

Bots with access to `run_e2e_tests` can run and interpret tests:

```
run_e2e_tests(action="run")                          # run all
run_e2e_tests(action="run", scenarios="delegation")  # filter by keyword
run_e2e_tests(action="status")                       # check if stack is up
run_e2e_tests(action="stop")                         # tear down stack
```

### Run an ad-hoc scenario (agent only)

Bots can create and execute scenarios on the fly without modifying files:

```
run_e2e_tests(
    action="run_scenario",
    scenario_yaml="""
name: my_test
bot_id: e2e-tools
steps:
  - message: "What time is it? Use your tools."
    stream: true
    assertions:
      - tool_called: [get_current_time]
      - response_not_empty: true
"""
)
```

This requires the E2E stack to already be running (`E2E_KEEP_RUNNING=1` or `action="run"` with `keep_running=true` first).

## Architecture

```
tests/e2e/
├── docker-compose.e2e.yml     # Compose stack (postgres, searxng, Spindrel server, ollama)
├── bot.e2e.yaml               # Default test bot (minimal, no tools)
├── bots/
│   ├── e2e-tools.yaml         # Bot with tools (time, web_search, get_tool_info, get_skill)
│   ├── e2e-rag.yaml           # Bot with tool RAG enabled
│   └── e2e-delegator.yaml     # Bot that delegates to e2e-tools
├── harness/
│   ├── config.py              # E2EConfig — all settings from E2E_* env vars
│   ├── environment.py         # E2EEnvironment — compose lifecycle (build, up, wait, down)
│   ├── client.py              # E2EClient — HTTP client (chat, chat_stream, admin APIs)
│   ├── streaming.py           # StreamEvent/StreamResult — SSE parsing
│   ├── assertions.py          # 14 fuzzy assertion functions
│   ├── runner.py              # Scenario executor (step loop, assertion dispatch, inline bot lifecycle)
│   ├── scenario.py            # Scenario dataclasses + YAML loader
│   └── waiters.py             # Polling helpers
├── scenarios/
│   ├── test_health.py         # Health endpoint checks
│   ├── test_chat_basic.py     # Non-streaming chat
│   ├── test_chat_stream.py    # Streaming SSE events
│   ├── test_tool_usage.py     # Tool selection via stream
│   ├── test_admin_crud.py     # Bot/channel admin APIs
│   ├── test_multi_turn.py     # Context persistence across turns
│   ├── test_error_handling.py # Auth failures, bad input
│   └── test_yaml_scenarios.py # Auto-discovers and runs all YAML scenarios
│   └── yaml/                  # YAML scenario definitions
│       ├── tool_time.yaml
│       ├── tool_negative.yaml
│       ├── tool_discovery.yaml
│       ├── tool_restriction.yaml
│       ├── tool_web_search.yaml
│       ├── tool_delegation.yaml
│       └── multi_turn_context.yaml
└── conftest.py                # Pytest fixtures (session-scoped env, per-test client)
```

## LLM Provider Configuration

E2E points at an external LLM endpoint. `E2E_LLM_BASE_URL` is required — there is no in-stack model. Gemini's OpenAI-compatible endpoint is the canonical default; any OpenAI-compatible URL works (OpenRouter, a self-hosted ollama, etc.).

```bash
E2E_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/ \
E2E_LLM_API_KEY=AIza... \
E2E_DEFAULT_MODEL=gemini-2.5-flash-lite \
pytest tests/e2e/ -v
```

Pointing at your own ollama host (e.g. a Mac mini on the LAN):

```bash
E2E_LLM_BASE_URL=http://mac-mini.local:11434/v1 \
E2E_DEFAULT_MODEL=llama3.2:3b \
pytest tests/e2e/ -v
```

All configuration env vars:

| Variable | Default | Purpose |
|----------|---------|---------|
| `E2E_LLM_BASE_URL` | **required** | LLM API base URL (OpenAI-compatible) |
| `E2E_LLM_API_KEY` | (empty) | LLM API key |
| `E2E_DEFAULT_MODEL` | `gemini-2.5-flash-lite` | Model for the default bot |
| `E2E_PORT` | `18000` | Spindrel server port on host |
| `E2E_API_KEY` | `e2e-test-key-12345` | API key for test server |
| `E2E_IMAGE` | `agent-server:e2e` | Docker image name |
| `E2E_KEEP_RUNNING` | (unset) | Set to `1` to keep stack up after tests |
| `E2E_STARTUP_TIMEOUT` | `120` | Seconds to wait for server health |
| `E2E_REQUEST_TIMEOUT` | `60` | Seconds per HTTP request |

## Writing YAML Scenarios

YAML scenarios are the primary way to add E2E tests. Drop a `.yaml` file in `tests/e2e/scenarios/yaml/` and it's auto-discovered.

### Basic structure

```yaml
scenarios:
  - name: my_scenario_name          # required, unique, becomes the pytest ID
    description: "What this tests"   # optional
    bot_id: e2e-tools                # pre-mounted bot to use
    tags: [tool-grounding]           # optional, for filtering
    timeout: 60                      # per-step timeout (seconds)
    channel: shared                  # "shared" (default) or "per_step"
    steps:
      - message: "User message to send"
        stream: true                 # true (SSE) or false (sync /chat)
        assertions:
          - tool_called: [get_current_time]
          - response_not_empty: true
          - no_errors: true
```

### Using an inline bot

Instead of `bot_id`, define a temporary bot that's created before the scenario and deleted after:

```yaml
scenarios:
  - name: custom_bot_test
    bot:
      id: e2e-temp-bot
      name: "Temporary Test Bot"
      system_prompt: "You only answer in haiku."
      local_tools: [get_current_time]
      tool_retrieval: false
    steps:
      - message: "What time is it?"
        stream: true
        assertions:
          - tool_called: [get_current_time]
```

### Multi-turn scenarios

Steps in a `shared` channel (default) maintain conversation context:

```yaml
scenarios:
  - name: context_persists
    bot_id: e2e-tools
    channel: shared
    steps:
      - message: "What time is it? Use your time tool."
        stream: true
        assertions:
          - tool_called: [get_current_time, get_current_local_time]
      - message: "What time did you just tell me? Don't use tools."
        stream: true
        assertions:
          - no_tools_called: true
          - response_not_empty: true
```

## Available Assertions

All assertions are fuzzy — designed for non-deterministic LLM output.

### Response assertions

| Key | Value | What it checks |
|-----|-------|---------------|
| `response_not_empty` | `true` | Response has 5+ non-whitespace chars |
| `response_contains_any` | `["word1", "word2"]` | At least one keyword present (case-insensitive) |
| `response_contains_all` | `["word1", "word2"]` | All keywords present (case-insensitive) |
| `response_not_contains` | `["forbidden"]` | None of these strings present |
| `response_matches` | `"\\d{2}:\\d{2}"` | Regex matches somewhere in response |
| `response_length` | `{min: 10, max: 500}` | Character count within bounds |

### Tool assertions

| Key | Value | What it checks |
|-----|-------|---------------|
| `tool_called` | `[tool_a, tool_b]` | At least one of these tools was called |
| `tool_called_all` | `[tool_a, tool_b]` | All of these tools were called |
| `tool_not_called` | `[tool_x]` | None of these tools were called |
| `no_tools_called` | `true` | No tools called at all |
| `tool_count` | `{min: 1, max: 3}` | Number of tool calls within bounds |
| `tool_called_with_args` | `{tool: "name", args: {key: "val"}}` | Tool called with specific arguments |

### Stream assertions

| Key | Value | What it checks |
|-----|-------|---------------|
| `no_errors` | `true` | No error events in the SSE stream |
| `event_sequence` | `["message_start", "content"]` | Event types appear in order (as subsequence) |

## Available Test Bots

| Bot ID | Tools | Special |
|--------|-------|---------|
| `e2e` | `get_current_time`, `get_current_local_time` | Default bot, minimal |
| `e2e-tools` | `get_current_time`, `get_current_local_time`, `get_tool_info`, `get_skill`, `web_search` | Tool grounding tests |
| `e2e-rag` | Same as e2e-tools | `tool_retrieval: true` with threshold 0.3 |
| `e2e-delegator` | `get_current_time`, `delegate_to_agent` | `delegate_bots: [e2e-tools]` |

## Services in the E2E Stack

| Service | Purpose |
|---------|---------|
| `postgres` | pgvector DB (ephemeral tmpfs, no persistent volume) |
| `searxng` | Web search backend for `web_search` tool tests |
| `agent-server` | Spindrel server (the system under test) |
| `ollama` | Local LLM (optional, activated with `--profile ollama`) |

## Common Patterns

### Testing tool grounding

"Does the LLM pick the right tool?" — the most common E2E test type:

```yaml
- message: "What time is it? Use your tools."
  assertions:
    - tool_called: [get_current_time]       # should pick this tool
    - tool_not_called: [web_search]          # should NOT pick this one
```

### Testing negative behavior

"Does the LLM know when NOT to use tools?":

```yaml
- message: "What is 2 + 2?"
  assertions:
    - no_tools_called: true                  # LLM should just answer
    - response_contains_any: ["4"]
```

### Testing delegation

Delegation creates a deferred Task — the parent stream completes with a task reference, but the child runs asynchronously. Assert on the parent's behavior:

```yaml
- message: "Delegate to e2e-tools: ask it what time it is."
  assertions:
    - tool_called: [delegate_to_agent]       # parent called the tool
    - response_contains_any: ["task", "delegat"]  # mentions delegation
```

### Testing error handling

Verify the system fails gracefully:

```yaml
- message: "Delegate to nonexistent-bot: say hello."
  assertions:
    - tool_called: [delegate_to_agent]
    - response_contains_any: ["error", "not found", "not allowed"]
```

## Debugging

### Keep the stack running

```bash
E2E_KEEP_RUNNING=1 pytest tests/e2e/ -v -k "test_health"
```

Then interact manually:

```bash
# Check health
curl -H "Authorization: Bearer e2e-test-key-12345" http://localhost:18000/health

# Send a chat message
curl -X POST http://localhost:18000/chat \
  -H "Authorization: Bearer e2e-test-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "bot_id": "e2e"}'

# Stream a chat
curl -N -X POST http://localhost:18000/chat/stream \
  -H "Authorization: Bearer e2e-test-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"message": "what time is it?", "bot_id": "e2e-tools"}'
```

### Tear down manually

```bash
docker compose -f tests/e2e/docker-compose.e2e.yml -p spindrel-e2e down -v --remove-orphans
```

### View server logs

```bash
docker compose -f tests/e2e/docker-compose.e2e.yml -p spindrel-e2e logs agent-server -f
```

## Tips for Reliable Scenarios

- **Be explicit in prompts** — "Use your tools" or "Use your web_search tool" reduces flakiness with small models
- **Use `tool_called` (any-of)** not `tool_called_all` when multiple tools could satisfy the request
- **Use `response_contains_any`** with several keyword variants — LLMs phrase things differently each run
- **Set `tool_retrieval: false`** on test bots to eliminate RAG variability
- **Use `stream: true`** for all tool-related assertions — tool events are only available in streaming mode
- **Test negative cases** — verify the LLM doesn't over-use tools (no_tools_called, tool_not_called)
