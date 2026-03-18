"""
Slack Socket Mode bot: routes Slack messages to the agent server POST /chat.
Runs as a separate process; no inbound ports. Configure via slack_config.yaml and env.
"""
import asyncio
import os
import re
import yaml
import httpx
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]  # xoxb-...
APP_LEVEL_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp-...
API_KEY = os.environ.get("AGENT_API_KEY") or os.environ.get("API_KEY")
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8000")

_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slack_config.yaml")
with open(_config_path) as f:
    cfg = yaml.safe_load(f) or {}

channel_map: dict[str, str] = cfg.get("channels", {})
user_map: dict[str, str] = cfg.get("users", {})
default_bot: str = cfg.get("default_bot", "default")
session_scope: str = cfg.get("session_scope", "user")

app = AsyncApp(token=BOT_TOKEN)
http = httpx.AsyncClient()


def resolve_bot(channel: str, user: str) -> str:
    # priority: user config → channel config → default
    return user_map.get(user) or channel_map.get(channel) or default_bot


def format_response_for_slack(response: str) -> str:
    """Replace [silent]...[/silent] with italicized muted indicator so it's visible but distinct."""
    if not response or not response.strip():
        return "_(no response)_"
    # Replace each [silent]...[/silent] with _🔇 inner_
    formatted = re.sub(
        r"\[silent\](.*?)\[/silent\]",
        lambda m: f"_🔇 {m.group(1).strip()}_",
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return formatted.strip()


async def dispatch(channel: str, user: str, text: str, say):
    text = (text or "").strip()
    if not text:
        await say("_No message to process._")
        return

    bot_id = resolve_bot(channel, user)
    client_id = f"slack:{user if session_scope == 'user' else channel}"

    try:
        r = await http.post(
            f"{AGENT_BASE_URL}/chat",
            json={"message": text, "bot_id": bot_id, "client_id": client_id},
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        reply = (body.get("response") or "").strip()
        await say(format_response_for_slack(reply))
    except Exception as e:
        await say(f"Error: {str(e)[:500]}")
        return


@app.event("message")
async def on_message(event, say):
    if event.get("subtype"):  # ignore edits, bot messages, joins, etc.
        return
    if event.get("bot_id"):  # ignore our own and other bots' messages
        return
    if (event.get("text") or "").strip().startswith("<@"):  # mention → handled by on_mention
        return
    await dispatch(event["channel"], event["user"], event.get("text", ""), say)


@app.event("app_mention")
async def on_mention(event, say):
    if event.get("bot_id"):
        return
    text = (event.get("text") or "").split(">", 1)[-1].strip()  # strip @mention prefix
    if not text:
        await say("_Say something after the mention._")
        return
    await dispatch(event["channel"], event["user"], text, say)


async def main():
    handler = AsyncSocketModeHandler(app, APP_LEVEL_TOKEN)
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
