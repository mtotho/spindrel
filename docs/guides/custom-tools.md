# Custom Tools & Extensions

This guide covers creating your own tools, managing a personal extensions repo, and loading external capabilities and tools into Spindrel.

---

## Quick Start: Drop-In Tools

The simplest way to add a tool: create a `.py` file in the `tools/` directory.

```python
# tools/weather.py
"""Current weather via OpenWeatherMap. Requires OPENWEATHERMAP_API_KEY."""

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

This quick-start approach uses `os.getenv()` — simple and works if you set values in `.env`. For UI-configurable settings, see the [Personal Extensions Repo](#personal-extensions-repo) section below which uses `setup.py` + the `_setting()` helper.

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

Colon-separated, absolute or relative paths. Tilde (`~`) is expanded to your home directory. Each directory is scanned the same way as `tools/` — every `.py` file (except underscore-prefixed) is imported.

> **Tip:** If your tools live inside an `INTEGRATION_DIRS` subdirectory, you don't need `TOOL_DIRS` — tools in integration directories are auto-discovered.

---

## Personal Extensions Repo

The recommended way to manage your own tools, capabilities, and skills: create a separate repo and point `INTEGRATION_DIRS` at it. Everything below is a complete, copy-paste-ready example.

### 1. Create the directory structure

```
my-spindrel-extensions/
├── .gitignore
└── my-tools/                    ← this becomes an integration named "my-tools"
    ├── setup.py                 ← declares settings (shows up in Admin > Integrations)
    ├── tools/
    │   └── weather.py           ← auto-discovered tool
    ├── carapaces/
    │   └── home-assistant/
    │       ├── carapace.yaml    ← expertise bundle
    │       └── skills/
    │           └── smart-home.md
    └── skills/
        └── cooking-tips.md      ← standalone skill
```

`INTEGRATION_DIRS` points to the **parent** directory (`my-spindrel-extensions/`). Each subdirectory inside it becomes a discoverable integration.

### 2. Create every file

**`.gitignore`**

```gitignore
__pycache__/
*.pyc
.env
```

**`my-tools/tools/weather.py`** — A complete, working tool. Uses `os.getenv()` to read the API key.

```python
"""Current weather via OpenWeatherMap."""

import json
import logging

import httpx

from app.tools.registry import register, get_settings

logger = logging.getLogger(__name__)

setting = get_settings()  # auto-detects integration, reads DB then .env
_BASE_URL = "https://api.openweathermap.org/data/2.5"


@register({
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "Get current weather conditions for a city. Returns temperature, "
            "conditions, humidity, wind speed, and feels-like temperature. "
            "Use for questions about current weather, temperature, or conditions outside."
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
                    "description": "Temperature units: 'imperial' (F), 'metric' (C), or 'standard' (K)",
                    "enum": ["imperial", "metric", "standard"],
                },
            },
            "required": ["city"],
        },
    },
})
async def get_weather(city: str, units: str = "imperial") -> str:
    api_key = setting("OPENWEATHERMAP_API_KEY")
    if not api_key:
        return json.dumps({"error": "OPENWEATHERMAP_API_KEY is not configured. Add it to .env or set it in Admin > Integrations."})

    unit_label = {"imperial": "°F", "metric": "°C", "standard": "K"}.get(units, "°F")
    speed_label = "mph" if units == "imperial" else "m/s"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE_URL}/weather",
                params={"q": city, "appid": api_key, "units": units},
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

**`my-tools/carapaces/home-assistant/carapace.yaml`** — A capability bundle that gives any bot smart-home knowledge.

```yaml
name: Home Assistant
description: Smart home monitoring and control via Home Assistant
system_prompt_fragment: |
  You have expertise in smart home automation. When the user asks about
  lights, thermostats, sensors, or home automation routines, follow the
  Deep Knowledge table.

  ### Deep Knowledge
  | When you need... | Fetch this skill |
  |---|---|
  | Smart-home device control patterns, routines, troubleshooting | `get_skill('smart-home')` |
```

The carapace has no `skills:` field. Skills live in the catalog; bots fetch them via `get_skill('id')`, the first successful fetch auto-enrolls the skill into the bot's working set, and from there it's persistent. Point at skills from the system_prompt_fragment's Deep Knowledge table.

**`my-tools/carapaces/home-assistant/skills/smart-home.md`** — The catalog skill the fragment points at.

```markdown
# Smart Home Automation

## Common Tasks

### Lights
- Turn lights on/off by room name
- Set brightness (0-100%) and color temperature
- Create scenes: "Movie Night", "Morning Routine"

### Climate
- Check current temperature by zone
- Set thermostat target temperature
- Switch between heat/cool/auto modes

### Automations
- Motion-triggered lights with timeout
- Temperature-based HVAC schedules
- Sunrise/sunset triggers for blinds

## Troubleshooting
- Device unavailable: check WiFi, power cycle, re-pair in Zigbee/Z-Wave
- Automation not firing: check conditions, time ranges, entity IDs
```

