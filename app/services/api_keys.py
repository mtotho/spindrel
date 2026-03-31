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
    "bots:read", "bots:write",
    # Tasks
    "tasks:read", "tasks:write",
    # Workspaces (broad)
    "workspaces:read", "workspaces:write",
    "workspaces.files:read", "workspaces.files:write",
    # Documents
    "documents:read", "documents:write",
    # Knowledge
    "knowledge:read", "knowledge:write",
    # Todos
    "todos:read", "todos:write",
    # Attachments
    "attachments:read",
    "attachments:write",
    # Logs
    "logs:read", "logs:write",
    # Tools
    "tools:read",
    # Providers
    "providers:read", "providers:write",
    # Users
    "users:read", "users:write",
    # Settings
    "settings:read", "settings:write",
    # Operations
    "operations:read", "operations:write",
    # Usage
    "usage:read",
    # Mission Control
    "mission_control:read", "mission_control:write",
    # Carapaces
    "carapaces:read", "carapaces:write",
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
    "tasks:read": "List and poll task status",
    "tasks:write": "Create and delete tasks",
    "workspaces:read": "List workspaces, get status, logs, and bot config",
    "workspaces:write": "Create, update, start, stop, recreate workspaces",
    "workspaces.files:read": "List and read workspace files",
    "workspaces.files:write": "Write, upload, and delete workspace files",
    "documents:read": "Semantic search over ingested documents",
    "documents:write": "Ingest and delete documents",
    "knowledge:read": "Read knowledge entries",
    "knowledge:write": "Create and manage knowledge entries",
    "todos:read": "List todos",
    "todos:write": "Create, update, and delete todos",
    "attachments:read": "Get attachment metadata and download files",
    "attachments:write": "Upload, delete, and purge attachments",
    "logs:read": "View agent turns, tool call history, traces, and server logs",
    "logs:write": "Change server log level",
    "tools:read": "List available tools",
    "providers:read": "List provider configurations and models",
    "providers:write": "Create and manage provider configurations",
    "users:read": "List users and get user details",
    "users:write": "Create and manage users",
    "settings:read": "Read server settings",
    "settings:write": "Modify server settings",
    "operations:read": "View backup config, backup history, and active operations",
    "operations:write": "Trigger backups, git pull, server restart, and update backup config",
    "usage:read": "View usage summary, logs, breakdown, timeseries, forecast, and limit status",
    "mission_control:read": "Read Mission Control dashboard data (overview, kanban, journal, memory, context)",
    "mission_control:write": "Write Mission Control data (create/move kanban cards, update preferences)",
    "carapaces:read": "List and get carapace details (skill+tool bundles)",
    "carapaces:write": "Create, update, and delete carapaces",
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
        "scopes": ["bots:read", "bots:write"],
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
    "Knowledge": {
        "description": "Bot knowledge entries (LLM-written persistent docs)",
        "scopes": ["knowledge:read", "knowledge:write"],
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
        "description": "Read registered tool schemas",
        "scopes": ["tools:read"],
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
        "scopes": ["usage:read"],
    },
    "Mission Control": {
        "description": "Aggregated dashboard: overview, kanban, journal, memory, debug context",
        "scopes": ["mission_control:read", "mission_control:write"],
    },
    "Carapaces": {
        "description": "Manage skill+tool bundles (composable expert configurations)",
        "scopes": ["carapaces:read", "carapaces:write"],
    },
}

