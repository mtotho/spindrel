"""Slack message and app_mention → agent /chat."""
import uuid

from agent_client import post_chat
from formatting import format_response_for_slack
from session_helpers import slack_client_id
from state import get_channel_state


async def dispatch(channel: str, user: str, text: str, say):
    text = (text or "").strip()
    if not text:
        await say("_No message to process._")
        return

    state = get_channel_state(channel)
    bot_id = state["bot_id"]
    client_id = slack_client_id(channel)
    session_id_override = state.get("session_id")
    if session_id_override is not None:
        session_id = session_id_override
    else:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{client_id}:{bot_id}"))

    message = f"[Slack channel:{channel} user:{user}] {text}"

    try:
        body = await post_chat(
            message=message,
            bot_id=bot_id,
            client_id=client_id,
            session_id=session_id,
        )
        reply = (body.get("response") or "").strip()
        await say(format_response_for_slack(reply))
    except Exception as e:
        await say(f"Error: {str(e)[:500]}")


def register_message_handlers(app):
    @app.event("message")
    async def on_message(event, say):
        if event.get("subtype"):
            return
        if event.get("bot_id"):
            return
        if (event.get("text") or "").strip().startswith("<@"):
            return
        await dispatch(event["channel"], event["user"], event.get("text", ""), say)

    @app.event("app_mention")
    async def on_mention(event, say):
        if event.get("bot_id"):
            return
        text = (event.get("text") or "").split(">", 1)[-1].strip()
        if not text:
            await say("_Say something after the mention._")
            return
        await dispatch(event["channel"], event["user"], text, say)
