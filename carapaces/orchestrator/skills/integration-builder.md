---
name: Integration Builder
description: "Creating custom integrations: scaffold→reload flow, directory structure, SETUP manifest, tool writing patterns, and limitations."
---

# Integration Builder Guide

## When to Create What

| You need... | Create a... | Why |
|---|---|---|
| A new function the bot can call | Tool (`tools/*.py`) | Simplest unit. Just `@register` + function. |
| Domain knowledge or behavioral instructions | Skill (`skills/*.md`) | Markdown, auto-synced, modes: pinned/rag/on_demand. |
| A bundle of tools + skills + behavioral instructions | Carapace (`carapaces/*.yaml`) | Composable expertise. Apply to bots or channels. |
| External service webhooks, background process, dispatcher, sidebar nav | Integration | Full integration with router, tools, skills, carapaces. |

**Rule of thumb:** If you need a router (webhook endpoints), a dispatcher (message delivery), or a background process — you need an integration. If you just need a tool or skill, create those directly.

## Prerequisites

The scaffold command writes to the first writable directory in `INTEGRATION_DIRS`. When a shared workspace is configured (the default Docker setup), the workspace integrations directory (`/workspace/integrations/`) is automatically added to `INTEGRATION_DIRS` at startup — no manual config needed.

## Scaffold → Reload Flow

### 1. Scaffold the integration

```
manage_integration(
    action="scaffold",
    integration_id="my_service",
    features=["tools", "skills", "carapaces"]
)
```

This creates the directory with working boilerplate at the workspace integrations path. Valid features: `tools`, `skills`, `carapaces`, `dispatcher`, `hooks`, `process`, `workflows`.

### 2. Edit the generated files

The scaffold creates minimal working files. Edit them:
- `setup.py` — Declare env vars, webhook, python dependencies, sidebar section
- `router.py` — Add your webhook/API endpoints
- `tools/*.py` — Add tools with `@register` decorator
- `skills/*.md` — Write domain knowledge
- `carapaces/*.yaml` — Bundle skills + tools + system prompt fragment

### 3. Hot-reload

```
manage_integration(action="reload")
```

This discovers new integrations, registers routers, loads tools, re-indexes embeddings, and syncs skills/carapaces/workflows. No server restart needed.

### 4. Verify

```
manage_integration(action="list")
```

The new integration should appear in the list.

## Directory Structure

```
my_service/
├── __init__.py              # Package marker (always created)
├── setup.py                 # SETUP manifest (always created)
├── router.py                # FastAPI endpoints (always created)
├── README.md                # Documentation (always created)
├── tools/                   # Optional: bot-callable tools
│   ├── __init__.py
│   └── my_service_tools.py
├── skills/                  # Optional: markdown knowledge files
│   └── my-service-guide.md
├── carapaces/               # Optional: expertise bundles
│   └── my_service.yaml
├── dispatcher.py            # Optional: message delivery to external service
├── hooks.py                 # Optional: lifecycle event handlers
├── process.py               # Optional: background worker
└── workflows/               # Optional: workflow definitions
    └── my_service-example.yaml
```

## setup.py SETUP Manifest

```python
SETUP = {
    "env_vars": [
        {"key": "MY_SERVICE_API_KEY", "required": True, "description": "API key"},
        {"key": "MY_SERVICE_URL", "required": False, "description": "Base URL", "default": "https://api.example.com"},
    ],
    "webhook": {"path": "/integrations/my_service/webhook", "description": "Incoming webhooks"},
    "python_dependencies": [
        {"package": "some-sdk", "import_name": "some_sdk"},
    ],
    "binding": {
        "client_id_prefix": "my_service:",
        "client_id_placeholder": "my_service:channel-name",
    },
    "sidebar_section": {
        "id": "my-service",
        "title": "MY SERVICE",
        "icon": "Plug",
        "items": [
            {"label": "Dashboard", "href": "/my-service", "icon": "LayoutDashboard"},
        ],
    },
    "activation": {
        "carapaces": ["my_service"],
        "requires_workspace": False,
    },
}
```

## Tool Writing Pattern

```python
from app.tools.registry import register, get_settings

# get_settings() auto-detects the integration — reads DB settings then env vars
setting = get_settings()

@register({
    "type": "function",
    "function": {
        "name": "my_tool_name",
        "description": "Clear description of what this tool does and when to use it.",
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "What this param is for"},
            },
            "required": ["param1"],
        },
    },
})
async def my_tool_name(param1: str) -> str:
    api_key = setting("MY_SERVICE_API_KEY")
    # ... implementation ...
    return json.dumps({"result": "..."})
```

**Key points:**
- Tool function name must match the schema `name`
- Always return a JSON string (not a dict)
- Use `get_settings()` at module level to read integration settings
- Async functions preferred; sync also works
- **Sensitive env vars:** For API keys and credentials, create them as secrets via `manage_secret(action="create", name="MY_SERVICE_API_KEY", value="...")`. Tools read them the same way (`setting("MY_SERVICE_API_KEY")` or `os.environ`) — secrets are injected as env vars transparently, but they're encrypted at rest and redacted from output.

## Hot-Reload Limitations

- **New integrations only.** Changed code in existing integrations requires a server restart (Python module caching).
- **Router registration is permanent** for the session — no un-registration without restart.
- **Tools are additive** — new tools are indexed, but removed tools won't be cleaned up until restart.
- **File sync is idempotent** — skills/carapaces/workflows use content hashing, safe to reload repeatedly.

## Path Resolution (Docker)

When running in Docker, workspace paths map differently:
- **Container**: `/workspace/integrations/my_service/`
- **Host**: `~/.agent-workspaces/.shared/{workspace_id}/integrations/my_service/`

The scaffold command creates files at the container path. Use `exec_command` to write/edit files inside the container.