# Pre-built scope bundles for common use cases.
# The API returns these alongside groups so the UI can offer one-click presets.
SCOPE_PRESETS: dict[str, dict] = {
    "slack_integration": {
        "name": "Slack Integration",
        "description": "Full access for the Slack bot — chat, channels, sessions, model switching, approvals",
        "scopes": [
            "admin",
            "chat", "bots:read",
            "channels:read", "channels:write",
            "sessions:read", "sessions:write",
            "todos:read",
        ],
        "instructions": (
            "Set this key as `AGENT_API_KEY` in your Slack integration environment.\n\n"
            "The Slack bot needs `admin` scope for model switching (`/model set`), "
            "channel settings, and tool approval handling.\n\n"
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
        "name": "Workspace Bot",
        "description": "For bots in shared workspace containers — chat, files, tasks, documents",
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
        ],
        "instructions": (
            "Injected automatically when a bot has API permissions configured.\n"
            "Use the `agent` CLI inside the workspace container."
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
    "mission_control": {
        "name": "Mission Control Dashboard",
        "description": "Read-write access for the Mission Control dashboard — channels, tasks, workspace files",
        "scopes": [
            "bots:read", "channels:read", "sessions:read",
            "tasks:read", "tasks:write",
            "todos:read", "todos:write",
            "workspaces:read", "workspaces.files:read", "workspaces.files:write",
            "attachments:read", "logs:read",
            "mission_control:read", "mission_control:write",
            "carapaces:read",
        ],
        "instructions": (
            "Used by the Mission Control dashboard container. Auto-provisioned on first start.\n\n"
            "Set as `AGENT_SERVER_API_KEY` in the Mission Control container environment."
        ),
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
            "mission_control:read", "mission_control:write",
        ],
        "instructions": "Auto-provisioned for non-admin users.",
    },
}

# ---------------------------------------------------------------------------
# Endpoint catalog (used by /discover)
# ---------------------------------------------------------------------------

ENDPOINT_CATALOG: list[dict] = [
    # Channels — core CRUD
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
        "scope": "channels:write", "method": "POST", "path": "/api/v1/channels",
        "description": "Create or retrieve a channel",
        "body": '{"bot_id": "str", "client_id": "str", "name?": "str"}',
        "response": "{id, name, bot_id, active_session_id, ...}",
    },
    {
        "scope": "channels:write", "method": "PUT", "path": "/api/v1/channels/{id}",
        "description": "Update basic channel settings",
    },
    {
        "scope": "channels:write", "method": "DELETE", "path": "/api/v1/channels/{id}",
        "description": "Delete a channel and all associated data",
    },
    # Channels — messages
    {
        "scope": "channels.messages:read", "method": "GET", "path": "/api/v1/channels/{id}/messages/search",
        "description": "Search messages across all sessions in a channel",
        "params": "?q=&role=&limit=50",
        "response": "[{id, role, content, created_at, ...}]",
    },
    {
        "scope": "channels.messages:write", "method": "POST", "path": "/api/v1/channels/{id}/messages",
        "description": "Inject message into a channel's active session",
        "body": '{"content": "str", "role?": "user", "source?": "str", "run_agent?": false}',
        "notes": "If run_agent=true, returns {task_id} for async processing.",
    },
    {
        "scope": "channels.messages:write", "method": "POST", "path": "/api/v1/channels/{id}/reset",
        "description": "Reset channel session (creates new session, preserves config)",
    },
    {
        "scope": "channels.messages:write", "method": "POST", "path": "/api/v1/channels/{id}/switch-session",
        "description": "Switch channel to a specific session",
        "body": '{"session_id": "uuid"}',
    },
    # Channels — config
    {
        "scope": "channels.config:read", "method": "GET", "path": "/api/v1/channels/{id}/config",
        "description": "Get full channel config (settings, heartbeat, effective tools)",
        "notes": "Also requires channels.heartbeat:read for heartbeat fields (covered by channels.config:read via parent scope).",
    },
    {
        "scope": "channels.config:write", "method": "PUT", "path": "/api/v1/channels/{id}/config",
        "description": "Update channel settings (model overrides, compaction, tools, skills)",
        "notes": "Heartbeat fields require channels.heartbeat:write. channels.config:write covers both.",
    },
    # Channels — heartbeat (via config endpoint)
    {
        "scope": "channels.heartbeat:write", "method": "PUT", "path": "/api/v1/channels/{id}/config",
        "description": "Update heartbeat schedule, prompt, and quiet hours (subset of config endpoint)",
        "notes": "Send only heartbeat_* fields. channels.config:write also covers this.",
    },
    # Channels — knowledge & attachments (read via channel scope)
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/knowledge",
        "description": "List knowledge docs accessible to a channel",
    },
    {
        "scope": "channels:read", "method": "GET", "path": "/api/v1/channels/{id}/attachment-stats",
        "description": "Get attachment storage stats for a channel",
    },
    # Channels — integrations
    {
        "scope": "channels.integrations:read", "method": "GET", "path": "/api/v1/channels/{id}/integrations",
        "description": "List integration bindings for a channel",
    },
    {
        "scope": "channels.integrations:write", "method": "POST", "path": "/api/v1/channels/{id}/integrations",
        "description": "Bind an integration to a channel",
        "body": '{"integration_type": "str", "client_id": "str"}',
    },
    {
        "scope": "channels.integrations:write", "method": "DELETE",
        "path": "/api/v1/channels/{id}/integrations/{binding_id}",
        "description": "Unbind integration from channel",
    },
    {
        "scope": "channels.integrations:write", "method": "POST",
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
        "notes": "Returns Server-Sent Events. Events: skill_context, memory_context, tool_start, tool_result, response, error.",
    },
    {
        "scope": "chat", "method": "POST", "path": "/chat/cancel",
        "description": "Cancel in-progress chat",
        "body": '{"session_id": "uuid"}',
    },
    # Bots
    {
        "scope": "bots:read", "method": "GET", "path": "/bots",
        "description": "List available bots with id, name, and model",
        "response": "[{id, name, model, audio_input?}]",
    },
    # Sessions
    {
        "scope": "sessions:write", "method": "POST", "path": "/api/v1/sessions",
        "description": "Create or retrieve a session for an integration client",
        "body": '{"bot_id": "str", "client_id": "str", "dispatch_config?": {}}',
        "response": "{session_id, created}",
    },
    {
        "scope": "sessions:write", "method": "POST", "path": "/api/v1/sessions/{id}/messages",
        "description": "Inject message into session (optionally trigger agent or fan out to dispatch targets)",
        "body": '{"content": "str", "role?": "user", "source?": "str", "run_agent?": false, "notify?": true}',
        "response": "{message_id, session_id, task_id?}",
    },
    {
        "scope": "sessions:read", "method": "GET", "path": "/api/v1/sessions/{id}/messages",
        "description": "Get session message history",
        "params": "?limit=50",
        "response": "[{id, role, content, tool_calls, created_at, ...}]",
    },
    # Tasks
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
    # Documents
    {
        "scope": "documents:write", "method": "POST", "path": "/api/v1/documents",
        "description": "Ingest and embed a document for semantic search",
        "body": '{"title": "str", "content": "str", "integration_id?": "str", "metadata?": {}}',
    },
    {
        "scope": "documents:read", "method": "GET", "path": "/api/v1/documents/search",
        "description": "Semantic search over ingested documents",
        "params": "?q=&integration_id=&limit=10",
    },
    {
        "scope": "documents:read", "method": "GET", "path": "/api/v1/documents/{id}",
        "description": "Get document by ID",
    },
    {
        "scope": "documents:write", "method": "DELETE", "path": "/api/v1/documents/{id}",
        "description": "Delete a document",
    },
    # Todos
    {
        "scope": "todos:read", "method": "GET", "path": "/api/v1/todos",
        "description": "List todos",
        "params": "?bot_id=&channel_id=&status=pending",
    },
    {
        "scope": "todos:write", "method": "POST", "path": "/api/v1/todos",
        "description": "Create a todo",
        "body": '{"bot_id": "str", "channel_id": "str", "content": "str", "priority?": int}',
    },
    {
        "scope": "todos:write", "method": "PATCH", "path": "/api/v1/todos/{id}",
        "description": "Update a todo",
        "body": '{"content?": "str", "status?": "str", "priority?": int}',
    },
    {
        "scope": "todos:write", "method": "DELETE", "path": "/api/v1/todos/{id}",
        "description": "Delete a todo",
    },
    # Attachments
    {
        "scope": "attachments:read", "method": "GET", "path": "/api/v1/attachments",
        "description": "List attachments",
        "params": "?channel_id=&message_id=&type=image&limit=50",
    },
    {
        "scope": "attachments:read", "method": "GET", "path": "/api/v1/attachments/{id}",
        "description": "Get attachment metadata",
    },
    {
        "scope": "attachments:read", "method": "GET", "path": "/api/v1/attachments/{id}/file",
        "description": "Download raw attachment file",
    },
    {
        "scope": "attachments:write", "method": "POST", "path": "/api/v1/attachments/upload",
        "description": "Upload a file as a standalone attachment",
        "body": "multipart/form-data: file (UploadFile), channel_id (UUID)",
        "response": "{id, channel_id, type, filename, mime_type, size_bytes, created_at, ...}",
    },
    {
        "scope": "admin", "method": "GET", "path": "/api/v1/admin/attachments",
        "description": "List all attachments with pagination and filters",
        "params": "?channel_id=&type=&limit=50&offset=0",
        "response": "{attachments: [{id, filename, type, size_bytes, channel_name, ...}], total}",
    },
    {
        "scope": "admin", "method": "GET", "path": "/api/v1/admin/attachments/stats",
        "description": "Global attachment storage stats",
        "response": "{total_count, with_file_data_count, total_size_bytes, by_type, by_channel}",
    },
    {
        "scope": "admin", "method": "DELETE", "path": "/api/v1/admin/attachments/{id}",
        "description": "Delete an attachment",
    },
    {
        "scope": "admin", "method": "POST", "path": "/api/v1/admin/attachments/purge",
        "description": "Bulk purge attachments by date/channel/type",
        "body": '{"before_date": "ISO", "channel_id?": "uuid", "type?": "str", "purge_file_data_only?": false}',
        "response": "{purged_count}",
    },
    # Workspaces
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces",
        "description": "List workspaces",
    },
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces",
        "description": "Create a workspace",
        "body": '{"name": "str", "docker_image": "str", "mounts?": [...], "env?": {...}}',
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}",
        "description": "Get workspace details",
    },
    {
        "scope": "workspaces:write", "method": "PUT", "path": "/api/v1/workspaces/{id}",
        "description": "Update workspace configuration",
    },
    {
        "scope": "workspaces:write", "method": "DELETE", "path": "/api/v1/workspaces/{id}",
        "description": "Delete a workspace",
    },
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/start",
        "description": "Start workspace container",
    },
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/stop",
        "description": "Stop workspace container",
    },
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/recreate",
        "description": "Recreate workspace container from scratch",
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}/status",
        "description": "Get workspace container status",
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}/logs",
        "description": "Get workspace container logs",
        "params": "?tail=300",
    },
    # Workspace files
    {
        "scope": "workspaces.files:read", "method": "GET", "path": "/api/v1/workspaces/{id}/files",
        "description": "Browse workspace file tree",
        "params": "?path=/",
    },
    {
        "scope": "workspaces.files:read", "method": "GET", "path": "/api/v1/workspaces/{id}/files/content",
        "description": "Read a file from workspace",
        "params": "?path=/path/to/file",
    },
    {
        "scope": "workspaces.files:write", "method": "PUT", "path": "/api/v1/workspaces/{id}/files/content",
        "description": "Write content to a file in workspace",
        "params": "?path=/path/to/file",
        "body": '{"content": "str"}',
    },
    {
        "scope": "workspaces.files:write", "method": "POST", "path": "/api/v1/workspaces/{id}/files/upload",
        "description": "Upload a file to workspace",
    },
    {
        "scope": "workspaces.files:write", "method": "DELETE", "path": "/api/v1/workspaces/{id}/files",
        "description": "Delete a file or directory from workspace",
        "params": "?path=/path/to/delete",
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/disk-usage",
        "description": "Get disk usage report for all workspaces",
        "response": "{filesystem: {total_bytes, used_bytes, free_bytes, usage_percent}, workspace_base_dir, workspace_total_bytes, workspaces: [{type, id, name, path, total_bytes, file_count, subdirs?}]}",
    },
    # Workspace — bot membership
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/bots",
        "description": "Add bot to workspace",
        "body": '{"bot_id": "str", "workspace_dir?": "str", "indexing?": {"enabled": true, "extensions": [".py",".md"]}}',
        "response": "WorkspaceOut (full workspace object with updated bots list)",
        "notes": "Returns 201 on success. The bot must exist in the bot registry.",
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}/bots/{bot_id}",
        "description": "Get bot's workspace config (dir, indexing overrides)",
        "response": "{bot_id, workspace_dir, indexing, ...}",
    },
    {
        "scope": "workspaces:write", "method": "PUT", "path": "/api/v1/workspaces/{id}/bots/{bot_id}",
        "description": "Update bot workspace membership/config",
        "body": '{"workspace_dir?": "str", "indexing?": {"enabled": bool, "extensions": [...]}}',
        "notes": "Also accepts PATCH method.",
    },
    {
        "scope": "workspaces:write", "method": "DELETE", "path": "/api/v1/workspaces/{id}/bots/{bot_id}",
        "description": "Remove bot from workspace",
        "notes": "Returns 204 No Content.",
    },
    # Workspace — channels
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}/channels",
        "description": "List channels belonging to bots in this workspace",
        "response": "[{id, name, bot_id, active_session_id, ...}]",
    },
    # Workspace — file operations (additional)
    {
        "scope": "workspaces.files:write", "method": "POST", "path": "/api/v1/workspaces/{id}/files/mkdir",
        "description": "Create directory in workspace",
        "params": "?path=/path/to/new/dir",
    },
    {
        "scope": "workspaces.files:write", "method": "POST", "path": "/api/v1/workspaces/{id}/files/move",
        "description": "Move/rename file or directory",
        "body": '{"src": "/old/path", "dst": "/new/path"}',
    },
    {
        "scope": "workspaces.files:read", "method": "GET", "path": "/api/v1/workspaces/{id}/files/index-status",
        "description": "RAG indexing status for workspace files",
        "response": "{indexed_count, pending_count, last_indexed_at, ...}",
    },
    # Workspace — indexing & skills
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/reindex",
        "description": "Trigger full workspace reindex (file content + embeddings)",
    },
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/reindex-skills",
        "description": "Re-discover and re-embed workspace skill files",
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}/skills",
        "description": "List discovered workspace skill files",
        "response": "[{path, mode, bot_id?, size_bytes, ...}]",
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}/indexing",
        "description": "Get full indexing config (global, workspace-level, per-bot overrides)",
    },
    {
        "scope": "workspaces:write", "method": "PUT", "path": "/api/v1/workspaces/{id}/bots/{bot_id}/indexing",
        "description": "Update per-bot indexing overrides",
        "body": '{"enabled?": bool, "extensions?": [...], "exclude_patterns?": [...]}',
        "notes": "Also accepts PATCH method.",
    },
    # Workspace — container operations
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/pull",
        "description": "Pull/update workspace Docker image",
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}/cron-jobs",
        "description": "List cron jobs discovered inside workspace container",
    },
    # Workspace — code editor
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/editor/enable",
        "description": "Enable code-server for workspace",
    },
    {
        "scope": "workspaces:write", "method": "POST", "path": "/api/v1/workspaces/{id}/editor/disable",
        "description": "Disable code-server for workspace",
    },
    {
        "scope": "workspaces:read", "method": "GET", "path": "/api/v1/workspaces/{id}/editor/status",
        "description": "Get code-server status (enabled, port, URL)",
    },
    {
        "scope": "workspaces:read", "method": "POST", "path": "/api/v1/workspaces/{id}/editor/session",
        "description": "Create editor session cookie for authenticated access",
    },
    # Logs — agent turns (high-level view of each agent invocation)
    {
        "scope": "logs:read", "method": "GET", "path": "/api/v1/admin/turns",
        "description": "List recent agent turns (one per user message). Each turn includes tool calls, token usage, errors, timing, model, and bot/channel info.",
        "params": "?count=20&bot_id=&channel_id=&after=30m|2h|1d|ISO&before=ISO&has_error=true&has_tool_calls=true&search=text",
        "response": "{turns: [{correlation_id, created_at, bot_id, model, channel_name, user_message, response_preview, total_tokens, duration_ms, has_error, tool_calls: [{tool_name, duration_ms, error}], errors: [{event_name, message}]}], total, count}",
        "notes": "Examples: `?has_error=true&after=1d` = errors in the last day. `?bot_id=mybot&count=50` = last 50 turns for a bot. `after` accepts relative durations (30m, 2h, 1d) or ISO timestamps. Turns are newest-first.",
    },
    # Logs — merged log entries (tool calls + trace events)
    {
        "scope": "logs:read", "method": "GET", "path": "/api/v1/admin/logs",
        "description": "List log entries (tool calls + trace events merged), paginated and sorted newest-first",
        "params": "?event_type=tool_call|error|token_usage&bot_id=&session_id=&channel_id=&page=1&page_size=50",
        "response": "{rows: [{kind, id, created_at, correlation_id, bot_id, tool_name, error, ...}], total, page, page_size, bot_ids}",
    },
    # Logs — trace detail
    {
        "scope": "logs:read", "method": "GET", "path": "/api/v1/admin/traces/{correlation_id}",
        "description": "Full trace timeline for a single agent turn (tool calls, trace events, and messages in chronological order)",
        "response": "{events: [{kind, created_at, tool_name, error, role, content, ...}], correlation_id, session_id, bot_id}",
    },
    # Logs — tool call audit
    {
        "scope": "logs:read", "method": "GET", "path": "/api/v1/tool-calls",
        "description": "List tool calls with detailed filtering. Use for auditing specific tools or investigating errors.",
        "params": "?bot_id=&tool_name=&tool_type=local|mcp|client&session_id=&error_only=true&since=ISO&until=ISO&limit=50&offset=0",
        "response": "[{id, tool_name, tool_type, arguments, result, error, duration_ms, bot_id, correlation_id, created_at}]",
    },
    {
        "scope": "logs:read", "method": "GET", "path": "/api/v1/tool-calls/stats",
        "description": "Aggregated tool call statistics (count, avg duration, error rate) grouped by tool_name, bot_id, or tool_type",
        "params": "?group_by=tool_name|bot_id|tool_type&since=ISO&until=ISO&bot_id=",
        "response": "{group_by, stats: [{key, count, total_duration_ms, avg_duration_ms, error_count}]}",
    },
    {
        "scope": "logs:read", "method": "GET", "path": "/api/v1/tool-calls/{tool_call_id}",
        "description": "Get full detail for a single tool call (untruncated result)",
    },
    # Logs — server application logs
    {
        "scope": "logs:read", "method": "GET", "path": "/api/v1/admin/server-logs",
        "description": "Application server logs from in-memory ring buffer. To find errors, use `?level=ERROR`. To search for keywords, use `?search=text`.",
        "params": "?tail=200&level=ERROR&logger=app.agent&search=text&since_minutes=60",
        "response": "{entries: [{timestamp, level, logger, message, formatted}], total, levels}",
        "notes": "level is minimum severity filter — `level=ERROR` returns only ERROR + CRITICAL. `level=WARNING` returns WARNING + ERROR + CRITICAL. logger is prefix-matched (e.g. `app.agent` matches `app.agent.loop`). Example: `?level=ERROR&since_minutes=60` = errors in the last hour.",
    },
    # Logs — log level management
    {
        "scope": "logs:read", "method": "GET", "path": "/api/v1/admin/log-level",
        "description": "Get current root logger level",
        "response": "{level: 'INFO'}",
    },
    {
        "scope": "logs:write", "method": "PUT", "path": "/api/v1/admin/log-level",
        "description": "Set root logger level dynamically",
        "body": '{"level": "DEBUG|INFO|WARNING|ERROR|CRITICAL"}',
    },
    # Operations
    {
        "scope": "operations:read", "method": "GET", "path": "/api/v1/admin/operations",
        "description": "List active background operations",
        "response": "{operations: [{id, type, label, current, total, status, elapsed, message}]}",
    },
    {
        "scope": "operations:write", "method": "POST", "path": "/api/v1/admin/operations/backup",
        "description": "Trigger backup (runs scripts/backup.sh as background task)",
        "response": "{operation_id, status}",
    },
    {
        "scope": "operations:write", "method": "POST", "path": "/api/v1/admin/operations/pull",
        "description": "Run git pull origin master (synchronous)",
        "response": "{exit_code, stdout, stderr}",
    },
    {
        "scope": "operations:write", "method": "POST", "path": "/api/v1/admin/operations/restart",
        "description": "Pull + restart server via systemd (requires confirm: true)",
        "body": '{"confirm": true}',
        "response": "{pull: {exit_code, stdout, stderr}, restart: {exit_code, stdout, stderr}}",
    },
    {
        "scope": "operations:read", "method": "GET", "path": "/api/v1/admin/operations/backup/config",
        "description": "Get backup configuration (DB overrides > .env > defaults)",
        "response": "{rclone_remote, local_keep, aws_region, backup_dir}",
    },
    {
        "scope": "operations:write", "method": "PUT", "path": "/api/v1/admin/operations/backup/config",
        "description": "Update backup settings in server_settings table",
        "body": '{"rclone_remote?": "str", "local_keep?": int, "aws_region?": "str", "backup_dir?": "str"}',
    },
    {
        "scope": "operations:read", "method": "GET", "path": "/api/v1/admin/operations/backup/history",
        "description": "List local backup archives with sizes and dates",
        "response": "{backup_dir, files: [{name, size_bytes, modified_at}]}",
    },
    # Usage & Cost
    {
        "scope": "usage:read", "method": "GET", "path": "/api/v1/admin/usage/summary",
        "description": "Aggregated cost summary (by model, bot, provider)",
        "params": "?after=&before=&bot_id=&model=&provider_id=&channel_id=",
        "response": "{total_calls, total_tokens, total_cost, cost_by_model, cost_by_bot, cost_by_provider}",
    },
    {
        "scope": "usage:read", "method": "GET", "path": "/api/v1/admin/usage/logs",
        "description": "Paginated usage log entries with cost per call",
        "params": "?after=&before=&bot_id=&model=&provider_id=&channel_id=&page=1&page_size=50",
        "response": "{entries: [{model, cost, prompt_tokens, completion_tokens, ...}], total, page}",
    },
    {
        "scope": "usage:read", "method": "GET", "path": "/api/v1/admin/usage/forecast",
        "description": "Cost forecast: projected daily/monthly spend from heartbeats, recurring tasks, and current pace",
        "response": "{daily_spend, monthly_spend, projected_daily, projected_monthly, components: [{source, label, daily_cost, monthly_cost}], limits: [{scope_type, period, limit_usd, current_spend, projected_spend, projected_percentage}]}",
    },
    {
        "scope": "usage:read", "method": "GET", "path": "/api/v1/admin/limits/status",
        "description": "Current spend vs. limit for all enabled usage limits",
        "response": "[{scope_type, scope_value, period, limit_usd, current_spend, percentage}]",
    },
    # Carapaces
    {
        "scope": "carapaces:read", "method": "GET", "path": "/api/v1/carapaces",
        "description": "List available carapaces (skill+tool bundles)",
        "response": "[{id, name, description, skills, local_tools, pinned_tools, includes, tags}]",
    },
    {
        "scope": "carapaces:read", "method": "GET", "path": "/api/v1/carapaces/{id}",
        "description": "Get carapace detail",
    },
    {
        "scope": "carapaces:write", "method": "POST", "path": "/api/v1/carapaces",
        "description": "Create a carapace",
        "body": '{"id": "str", "name": "str", "skills?": [], "local_tools?": [], "pinned_tools?": [], "includes?": [], "system_prompt_fragment?": "str"}',
    },
    {
        "scope": "carapaces:write", "method": "PUT", "path": "/api/v1/carapaces/{id}",
        "description": "Update a carapace",
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
    lines.append(
        "**IMPORTANT:** `agent-api` is a CLI command, NOT a tool. "
        "Run it via `exec_command`: `exec_command(command=\"agent-api GET /path\")`.\n"
        "Examples: `exec_command(command=\"agent-api GET /api/v1/channels\")`, "
        "`exec_command(command='agent-api POST /chat {\"message\":\"hello\"}')`.\n"
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
