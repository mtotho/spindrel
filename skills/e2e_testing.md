---
name: E2E Testing
description: Run and interpret end-to-end tests against a Spindrel server instance
triggers: e2e, end-to-end, integration test, smoke test, test harness, run tests, run scenario
category: development
mode: on_demand
---

# E2E Test Harness

The `run_e2e_tests` tool runs end-to-end tests against a real Spindrel server instance. Unlike unit tests (which mock the LLM), these exercise the full pipeline: user message → context assembly → real LLM call → tool selection → tool execution → response.

## Actions

| Action | Purpose |
|--------|---------|
| `status` | Check if the E2E stack is running |
| `run` | Start stack (if needed) + run tests via pytest |
| `stop` | Tear down the stack |
| `run_scenario` | Execute an ad-hoc inline YAML scenario (stack must be running) |

## Running the Full Suite

```
run_e2e_tests(action="run")
run_e2e_tests(action="run", scenarios="delegation")   # filter by keyword
run_e2e_tests(action="run", keep_running=true)         # keep stack up after
```

## Running Ad-Hoc Scenarios

Create and execute a scenario on the fly — no file needed. The E2E stack must already be running.

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

Returns JSON with pass/fail, step details, tool usage, and response previews.

## Available Test Bots

| Bot ID | Tools | Notes |
|--------|-------|-------|
| `e2e` | `get_current_time`, `get_current_local_time` | Default, minimal |
| `e2e-tools` | time tools + `get_tool_info` + `get_skill` + `web_search` | Most scenarios use this |
| `e2e-rag` | Same as e2e-tools | Has `tool_retrieval: true` |
| `e2e-delegator` | `get_current_time` + `delegate_to_agent` | Can delegate to `e2e-tools` |

## Writing YAML Scenarios

Drop a `.yaml` file in `tests/e2e/scenarios/yaml/` — auto-discovered by pytest.

```yaml
scenarios:
  - name: my_scenario
    bot_id: e2e-tools
    tags: [tool-grounding]
    steps:
      - message: "Search the web for Python release date. Use web_search."
        stream: true
        assertions:
          - tool_called: [web_search]
          - response_not_empty: true
          - no_errors: true
```

### Inline bots (created/deleted per scenario)

```yaml
scenarios:
  - name: restricted_test
    bot:
      id: e2e-temp
      system_prompt: "Only use tools when asked."
      local_tools: [get_current_time]
      tool_retrieval: false
    steps:
      - message: "What time is it?"
        assertions:
          - tool_called: [get_current_time]
```

## Available Assertions

**Response:** `response_not_empty`, `response_contains_any: [keywords]`, `response_contains_all: [keywords]`, `response_not_contains: [forbidden]`, `response_matches: "regex"`, `response_length: {min: N, max: N}`

**Tools:** `tool_called: [any_of]`, `tool_called_all: [all_of]`, `tool_not_called: [none_of]`, `no_tools_called: true`, `tool_count: {min: N, max: N}`, `tool_called_with_args: {tool: "name", args: {k: v}}`

**Stream:** `no_errors: true`, `event_sequence: [types]`

## LLM Provider Config

Default: ollama + gemma3:1b. Override with env vars:

```bash
E2E_LLM_PROVIDER=external E2E_LLM_BASE_URL=https://... E2E_LLM_API_KEY=sk-... E2E_DEFAULT_MODEL=model-name
```

## Delegation Caveats

`delegate_to_agent` creates a **deferred Task** — the parent stream completes before the child runs. You can assert the parent called the tool and mentioned delegation, but not the child's output.

## Common Failures

- **Tool not called**: LLM didn't pick the expected tool. Be explicit in prompts ("Use your web_search tool"). Small models are flaky — try a larger model.
- **Startup timeout**: Server slow to start. Increase `E2E_STARTUP_TIMEOUT`.
- **Import error on run_scenario**: The E2E harness isn't available in the Docker production image. Run from source (dev server).

Full reference: `docs/guides/e2e-testing.md`
