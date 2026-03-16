import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {"tools": [], "fetched_at": 0.0}
_cache_ttl = 60.0
_lock = asyncio.Lock()


async def fetch_mcp_tools(allowed_servers: list[str] | None = None) -> list[dict]:
    if not allowed_servers:
        return []

    now = time.monotonic()
    if _cache["tools"] and (now - _cache["fetched_at"]) < _cache_ttl:
        return _filter_by_servers(_cache["tools"], allowed_servers)

    async with _lock:
        # Double-check after acquiring lock
        now = time.monotonic()
        if _cache["tools"] and (now - _cache["fetched_at"]) < _cache_ttl:
            return _filter_by_servers(_cache["tools"], allowed_servers)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    settings.LITELLM_MCP_URL,
                    json={"method": "tools/list"},
                    headers={"Authorization": f"Bearer {settings.LITELLM_API_KEY}"},
                )
                resp.raise_for_status()
                data = resp.json()
                tools = data.get("result", {}).get("tools", [])

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

                _cache["tools"] = openai_tools
                _cache["fetched_at"] = time.monotonic()
                logger.info("Fetched %d MCP tools", len(openai_tools))
        except Exception:
            logger.exception("Failed to fetch MCP tools")
            return _filter_by_servers(_cache["tools"], allowed_servers)

    return _filter_by_servers(_cache["tools"], allowed_servers)


async def call_mcp_tool(tool_name: str, arguments: str) -> str:
    try:
        args = json.loads(arguments) if arguments else {}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                settings.LITELLM_MCP_URL,
                json={
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args},
                },
                headers={"Authorization": f"Bearer {settings.LITELLM_API_KEY}"},
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("result", {}).get("content", [])
            texts = [c.get("text", str(c)) for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else json.dumps(data.get("result", {}))
    except Exception as e:
        logger.exception("MCP tool call failed: %s", tool_name)
        return json.dumps({"error": f"MCP tool call failed: {e}"})


def _filter_by_servers(tools: list[dict], allowed_servers: list[str]) -> list[dict]:
    return [
        t for t in tools
        if any(t["function"]["name"].startswith(f"{s}_") for s in allowed_servers)
    ]
