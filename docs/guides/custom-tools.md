# Custom Tools & Extensions

This guide covers creating your own tools, managing a personal extensions repo, and loading external carapaces and tools into Spindrel.

---

## Quick Start: Drop-In Tools

The simplest way to add a tool: create a `.py` file in the `tools/` directory.

```python
# tools/weather.py
"""Current weather via OpenWeatherMap. Requires OPENWEATHERMAP_API_KEY in .env."""

import json
import logging
import os

import httpx

from app.tools.registry import register

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY", "")
_BASE_URL = "https://api.openweathermap.org/data/2.5"


@register({
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "Get current weather conditions for a city. Returns temperature, "
            "conditions, humidity, wind speed, and feels-like temperature."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, optionally with country code (e.g. 'London' or 'Paris,FR')",
                },
                "units": {
                    "type": "string",
                    "description": "Temperature units",
                    "enum": ["imperial", "metric", "standard"],
                },
            },
            "required": ["city"],
        },
    },
})
async def get_weather(city: str, units: str = "imperial") -> str:
    if not _API_KEY:
        return json.dumps({"error": "OPENWEATHERMAP_API_KEY is not configured"})

    unit_label = {"imperial": "°F", "metric": "°C", "standard": "K"}.get(units, "°F")
    speed_label = "mph" if units == "imperial" else "m/s"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE_URL}/weather",
                params={"q": city, "appid": _API_KEY, "units": units},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return json.dumps({"error": f"City not found: {city}"})
        return json.dumps({"error": f"Weather API error: {e.response.status_code}"})
    except Exception:
        logger.exception("Weather fetch failed for %s", city)
        return json.dumps({"error": "Failed to fetch weather"})

    weather = data.get("weather", [{}])[0]
    main = data.get("main", {})
    wind = data.get("wind", {})

    return json.dumps({
        "city": data.get("name", city),
        "country": data.get("sys", {}).get("country"),
        "conditions": weather.get("description", "unknown"),
        "temperature": f"{main.get('temp')}{unit_label}",
        "feels_like": f"{main.get('feels_like')}{unit_label}",
        "humidity": f"{main.get('humidity')}%",
        "wind_speed": f"{wind.get('speed')} {speed_label}",
    })
```

Restart the server and the tool is available to any bot.

### How It Works

