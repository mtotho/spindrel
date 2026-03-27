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
    {"scope": "channels:read", "method": "GET", "path": "/api/v1/channels", "description": "List channels"},
    {"scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}", "description": "Get channel details"},
    {"scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/config", "description": "Get channel config"},
    {"scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/messages/search", "description": "Search channel messages"},
    {"scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/knowledge", "description": "List channel knowledge"},
    {"scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/attachment-stats", "description": "Get attachment stats"},
    {"scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/integrations", "description": "List channel integrations"},
    {"scope": "channels:write", "method": "POST", "path": "/api/v1/channels", "description": "Create a channel"},
    {"scope": "channels:write", "method": "PUT", "path": "/api/v1/channels/{id}", "description": "Update a channel"},
    {"scope": "channels:write", "method": "DELETE", "path": "/api/v1/channels/{id}", "description": "Delete a channel"},
    {"scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/messages", "description": "Inject message into channel"},
    {"scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/reset", "description": "Reset channel session"},
    {"scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/switch-session", "description": "Switch channel session"},
    {"scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/integrations", "description": "Bind integration"},
    {"scope": "channels:write", "method": "DELETE", "path": "/api/v1/channels/{id}/integrations/{binding_id}", "description": "Unbind integration"},
    {"scope": "channels:write", "method": "POST", "path": "/api/v1/channels/{id}/integrations/{binding_id}/adopt", "description": "Adopt integration"},
    # Chat
    {"scope": "chat", "method": "POST", "path": "/chat", "description": "Send chat message (non-streaming)"},
    {"scope": "chat", "method": "POST", "path": "/chat/stream", "description": "Send chat message (streaming)"},
    {"scope": "chat", "method": "POST", "path": "/chat/cancel", "description": "Cancel in-progress chat"},
    # Sessions
    {"scope": "sessions:read", "method": "GET", "path": "/api/v1/sessions/{id}", "description": "Get session details"},
    {"scope": "sessions:read", "method": "GET", "path": "/api/v1/sessions/{id}/messages", "description": "Get session messages"},
    # Tasks
    {"scope": "tasks:read", "method": "GET", "path": "/api/v1/tasks", "description": "List tasks"},
    {"scope": "tasks:read", "method": "GET", "path": "/api/v1/tasks/{id}", "description": "Get task details"},
    {"scope": "tasks:write", "method": "POST", "path": "/api/v1/tasks", "description": "Create a task"},
    {"scope": "tasks:write", "method": "DELETE", "path": "/api/v1/tasks/{id}", "description": "Delete a task"},
    # Discovery
    {"scope": None, "method": "GET", "path": "/api/v1/discover", "description": "Discover available endpoints"},
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

def has_scope(key_scopes: list[str], required: str) -> bool:
    """Check if key_scopes satisfy the required scope.

    Rules:
    - 'admin' bypasses all checks
    - Write implies read (e.g. 'channels:write' grants 'channels:read')
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
