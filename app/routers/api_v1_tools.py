"""Public tool introspection — ``GET /api/v1/tools/{name}/signature``.

Widget-facing endpoint that returns a tool's input schema and (when
declared) its return-shape schema. The SDK's ``window.spindrel.toolSchema``
helper calls this so widget authors can look up expected envelope
shapes before guessing.

Local tools register ``input_schema`` via the OpenAI function-call shape
on ``@register(schema)`` and ``returns_schema`` via ``returns=`` on the
same decorator (see ``app/tools/registry.py``). MCP tools carry input
schemas in the cached server listing; they don't advertise return
schemas at all — the MCP protocol has no slot for them — so
``returns_schema`` is ``null`` for every MCP tool. That's expected;
the ambient trace ring (see ``app/services/widget_debug.py``) is the
primary mechanism for learning MCP return shapes.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import verify_auth_or_user
from app.tools import mcp as mcp_tools
from app.tools.registry import _tools as _local_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolSignature(BaseModel):
    name: str
    kind: str
    description: str | None = None
    input_schema: dict | None = None
    returns_schema: dict | None = None
    source_integration: str | None = None
    execution_policy: str = "normal"
    requires_bot_context: bool = False
    requires_channel_context: bool = False


def _local_signature(name: str) -> ToolSignature | None:
    entry = _local_tools.get(name)
    if entry is None:
        return None
    schema = entry.get("schema") or {}
    fn = schema.get("function") or {}
    return ToolSignature(
        name=name,
        kind="local",
        description=fn.get("description"),
        input_schema=fn.get("parameters"),
        returns_schema=entry.get("returns"),
        source_integration=entry.get("source_integration"),
        execution_policy=str(entry.get("execution_policy") or "normal"),
        requires_bot_context=bool(entry.get("requires_bot_context")),
        requires_channel_context=bool(entry.get("requires_channel_context")),
    )


def _mcp_signature(name: str) -> ToolSignature | None:
    cache = getattr(mcp_tools, "_cache", {}) or {}
    for server_name, cached in cache.items():
        for tool in cached.get("tools", []):
            fn = tool.get("function") or {}
            if fn.get("name") == name:
                return ToolSignature(
                    name=name,
                    kind="mcp",
                    description=fn.get("description"),
                    input_schema=fn.get("parameters"),
                    returns_schema=None,
                    source_integration=server_name,
                )
    return None


@router.get("/{tool_name}/signature", response_model=ToolSignature)
async def get_tool_signature(
    tool_name: str,
    _auth=Depends(verify_auth_or_user),
) -> ToolSignature:
    """Return the input + (optional) return schema for a tool.

    Resolves local tools first; falls back to MCP tools including the
    common bare → ``<server>-<name>`` prefix lookup that LLMs tend to
    drop. 404 when nothing matches.
    """
    sig = _local_signature(tool_name)
    if sig is not None:
        return sig
    sig = _mcp_signature(tool_name)
    if sig is not None:
        return sig
    resolved = mcp_tools.resolve_mcp_tool_name(tool_name)
    if resolved and resolved != tool_name:
        sig = _mcp_signature(resolved)
        if sig is not None:
            return sig
    raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
