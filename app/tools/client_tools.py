"""Registry of client-side tool schemas.

These tools are presented to the LLM like any other tool, but when invoked,
the server forwards the call to the client for execution (via a tool_request
SSE event) and waits for the result.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_client_tools: dict[str, dict[str, Any]] = {}


def register_client_tool(schema: dict) -> None:
    name = schema["function"]["name"]
    _client_tools[name] = schema
    logger.info("Registered client tool: %s", name)


def get_client_tool_schemas(allowed_names: list[str] | None = None) -> list[dict]:
    if not allowed_names:
        return []
    return [_client_tools[n] for n in allowed_names if n in _client_tools]


def is_client_tool(name: str) -> bool:
    return name in _client_tools


# ---------------------------------------------------------------------------
# Built-in client tool definitions
# ---------------------------------------------------------------------------

register_client_tool({
    "type": "function",
    "function": {
        "name": "shell_exec",
        "description": (
            "Execute a shell command on the user's local machine and return "
            "stdout/stderr. Use for system queries (disk space, uptime, "
            "network info, listing files, etc.). Commands run with the "
            "user's permissions. Prefer short, read-only commands."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
            },
            "required": ["command"],
        },
    },
})
