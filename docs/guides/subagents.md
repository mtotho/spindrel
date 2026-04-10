# Sub-Agents

Sub-agents are lightweight, ephemeral workers that a bot spawns inline to perform focused tasks. They run in parallel on cheaper models, return results directly to the parent bot, and are never visible to the user.

## Quick Start

**1. Add `spawn_subagents` to a bot's tools** (admin UI or YAML):

```yaml
# bots/my_bot.yaml
id: my_bot
local_tools:
  - spawn_subagents
```

**2. The bot uses it automatically** when it has multiple independent tasks:

```
user: Scan the codebase for security issues and summarize the README
bot:  [calls spawn_subagents with 2 agents: file-scanner + summarizer]
      Here's what I found: ...
```

The bot decides when to use sub-agents based on the tool description guidance. No additional configuration needed.

## Sub-Agents vs Delegation

| | `spawn_subagents` | `delegate_to_agent` |
|---|---|---|
| **Execution** | Synchronous, inline | Asynchronous (Task worker) |
| **Identity** | Anonymous worker | Named bot with persona |
| **Result** | Returned to parent only | Posted to channel |
| **Parallelism** | Multiple run concurrently | One at a time |
| **Context** | Minimal (system prompt + task) | Full bot context assembly |
| **Use case** | Grunt work, scanning, summarizing | "Hey image-bot, make me a picture" |

**Rule of thumb:** If the user should see the result from a specific bot, use delegation. If the parent bot needs help thinking, use sub-agents.

## Built-in Presets

Presets are named profiles with a default tool set, system prompt, and model tier.

| Preset | Default Tier | Tools | Best For |
|--------|-------------|-------|----------|
| `file-scanner` | fast | `file`, `exec_command` | Bulk file reading, pattern extraction, listing |
| `summarizer` | fast | (none) | Compressing large text inputs |
| `researcher` | standard | `web_search` | Web research with source citations |
| `code-reviewer` | standard | `file`, `exec_command` | Code review, bug detection, quality checks |
| `data-extractor` | fast | `file`, `exec_command` | Structured data extraction (JSON, tables) |

### Using a preset

The bot calls `spawn_subagents` with one or more agent specs:

```json
{
  "agents": [
    {"preset": "file-scanner", "prompt": "Find all API endpoints in app/routers/"},
    {"preset": "summarizer", "prompt": "Summarize this conversation: ..."}
  ]
}
```

### Custom sub-agents (no preset)

Instead of a preset, specify `tools` and optionally `system_prompt`:

```json
{
  "agents": [
    {
      "tools": ["web_search", "exec_command"],
      "system_prompt": "You are a fact-checker. Verify claims with sources.",
      "prompt": "Is it true that ...",
      "model_tier": "standard"
    }
  ]
}
```

## Model Tiers

Sub-agents use the **model tier** system to select cost-appropriate models. Tiers are mapped to concrete models in **Settings > Global > Model Tiers**.

| Tier | Intended Use |
|------|-------------|
| `free` | Zero-cost / rate-limited models |
| `fast` | Cheap, quick tasks (scanning, extraction) |
| `standard` | Moderate tasks (research, code review) |
| `capable` | Complex reasoning, polished output |
| `frontier` | Highest capability, highest cost |

Resolution order:
1. Explicit `model` param (escape hatch — specific model ID)
2. Explicit `model_tier` param
3. Preset's `default_tier`
4. Parent bot's model (fallback)

### Configuring tiers

Go to **Settings > Global > Model Tiers** to map each tier to a concrete model. Example:

| Tier | Model |
|------|-------|
| fast | `gemini/gemini-2.5-flash` |
| standard | `gemini/gemini-2.5-pro` |
| capable | `anthropic/claude-sonnet-4-6` |
| frontier | `anthropic/claude-opus-4-6` |

## Limits

- **Max 10 sub-agents per call** — excess agents are dropped with a warning
- **Max 5 tool iterations per sub-agent** — sub-agents should be quick
- **Max 4000 chars per result** — configurable via `max_chars` per agent spec
- **No recursive spawning** — sub-agents cannot call `spawn_subagents` or `delegate_to_agent`

## How It Works

1. Parent bot calls `spawn_subagents` with an array of agent specs
2. Each spec is resolved: preset defaults + explicit overrides
3. All sub-agents run **concurrently** via `asyncio.gather`
4. Each sub-agent gets a minimal context: system prompt + task prompt (no conversation history)
5. Results are collected and returned as a single JSON tool response to the parent
6. Parent synthesizes the results and responds to the user

Sub-agent results are **never posted to the channel** — they exist only in the parent's tool call/result flow.

## Defining Custom Presets

Presets are currently defined in code at `app/agent/subagents.py` in the `SUBAGENT_PRESETS` dictionary:

```python
SUBAGENT_PRESETS = {
    "file-scanner": {
        "tools": ["file", "exec_command"],
        "system_prompt": "You scan files and extract information. Be concise...",
        "default_tier": "fast",
    },
    # ... more presets
}
```

To add a new preset:

1. Add an entry to `SUBAGENT_PRESETS` with `tools`, `system_prompt`, and `default_tier`
2. The preset is immediately available — no migration or restart needed (beyond code deploy)
3. The tool description auto-updates to list the new preset

Future: presets may become configurable via the admin UI or YAML files.

## Examples

### Parallel file scanning

```
user: What test coverage do we have for the auth module?
bot:  [spawn_subagents: 
        file-scanner → "List all test files in tests/ that import from app/auth/"
        file-scanner → "List all functions in app/auth/ that are public"
      ]
      Based on the scan: 12 public functions in auth, 8 have test coverage...
```

### Research + summarize

```
user: What are the latest developments in WebTransport?
bot:  [spawn_subagents:
        researcher → "Find recent WebTransport developments, standards updates, browser support"
        researcher → "Find WebTransport vs WebSocket performance comparisons"
      ]
      Here's a summary of the current WebTransport landscape...
```

### Iterative slide creation (Marp)

```
user: Create a presentation about our Q1 results
bot:  [spawn_subagents:
        file-scanner → "Extract key metrics from data/q1-results.csv"
        summarizer → "Summarize the Q1 OKR document into 5 bullet points"
      ]
      [calls create_slides with synthesized content]
      Here's your Q1 presentation...
```
