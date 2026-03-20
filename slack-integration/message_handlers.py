"""Slack message and app_mention → agent /chat."""
import base64
import uuid

from agent_client import http, stream_chat
from formatting import format_response_for_slack
from session_helpers import slack_client_id
from slack_settings import BOT_TOKEN
from state import get_channel_state

TEXT_MIMES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "application/json",
    "application/xml",
    "text/x-python",
    "application/x-yaml",
}
MAX_TEXT_FILE_BYTES = 32_000  # ~8k tokens


async def _download_slack_file(url: str) -> bytes:
    r = await http.get(url, headers={"Authorization": f"Bearer {BOT_TOKEN}"})
    r.raise_for_status()
    return r.content


async def _process_slack_files(files: list[dict]) -> tuple[str, list[dict]]:
    """Download Slack shares: append text file bodies to the message; collect images for the API."""
    text_parts: list[str] = []
    attachments: list[dict] = []
    for f in files or []:
        mime = f.get("mimetype") or ""
        name = f.get("name") or "attachment"
        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            continue
        try:
            data = await _download_slack_file(url)
        except Exception as e:
            text_parts.append(f"\n[Could not fetch {name}: {e}]")
            continue
        if mime in TEXT_MIMES or mime.startswith("text/"):
            raw = data[:MAX_TEXT_FILE_BYTES]
            content = raw.decode("utf-8", errors="replace")
            truncated = len(data) > MAX_TEXT_FILE_BYTES
            suffix = "\n[...truncated]" if truncated else ""
            text_parts.append(f"\n\n[Attached file: {name}]\n```\n{content}{suffix}\n```")
        elif mime.startswith("image/"):
            attachments.append({
                "type": "image",
                "content": base64.b64encode(data).decode("ascii"),
                "mime_type": mime,
                "name": name,
            })
    return "".join(text_parts), attachments


async def _handle_client_actions(client, channel: str, actions: list) -> None:
    for action in actions or []:
        if action.get("type") != "upload_image":
            continue
        raw = action.get("data")
        if not raw:
            continue
        try:
            img_bytes = base64.b64decode(raw)
        except Exception:
            continue
        caption = action.get("caption") or None
        await client.files_upload_v2(
            channel=channel,
            content=img_bytes,
            filename=action.get("filename") or "generated.png",
            initial_comment=caption,
        )


async def dispatch(
    channel: str,
    user: str,
    text: str,
    say,
    client,
    files: list | None = None,
    thread_ts: str | None = None,
):
    text = (text or "").strip()

    state = get_channel_state(channel)
    bot_id = state["bot_id"]
    client_id = slack_client_id(channel)
    session_id_override = state.get("session_id")
    if session_id_override is not None:
        session_id = session_id_override
    else:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{client_id}:{bot_id}"))

    appended, attachments = await _process_slack_files(files or [])

    if not text and not appended and not attachments:
        await say("_No message to process._")
        return
    if not text and attachments and not appended:
        text = "(see attached image(s))"

    message = f"[Slack channel:{channel} user:{user}] {text}{appended}"

    dispatch_config = {
        "channel_id": channel,
        "thread_ts": thread_ts,
        "token": BOT_TOKEN,
    }

    # Post a placeholder immediately so the user sees the bot is working
    thinking_msg = await say("⏳ _thinking..._")
    thinking_ts = thinking_msg["ts"]
    thinking_channel = thinking_msg["channel"]

    try:
        client_actions: list = []
        async for event in stream_chat(
            message=message,
            bot_id=bot_id,
            client_id=client_id,
            session_id=session_id,
            attachments=attachments if attachments else None,
            dispatch_type="slack",
            dispatch_config=dispatch_config,
        ):
            etype = event.get("type")
            if etype == "tool_start":
                tool = event.get("tool", "tool")
                await client.chat_update(
                    channel=thinking_channel,
                    ts=thinking_ts,
                    text=f"🔧 _{tool}..._",
                )
            elif etype == "response":
                reply = (event.get("text") or "").strip()
                client_actions = event.get("client_actions") or []
                await client.chat_update(
                    channel=thinking_channel,
                    ts=thinking_ts,
                    text=format_response_for_slack(reply),
                )
        await _handle_client_actions(client, thinking_channel, client_actions)
    except Exception as e:
        await client.chat_update(
            channel=thinking_channel,
            ts=thinking_ts,
            text=f"_Error: {str(e)[:500]}_",
        )


def register_message_handlers(app):
    @app.event("message")
    async def on_message(event, say, client):
        # Most subtypes (bot_message, channel_join, …) are noise; file uploads often use file_share.
        st = event.get("subtype")
        if st and st != "file_share":
            return
        if event.get("bot_id"):
            return
        if (event.get("text") or "").strip().startswith("<@"):
            return
        thread_ts = event.get("thread_ts") or event.get("ts")
        await dispatch(
            event["channel"],
            event["user"],
            event.get("text", ""),
            say,
            client,
            event.get("files"),
            thread_ts=thread_ts,
        )

    @app.event("app_mention")
    async def on_mention(event, say, client):
        if event.get("bot_id"):
            return
        text = (event.get("text") or "").split(">", 1)[-1].strip()
        if not text and not event.get("files"):
            await say("_Say something after the mention, or attach a file._")
            return
        thread_ts = event.get("thread_ts") or event.get("ts")
        await dispatch(
            event["channel"],
            event["user"],
            text,
            say,
            client,
            event.get("files"),
            thread_ts=thread_ts,
        )
