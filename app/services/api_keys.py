"""Scoped API key management service."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Bot as BotRow

# ---------------------------------------------------------------------------
# Scope definitions
# ---------------------------------------------------------------------------

ALL_SCOPES = [
    "admin",
    "channels:read", "channels:write",
    "chat",
    "sessions:read", "sessions:write",
    "bots:read", "bots:write",
    "tasks:read", "tasks:write",
    "workspaces:read", "workspaces:write",
    "knowledge:read", "knowledge:write",
    "tools:read",
    "providers:read", "providers:write",
    "users:read", "users:write",
    "settings:read", "settings:write",
]

SCOPE_GROUPS: dict[str, list[str]] = {
    "Admin": ["admin"],
    "Channels": ["channels:read", "channels:write"],
    "Chat": ["chat"],
    "Sessions": ["sessions:read", "sessions:write"],
    "Bots": ["bots:read", "bots:write"],
    "Tasks": ["tasks:read", "tasks:write"],
    "Workspaces": ["workspaces:read", "workspaces:write"],
    "Knowledge": ["knowledge:read", "knowledge:write"],
    "Tools": ["tools:read"],
    "Providers": ["providers:read", "providers:write"],
    "Users": ["users:read", "users:write"],
    "Settings": ["settings:read", "settings:write"],
}

# ---------------------------------------------------------------------------
# Endpoint catalog (used by /discover)
# ---------------------------------------------------------------------------

ENDPOINT_CATALOG: list[dict] = [
    # Channels
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels",
        "description": "List channels",
        "params": "?integration=&bot_id=&user_id=",
        "response": "[{id, name, bot_id, integration, active_session_id, ...}]",
    },
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}",
        "description": "Get channel details",
        "response": "{id, name, bot_id, active_session_id, integrations: [...], ...}",
    },
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/config",
        "description": "Get full channel config (settings, effective tools, etc.)",
    },
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/messages/search",
        "description": "Search channel messages",
        "params": "?q=&role=&limit=50",
        "response": "[{id, role, content, created_at, ...}]",
    },
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/knowledge",
        "description": "List knowledge docs for a channel",
    },
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/attachment-stats",
        "description": "Get attachment statistics for a channel",
    },
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/integrations",
        "description": "List integration bindings for a channel",
    },
    {
        "scope": "channels:write", "method": "POST", "path": "/api/v1/channels",
        "description": "Create or retrieve a channel",
        "body": '{"bot_id": "str", "client_id": "str", "name?": "str"}',
        "response": "{id, name, bot_id, active_session_id, ...}",
    },
    {
        "scope": "channels:write", "method": "PUT", "path": "/api/v1/channels/{id}",
        "description": "Update channel settings",
        "body": '{"name?": "str", "channel_prompt?": "str", "max_iterations?": int, ...}',
    },
    {
        "scope": "channels:write", "method": "DELETE", "path": "/api/v1/channels/{id}",
        "description": "Delete a channel",
    },
    {
        "scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/messages",
        "description": "Inject message into a channel's active session",
        "body": '{"content": "str", "role?": "user", "source?": "str", "run_agent?": false}',
        "notes": "If run_agent=true, returns {task_id} for async processing.",
    },
    {
        "scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/reset",
        "description": "Reset channel session (creates new session, preserves config)",
    },
    {
        "scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/switch-session",
        "description": "Switch channel to a specific session",
        "body": '{"session_id": "uuid"}',
    },
    {
        "scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/integrations",
        "description": "Bind an integration to a channel",
        "body": '{"integration_type": "str", "client_id": "str"}',
    },
    {
        "scope": "channels:write", "method": "DELETE",
        "path": "/api/v1/channels/{id}/integrations/{binding_id}",
        "description": "Unbind integration from channel",
    },
    {
        "scope": "channels:write", "method": "POST",
        "path": "/api/v1/channels/{id}/integrations/{binding_id}/adopt",
        "description": "Adopt integration binding from another channel",
    },
    # Chat
    {
        "scope": "chat", "method": "POST", "path": "/chat",
        "description": "Send chat message (non-streaming, returns full response)",
        "body": '{"message": "str", "bot_id": "str", "client_id": "str", "channel_id?": "uuid", "model_override?": "str"}',
        "response": '{"response": "str", "session_id": "uuid"}',
    },
    {
        "scope": "chat", "method": "POST", "path": "/chat/stream",
        "description": "Send chat message (SSE streaming)",
        "body": '{"message": "str", "bot_id": "str", "client_id": "str", "channel_id?": "uuid"}',
        "notes": "Returns Server-Sent Events stream. Events: skill_context, memory_context, tool_start, tool_result, response, error.",
    },
    {
        "scope": "chat", "method": "POST", "path": "/chat/cancel",
        "description": "Cancel in-progress chat for a session",
        "body": '{"session_id": "uuid"}',
    },
    # Sessions
    {
        "scope": "sessions:read", "method": "GET", "path": "/api/v1/sessions/{id}",
        "description": "Get session details",
        "response": "{id, bot_id, channel_id, created_at, updated_at, summary}",
    },
    {
        "scope": "sessions:read", "method": "GET", "path": "/api/v1/sessions/{id}/messages",
        "description": "Get session message history",
        "params": "?limit=50",
        "response": "[{id, role, content, tool_calls, created_at, ...}]",
    },
    # Tasks
    {
        "scope": "tasks:read", "method": "GET", "path": "/api/v1/tasks",
        "description": "List tasks",
        "params": "?status=&bot_id=&limit=50",
        "response": "[{id, status, type, bot_id, created_at, ...}]",
    },
    {
        "scope": "tasks:read", "method": "GET", "path": "/api/v1/tasks/{id}",
        "description": "Get task details and result",
        "response": "{id, status, type, result, error, created_at, completed_at}",
        "notes": "Status: pending → running → complete | failed. Poll at 5s+ intervals.",
    },
    {
        "scope": "tasks:write", "method": "POST", "path": "/api/v1/tasks",
        "description": "Create a task",
        "body": '{"type": "str", "bot_id": "str", "payload": {}}',
    },
    {
        "scope": "tasks:write", "method": "DELETE", "path": "/api/v1/tasks/{id}",
        "description": "Delete a task",
    },
    # Discovery
    {
        "scope": None, "method": "GET", "path": "/api/v1/discover",
        "description": "Discover available endpoints (filtered by your key's scopes)",
        "params": "?detail=true for full API docs",
    },
]

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
    lines.append("All paths relative to `$AGENT_SERVER_URL`. Auth via `$AGENT_SERVER_API_KEY`.\n")
    lines.append("Use `agent api METHOD /path [body]` or `agent-api METHOD /path [body]` from the CLI.\n")

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


def has_scope(key_scopes: list[str], required: str) -> bool:
    """Check if key_scopes satisfy the required scope.

    Rules:
    - 'admin' bypasses all checks
    - Write implies read (e.g. 'channels:write' grants 'channels:read')
    - Broader scopes cover narrower ones (e.g. 'channels:write' covers
      'channels:write:abc123') — future resource-level scoping

    Scope format: <resource>:<action>[:<resource_id>]
    This allows future granular permissions without changing the enforcement logic.
    For example:
        'channels:read' — read all channels
        'channels:read:abc123' — read only channel abc123
        'channels:*' — all channel actions (wildcard, future)
    """
    if "admin" in key_scopes:
        return True
    if required in key_scopes:
        return True
    # Write implies read
    if required.endswith(":read"):
        write_scope = required.replace(":read", ":write")
        if write_scope in key_scopes:
            return True
    # Broader scope covers narrower (e.g. key has 'channels:write',
    # required is 'channels:write:abc123')
    for s in key_scopes:
        if required.startswith(s + ":"):
            return True
    # Wildcard support (future): 'channels:*' covers 'channels:read'
    req_parts = required.split(":")
    if len(req_parts) >= 2:
        wildcard = f"{req_parts[0]}:*"
        if wildcard in key_scopes:
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
