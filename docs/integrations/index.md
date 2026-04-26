# Creating an Integration

> **For the canonical contract + responsibility boundaries, see [`docs/guides/integrations.md`](../guides/integrations.md).** That page wins when it disagrees with this one. This page is the authoring walkthrough — step-by-step scaffolding, YAML key detail, and real examples.

This guide explains how to create a new integration — a self-contained module that
connects an external service (GitHub, Slack, webhooks, etc.) to Spindrel without
touching core code.

> **Architecture decisions and design philosophy** → see [Design Philosophy](design.md)

---

## Workspace Integrations

The shared workspace includes an `integrations/` directory that is automatically added
to the discovery path at startup. Bots can write integration code directly to
`/workspace/integrations/` and it will be discovered on the next server restart.

This is the bridge between bot-generated code and the integration system — bots
(especially via Claude Code) can scaffold complete integrations that the server picks
up automatically. No manual `INTEGRATION_DIRS` configuration needed.

```
/workspace/integrations/
├── my_api_client/
│   └── tools/
│       └── api_tool.py     # Custom tool — auto-discovered
├── my_webhook/
│   ├── router.py            # Webhook endpoint
│   ├── integration.yaml     # Metadata + settings declarations
│   └── tools/
│       └── handler.py
```

In Docker, this works automatically — the workspace volume mount covers it.

---

## External Integrations (INTEGRATION_DIRS)

Integrations don't have to live inside the Spindrel repo. Set `INTEGRATION_DIRS` in
`.env` to point to one or more directories containing integration folders:

```bash
# .env
INTEGRATION_DIRS=/home/you/my-integrations
```

Colon-separated for multiple directories. Tilde (`~`) is expanded to your home directory. Each directory is scanned the same way as `integrations/` — any subfolder with a
`router.py`, `tools/*.py`, `skills/*.md`, or `integration.yaml` is discovered
automatically.

**Docker deployment:** mount your external integrations directory into the container and
set `INTEGRATION_DIRS` to the mount point:

```yaml
# docker-compose.override.yml
services:
  agent-server:
    volumes:
      - /home/you/my-integrations:/app/ext-integrations:ro
    environment:
      - INTEGRATION_DIRS=/app/ext-integrations
```

**Self-contained structure:** each external integration should include its own `config.py`
for settings and use `integrations/_register.py` (or a local copy of the stub) for tool
registration. See the "Creating an External Integration" section in [example.md](example.md).

---

## Folder Structure

Each integration lives under `integrations/<name>/`. The auto-discovery system scans
this directory at startup. All files are optional except your integration must have at
least one of `integration.yaml`, `router.py`, or `tools/*.py` to do anything useful.

```
integrations/
├── __init__.py          # auto-discovery (don't edit)
├── sdk.py               # single-import convenience module
├── utils.py             # helpers: ingest_document, inject_message, etc.
└── mygithub/            # your integration folder
    ├── integration.yaml # metadata, settings, events, binding, capabilities
    ├── router.py        # HTTP endpoints → registered at /integrations/mygithub/
    ├── target.py        # typed dispatch target (optional — can be declared in YAML)
    ├── renderer.py      # message delivery via the channel-events bus
    ├── hooks.py         # lifecycle hooks (metadata auto-registered from YAML)
    ├── config.py        # integration-specific settings (DB-backed properties)
    ├── tools/
    │   ├── __init__.py
    │   └── my_tool.py   # agent tools — auto-discovered by the loader
    └── skills/
        └── mygithub.md  # skill documents — synced at startup
```

### What each file does

| File | Auto-loaded? | Purpose |
|---|---|---|
| `integration.yaml` | Yes — seeded to DB on first startup | Metadata, settings, events, binding config, capabilities, process declaration |
| `router.py` | Yes — registered at `/integrations/<name>/` | Receive webhooks, expose config endpoints |
| `target.py` | Yes — registers typed dispatch target | Define where/how to deliver messages (can also be declared in YAML `target:` section) |
| `renderer.py` | Yes — registers with renderer registry | Deliver channel events (messages, streaming, reactions) to the external service |
| `hooks.py` | Yes — registers metadata + lifecycle hooks | Integration metadata (auto-registered from YAML if not provided) + lifecycle event callbacks |
| `config.py` | No (imported by your code) | Integration-specific settings with DB-backed `get_value()` accessors |
| `tools/*.py` | Yes — auto-discovered | Agent tools (underscore-prefixed files skipped) |
| `skills/*.md` | Yes — synced at startup | Skill documents ingested into the skill system |
| `setup.py` | *(no longer loaded)* | Legacy metadata format. All declarations live in `integration.yaml` now. |

---

## Agent Tools

Integration tools live in `integrations/<name>/tools/*.py`. The loader auto-discovers
them at startup — any `*.py` file (except underscore-prefixed) is imported and its
`@register`-decorated functions become available as agent tools.

### Registration

Import `register` from the shim at `integrations/_register.py`:

```python
from integrations.sdk import register_tool as register

@register({
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "Does something useful.",
        "parameters": {"type": "object", "properties": {}},
    },
})
async def my_tool() -> str:
    return '{"result": "ok"}'
```

When running inside Spindrel, this resolves to the real registry. When
developing an integration **outside** the server (standalone repo, tests, etc.),
it falls back to a stub that attaches the schema to the function — no server
dependency needed.

**If you're building an external integration**, you only need this stub:

```python
# Minimal drop-in replacement for integrations/_register.py
def register(schema, *, source_dir=None):
    def decorator(func):
        func._tool_schema = schema
        return func
    return decorator
```

To deploy: drop your integration folder into `integrations/` and add your tool
directory to `TOOL_DIRS` (or rely on the `integrations/*/tools/` auto-discovery).

### Config

Integration-specific settings go in your own `config.py` — **not** in `app/config.py`:

```python
# integrations/mygithub/config.py
from pydantic_settings import BaseSettings

class MyConfig(BaseSettings):
    MYGITHUB_TOKEN: str = ""
    MYGITHUB_WEBHOOK_SECRET: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = MyConfig()
```

Then import from your tools: `from integrations.mygithub.config import settings`.

### Shared helpers

Use underscore-prefixed files for shared code within your integration (the loader
skips them): `integrations/<name>/tools/_helpers.py`.

---

## Quickstart

### 1. Create the folder and manifest

```bash
mkdir integrations/mygithub
```

Create `integrations/mygithub/integration.yaml`:

```yaml
id: mygithub
name: GitHub Integration
icon: Code2
description: GitHub repository management.
version: "1.0"

settings:
  - key: MYGITHUB_TOKEN
    type: string
    label: "Personal access token"
    required: true
    secret: true
  - key: MYGITHUB_WEBHOOK_SECRET
    type: string
    label: "Webhook signature secret"
    secret: true

events:
  - { type: pull_request, label: Pull requests, category: webhook }
  - { type: push, label: Pushes, category: webhook }

webhook:
  path: /integrations/mygithub/webhook
  description: "Receives push and PR events from GitHub"

binding:
  client_id_prefix: "mygithub:"
  client_id_placeholder: "mygithub:owner/repo"
  client_id_description: "GitHub owner/repo"

activation:
  tools: [github_get_issue, github_create_comment]
  description: "GitHub repository management"
```