!!! tip "Shipped Home Assistant capability"
    Spindrel ships a comprehensive `home-assistant` capability with preference learning, routine tracking, device inventory, and daily health checks. Use `carapaces: [home-assistant]` (*`carapaces` is the config key for capabilities*) in your bot YAML — no need to build your own. See the [MCP Servers guide](mcp-servers.md#worked-example-home-assistant) for the full walkthrough.

**`my-tools/skills/cooking-tips.md`** — A standalone skill (not part of a capability).

```markdown
# Cooking Tips

Quick reference for common cooking questions.

## Temperature Guide
- Chicken breast: 165°F / 74°C internal
- Steak medium-rare: 130°F / 54°C internal
- Bread: 190-210°F / 88-99°C internal

## Conversions
- 1 cup = 240ml = 16 tbsp
- 1 tbsp = 15ml = 3 tsp
- 1 oz = 28g
```

### 3. Point Spindrel at it

Add one line to your `.env`:

```bash
INTEGRATION_DIRS=/home/you/my-spindrel-extensions
```

Restart the server. Your extension appears in **Admin > Integrations** as an **EXTERNAL** integration with tools and capabilities badges.

### 4. Configure API keys

Two options — use whichever you prefer.

**Option A: Spindrel's `.env` file (simplest)**

Add the key to Spindrel's main `.env` and restart:

```bash
# .env (in Spindrel's root directory)
OPENWEATHERMAP_API_KEY=your-key-here
```

Tools using `os.getenv()` pick it up automatically. No `setup.py` needed. This is the simplest approach if you're the only user.

**Option B: Admin UI (no file editing)**

Add a `setup.py` to your extension to declare what settings it needs:

```python
# my-tools/setup.py
SETUP = {
    "icon": "Wrench",
    "env_vars": [
        {
            "key": "OPENWEATHERMAP_API_KEY",
            "required": False,
            "description": "API key from openweathermap.org (free tier works)",
            "secret": True,
        },
    ],
}
```

Your extension gets a settings panel in **Admin > Integrations** where you can set API keys from the UI. Secrets are encrypted at rest.

To read UI-configured values from your tool, use `get_settings()` from the registry:

```python
from app.tools.registry import register, get_settings

setting = get_settings()  # auto-detects your integration — no ID needed

@register({...})
async def my_tool() -> str:
    api_key = setting("OPENWEATHERMAP_API_KEY")
    ...
```

`get_settings()` is called at module level and automatically knows which integration the tool belongs to. It checks DB (admin UI values) first, then falls back to `os.environ` (`.env` values). Both configuration methods work simultaneously — DB takes priority.

**Which should I use?** If you're the only user and comfortable editing `.env`, Option A is fine. If you want a settings UI, want secrets encrypted, or are sharing the extension with others, add the `setup.py` (Option B).

### 5. Use it

Assign the capability to a bot:

```yaml
# bots/assistant.yaml
carapaces: [home-assistant]
```

Pin the weather tool if you want it always available:

```yaml
pinned_tools: [get_weather]
```

Or just ask your bot "what's the weather in Chicago?" — tool RAG will find it automatically.

### Docker Deployment

Mount your extensions directory into the container:

```yaml
# docker-compose.override.yml
services:
  agent-server:
    volumes:
      - /home/you/my-spindrel-extensions:/app/ext:ro
    environment:
      - INTEGRATION_DIRS=/app/ext
```

### Multiple Extension Directories

Colon-separate paths to load from multiple locations:

```bash
INTEGRATION_DIRS=/home/you/personal-extensions:/home/you/work-extensions
```

### setup.py Reference

The `SETUP` dict controls what appears in the Admin UI for your extension.

**`env_vars` fields:**

| Field | Type | Description |
|-------|------|-------------|
| `key` | string | Environment variable name |
| `required` | bool | Whether the integration shows as "Not Configured" without it |
| `description` | string | Help text shown in the settings UI |
| `secret` | bool | If `true`, value is masked in the UI and encrypted at rest |

**Other optional `SETUP` fields:** `icon`, `webhook`, `binding`, `sidebar_section`, `dashboard_modules`, `activation`. See [Creating Integrations](../integrations/index.md) for the full manifest reference.

> **Tip:** Check **Admin > Integrations** to see your extension, **Admin > Capabilities** to see discovered capabilities and their IDs.

---

## Full Integration (Advanced)

If your extension needs more than tools, capabilities, and settings — webhooks, background processes, dispatchers, or custom UI pages — create a full integration. See the [Creating Integrations](../integrations/index.md) guide.

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
