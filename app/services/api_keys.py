"""Scoped API key management service."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Bot as BotRow, IntegrationSetting, User

# ---------------------------------------------------------------------------
# Scope definitions
# ---------------------------------------------------------------------------

ALL_SCOPES = [
    "admin",
    # Channels (broad)
    "channels:read", "channels:write",
    # Channels (granular)
    "channels.messages:read", "channels.messages:write",
    "channels.config:read", "channels.config:write",
    "channels.heartbeat:read", "channels.heartbeat:write",
    "channels.integrations:read", "channels.integrations:write",
    # Chat
    "chat",
    # Sessions
    "sessions:read", "sessions:write",
    # Bots
    "bots:read", "bots:write", "bots:delete",
    # Tasks
    "tasks:read", "tasks:write",
    # Workspaces (broad)
    "workspaces:read", "workspaces:write",
    "workspaces.files:read", "workspaces.files:write",
    # Documents
    "documents:read", "documents:write",
    # Todos
    "todos:read", "todos:write",
    # Attachments
    "attachments:read",
    "attachments:write",
    # Logs
    "logs:read", "logs:write",
    # Tools
    "tools:read", "tools:execute",
    # Providers
    "providers:read", "providers:write",
    # Users
    "users:read", "users:write",
    # Settings
    "settings:read", "settings:write",
    # Operations
    "operations:read", "operations:write",
    # Usage
    "usage:read", "usage:write",
    # Workflows
    "workflows:read", "workflows:write",
    # LLM
    "llm:completions",
    # API Keys
    "api_keys:read", "api_keys:write",
    # Integrations
    "integrations:read", "integrations:write",
    # MCP Servers
    "mcp_servers:read", "mcp_servers:write",
    # Skills
    "skills:read", "skills:write",
    # Secrets
    "secrets:read", "secrets:write",
    # Webhooks
    "webhooks:read", "webhooks:write",
    # Docker Stacks
    "docker_stacks:read", "docker_stacks:write",
    # Alerts
    "alerts:read", "alerts:write",
    # Approvals
    "approvals:read", "approvals:write",
    # Tool Policies
    "tool_policies:read", "tool_policies:write",
    # Bot Hooks
    "bot_hooks:read", "bot_hooks:write",
    # Storage
    "storage:read", "storage:write",
    # Push notifications
    "push:send",
]

# Scope descriptions (shown in admin UI)
SCOPE_DESCRIPTIONS: dict[str, str] = {
    "admin": "Full access to all endpoints including admin panel",
    "channels:read": "List and get channel details",
    "channels:write": "Create, update, delete channels (includes all channel sub-scopes)",
    "channels.messages:read": "Search messages within channels",
    "channels.messages:write": "Inject messages into a channel's session",
    "channels.config:read": "Read channel settings (model overrides, compaction, tools, etc.)",
    "channels.config:write": "Modify channel settings (model, compaction, tools, skills, etc.)",
    "channels.heartbeat:read": "Read heartbeat schedule and configuration",
    "channels.heartbeat:write": "Enable/disable heartbeats, change schedule and prompt",
    "channels.integrations:read": "List integration bindings on channels",
    "channels.integrations:write": "Bind/unbind integrations, adopt bindings",
    "chat": "Send chat messages (blocking and streaming), cancel, submit tool results",
    "sessions:read": "Get session details and message history",
    "sessions:write": "Create sessions, inject messages into sessions",
    "bots:read": "List bots and get bot configuration",
    "bots:write": "Create and update bot configuration",
    "bots:delete": "Delete bots (destructive — separate from write)",
    "tasks:read": "List and poll task status",
    "tasks:write": "Create and delete tasks",
    "workspaces:read": "List workspaces, get status, logs, and bot config",
    "workspaces:write": "Create, update, start, stop, recreate workspaces",
    "workspaces.files:read": "List and read workspace files",
    "workspaces.files:write": "Write, upload, and delete workspace files",
    "documents:read": "Semantic search over ingested documents",
    "documents:write": "Ingest and delete documents",
    "todos:read": "List todos",
    "todos:write": "Create, update, and delete todos",
    "attachments:read": "Get attachment metadata and download files",
    "attachments:write": "Upload, delete, and purge attachments",
    "logs:read": "View agent turns, tool call history, traces, and server logs",
    "logs:write": "Change server log level",
    "tools:read": "List available tools",
    "tools:execute": "Execute local tools directly via API",
    "providers:read": "List provider configurations and models",
    "providers:write": "Create and manage provider configurations",
    "users:read": "List users and get user details",
    "users:write": "Create and manage users",
    "settings:read": "Read server settings",
    "settings:write": "Modify server settings",
    "operations:read": "View backup config, backup history, and active operations",
    "operations:write": "Trigger backups, git pull, server restart, and update backup config",
    "usage:read": "View usage summary, logs, breakdown, timeseries, forecast, and limit status",
    "usage:write": "Create, update, and delete usage limits",
    "workflows:read": "List workflows, view workflow runs and step details",
    "workflows:write": "Create, update, delete workflows; trigger, cancel, approve, skip, retry runs",
    "llm:completions": "Make LLM chat completion calls through the server's provider system",
    "api_keys:read": "List and view API key metadata",
    "api_keys:write": "Create, update, and delete API keys",
    "integrations:read": "List integrations and view settings, process status, and API keys",
    "integrations:write": "Update integration settings, control processes, install dependencies, and manage API keys",
    "mcp_servers:read": "List and view MCP server configurations",
    "mcp_servers:write": "Create, update, and delete MCP server configurations",
    "skills:read": "List and view skill definitions and metadata",
    "skills:write": "Create, update, and delete skills",
    "secrets:read": "List secret value metadata (names, not values)",
    "secrets:write": "Create, update, and delete secret values",
    "webhooks:read": "List webhooks and view delivery history",
    "webhooks:write": "Create, update, delete, and test webhooks",
    "docker_stacks:read": "List Docker stack configurations",
    "docker_stacks:write": "Create, update, delete, and control Docker stacks",
    "alerts:read": "List and view spike alert configurations",
    "alerts:write": "Create, update, and delete spike alerts",
    "approvals:read": "List pending and historical tool approvals",
    "approvals:write": "Approve or deny tool call requests",
    "tool_policies:read": "List and view tool policy configurations",
    "tool_policies:write": "Create, update, and delete tool policies",
    "bot_hooks:read": "List and view bot lifecycle hooks",
    "bot_hooks:write": "Create, update, and delete bot hooks",
    "storage:read": "View storage usage statistics",
    "storage:write": "Manage storage (cleanup, purge)",
    "push:send": "Send Web Push notifications to a user's subscribed devices",
}

# Grouped scopes for the UI — each group has a description and ordered scope list.
# The API returns this structure; the frontend renders grouped checkboxes.
SCOPE_GROUPS: dict[str, dict] = {
    "Admin": {
        "description": "Full administrative access — use with caution",
        "scopes": ["admin"],
    },
    "Channels": {
        "description": "Channel CRUD and sub-resources (messages, config, heartbeat, integrations)",
        "scopes": [
            "channels:read", "channels:write",
            "channels.messages:read", "channels.messages:write",
            "channels.config:read", "channels.config:write",
            "channels.heartbeat:read", "channels.heartbeat:write",
            "channels.integrations:read", "channels.integrations:write",
        ],
    },
    "Chat": {
        "description": "Send messages to bots via the chat API",
        "scopes": ["chat"],
    },
    "Sessions": {
        "description": "Low-level session access (prefer channels for most use cases)",
        "scopes": ["sessions:read", "sessions:write"],
    },
    "Bots": {
        "description": "Read and manage bot configurations",
        "scopes": ["bots:read", "bots:write", "bots:delete"],
    },
    "Tasks": {
        "description": "Async task polling and creation",
        "scopes": ["tasks:read", "tasks:write"],
    },
    "Workspaces": {
        "description": "Shared workspace management and file operations",
        "scopes": [
            "workspaces:read", "workspaces:write",
            "workspaces.files:read", "workspaces.files:write",
        ],
    },
    "Documents": {
        "description": "Ingest text for RAG and search over embedded documents",
        "scopes": ["documents:read", "documents:write"],
    },
    "Todos": {
        "description": "Persistent work items scoped to bot + channel",
        "scopes": ["todos:read", "todos:write"],
    },
    "Logs": {
        "description": "Agent turns, tool call audit, traces, and server application logs",
        "scopes": ["logs:read", "logs:write"],
    },
    "Attachments": {
        "description": "Access file attachments from conversations",
        "scopes": ["attachments:read", "attachments:write"],
    },
    "Tools": {
        "description": "Read and execute registered tools",
        "scopes": ["tools:read", "tools:execute"],
    },
    "Providers": {
        "description": "LLM provider configurations and model lists",
        "scopes": ["providers:read", "providers:write"],
    },
    "Users": {
        "description": "User management",
        "scopes": ["users:read", "users:write"],
    },
    "Settings": {
        "description": "Server-wide settings",
        "scopes": ["settings:read", "settings:write"],
    },
    "Operations": {
        "description": "System operations: backup, pull, restart",
        "scopes": ["operations:read", "operations:write"],
    },
    "Usage": {
        "description": "Cost analytics, forecasting, and usage limits",
        "scopes": ["usage:read", "usage:write"],
    },
    "Workflows": {
        "description": "Multi-step automations with conditions, approvals, and cross-bot coordination",
        "scopes": ["workflows:read", "workflows:write"],
    },
    "LLM": {
        "description": "Direct LLM calls through the server's multi-provider infrastructure",
        "scopes": ["llm:completions"],
    },
    "API Keys": {
        "description": "Manage scoped API keys",
        "scopes": ["api_keys:read", "api_keys:write"],
    },
    "Integrations": {
        "description": "Integration setup, settings, process control, and dependencies",
        "scopes": ["integrations:read", "integrations:write"],
    },
    "MCP Servers": {
        "description": "Model Context Protocol server configurations",
        "scopes": ["mcp_servers:read", "mcp_servers:write"],
    },
    "Skills": {
        "description": "Skill definitions and metadata",
        "scopes": ["skills:read", "skills:write"],
    },
    "Secrets": {
        "description": "Secret value management (encrypted storage)",
        "scopes": ["secrets:read", "secrets:write"],
    },
    "Webhooks": {
        "description": "Webhook endpoints and delivery management",
        "scopes": ["webhooks:read", "webhooks:write"],
    },
    "Docker Stacks": {
        "description": "Docker stack configurations and control",
        "scopes": ["docker_stacks:read", "docker_stacks:write"],
    },
    "Alerts": {
        "description": "Spike alert configurations and notifications",
        "scopes": ["alerts:read", "alerts:write"],
    },
    "Approvals": {
        "description": "Tool call approval queue",
        "scopes": ["approvals:read", "approvals:write"],
    },
    "Tool Policies": {
        "description": "Tool-level permission policies (allow/deny/approval-required)",
        "scopes": ["tool_policies:read", "tool_policies:write"],
    },
    "Bot Hooks": {
        "description": "Bot lifecycle hooks — run commands on file access, writes, or exec events",
        "scopes": ["bot_hooks:read", "bot_hooks:write"],
    },
    "Storage": {
        "description": "Storage usage and management",
        "scopes": ["storage:read", "storage:write"],
    },
    "Push Notifications": {
        "description": "Send Web Push notifications to a user's subscribed devices",
        "scopes": ["push:send"],
    },
}

# Pre-built scope bundles for common use cases.
# The API returns these alongside groups so the UI can offer one-click presets.
SCOPE_PRESETS: dict[str, dict] = {
    "slack_integration": {
        "name": "Messaging Integration",
        "description": "Chat, channels, sessions, model switching, LLM calls — for Slack, Discord, BlueBubbles, Gmail, etc.",
        "scopes": [
            "chat", "bots:read",
            "channels:read", "channels:write",
            "channels.config:read", "channels.config:write",
            "sessions:read", "sessions:write",
            "todos:read",
            "llm:completions",
        ],
        "instructions": (
            "Set this key as `AGENT_API_KEY` in your integration environment.\n\n"
            "Covers chat, channel management, session control, model switching, "
            "and tool approval handling.\n\n"
            "If running via docker compose, add to your `.env`:\n"
            "```\nAGENT_API_KEY=ask_your_key_here\n```"
        ),
    },
    "chat_client": {
        "name": "Chat Client",
        "description": "Send messages and read responses — no admin access",
        "scopes": [
            "chat", "bots:read",
            "channels:read", "channels:write",
            "sessions:read",
            "attachments:read", "attachments:write",
        ],
        "instructions": "Set as `AGENT_SERVER_API_KEY` in the client environment.",
    },
    "workspace_bot": {
        "name": "Container Bot",
        "description": "For bots in their container environment — chat, files, tasks, documents, tools",
        "scopes": [
            "chat", "bots:read",
            "channels:read", "channels:write",
            "sessions:read",
            "tasks:read", "tasks:write",
            "documents:read", "documents:write",
            "todos:read", "todos:write",
            "workspaces.files:read", "workspaces.files:write",
            "attachments:read", "attachments:write",
            "carapaces:read", "carapaces:write",
            "tools:read", "tools:execute",
        ],
        "instructions": (
            "Injected automatically when a bot has API permissions configured.\n"
            "The bot reaches the server via the `call_api` and `list_api_endpoints` tools."
        ),
    },
    "read_only": {
        "name": "Read-Only Monitor",
        "description": "Read channels, sessions, tasks — no write access",
        "scopes": [
            "bots:read", "channels:read", "sessions:read",
            "tasks:read", "todos:read", "attachments:read", "logs:read",
        ],
        "instructions": "Safe for dashboards and monitoring. Cannot send messages or modify data.",
    },
    "admin_user": {
        "name": "Admin User",
        "description": "Full admin access for admin users — bypasses all scope checks",
        "scopes": ["admin"],
        "instructions": "Auto-provisioned for admin users.",
    },
    "member_user": {
        "name": "Member User",
        "description": "Standard member access — chat, read bots/channels, manage own todos and attachments",
        "scopes": [
            "chat", "bots:read",
            "channels:read", "channels:write",
            "sessions:read",
            "attachments:read", "attachments:write",
            "todos:read", "todos:write",
            "approvals:read",
        ],
        "instructions": "Auto-provisioned for non-admin users.",
    },
}

# ---------------------------------------------------------------------------
# Endpoint catalog (used by /discover)
# Built at startup by endpoint_catalog.build_endpoint_catalog()
# ---------------------------------------------------------------------------

ENDPOINT_CATALOG: list[dict] = []

# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def generate_key() -> tuple[str, str, str]:
    """Generate a new API key. Returns (full_key, prefix, key_hash)."""
    random_part = secrets.token_hex(32)  # 64 hex chars
    full_key = f"ask_{random_part}"
    prefix = full_key[:12]
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, prefix, key_hash


def hash_key(raw_key: str) -> str:
    """Hash a raw key for lookup."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def generate_api_docs(scopes: list[str] | None = None) -> str:
    """Generate markdown API documentation filtered by scopes.

    If scopes is None, returns docs for all endpoints (full access).
    Used by the discover endpoint and the dynamic API skill.
    """
    if scopes is not None:
        endpoints = [
            ep for ep in ENDPOINT_CATALOG
            if ep.get("scope") is None or has_scope(scopes, ep["scope"])
        ]
    else:
        endpoints = list(ENDPOINT_CATALOG)

    if not endpoints:
        return "No API endpoints available for your permissions."

    # Group by scope
    grouped: dict[str, list[dict]] = {}
    for ep in endpoints:
        scope = ep.get("scope") or "general"
        grouped.setdefault(scope, []).append(ep)

    lines = ["# Agent Server API Reference\n"]
    if scopes is not None:
        lines.append(f"**Your scopes:** {', '.join(scopes)}\n")
    lines.append(
        "Call these endpoints with the `call_api` tool — it runs in-process with your "
        "scoped key, so no auth headers or shell escaping. Use `list_api_endpoints` first "
        "to discover what your scopes permit.\n"
    )
    lines.append(
        "Examples:\n"
        "- `call_api(method=\"GET\", path=\"/api/v1/channels\")`\n"
        "- `call_api(method=\"POST\", path=\"/chat\", body='{\"message\":\"hello\"}')`\n"
    )

    for scope, eps in sorted(grouped.items()):
        # Friendly group name
        group_name = scope.replace(":", " ").replace("_", " ").title()
        lines.append(f"## {group_name}\n")
        for ep in eps:
            lines.append(f"### `{ep['method']} {ep['path']}`")
            lines.append(f"{ep['description']}\n")
            if ep.get("params"):
                lines.append(f"**Query params:** `{ep['params']}`\n")
            if ep.get("body"):
                lines.append(f"**Request body:** `{ep['body']}`\n")
            if ep.get("response"):
                lines.append(f"**Response:** `{ep['response']}`\n")
            if ep.get("notes"):
                lines.append(f"**Notes:** {ep['notes']}\n")

    return "\n".join(lines)


