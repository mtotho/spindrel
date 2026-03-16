import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_cache: dict[str, dict[str, Any]] = {}
_cache_ttl = 60.0
_lock = asyncio.Lock()


def _litellm_base() -> str:
    """Derive the LiteLLM proxy root from LITELLM_BASE_URL (strip /v1 suffix)."""
    base = settings.LITELLM_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _server_mcp_url(server_name: str) -> str:
    return f"{_litellm_base()}/{server_name}/mcp"


async def fetch_mcp_tools(allowed_servers: list[str] | None = None) -> list[dict]:
    if not allowed_servers:
        return []

    all_tools: list[dict] = []

    for server in allowed_servers:
        tools = await _fetch_server_tools(server)
        all_tools.extend(tools)

    return all_tools


async def _fetch_server_tools(server_name: str) -> list[dict]:
    now = time.monotonic()
    cached = _cache.get(server_name)
    if cached and (now - cached["fetched_at"]) < _cache_ttl:
        logger.debug("MCP cache hit for '%s': %d tools", server_name, len(cached["tools"]))
        return cached["tools"]

    async with _lock:
        cached = _cache.get(server_name)
        if cached and (time.monotonic() - cached["fetched_at"]) < _cache_ttl:
            return cached["tools"]

        url = _server_mcp_url(server_name)
        try:
            logger.info("Fetching MCP tools from %s", url)
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.post(
                    url,
                    json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
                    headers={
                        "Authorization": f"Bearer {settings.LITELLM_API_KEY}",
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                )
                if resp.status_code != 200:
                    logger.error("MCP server '%s' returned %d: %s",
                                  server_name, resp.status_code, resp.text[:500])
                    resp.raise_for_status()
                ct = resp.headers.get("content-type", "")
                logger.debug("MCP response: status=%d content-type=%s body=%s",
                              resp.status_code, ct, resp.text[:500])

                if "text/event-stream" in ct:
                    data = _parse_sse_json(resp.text)
                else:
                    data = resp.json()
                tools = data.get("result", {}).get("tools", [])

                if not tools:
                    logger.warning("MCP server '%s' returned 0 tools. Response: %s",
                                    server_name, json.dumps(data)[:500])

                openai_tools = []
                for tool in tools:
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                        },
                    })

                _cache[server_name] = {"tools": openai_tools, "fetched_at": time.monotonic()}
                tool_names = [t["function"]["name"] for t in openai_tools]
                logger.info("Fetched %d MCP tools from '%s': %s",
                             len(openai_tools), server_name, tool_names)
                return openai_tools
        except Exception:
            logger.exception("Failed to fetch MCP tools from %s", url)
            if cached:
                return cached["tools"]
            return []


async def call_mcp_tool(tool_name: str, arguments: str) -> str:
    server_name = _find_server_for_tool(tool_name)
    url = _server_mcp_url(server_name) if server_name else f"{_litellm_base()}/mcp"

    try:
        args = json.loads(arguments) if arguments else {}
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args},
                    "id": 1,
                },
                headers={
                    "Authorization": f"Bearer {settings.LITELLM_API_KEY}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "text/event-stream" in ct:
                data = _parse_sse_json(resp.text)
            else:
                data = resp.json()
            content = data.get("result", {}).get("content", [])
            texts = [c.get("text", str(c)) for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else json.dumps(data.get("result", {}))
    except Exception as e:
        logger.exception("MCP tool call failed: %s", tool_name)
        return json.dumps({"error": f"MCP tool call failed: {e}"})


def _parse_sse_json(text: str) -> dict:
    """Extract JSON from an SSE response (parse the last 'data:' line)."""
    for line in reversed(text.strip().splitlines()):
        if line.startswith("data: "):
            return json.loads(line[6:])
    return json.loads(text)


def is_mcp_tool(name: str) -> bool:
    """Check if a tool name belongs to any cached MCP server."""
    return _find_server_for_tool(name) is not None


def _find_server_for_tool(tool_name: str) -> str | None:
    """Look up which server a tool belongs to from the cache."""
    for server_name, cached in _cache.items():
        for tool in cached.get("tools", []):
            if tool["function"]["name"] == tool_name:
                return server_name
    return None
