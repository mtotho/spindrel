"""Factories for app.db.models.MCPServer."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.db.models import MCPServer


def build_mcp_server(**overrides) -> MCPServer:
    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=f"mcp-{suffix}",
        display_name=f"MCP Server {suffix}",
        url="http://localhost:9999/mcp",
        api_key=None,
        is_enabled=True,
        config={},
        source="manual",
        source_path=None,
        created_at=now,
        updated_at=now,
    )
    return MCPServer(**{**defaults, **overrides})
