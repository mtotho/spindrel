import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

MCP_CONFIG_PATH = Path("mcp.yaml")

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")

_servers: dict[str, "MCPServerConfig"] = {}
_cache: dict[str, dict[str, Any]] = {}
_cache_ttl = 60.0
_lock = asyncio.Lock()


@dataclass
class MCPServerConfig:
    name: str
    url: str
    api_key: str = ""


def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} placeholders with environment variable values.

    Checks os.environ first, then falls back to pydantic settings (which
    loads from .env) for known config values.
    """
    from app.config import settings

    def _lookup(match: re.Match) -> str:
        var = match.group(1)
        env_val = os.environ.get(var)
        if env_val is not None:
            return env_val
        return getattr(settings, var, "")

    return _ENV_VAR_RE.sub(_lookup, value)


def load_mcp_config(config_path: Path = MCP_CONFIG_PATH) -> None:
    """Load MCP server definitions from mcp.yaml."""
    _servers.clear()
    if not config_path.exists():
        logger.info("No MCP config at %s, skipping", config_path)
        return

    with open(config_path) as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, dict):
        logger.warning("MCP config at %s is empty or invalid", config_path)
        return

    for name, conf in data.items():
        if not isinstance(conf, dict) or "url" not in conf:
            logger.warning("MCP server '%s' missing 'url', skipping", name)
            continue
        server = MCPServerConfig(
            name=name,
            url=_resolve_env_vars(str(conf["url"])),
            api_key=_resolve_env_vars(str(conf.get("api_key", ""))),
        )
        _servers[name] = server
        logger.info("Loaded MCP server: %s -> %s", name, server.url)


def _get_server(name: str) -> MCPServerConfig | None:
    return _servers.get(name)


async def fetch_mcp_tools(allowed_servers: list[str] | None = None) -> list[dict]:
    if not allowed_servers:
        return []

    all_tools: list[dict] = []
    for server_name in allowed_servers:
        server = _get_server(server_name)
        if not server:
            logger.warning("Bot references unknown MCP server '%s' (not in mcp.yaml)", server_name)
            continue
        tools = await _fetch_server_tools(server)
        all_tools.extend(tools)

    return all_tools


async def _fetch_server_tools(server: MCPServerConfig) -> list[dict]:
    now = time.monotonic()
    cached = _cache.get(server.name)
    if cached and (now - cached["fetched_at"]) < _cache_ttl:
        logger.debug("MCP cache hit for '%s': %d tools", server.name, len(cached["tools"]))
        return cached["tools"]

    async with _lock:
        cached = _cache.get(server.name)
        if cached and (time.monotonic() - cached["fetched_at"]) < _cache_ttl:
            return cached["tools"]

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if server.api_key:
            headers["Authorization"] = f"Bearer {server.api_key}"

        try:
            logger.info("Fetching MCP tools from %s", server.url)
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.post(
                    server.url,
                    json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.error("MCP server '%s' returned %d: %s",
                                  server.name, resp.status_code, resp.text[:500])
                    resp.raise_for_status()

                ct = resp.headers.get("content-type", "")
                if "text/event-stream" in ct:
                    data = _parse_sse_json(resp.text)
                else:
                    data = resp.json()

                tools = data.get("result", {}).get("tools", [])
                if not tools:
                    logger.warning("MCP server '%s' returned 0 tools", server.name)

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

                _cache[server.name] = {"tools": openai_tools, "fetched_at": time.monotonic()}
                tool_names = [t["function"]["name"] for t in openai_tools]
                logger.info("Fetched %d MCP tools from '%s': %s",
                             len(openai_tools), server.name, tool_names)

                async def _bg_index() -> None:
                    from app.agent.tools import index_mcp_tools

                    try:
                        await index_mcp_tools(server.name, openai_tools)
                    except Exception:
                        logger.exception("Background MCP tool index failed for %s", server.name)

                asyncio.create_task(_bg_index())
                return openai_tools
        except Exception:
            logger.exception("Failed to fetch MCP tools from %s", server.url)
            if cached:
                return cached["tools"]
            return []


async def call_mcp_tool(tool_name: str, arguments: str) -> str:
    server_name = _find_server_for_tool(tool_name)
    server = _get_server(server_name) if server_name else None
    if not server:
        return json.dumps({"error": f"No MCP server found for tool: {tool_name}"})

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if server.api_key:
        headers["Authorization"] = f"Bearer {server.api_key}"

    try:
        args = json.loads(arguments) if arguments else {}
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.post(
                server.url,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args},
                    "id": 1,
                },
                headers=headers,
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