See the [integration.yaml Reference](#integrationyaml-reference) section below for all
available keys.

### 2. Add `__init__.py`

```python
# integrations/mygithub/__init__.py
# (can be empty — metadata comes from integration.yaml)
```

### 3. Add a router (`router.py`)

The router is a standard FastAPI `APIRouter`. It's registered at `/integrations/<name>/`
automatically — no changes to `app/main.py` needed.

```python
from fastapi import APIRouter, Request
from integrations import utils

router = APIRouter()

@router.post("/webhook")
async def github_webhook(request: Request):
    data = await request.json()
    event = request.headers.get("X-GitHub-Event")

    if event == "pull_request":
        pr = data["pull_request"]

        # 1. Get or create a session for this repo
        from app.db.engine import async_session
        async with async_session() as db:
            session_id = await utils.get_or_create_session(
                client_id=f"github:{data['repository']['full_name']}",
                bot_id="code_review_bot",
                db=db,
            )

            # 2. Inject a message — agent runs and result is dispatched
            result = await utils.inject_message(
                session_id=session_id,
                content=f"PR #{pr['number']} opened: {pr['title']}\n{pr['html_url']}",
                source="github",
                run_agent=True,
                notify=True,
                db=db,
            )

    return {"ok": True}
```

### 4. Add a target and renderer (message delivery)

If your integration delivers messages to an external service (e.g. a chat platform),
you need a **target** (where to send) and a **renderer** (how to send).

**Targets** can be declared in `integration.yaml` (preferred for simple cases) or in
`target.py` (for complex validation logic):

```yaml
# integration.yaml — declarative target
target:
  type: mygithub
  fields:
    owner: string
    repo: string
    issue_number: int
    token: string
```

This auto-generates a frozen dataclass `MygithubTarget` and registers it. For custom
logic, create `target.py` instead:

```python
# target.py — manual target with custom methods
from integrations.sdk import BaseTarget, target_registry

class MyGitHubTarget(BaseTarget, dispatch_type="mygithub"):
    owner: str
    repo: str
    issue_number: int
    token: str

target_registry.register(MyGitHubTarget)
```

**Renderers** handle the actual delivery. Create `renderer.py`. For most integrations,
use `SimpleRenderer` — it encodes the delivery contract automatically so you only need
to implement `send_text()`:

```python
from integrations.sdk import SimpleRenderer, Capability, renderer_registry

class MyGitHubRenderer(SimpleRenderer):
    integration_id = "mygithub"
    capabilities = frozenset({Capability.TEXT})

    async def send_text(self, target, text: str) -> bool:
        resp = await _post_comment(
            target.owner, target.repo, target.issue_number,
            text, target.token,
        )
        return resp.status_code == 200

renderer_registry.register(MyGitHubRenderer())
```

`SimpleRenderer` handles the delivery contract for you:

- **`NEW_MESSAGE`** (durable, via outbox) calls your `send_text()` for user-visible messages.
- **`TURN_ENDED`** (ephemeral, via bus) is automatically skipped — non-streaming renderers have
  no placeholder to finalize.
- **Echo prevention**: own-origin user messages are filtered automatically.
- **Internal roles** (`tool`, `system`) are filtered automatically.

For streaming integrations that need progressive UX (thinking placeholders, live token
updates), use the raw `ChannelRenderer` Protocol instead — see
[Which base class?](design.md#which-base-class) for guidance.

> **Important: delivery path contract.** `NEW_MESSAGE` is the sole durable delivery path —
> it flows through the outbox with retry guarantees. Streaming kinds (`TURN_STARTED`,
> `TURN_STREAM_TOKEN`, `TURN_ENDED`) flow via the ephemeral bus and are best-effort only.
> Renderers that support streaming can use them for progressive UX (e.g. updating a
> "thinking..." placeholder), but must never rely on them for final message delivery.
> See [Delivery Contract](design.md#delivery-contract-streaming-vs-durable) for details.

**Capabilities** declared in `integration.yaml` override the renderer's `CAPABILITIES`
ClassVar — use YAML to adjust without editing Python:

```yaml
# integration.yaml
capabilities:
  - text
  - rich_text
  - mentions
```

Skip this step if your integration is tool-only (no message delivery) or poll-only
(no outbound messages).

### 5. Add hooks (`hooks.py`)

Hooks let your integration register metadata (client ID prefix, user attribution,
display name resolution) and subscribe to agent lifecycle events — without touching
core code.

**Integration metadata** — register at import time:

```python
from app.agent.hooks import IntegrationMeta, register_integration

def _user_attribution(user) -> dict:
    """Return payload fields for user identity (username, icon)."""
    attrs = {}
    if user.display_name:
        attrs["username"] = user.display_name
    cfg = (user.integration_config or {}).get("mygithub", {})
    if cfg.get("avatar_url"):
        attrs["icon_url"] = cfg["avatar_url"]
    return attrs

register_integration(IntegrationMeta(
    integration_type="mygithub",
    client_id_prefix="mygithub:",
    user_attribution=_user_attribution,
))
```

This registers your integration's client ID prefix (used by `is_integration_client_id()`),
user attribution (used when mirroring messages), and optionally a `resolve_display_names`
callback for the admin UI channel list.

**Lifecycle hooks** — subscribe to agent events:

```python
from app.agent.hooks import HookContext, register_hook

async def _on_after_tool_call(ctx: HookContext, **kwargs) -> None:
    tool = ctx.extra.get("tool_name", "")
    ms = ctx.extra.get("duration_ms", 0)
    print(f"Tool {tool} took {ms}ms for bot {ctx.bot_id}")

register_hook("after_tool_call", _on_after_tool_call)
```

Available lifecycle events:

| Event | Mode | Fired when | `ctx.extra` keys |
|-------|------|-----------|-----------------|
| `before_context_assembly` | fire-and-forget | Before context is built for an LLM call | `user_message` |
| `before_llm_call` | fire-and-forget | Before each LLM API call | `model`, `message_count`, `tools_count`, `provider_id`, `iteration` |
| `after_llm_call` | fire-and-forget | After LLM API call completes | `model`, `duration_ms`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `tool_calls_count`, `fallback_used`, `fallback_model`, `iteration`, `provider_id` |
| `before_tool_execution` | fire-and-forget | After auth/policy checks pass, before tool runs | `tool_name`, `tool_type`, `args`, `iteration` |
| `after_tool_call` | fire-and-forget | After each tool execution | `tool_name`, `tool_args`, `duration_ms` |
| `after_response` | fire-and-forget | After agent returns final response | `response_length`, `tool_calls_made` |
| `before_transcription` | **override-capable** | Before audio is transcribed (STT) | `audio_format`, `audio_size_bytes`, `source` |

All fire-and-forget hooks are broadcast — errors are logged but never propagate.
Both sync and async callbacks are supported. Hooks receive a `HookContext` with
`bot_id`, `session_id`, `channel_id`, `client_id`, `correlation_id`, and `extra`.

**Override-capable hooks** use `fire_hook_with_override()` — the first callback that
returns a non-`None` value short-circuits the chain. This lets integrations replace
default behavior (e.g. providing custom STT for `before_transcription`):

```python
from app.agent.hooks import register_hook

async def _custom_stt(ctx, **kwargs):
    audio_format = ctx.extra.get("audio_format")
    audio_bytes = ctx.extra.get("audio_size_bytes")
    # Call your custom STT service...
    return "transcribed text"  # or None to fall through to default

register_hook("before_transcription", _custom_stt)
```

**Webhook emission** — all hook events are automatically forwarded to webhook endpoints
configured via **Admin > Developer > Webhooks**. Each endpoint supports event filtering,
HMAC-SHA256 signing, and delivery retry. See the [Webhooks guide](../guides/webhooks.md)
for setup details and signature verification examples.

See `integrations/slack/hooks.py` for a real example: Slack uses `after_tool_call`
to add emoji reactions as tool indicators and log tool calls to an audit channel.

### 6. Add a background process

If your integration needs a long-running process (e.g. a bot framework using socket mode),
declare it in `integration.yaml` (preferred) or `process.py`.

**YAML declaration** (preferred):

```yaml
# integration.yaml
process:
  cmd: ["python", "integrations/mygithub/listener.py"]
  description: "GitHub webhook listener"
  required_env: ["GITHUB_WEBHOOK_SECRET", "GITHUB_TOKEN"]
  watch_paths: ["integrations/mygithub/"]  # optional: auto-restart on file changes
```

**Legacy `process.py`** (still supported):

```python
DESCRIPTION = "GitHub webhook listener"
CMD = ["python", "integrations/mygithub/listener.py"]
REQUIRED_ENV = ["GITHUB_WEBHOOK_SECRET", "GITHUB_TOKEN"]
```

The process is only started if every var in `required_env` / `REQUIRED_ENV` is set.

---

## APIs Available to Integrations

### Option A: Python helpers (`integrations/utils.py`)

Use these inside router handlers (they take an open `AsyncSession`):

```python
from integrations import utils
from app.db.engine import async_session

async with async_session() as db:
    # Ingest + embed a document (searchable by agents via RAG)
    doc_id = await utils.ingest_document(
        integration_id="mygithub",
        title="PR #42: Add dark mode",
        content="...",
        session_id=None,           # optional: scope to a session
        metadata={"pr_number": 42},
        db=db,
    )

    # Semantic search across ingested documents
    docs = await utils.search_documents(
        q="dark mode css changes",
        integration_id="mygithub",
        limit=5,
        db=db,
    )

    # Get or create a persistent session for a user/channel/resource
    session_id = await utils.get_or_create_session(
        client_id="github:owner/repo",   # unique identifier for this integration entity
        bot_id="my_bot",
        dispatch_config={               # optional: where to deliver results
            "type": "slack",
            "channel_id": "C12345",
            "token": "xoxb-...",
        },
        db=db,
    )

    # Inject a message into a session
    result = await utils.inject_message(
        session_id=session_id,
        content="New PR from alice: Add dark mode",
        source="github",
        run_agent=True,    # True → runs agent, creates a task, returns task_id
        notify=True,       # True → fans out result to dispatch_config target
        execution_config={                     # optional: per-event agent config
            "system_preamble": "Review this PR...",
            "skills": ["integrations/github/github"],
            "tools": ["github_get_pr"],
        },
        db=db,
    )
    # result = {"message_id": "uuid", "session_id": "uuid", "task_id": "uuid-or-null"}
```

### Option B: Public REST API (`/api/v1/`)

Use this from external processes (your integration's background process, tests, etc.).
All endpoints require `Authorization: Bearer <API_KEY>`.

#### Documents

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/documents` | Ingest + embed a document |
| `GET` | `/api/v1/documents/search?q=...` | Semantic search |
| `GET` | `/api/v1/documents/{id}` | Fetch a document |
| `DELETE` | `/api/v1/documents/{id}` | Delete a document |

```json
// POST /api/v1/documents
{
  "title": "PR #42: Add dark mode",
  "content": "...",
  "integration_id": "mygithub",
  "session_id": null,
  "metadata": {"pr_number": 42}
}
```

```
// GET /api/v1/documents/search
?q=dark+mode&integration_id=mygithub&limit=5
```

#### Sessions

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/sessions` | Create or get a session |
| `POST` | `/api/v1/sessions/{id}/messages` | Inject a message |
| `GET` | `/api/v1/sessions/{id}/messages` | List messages |

```json
// POST /api/v1/sessions
{
  "bot_id": "my_bot",
  "client_id": "github:owner/repo",
  "dispatch_config": {
    "type": "slack",
    "channel_id": "C12345",
    "token": "xoxb-..."
  }
}
// → {"session_id": "uuid"}
```

```json
// POST /api/v1/sessions/{id}/messages
{
  "content": "New PR from alice: Add dark mode",
  "source": "github",
  "run_agent": true,
  "notify": true
}
// → {"message_id": "uuid", "session_id": "uuid", "task_id": "uuid-or-null"}
```

#### Tasks

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/tasks/{id}` | Poll a task's status and result |

Poll this after `run_agent=true` returns a `task_id`. Status: `pending`, `running`, `complete`, `failed`.

---

## Webhook Prompt Injection (execution_config)

When a webhook fires, the bot often needs event-specific instructions, skills, and tools
that aren't permanently assigned to it. Instead of bloating the bot's config with tools for
every integration it *might* receive webhooks from, integrations inject them per-event via
`execution_config`.

### How it works

Pass `execution_config` to `utils.inject_message()` when `run_agent=True`. It's stored on
the `Task` and read by `run_task()` before calling the agent:

```python
result = await utils.inject_message(
    session_id, content, source="myintegration",
    run_agent=True,
    execution_config={
        "system_preamble": "You are responding to a detection event...",
        "skills": ["integrations/frigate/frigate"],
        "tools": ["frigate_event_snapshot"],
    },
    db=db,
)
```

### Fields

| Field | Type | Effect |
|-------|------|--------|
| `system_preamble` | `str` | Injected as a system message before the agent runs. Use for event-specific instructions. |
| `skills` | `list[str]` | Skill IDs (e.g. `"integrations/github/github"`) — their full content is fetched from the DB and injected into context. The bot does NOT need these skills assigned. |
| `tools` | `list[str]` | Tool names (e.g. `"github_get_pr"`) — their schemas are added to the LLM's tool list for this request only. The bot does NOT need these tools in its config. |
| `model_override` | `str` | Override the bot's model for this task (also supported via `callback_config`). |

All fields are optional. Everything is per-task and one-shot — the bot's permanent config
is not affected.

### How skills and tools are resolved

- **Skills** — looked up by ID in the `documents` table via `fetch_skill_chunks_by_id()`.
  Any skill that has been synced from a `.md` file (including integration skills like
  `integrations/github/skills/github.md`) is available regardless of bot assignment.
  The skill ID is the path-based key: `integrations/<name>/<stem>`.

- **Tools** — looked up by name in the global tool registry via `get_local_tool_schemas()`.
  Any registered tool (from `tools/`, `app/tools/local/`, or `integrations/*/tools/`) is
  available. They're passed as `injected_tools` to `run()`, which merges them into the
  LLM's tool list via the `current_injected_tools` ContextVar.

- **Ephemeral skills merge** — if the user's message also contains `@skill:name` tags,
  the tagged skills are merged with execution_config skills (not replaced). Deduplication
  is automatic.

### Built-in webhook prompts

The GitHub and Frigate integrations ship with `_build_execution_config()` functions that
return event-specific preambles, skills, and tools:

**GitHub** (`integrations/github/router.py`):

| Event | Preamble | Tools | Skill |
|-------|----------|-------|-------|
| `pull_request` (opened) | Review code, provide feedback | `github_get_pr` | `integrations/github/github` |
| `issues` (opened) | Triage, suggest solutions | — | `integrations/github/github` |
| `issue_comment` | Read context, respond | — | `integrations/github/github` |
| `pull_request_review` (changes_requested) | Address concerns | `github_get_pr` | `integrations/github/github` |
| `pull_request_review_comment` | Focus on code discussed | `github_get_pr` | `integrations/github/github` |

**Frigate** (`integrations/frigate/router.py`):

| Event | Preamble | Tools | Skill |
|-------|----------|-------|-------|
| Detection (new) | Camera/label/score context, view snapshot | `frigate_event_snapshot` | `integrations/frigate/frigate` |

---

## integration.yaml Reference

`integration.yaml` is the preferred way to declare integration metadata. It is seeded
to the database on first startup; after that, the DB is the source of truth (editable
via the admin UI). The server reports drift if the file changes after seeding.

### Full key reference

```yaml
# Required
id: mygithub                    # unique integration identifier
name: My GitHub                 # display name
version: "1.0"                  # semver string

# Optional metadata
icon: Code2                     # lucide-react icon name (default: Plug)
description: "Short description shown in admin UI"

# Settings — rendered as a form in Admin > Integrations > [name]
settings:
  - key: MY_TOKEN               # env var name
    type: string                # string | number | boolean
    label: "Human-readable label"
    required: true              # default: false
    secret: true                # mask value in UI (default: false)
    default: ""                 # default value if not set
    description: "Optional longer help text"

# Events — what this integration can emit (used by task trigger UI)
events:
  - type: pull_request          # event type identifier
    label: Pull requests        # human-readable label
    description: "PR opened, closed, merged"  # optional tooltip
    category: webhook           # webhook | message | poll | device

# Webhook — displayed in admin UI for users to configure in external services
webhook:
  path: /integrations/mygithub/webhook
  description: "Receives events from GitHub"

# Binding — how channels are linked to this integration
binding:
  client_id_prefix: "mygithub:"
  client_id_placeholder: "mygithub:owner/repo"
  client_id_description: "GitHub owner/repo"
  display_name_placeholder: "octocat/hello-world"
  suggestions_endpoint: "/integrations/mygithub/binding-suggestions"
  config_fields:
    - key: event_filter
      type: multiselect
      label: Event Filter
      description: "Which events to process (empty = all)"
      # options auto-derived from top-level events: section

# Target — typed dispatch target (alternative to target.py)
target:
  type: mygithub
  fields:
    owner: string
    repo: string
    issue_number: int
    token: string
    thread_id: string?          # ? suffix = optional field
    reply: bool = false         # default values supported

# Capabilities — what the renderer supports (overrides renderer ClassVar)
capabilities:
  - text
  - rich_text
  - threading
  - reactions
  - attachments
  - streaming_edit
  - approval_buttons
  # ... see app/domain/capability.py for full list

# Activation — what gets activated when this integration is enabled on a bot
activation:
  tools: [github_get_issue]     # tool names exposed by activation
  requires_workspace: false
  description: "GitHub repository management"

# Provides — what modules this integration supplies (auto-detected if omitted)
provides:
  - target
  - renderer
  - router
  - hooks
  - tools
  - skills

# Process — background process declaration (alternative to process.py)
process:
  cmd: ["python", "integrations/mygithub/listener.py"]
  description: "GitHub webhook listener"
  required_env: ["MY_TOKEN"]
  watch_paths: ["integrations/mygithub/"]

# API permissions — scopes required for the integration's router
api_permissions:
  - chat
  - bots:read
  - channels:read

# Sidebar navigation section
sidebar_section:
  id: my-dashboard
  title: MY DASHBOARD
  icon: LayoutDashboard
  items:
    - { label: Overview, href: /my-dashboard, icon: LayoutDashboard }

# Dashboard modules
dashboard_modules:
  - { id: analytics, label: Analytics, icon: BarChart3, description: "Usage analytics" }
```

All keys are optional except `id`. See `integrations/github/integration.yaml` and
`integrations/slack/integration.yaml` for real-world examples.

---

## Sidecar Docker Stacks

Some integrations ship their own containers — SearXNG for `web_search`, Whisper + Piper
for `wyoming`, etc. Spindrel manages these stacks for you (start on enable,
stop on disable, logs + status in the admin UI) but the main `docker-compose.yml`
stays completely ignorant of them. Integrations can be added at any time — including
by end users dropping a folder into `INTEGRATION_DIRS` — and the agent still reaches
them by hostname.

### The contract

Two pieces:

**1. `integration.yaml` declares the stack:**

```yaml
docker_compose:
  file: docker-compose.yml
  # Project name is interpolated with SPINDREL_INSTANCE_ID so multiple
  # Spindrel instances on one Docker daemon (prod + e2e) don't collide.
  project_name: "spindrel-${SPINDREL_INSTANCE_ID}-web-search"
  enabled_setting: WEB_SEARCH_CONTAINERS
  config_files: [config/searxng/settings.yml]  # bind-mounted read-only
  description: "SearXNG + Playwright for private web search"
```

**2. Your `docker-compose.yml` attaches each service to the agent's network as
an *external* network, with an instance-scoped alias:**

```yaml
name: "spindrel-${SPINDREL_INSTANCE_ID:-default}-web-search"

services:
  searxng:
    image: searxng/searxng
    networks:
      agent_net:
        aliases:
          - "searxng-${SPINDREL_INSTANCE_ID:-default}"
    restart: unless-stopped

networks:
  agent_net:
    external: true
    name: "${AGENT_NETWORK_NAME:-agent-server_default}"
```

That's it. At runtime, your integration code reaches the sidecar by its alias:

```python
SEARXNG_URL = f"http://searxng-{SPINDREL_INSTANCE_ID}:8080"
```

### Why declarative, not imperative

The agent passes `SPINDREL_INSTANCE_ID` and `AGENT_NETWORK_NAME` as env to every
`docker compose` subprocess it invokes. Compose resolves the `${VAR}` references
inside your YAML on every `up`, `restart`, and recreate. That means the network
attachment and alias survive **every** lifecycle event: agent-initiated start,
`docker restart`, daemon reboot, crash + `restart: unless-stopped` auto-recovery.

Don't hand-call `docker network connect` from your integration — it looks the same
at first boot but is lost the moment Docker re-creates the container, and Spindrel
won't know to re-bridge because your stack is already "running".

### What the main compose file needs to expose

Nothing integration-specific. Your integration relies on Spindrel's default
network being named `{COMPOSE_PROJECT_NAME}_default` (standard Docker Compose
behaviour) and that name propagating into `AGENT_NETWORK_NAME` (auto-detected from
the container's own network attachments — see `app/config.py::_default_agent_network`).
Users who customize their deployment only need to set `AGENT_NETWORK_NAME` in their
Spindrel env if auto-detection fails.

---

## Polling Patterns

For integrations that poll an external service (no inbound webhooks), the recommended
pattern is a background process that calls Spindrel's REST API.

**Example: Frigate MQTT listener** (`integrations/frigate/mqtt_listener.py`)

The Frigate integration runs an MQTT listener as a sidecar process that fans events out into Spindrel via HTTP:

1. Declare the process in `integration.yaml`:
   ```yaml
   process:
     cmd: ["python", "integrations/frigate/mqtt_listener.py"]
     description: "Frigate MQTT event listener"
     required_env: ["FRIGATE_MQTT_BROKER"]
   ```

2. The listener subscribes to MQTT topics, then calls:
   ```python
   POST /integrations/frigate/webhook
   {"camera": "front-door", "label": "person", "score": 0.87, ...}
   ```

3. Emit events for task triggers:
   ```python
   from integrations.sdk import emit_integration_event
   emit_integration_event("frigate", "object_detected", {"camera": "front-door", "label": "person"})
   ```

This pattern provides process isolation (listener crash doesn't affect the server),
works with external integrations (no `app/` imports needed in the sidecar), and
scales naturally (run multiple listeners for different sources).

**Cooldowns**: `emit_integration_event` has per-category defaults to prevent spam:
- `webhook`: 0s (every event fires)
- `message`: 300s (5-minute cooldown per source)
- `poll`: 60s (1-minute cooldown)
- `device`: 30s

Override via `cooldown=0` parameter if you need every event.

---

## Manifest Field Detail

The reference at [integration.yaml Reference](#integrationyaml-reference) above shows the canonical shape. This section adds field-level detail for the entries with non-trivial structure (`settings`, `webhook`, `sidebar_section`, `dashboard_modules`, `tool_widgets`, `activation`).

> **Note:** the legacy `setup.py` / `SETUP` dict format is no longer loaded. Anything previously declared there now lives in `integration.yaml` under the equivalent key.

### `settings` — UI-configurable env vars

Declare the env vars your integration needs. The admin UI renders a settings form with set/unset status indicators.

```yaml
settings:
  - key: MY_API_TOKEN
    type: string
    label: "API token for the external service"
    required: true
    secret: true
  - key: MY_PORT
    type: number
    label: "Port for the listener"
    required: false
    default: "8080"
```

| Field | Type | Description |
|-------|------|-------------|
| `key` | `str` | Environment variable name |
| `type` | `str` | `string` (default), `number`, `boolean`, `multiselect` |
| `label` | `str` | Human-readable explanation shown in the UI |
| `required` | `bool` | Whether the integration shows as "Not Configured" without it |
| `secret` | `bool` | Mask value in UI and encrypt at rest (optional, default false) |
| `default` | `str` | Default value if not set (optional) |

Values are resolved in order: DB setting → environment variable → default.

### `webhook` — Webhook endpoint

If your integration receives webhooks, declare the endpoint so the admin UI can
display the full URL for users to configure in external services.

```yaml
webhook:
  path: /integrations/myintegration/webhook
  description: "Receives events from the external service"
```

### `sidebar_section` — Sidebar navigation

Integrations can add a navigation section to the main sidebar. The UI fetches
declared sections from `GET /api/v1/admin/integrations/sidebar-sections` and
renders them dynamically.

```yaml
sidebar_section:
  id: my-dashboard                       # unique section ID
  title: MY DASHBOARD                    # sidebar header text
  icon: LayoutDashboard                  # lucide-react icon name
  items:
    - { label: Overview, href: /my-dashboard,          icon: LayoutDashboard }
    - { label: Reports,  href: /my-dashboard/reports,  icon: BarChart3 }
    - { label: Settings, href: /my-dashboard/settings, icon: Settings }
  readiness_endpoint: /api/v1/my-dashboard/readiness   # optional
  readiness_field: overview                            # optional
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | **Required.** Unique section identifier. Used for hide/show toggle. |
| `title` | `str` | Header text shown above the nav items. Defaults to `id.upper()`. |
| `icon` | `str` | [Lucide icon](https://lucide.dev) name for the collapsed sidebar rail. Defaults to `"Plug"`. |
| `items` | `list[dict]` | **Required.** Navigation items with `label`, `href`, and `icon` fields. |
| `readiness_endpoint` | `str` | Optional API path to check feature health status. |
| `readiness_field` | `str` | Optional field name in the readiness response to read. |

Each item in `items`:

| Field | Type | Description |
|-------|------|-------------|
| `label` | `str` | **Required.** Display text in the sidebar. |
| `href` | `str` | **Required.** Route path (e.g. `/my-dashboard/reports`). |
| `icon` | `str` | Lucide icon name. Defaults to `"Plug"`. |

Users can hide sidebar sections via the Zustand-persisted UI store (toggle in the
integration's settings page).

!!! note "Available icons"
    The frontend resolves icon names from a built-in map. Supported names include:
    `LayoutDashboard`, `Columns`, `BookOpen`, `Brain`, `HelpCircle`, `Settings`,
    `Zap`, `Plug`, `Bot`, `Layers`, `FileText`, `Paperclip`, `ClipboardList`,
    `Key`, `Shield`, `ShieldCheck`, `Activity`, `Server`, `Wrench`, `BarChart3`,
    `Users`, `HardDrive`, `Code2`, `Hash`, `Home`, `MessageSquare`, `Container`,
    `Clock`, `Heart`, `Lock`, `Sun`, `Moon`. Unrecognized names fall back to `Plug`.

### `dashboard_modules` — Pluggable dashboard panels

Integrations can register custom modules that appear on the Mission Control
dashboard (or any integration-owned dashboard).

```yaml
dashboard_modules:
  - id: analytics
    label: Analytics
    icon: BarChart3
    description: "Usage analytics and trends"
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique module identifier |
| `label` | `str` | Display name |
| `icon` | `str` | Lucide icon name |
| `description` | `str` | Short description shown on the dashboard card |

Modules are data-driven — integrations serve structured JSON from their router
endpoints, and the frontend renders it generically.

### `tool_widgets` — Interactive tool result widgets

Integrations can declare widget templates that transform tool results into
interactive component UIs rendered inline in chat and in the channel side-panel
as pinned widgets. When a tool returns JSON, the template engine matches the
tool name, merges per-pin config, substitutes `{{...}}` expressions, and
produces a rich component envelope that re-renders on refresh / user action.

```yaml
tool_widgets:
  MyToolName:
    content_type: application/vnd.spindrel.components+json
    display: inline
    display_label: "{{entity_name}}"     # Header label on pinned widgets
    default_config:                       # Default per-pin config
      show_details: false
    state_poll:                           # Optional: re-fetch on pin mount / timer
      tool: MyToolName
      args:
        entity: "{{display_label}}"       # {{widget_meta.*}} substitution
        verbose: "{{widget_config.show_details}}"# {{widget_config.*}} substitution from pin
      refresh_interval_seconds: 3600      # Auto-refresh interval (UI timer)
      template: *shared                   # Re-use the main template via YAML anchor
    template:
      v: 1
      components:
        - type: status
          text: "Done"
          color: success
        - type: toggle
          label: "{{entity_name}}"
          on_label: "On"
          off_label: "Off"
          value: true
          action:
            dispatch: tool
            tool: MyInverseTool
            args: { name: "{{data.result_field}}" }
            optimistic: true
        # Subtle toggle — almost invisible until the pinned card is hovered
        - type: button
          label: "Show details"
          subtle: true
          when: "{{widget_config.show_details | not}}"
          action:
            dispatch: widget_config        # Patches the pin's config + refreshes
            config: { show_details: true }
        - type: tiles                      # Responsive fit-as-many-per-row grid
          min_width: 84
          when: "{{data.items | not_empty}}"
          items:
            each: "{{data.items}}"
            template: { label: "{{_.date}}", value: "{{_.value}}", caption: "{{_.note}}" }
```

**Top-level template fields:**

| Field | Type | Description |
|-------|------|-------------|
| `content_type` | `str` | Output MIME type. Use `application/vnd.spindrel.components+json` for interactive widgets. |
| `display` | `"inline" \| "badge" \| "panel"` | `"inline"` standalone card under the message. `"badge"` inside ToolBadges. |
| `display_label` | `str` | Template expression resolved against the tool result. Carried on the envelope, used as the pinned widget's header text and passed back to `state_poll.args` as `{{display_label}}` on refresh. |
| `default_config` | `object` | Default per-pin config. Shallow-merged under the pin's stored `widget_config` at render time and exposed as `{{widget_config.*}}` (`{{config.*}}` remains a compatibility alias). |
| `state_poll` | `object` | Declares a tool to re-call on refresh / timer tick. See below. |
| `transform` | `str` | `"module.path:function"` post-substitution Python hook that rewrites the components list. |
| `template` | `object` | Component body with `v: 1` schema version and `components` array. |

**Component primitives:** `text`, `heading`, `status`, `properties`, `table`,
`tiles`, `toggle`, `button`, `select`, `input`, `slider`, `form`, `section`,
`divider`, `code`, `image`, `links`. Unknown types render as muted JSON for
forward compatibility.

- **`tiles`**: responsive grid (`grid-template-columns: repeat(auto-fill, minmax(min_width, 1fr))`). Fields: `items` (`[{label, value, caption}]`) or `each: "{{array}}"` + per-item `template`, `min_width` (px, default 84), `gap` (px, default 6).
- **`button`**: `{label, action, variant?, disabled?, subtle?}`. `subtle: true` renders opacity-25 until the enclosing `group` element (e.g. a pinned widget card) is hovered — useful for progressive-disclosure config toggles.

**Interactive components** carry a `WidgetAction`. Three dispatch modes:

| `dispatch` | Use for | Required fields |
|-----------|---------|-----------------|
| `"tool"` | Call an MCP or local tool, re-render via widget template. | `tool`, `args`, `value_key?`, `optimistic?` |
| `"api"` | Proxy to an allowlisted internal REST endpoint. | `endpoint`, `method`, (`args` → body) |
| `"widget_config"` | Shallow-merge a config patch into the enclosing pin's stored config and return a refreshed envelope. | `config` (the patch). `pin_id` is auto-injected by the client. |

All actions POST to `/api/v1/widget-actions`. When the response carries an
envelope, the card replaces its body — enabling stateful cycling (toggle →
inverse tool → refreshed card) and config-driven re-render (hover → subtle
button → widget_config patch → state_poll re-call → envelope with new data).

**State polling (`state_poll`):**

| Field | Type | Description |
|-------|------|-------------|
| `tool` | `str` | Tool to re-call on refresh. Usually the widget's own tool, or a "get current state" read-only tool. |
| `args` | `object` | Args for the poll tool. Supports `{{display_label}}`, `{{tool_name}}`, `{{widget_config.*}}` substitution from the widget_meta + pin config at call time (`{{config.*}}` remains a compatibility alias). |
| `refresh_interval_seconds` | `int` | Auto-refresh cadence for pinned widgets. Propagates onto the envelope so the UI sets a `setInterval`. |
| `transform` | `str` | Optional `"module:func"` hook called with `(raw_result, widget_meta) → data_dict` when the poll tool returns a shape that differs from the main template's input (e.g. HA `GetLiveContext` filtering to one entity). |
| `template` | `object` | Component body rendered from the (possibly transformed) poll result. Often shared with the main template via a YAML anchor. |

Poll results are cached 30s keyed by `(tool, args_json)` so multiple pinned
widgets for the same tool-and-args deduplicate, while different args (e.g.
different weather locations) don't collide.

**Template expressions** use `{{...}}` syntax over a merged data dict whose
keys are: the tool result JSON + `config` (merged default + pin config) +
`display_label` / `tool_name` (in state_poll args only).

| Expression | Example | Result |
|-----------|---------|--------|
| Key lookup | `{{name}}` | `data["name"]` |
| Dot path | `{{current.temperature}}` | Nested object access |
| Array index | `{{items[0].id}}` | Array + nested access |
| Equality | `{{state == 'on'}}` | Boolean comparison |
| Pipe transform | `{{a \| pluck: name}}` | Extract field from each item |
| Chained pipes | `{{data.success \| pluck: name \| join: , }}` | Pluck then join |
| Single-expression preserves type | `{{flag}}` → `true` (bool) | Fast path keeps non-string types |
| Mixed string coerces | `"{{a}} / {{b}}"` → `"1 / 2"` | Multi-expression → string |

**Pipe transforms:**

| Transform | Use |
|----------|-----|
| `pluck: key` | `[{a:1}, {a:2}]` → `[1, 2]` |
| `join: sep` | `["a","b"]` → `"a, b"` (default sep `", "`) |
| `map: {out: src}` | `[{name:"x", id:"1"}]` → `[{label:"x", value:"1"}]` |
| `where: key=val` | Filter list by field equality |
| `first` | First item of a list |
| `default: X` | Fallback when value is None |
| `in: a,b,c` | Boolean membership test |
| `not_empty` | Boolean truthy test |
| `not` | Boolean inverse — gate "off-state" buttons on a flag |
| `status_color` | Map `"active"/"running"/"complete"/"failed"/…` to a semantic color |
| `count` | Length of a list/dict |

**Component-level features:**

| Feature | Use |
|--------|-----|
| `when: "{{expr}}"` | Conditionally include/exclude a component (uses `_is_truthy` — `False`, `None`, `""`, `"0"`, `"false"` all drop the node). |
| `each: "{{array}}" + template:` | Iterate over an array to produce rows/items. Use `{{_.field}}` to refer to the current item. |

**Per-pin config flow (widget_config dispatch):**

1. Template renders a `button` / `toggle` with `action: {dispatch: widget_config, config: {show_forecast: true}}`.
2. UI POSTs to `/api/v1/widget-actions` with `pin_id` auto-filled.
3. Server shallow-merges the patch into `channel.config.pinned_widgets[*].config` via the shared `apply_widget_config_patch` helper (also exposed as `PATCH /api/v1/channels/{channel_id}/widget-pins/{pin_id}/config`).
4. Server invalidates the state_poll cache for the tool, calls `_do_state_poll` with the new `widget_config`, and returns the refreshed envelope.
5. UI swaps the envelope body. `{{widget_config.*}}` in both the main template and `state_poll.args` now sees the new value — so the toggle's visible state, gated components, and the underlying tool call all update in one round-trip.

**Envelope replacement:** When a widget action returns a component envelope,
WidgetCard / PinnedToolWidget replaces its body and re-renders. Pinned
widgets also auto-refresh on mount, when another widget in the channel
broadcasts a new envelope for the same entity, and on the
`refresh_interval_seconds` timer if set.

See `integrations/openweather/integration.yaml` for the full per-pin config +
tiles + hover-reveal pattern, and `integrations/homeassistant/integration.yaml`
for the shared `state_poll` + code transform + display_label pattern.

### `activation` — Integration activation

Integrations declare an activation manifest that exposes the integration's tools to a channel when the user activates it. There is no separate capability bundle — declared tools become available, and integration-shipped skills enter the normal skill RAG pool. See [Activation & Templates](activation-and-templates.md) for the full guide on activation, workspace template compatibility, and versioning.

---

## Dispatch Targets

Each channel has a `dispatch_config` JSONB field that describes where to deliver messages.
When a renderer receives a `ChannelEvent`, it reads the target from `event.target` — a
typed dataclass built from `dispatch_config`.

Standard target shapes:

```json
// dispatch_type = "slack"
{"channel_id": "C123", "token": "xoxb-...", "thread_ts": "1234.56", "reply_in_thread": true}

// dispatch_type = "webhook"
{"url": "https://myservice.example.com/hook"}

// dispatch_type = "internal"  (injects result back into a session as a user message)
{"session_id": "uuid"}

// dispatch_type = "none"  (result stays in DB; caller polls /api/v1/tasks/{id})
{}
```

For a custom dispatch type, declare a `target:` section in `integration.yaml` or create
a `target.py` (see step 4 above), then create a `renderer.py` to handle delivery.

---

## Example

See [example.md](example.md) for the minimal `integrations/example/` scaffold.

---

## Potential Future Integrations

| Integration | Description | Effort |
|-------------|-------------|--------|
| **Telegram** | Mobile chat access to all bots via Telegram Bot API (polling or webhook mode) | Small |
| **Ntfy** | Push notifications from bots to phone/desktop via [ntfy.sh](https://ntfy.sh) (self-hostable) | Tiny |

---

## What Integration Code Must Not Do

- Import from `app/` directly — use `integrations/sdk.py` for all SDK imports, `integrations/utils.py` for helpers, and keep config in your own `config.py`
- Put integration-specific config in `app/config.py` — create your own `integrations/<name>/config.py`
- Duplicate Slack API call logic — use `integrations/slack/client.py` for messages and `integrations/slack/uploads.py` for file uploads
- Add new columns to core models (`Bot`, `Task`, `Session`) for integration-specific data — use `dispatch_config`, `integration_config` JSONB fields, or add your own table
- Edit `app/main.py` or `app/agent/tasks.py` — integration code stays in `integrations/`