def _parse_scope(scope: str) -> tuple[str, str]:
    """Parse scope into (resource, action). Handles 'resource:action' and 'resource.sub:action'."""
    parts = scope.split(":")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return scope, ""


def has_scope(key_scopes: list[str], required: str) -> bool:
    """Check if key_scopes satisfy the required scope.

    Rules:
    - 'admin' bypasses all checks
    - Exact match always works
    - Write implies read (e.g. 'channels:write' grants 'channels:read')
    - Parent resource covers child (e.g. 'channels:write' covers 'channels.messages:write')
    - Broader scopes cover narrower (e.g. 'channels:write' covers 'channels:write:abc123')
    - Wildcard: 'channels:*' covers any 'channels:action'

    Scope format: <resource>[.sub]:action[:<resource_id>]
    Examples:
        'channels:read'               — read all channels
        'channels.messages:write'     — inject messages only
        'channels:write'              — all channel write ops (covers channels.messages:write)
        'channels:read:abc123'        — read specific channel (future)
        'channels:*'                  — all channel actions
    """
    if "admin" in key_scopes:
        return True
    if required in key_scopes:
        return True

    req_resource, req_action = _parse_scope(required)

    for s in key_scopes:
        s_resource, s_action = _parse_scope(s)

        # Write implies read (same resource)
        if req_action == "read" and s_action == "write" and req_resource == s_resource:
            return True

        # Parent resource covers child: 'channels:write' covers 'channels.messages:write'
        if req_resource.startswith(s_resource + "."):
            if s_action == req_action:
                return True
            if s_action == "write" and req_action == "read":
                return True

        # Broader scope covers narrower: 'channels:write' covers 'channels:write:abc123'
        if required.startswith(s + ":"):
            return True

        # Wildcard: 'channels:*' covers 'channels:read', 'channels.messages:write', etc.
        if s_action == "*" and (req_resource == s_resource or req_resource.startswith(s_resource + ".")):
            return True

    return False


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