At startup, Spindrel imports every `.py` file in `tools/` (except underscore-prefixed files). Any function decorated with `@register(schema)` is registered as a local tool. The schema follows the [OpenAI function calling format](https://platform.openai.com/docs/guides/function-calling).

### Key Rules

- **Return JSON strings** — tools must return `str` (JSON-serialized)
- **Async preferred** — use `async def` for I/O-bound tools (HTTP calls, file reads)
- **Sync works too** — `def my_tool()` is fine for CPU-bound or trivial tools
- **Graceful degradation** — check for missing API keys/config and return a clear error message
- **Underscore prefix = skip** — `_helpers.py` won't be imported as a tool

### Tool Discovery (RAG)

Tools aren't all sent to the LLM on every request. Spindrel uses **tool retrieval** — the user's message is embedded and compared against tool schemas via cosine similarity. Only relevant tools are included in the LLM call.

To ensure a tool is always available to a specific bot (bypassing retrieval), add it to `pinned_tools` in the bot's YAML:

```yaml
# bots/assistant.yaml
pinned_tools: [get_weather]
```

Or list it in `local_tools` to make it available (but still subject to retrieval):

```yaml
local_tools: [get_weather]
```

---

## Extra Tool Directories (`TOOL_DIRS`)

If you keep tools outside the `tools/` directory (e.g., in a separate repo), point `TOOL_DIRS` to those directories:

```bash
# .env
TOOL_DIRS=/home/you/my-tools:/home/you/work-tools
```

Colon-separated, absolute or relative paths. Each directory is scanned the same way as `tools/` — every `.py` file (except underscore-prefixed) is imported.

---

## Personal Extensions Repo

If you have your own collection of tools **and** carapaces (expertise bundles), the best approach is to structure them as a lightweight extension directory and use `INTEGRATION_DIRS`.

### Directory Structure

```
my-extensions/              ← your repo (can be anywhere on disk)
└── personal/               ← this becomes an "integration" named "personal"
    ├── tools/
    │   ├── weather.py      ← auto-discovered as a tool
    │   ├── stocks.py
    │   └── _helpers.py     ← skipped (underscore prefix)
    ├── carapaces/
    │   ├── baking/
    │   │   ├── carapace.yaml
    │   │   └── skills/
    │   │       └── sourdough.md
    │   └── gardening/
    │       └── carapace.yaml
    └── skills/
        └── home-automation.md
```

The key: `INTEGRATION_DIRS` points to the **parent** directory. Each subdirectory becomes a discoverable integration.

### Configuration

```bash
# .env
INTEGRATION_DIRS=/home/you/my-extensions
```

That's it. On the next server restart, Spindrel auto-discovers:

- **Tools** from `my-extensions/personal/tools/*.py`
- **Carapaces** from `my-extensions/personal/carapaces/`
- **Skills** from `my-extensions/personal/skills/*.md`

No `setup.py`, `router.py`, or any other boilerplate needed for basic tool + carapace loading.

### Docker Deployment

Mount your extensions directory into the container:

```yaml
# docker-compose.override.yml
services:
  agent-server:
    volumes:
      - /home/you/my-extensions:/app/ext:ro
    environment:
      - INTEGRATION_DIRS=/app/ext
```

The `:ro` (read-only) mount is optional but recommended — the server only reads from extension directories.

### Multiple Extension Directories

Colon-separate multiple paths:

```bash
INTEGRATION_DIRS=/home/you/my-extensions:/home/you/work-extensions
```

Each path is scanned for subdirectories containing `tools/`, `carapaces/`, or `skills/`.

### Using Your Carapaces

Once loaded, your carapaces work like any other. Assign them to bots:

```yaml
# bots/assistant.yaml
carapaces: [personal/baking, personal/gardening]
```

The carapace ID for external extensions follows the pattern `{parent_dir_name}/{integration_name}/{carapace_name}`.

> **Tip:** Check **Admin > Carapaces** in the UI to see all discovered carapaces and their IDs.

---

## Full Integration (Advanced)

If your extension needs more than tools and carapaces — webhooks, background processes, dispatchers, or a settings page — create a full integration. See the [Creating Integrations](../integrations/index.md) guide.

The short version: add any of these optional files to your extension directory:

| File | What it adds |
|------|-------------|
| `setup.py` | Env var declarations, sidebar section, dashboard modules |
| `router.py` | HTTP endpoints (webhooks, config API) |
| `dispatcher.py` | Result delivery to external services |
| `hooks.py` | Lifecycle event handlers |
| `process.py` | Background process (auto-started) |

---

## Tool Registration Reference

### Schema Format

The `@register` decorator takes an OpenAI function calling schema:

```python
@register({
    "type": "function",
    "function": {
        "name": "tool_name",           # unique name, snake_case
        "description": "What this tool does. Be specific — this is used for tool retrieval.",
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "What this parameter is for",
                },
                "param2": {
                    "type": "integer",
                    "description": "Optional numeric param",
                },
            },
            "required": ["param1"],    # which params are required
        },
    },
})
async def tool_name(param1: str, param2: int = 10) -> str:
    return json.dumps({"result": "ok"})
```

### Import for External Tools

If your tool lives outside the agent-server repo (in `TOOL_DIRS` or `INTEGRATION_DIRS`), you can still import from `app.tools.registry`:

```python
from app.tools.registry import register
```

This works because the server adds the project root to `sys.path` before importing tools. If you want your tools to be testable independently (without the server running), use the integration shim pattern:

```python
# Minimal drop-in for standalone development
try:
    from app.tools.registry import register
except ImportError:
    def register(schema, *, source_dir=None):
        def decorator(func):
            func._tool_schema = schema
            return func
        return decorator
```

### Common Patterns

**HTTP API wrapper:**

```python
@register({...})
async def my_api_tool(query: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.example.com/search", params={"q": query})
        resp.raise_for_status()
        return json.dumps(resp.json())
```

**File operation:**

```python
@register({...})
async def read_csv_stats(file_path: str) -> str:
    import csv
    from pathlib import Path
    p = Path(file_path)
    if not p.exists():
        return json.dumps({"error": f"File not found: {file_path}"})
    with open(p) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return json.dumps({"row_count": len(rows), "columns": reader.fieldnames})
```

**Tool with env var dependency:**

```python
_TOKEN = os.getenv("MY_SERVICE_TOKEN", "")

@register({...})
async def my_service_action(action: str) -> str:
    if not _TOKEN:
        return json.dumps({"error": "MY_SERVICE_TOKEN is not configured. Set it in .env."})
    # ... use _TOKEN ...
```
