#!/usr/bin/env python3
"""agent-cli: CLI for interacting with the agent server from workspace containers.

Installed at /usr/local/bin/agent in workspace containers.
Reads AGENT_SERVER_URL and AGENT_SERVER_API_KEY from environment.

Usage:
    agent discover              Show available API endpoints
    agent chat <message>        Send a chat message
    agent channels              List channels
    agent channels get <id>     Get channel details
    agent channels create       Create/get channel (--bot-id, --client-id)
    agent channels messages <id> [--inject "msg"]  List or inject messages
    agent tasks                 List tasks
    agent tasks get <id>        Get task details
    agent tasks wait <id>       Poll task until complete
    agent api <METHOD> <path> [body]  Raw API call (like agent-api)
    agent docs [scope]          Show API documentation for your permissions
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import urljoin

try:
    import httpx
except ImportError:
    # Fallback: use urllib if httpx not available
    httpx = None

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("AGENT_SERVER_URL", "")
API_KEY = os.environ.get("AGENT_SERVER_API_KEY", "")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _url(path: str) -> str:
    base = BASE_URL.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _request(method: str, path: str, body: dict | str | None = None,
             params: dict | None = None) -> dict | list | str:
    """Make an HTTP request. Returns parsed JSON or raw text."""
    url = _url(path)
    headers = _headers()

    if httpx is not None:
        return _request_httpx(method, url, headers, body, params)
    return _request_urllib(method, url, headers, body, params)


def _request_httpx(method, url, headers, body, params):
    kwargs: dict = {"headers": headers, "timeout": 60.0}
    if params:
        kwargs["params"] = params
    if body is not None:
        if isinstance(body, str):
            kwargs["content"] = body
        else:
            kwargs["json"] = body

    r = httpx.request(method.upper(), url, **kwargs)
    if r.status_code >= 400:
        _error(f"HTTP {r.status_code}: {r.text}")
    try:
        return r.json()
    except Exception:
        return r.text


def _request_urllib(method, url, headers, body, params):
    import urllib.request
    import urllib.error
    import urllib.parse

    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    data = None
    if body is not None:
        if isinstance(body, str):
            data = body.encode()
        else:
            data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode()
    except urllib.error.HTTPError as e:
        _error(f"HTTP {e.code}: {e.read().decode()}")
    try:
        return json.loads(text)
    except Exception:
        return text


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _error(msg: str):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def _check_env():
    if not BASE_URL:
        _error("AGENT_SERVER_URL not set")
    if not API_KEY:
        _error("AGENT_SERVER_API_KEY not set")


def _json_out(data):
    """Pretty-print JSON data."""
    print(json.dumps(data, indent=2, default=str))


def _table(rows: list[dict], columns: list[str], headers: list[str] | None = None):
    """Print a simple table."""
    if not rows:
        print("(no results)")
        return
    hdrs = headers or columns
    widths = [len(h) for h in hdrs]
    str_rows = []
    for row in rows:
        vals = []
        for i, col in enumerate(columns):
            v = str(row.get(col, ""))
            if len(v) > 60:
                v = v[:57] + "..."
            vals.append(v)
            widths[i] = max(widths[i], len(v))
        str_rows.append(vals)

    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*hdrs))
    print(fmt.format(*["-" * w for w in widths]))
    for vals in str_rows:
        print(fmt.format(*vals))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_discover(args):
    """Show available API endpoints for your key."""
    data = _request("GET", "/api/v1/discover")
    if data.get("name"):
        print(f"Key: {data['name']}")
    if data.get("scopes"):
        print(f"Scopes: {', '.join(data['scopes'])}")
    print()
    _table(data.get("endpoints", []),
           ["method", "path", "description"],
           ["Method", "Path", "Description"])


def cmd_chat(args):
    """Send a chat message."""
    if not args:
        _error("Usage: agent chat <message> [--bot-id ID] [--channel-id ID]")

    bot_id = _pop_flag(args, "--bot-id")
    channel_id = _pop_flag(args, "--channel-id")
    client_id = _pop_flag(args, "--client-id") or "agent-cli"
    message = " ".join(args)

    body: dict = {
        "message": message,
        "bot_id": bot_id or os.environ.get("BOT_ID", ""),
        "client_id": client_id,
    }
    if channel_id:
        body["channel_id"] = channel_id

    data = _request("POST", "/chat", body)
    if isinstance(data, dict):
        print(data.get("response", json.dumps(data, indent=2)))
    else:
        print(data)


def cmd_channels(args):
    """Channel operations."""
    if not args:
        # List channels
        data = _request("GET", "/api/v1/channels")
        if isinstance(data, list):
            _table(data, ["id", "name", "bot_id", "integration"],
                   ["ID", "Name", "Bot", "Integration"])
        else:
            _json_out(data)
        return

    sub = args[0]
    rest = args[1:]

    if sub == "get" and rest:
        data = _request("GET", f"/api/v1/channels/{rest[0]}")
        _json_out(data)
    elif sub == "create":
        bot_id = _pop_flag(rest, "--bot-id") or os.environ.get("BOT_ID", "")
        client_id = _pop_flag(rest, "--client-id") or "agent-cli"
        data = _request("POST", "/api/v1/channels",
                        {"bot_id": bot_id, "client_id": client_id})
        _json_out(data)
    elif sub == "messages" and rest:
        ch_id = rest[0]
        inject = _pop_flag(rest[1:], "--inject")
        if inject:
            data = _request("POST", f"/api/v1/channels/{ch_id}/messages",
                            {"content": inject, "role": "user", "source": "agent-cli"})
            _json_out(data)
        else:
            data = _request("GET", f"/api/v1/channels/{ch_id}/messages/search",
                            params={"limit": "20"})
            if isinstance(data, list):
                for msg in data:
                    role = msg.get("role", "?")
                    content = str(msg.get("content", ""))[:120]
                    ts = msg.get("created_at", "")[:19]
                    print(f"[{ts}] {role}: {content}")
            else:
                _json_out(data)
    elif sub == "reset" and rest:
        data = _request("POST", f"/api/v1/channels/{rest[0]}/reset")
        _json_out(data)
    else:
        _error(f"Unknown channels subcommand: {sub}")


def cmd_tasks(args):
    """Task operations."""
    if not args:
        data = _request("GET", "/api/v1/tasks")
        if isinstance(data, list):
            _table(data, ["id", "status", "type", "created_at"],
                   ["ID", "Status", "Type", "Created"])
        else:
            _json_out(data)
        return

    sub = args[0]
    rest = args[1:]

    if sub == "get" and rest:
        data = _request("GET", f"/api/v1/tasks/{rest[0]}")
        _json_out(data)
    elif sub == "wait" and rest:
        task_id = rest[0]
        interval = int(_pop_flag(rest[1:], "--interval") or "5")
        print(f"Waiting for task {task_id}...", file=sys.stderr)
        while True:
            data = _request("GET", f"/api/v1/tasks/{task_id}")
            status = data.get("status", "unknown") if isinstance(data, dict) else "unknown"
            if status in ("complete", "completed", "failed", "error"):
                _json_out(data)
                sys.exit(0 if status in ("complete", "completed") else 1)
            print(f"  status: {status}", file=sys.stderr)
            time.sleep(interval)
    else:
        _error(f"Unknown tasks subcommand: {sub}")


def cmd_docs(args):
    """Show full API documentation for your permissions.

    Uses the discover endpoint's ?detail=true for rich markdown docs.
    Usage: agent docs
    """
    # Fetch detailed markdown docs from the server
    data = _request("GET", "/api/v1/discover", params={"detail": "true"})
    if isinstance(data, str):
        print(data)
    else:
        # Fallback: structured response
        _json_out(data)


def cmd_api(args):
    """Raw API call — compatible with the old agent-api shell script."""
    if len(args) < 2:
        _error("Usage: agent api <METHOD> <path> [json_body]")

    method = args[0]
    path = args[1]
    body = None
    if len(args) > 2:
        body_str = " ".join(args[2:])
        try:
            body = json.loads(body_str)
        except json.JSONDecodeError:
            body = body_str

    data = _request(method, path, body)
    if isinstance(data, (dict, list)):
        _json_out(data)
    else:
        print(data)


# ---------------------------------------------------------------------------
# Arg parsing helpers
# ---------------------------------------------------------------------------

def _pop_flag(args: list, flag: str) -> str | None:
    """Pop a --flag value from args list. Returns the value or None."""
    try:
        idx = args.index(flag)
        if idx + 1 < len(args):
            val = args[idx + 1]
            args.pop(idx + 1)
            args.pop(idx)
            return val
        args.pop(idx)
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COMMANDS = {
    "discover": cmd_discover,
    "chat": cmd_chat,
    "channels": cmd_channels,
    "tasks": cmd_tasks,
    "docs": cmd_docs,
    "api": cmd_api,
}

HELP = """agent-cli: Interact with the agent server from workspace containers.

Commands:
  discover              Show available API endpoints for your key
  chat <message>        Send a chat message
  channels              List channels
  channels get <id>     Get channel details
  channels create       Create channel (--bot-id, --client-id)
  channels messages <id> [--inject "msg"]
  tasks                 List tasks
  tasks get <id>        Get task details
  tasks wait <id>       Poll until task completes
  docs [scope]          Show API docs for your permissions
  api <METHOD> <path>   Raw API call

Environment:
  AGENT_SERVER_URL      Server base URL (auto-set in workspace containers)
  AGENT_SERVER_API_KEY  API key for auth (auto-set in workspace containers)
  BOT_ID                Default bot ID for chat commands

Examples:
  agent discover
  agent chat "What channels do I have access to?"
  agent channels
  agent api GET /api/v1/channels | jq .
  agent docs chat
"""


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        sys.exit(0)

    cmd_name = args[0]
    if cmd_name not in COMMANDS:
        _error(f"Unknown command: {cmd_name}\nRun 'agent --help' for usage.")

    _check_env()
    COMMANDS[cmd_name](args[1:])


if __name__ == "__main__":
    main()