async def create_api_key(
    db: AsyncSession,
    name: str,
    scopes: list[str],
    user_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    store_key_value: bool = False,
) -> tuple[ApiKey, str]:
    """Create a new API key. Returns (row, full_key).

    If store_key_value=True, the full key is stored in key_value for later
    retrieval (used for bot-injected keys).
    """
    full_key, prefix, key_hash = generate_key()
    now = datetime.now(timezone.utc)
    row = ApiKey(
        id=uuid.uuid4(),
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        key_value=full_key if store_key_value else None,
        scopes=scopes,
        created_by_user_id=user_id,
        is_active=True,
        expires_at=expires_at,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, full_key


async def validate_api_key(db: AsyncSession, raw_key: str) -> ApiKey | None:
    """Validate a raw API key. Returns the ApiKey row if valid, None otherwise."""
    key_hash = hash_key(raw_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if not row.is_active:
        return None
    if row.expires_at:
        exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return None
    # Update last_used_at
    row.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return row


async def get_bot_api_key_value(db: AsyncSession, bot_id: str) -> str | None:
    """Get the full API key value for a bot (for injection into containers).
    Returns None if no key assigned or key has no stored value.
    """
    row = (await db.execute(
        select(BotRow.api_key_id).where(BotRow.id == bot_id)
    )).scalar_one_or_none()
    if not row:
        return None
    api_key = await db.get(ApiKey, row)
    if not api_key or not api_key.is_active:
        return None
    return api_key.key_value


def resolve_scopes(preset_or_list: str | list[str]) -> list[str]:
    """Resolve a preset name or explicit scope list to a list of scopes."""
    if isinstance(preset_or_list, list):
        return preset_or_list
    preset = SCOPE_PRESETS.get(preset_or_list)
    if not preset:
        raise ValueError(f"Unknown scope preset: {preset_or_list!r}")
    return preset["scopes"]


async def ensure_entity_api_key(
    db: AsyncSession,
    *,
    name: str,
    scopes: list[str],
    existing_key_id: uuid.UUID | None = None,
) -> tuple[ApiKey, str | None]:
    """Ensure an API key exists for an entity (user, integration, etc.).

    If existing_key_id is set, updates scopes on the existing key and returns
    (key, None) — no new key value to reveal.

    If no key exists, creates a new one with store_key_value=True and returns
    (key, full_key_value) — caller should store/reveal the value.
    """
    if existing_key_id:
        api_key = await db.get(ApiKey, existing_key_id)
        if api_key and api_key.is_active:
            api_key.scopes = scopes
            api_key.updated_at = datetime.now(timezone.utc)
            await db.flush()
            return api_key, None

    # Create new key
    key, full_value = await create_api_key(
        db, name=name, scopes=scopes, store_key_value=True,
    )
    return key, full_value


async def get_integration_api_key_value(db: AsyncSession, integration_id: str) -> str | None:
    """Get the full API key value for an integration.

    Reads the _api_key_id from IntegrationSetting, then returns the stored
    key_value from ApiKey. Returns None if not provisioned.
    """
    result = await db.execute(
        select(IntegrationSetting.value).where(
            IntegrationSetting.integration_id == integration_id,
            IntegrationSetting.key == "_api_key_id",
        )
    )
    key_id_str = result.scalar_one_or_none()
    if not key_id_str:
        return None
    try:
        key_id = uuid.UUID(key_id_str)
    except ValueError:
        return None
    api_key = await db.get(ApiKey, key_id)
    if not api_key or not api_key.is_active:
        return None
    return api_key.key_value


async def get_integration_api_key(db: AsyncSession, integration_id: str) -> ApiKey | None:
    """Get the ApiKey row for an integration (metadata only, not the value)."""
    result = await db.execute(
        select(IntegrationSetting.value).where(
            IntegrationSetting.integration_id == integration_id,
            IntegrationSetting.key == "_api_key_id",
        )
    )
    key_id_str = result.scalar_one_or_none()
    if not key_id_str:
        return None
    try:
        key_id = uuid.UUID(key_id_str)
    except ValueError:
        return None
    return await db.get(ApiKey, key_id)


async def provision_integration_api_key(
    db: AsyncSession,
    integration_id: str,
    scopes: list[str],
) -> tuple[ApiKey, str | None]:
    """Provision or update an integration's scoped API key.

    Stores the key ID in IntegrationSetting("_api_key_id").
    Returns (key, full_key_value) — full_key_value is None if key already existed.
    """
    # Check existing
    existing = await get_integration_api_key(db, integration_id)
    existing_id = existing.id if existing else None

    key, full_value = await ensure_entity_api_key(
        db,
        name=f"integration:{integration_id}",
        scopes=scopes,
        existing_key_id=existing_id,
    )

    # Upsert key ID in IntegrationSetting
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(IntegrationSetting).where(
            IntegrationSetting.integration_id == integration_id,
            IntegrationSetting.key == "_api_key_id",
        )
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = str(key.id)
        setting.updated_at = now
    else:
        db.add(IntegrationSetting(
            integration_id=integration_id,
            key="_api_key_id",
            value=str(key.id),
            is_secret=False,
            updated_at=now,
        ))
    await db.commit()
    await db.refresh(key)
    return key, full_value


async def revoke_integration_api_key(db: AsyncSession, integration_id: str) -> bool:
    """Revoke an integration's API key. Returns True if key was found and revoked."""
    api_key = await get_integration_api_key(db, integration_id)
    if not api_key:
        return False
    api_key.is_active = False
    api_key.updated_at = datetime.now(timezone.utc)

    # Remove the setting
    result = await db.execute(
        select(IntegrationSetting).where(
            IntegrationSetting.integration_id == integration_id,
            IntegrationSetting.key == "_api_key_id",
        )
    )
    setting = result.scalar_one_or_none()
    if setting:
        await db.delete(setting)

    await db.commit()
    return True
