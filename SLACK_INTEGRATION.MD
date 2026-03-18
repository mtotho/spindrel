# Slack Integration Plan

**Implemented.** The bot is in `slack_bot.py`, config in `slack_config.yaml`. When `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set in `.env`, `./scripts/dev-server.sh` starts the Slack bot automatically.

## Overview

Implement a Slack Socket Mode bot that routes messages to the existing FastAPI agent server (`/chat`) with no inbound exposure. Slack pushes events over an outbound WebSocket; the bot calls the agent server as an HTTP client.

## New Files

### `slack_bot.py` (project root, alongside `main.py`)

```python
import asyncio
import os
import yaml
import httpx
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

BOT_TOKEN       = os.environ["SLACK_BOT_TOKEN"]    # xoxb-...
APP_LEVEL_TOKEN = os.environ["SLACK_APP_TOKEN"]    # xapp-...
API_KEY         = os.environ["AGENT_API_KEY"]
AGENT_BASE_URL  = os.environ.get("AGENT_BASE_URL", "http://localhost:8000")

with open("slack_config.yaml") as f:
    cfg = yaml.safe_load(f)

channel_map: dict[str, str] = cfg.get("channels", {})
user_map: dict[str, str]    = cfg.get("users", {})
default_bot: str            = cfg.get("default_bot", "default")
session_scope: str          = cfg.get("session_scope", "user")

app = AsyncApp(token=BOT_TOKEN)
http = httpx.AsyncClient()


def resolve_bot(channel: str, user: str) -> str:
    # priority: user config → channel config → default
    return user_map.get(user) or channel_map.get(channel) or default_bot


async def dispatch(channel: str, user: str, text: str, say):
    bot_id    = resolve_bot(channel, user)
    client_id = f"slack:{user if session_scope == 'user' else channel}"

    try:
        r = await http.post(
            f"{AGENT_BASE_URL}/chat",
            json={"message": text, "bot_id": bot_id, "client_id": client_id},
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=120,
        )
        r.raise_for_status()
        await say(r.json()["response"])
    except Exception as e:
        await say(f"Error: {e}")


@app.event("message")
async def on_message(event, say):
    if event.get("subtype"):  # ignore edits, bot messages, joins, etc.
        return
    await dispatch(event["channel"], event["user"], event["text"], say)


@app.event("app_mention")
async def on_mention(event, say):
    text = event["text"].split(">", 1)[-1].strip()  # strip @mention prefix
    await dispatch(event["channel"], event["user"], text, say)


async def main():
    handler = AsyncSocketModeHandler(app, APP_LEVEL_TOKEN)
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
```

---

### `slack_config.yaml` (project root, alongside `bots/`)

```yaml
default_bot: assistant
session_scope: user  # "user" = per-user sessions, "channel" = shared session

# Optional: map specific channels to a bot (fallback if user not mapped)
channels:
  C08ABC123: assistant

# Per-user bot assignment (takes priority over channel)
users:
  U08ABC123: bennie
  U08DEF456: coding-helper
```

To change a bot assignment: edit this file and restart `slack_bot.py`. To find a Slack user ID, check the member profile in Slack or log `event["user"]` on first message.

---

## Env Vars

Add to `.env`:

```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
AGENT_API_KEY=...              # same key already used by other clients
AGENT_BASE_URL=http://localhost:8000   # optional, defaults to localhost
```

---

## Dependencies

Add to `requirements.txt` / `pyproject.toml`:

```
slack-bolt
httpx
```

---

## Slack App Configuration (api.slack.com)

1. Create a new app (or use existing) → **Socket Mode** → Enable → generates `xapp-` App-Level Token with `connections:write` scope
2. **OAuth & Permissions** → Bot Token Scopes: `chat:write`, `im:history`, `channels:history`, `groups:history`
3. **Event Subscriptions** → Subscribe to bot events: `message.channels`, `message.im`, `app_mention`
4. Install app to workspace → copy `xoxb-` Bot Token

---

## How It Works

- `slack_bot.py` runs as a **separate process** alongside the existing FastAPI server
- It opens an outbound WebSocket to Slack (no inbound ports/firewall rules needed)
- Slack pushes message events over the socket
- `dispatch()` calls `POST /chat` on the agent server — same endpoint used by all other clients
- `session_scope: user` means each Slack user gets their own persistent session per bot (isolated from mobile/web sessions via `slack:` prefix on `client_id`)
- Restart `slack_bot.py` to pick up config changes

---

## Running

```bash
python slack_bot.py
```

Or run `./scripts/dev-server.sh` — it starts the Slack bot in the background when both Slack tokens are set in `.env`.