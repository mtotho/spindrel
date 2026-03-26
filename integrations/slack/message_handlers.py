"""Slack message and app_mention → agent /chat."""
import base64
import logging

from agent_client import http, ensure_channel, store_passive_message_http, stream_chat
from formatting import format_response_for_slack, format_tool_status, split_for_slack
from session_helpers import slack_client_id
from slack_settings import BOT_TOKEN, get_bot_display_info, get_channel_config
from state import get_channel_state

logger = logging.getLogger(__name__)

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


async def _process_slack_files(files: list[dict], user: str = "") -> tuple[str, list[dict], list[dict]]:
    """Download Slack shares: append text file bodies to the message; collect images for the API.

    Returns (text_parts_joined, attachments_for_vision, file_metadata_for_server).
    """
    text_parts: list[str] = []
    attachments: list[dict] = []
    file_metadata: list[dict] = []
    for f in files or []:
        mime = f.get("mimetype") or ""
        name = f.get("name") or "attachment"
        url = f.get("url_private_download") or f.get("url_private")
        size = f.get("size") or 0
        if not url:
            continue
        try:
            data = await _download_slack_file(url)
        except Exception as e:
            text_parts.append(f"\n[Could not fetch {name}: {e}]")
            continue
        # Track file metadata for server-side attachment persistence (includes bytes)
        file_metadata.append({
            "url": url,
            "filename": name,
            "mime_type": mime,
            "size_bytes": size,
            "posted_by": f"slack:{user}" if user else None,
            "file_data": base64.b64encode(data).decode("ascii"),
        })
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
    return "".join(text_parts), attachments, file_metadata


_DEFAULT_UPLOAD_USERNAME = "Attachment"
_DEFAULT_UPLOAD_ICON = ":camera:"


async def _handle_client_actions(client, channel: str, actions: list, *,
                                 thread_ts: str | None = None,
                                 identity: dict | None = None) -> None:
    for action in actions or []:
        if action.get("type") not in ("upload_image", "upload_file"):
            continue
        raw = action.get("data")
        if not raw:
            continue
        try:
            img_bytes = base64.b64decode(raw)
        except Exception:
            continue
        caption = action.get("caption") or None
        # Post caption as attributed message (file uploads always show as the app)
        if caption:
            msg_kwargs: dict = {
                "channel": channel,
                "text": caption,
                "username": (identity or {}).get("username") or _DEFAULT_UPLOAD_USERNAME,
                "icon_emoji": (identity or {}).get("icon_emoji") or _DEFAULT_UPLOAD_ICON,
            }
            if thread_ts:
                msg_kwargs["thread_ts"] = thread_ts
            try:
                await client.chat_postMessage(**msg_kwargs)
            except Exception:
                logger.warning("_handle_client_actions: failed to post caption message", exc_info=True)
        await client.files_upload_v2(
            channel=channel,
            content=img_bytes,
            filename=action.get("filename") or "generated.png",
        )


def _get_identity(bot_id: str) -> dict:
    """Build display identity kwargs for a bot (requires chat:write.customize scope)."""
    display_info = get_bot_display_info(bot_id)
    identity: dict = {}
    if display_info.get("display_name"):
        identity["username"] = display_info["display_name"]
    if display_info.get("icon_emoji"):
        identity["icon_emoji"] = display_info["icon_emoji"]
    elif display_info.get("icon_url"):
        identity["icon_url"] = display_info["icon_url"]
    return identity


async def _run_dispatch(channel: str, payload: dict, client, identity: dict) -> None:
    """Run one full agent dispatch cycle: post thinking placeholder, stream response, update/replace."""
    full_message = payload["full_message"]
    bot_id = payload["bot_id"]
    client_id = payload["client_id"]
    attachments = payload["attachments"]
    file_metadata = payload.get("file_metadata") or []
    dispatch_config = payload["dispatch_config"]
    thread_ts = payload["thread_ts"]
    msg_metadata = payload["msg_metadata"]

    # Defer posting the thinking placeholder until we know the server is actually
    # running the agent.  If the first event back is `queued`, we skip posting
    # entirely so there is no orphaned placeholder to clean up.
    thinking_ts: str | None = None
    thinking_channel: str | None = None

    async def _ensure_thinking() -> None:
        nonlocal thinking_ts, thinking_channel
        if thinking_ts is None:
            msg = await client.chat_postMessage(
                channel=channel,
                text="⏳ _thinking..._",
                **identity,
            )
            thinking_ts = msg["ts"]
            thinking_channel = msg["channel"]

    try:
        client_actions: list = []
        _delegation_posts_seen = False
        _assistant_texts_posted = False
        async for event in stream_chat(
            message=full_message,
            bot_id=bot_id,
            client_id=client_id,
            attachments=attachments if attachments else None,
            file_metadata=file_metadata if file_metadata else None,
            dispatch_type="slack",
            dispatch_config=dispatch_config,
            msg_metadata=msg_metadata,
        ):
            etype = event.get("type")
            if etype == "queued":
                # Server queued the message — response will arrive later via
                # the task dispatcher.  Nothing was posted, nothing to clean up.
                return
            await _ensure_thinking()
            if etype == "tool_start":
                tool = event.get("tool", "tool")
                status = format_tool_status(tool, event.get("args"))
                await client.chat_update(
                    channel=thinking_channel,
                    ts=thinking_ts,
                    text=status,
                    **identity,
                )
            elif etype == "assistant_text":
                # Intermediate text the LLM produced alongside tool calls.
                # Turn the current thinking placeholder into a real message,
                # then post a fresh thinking placeholder for the next tool cycle.
                _at_text = (event.get("text") or "").strip()
                if _at_text:
                    _assistant_texts_posted = True
                    formatted_at = format_response_for_slack(_at_text)
                    chunks_at = split_for_slack(formatted_at)
                    # First chunk replaces the thinking placeholder
                    await client.chat_update(
                        channel=thinking_channel,
                        ts=thinking_ts,
                        text=chunks_at[0],
                        **identity,
                    )
                    # Extra chunks as follow-up messages
                    for chunk in chunks_at[1:]:
                        await client.chat_postMessage(
                            channel=thinking_channel,
                            text=chunk,
                            thread_ts=thread_ts,
                            **identity,
                        )
                    # Post a fresh thinking placeholder for the next iteration
                    msg = await client.chat_postMessage(
                        channel=thinking_channel,
                        text="⏳ _working..._",
                        **identity,
                    )
                    thinking_ts = msg["ts"]
                    thinking_channel = msg["channel"]
            elif etype == "warning":
                _warn_code = event.get("code", "unknown")
                _warn_msg = event.get("message", "")
                logger.warning("Agent warning for channel %s: [%s] %s", channel, _warn_code, _warn_msg)
                # Show warnings inline in the thinking placeholder
                await client.chat_update(
                    channel=thinking_channel,
                    ts=thinking_ts,
                    text=f"⚠️ _{_warn_msg}_",
                    **identity,
                )
            elif etype == "error":
                _err_code = event.get("code", "")
                _err_msg = event.get("message") or event.get("detail") or "Unknown error"
                logger.error("Agent error for channel %s: [%s] %s", channel, _err_code, _err_msg)
                _err_display = f"⚠️ _{_err_msg[:500]}_"
                if thinking_ts and thinking_channel:
                    await client.chat_update(
                        channel=thinking_channel,
                        ts=thinking_ts,
                        text=_err_display,
                        **identity,
                    )
                else:
                    await client.chat_postMessage(
                        channel=channel,
                        text=_err_display,
                        **identity,
                    )
                thinking_ts = None
                return
            elif etype == "delegation_post":
                _delegation_posts_seen = True
                child_bot_id = event.get("bot_id") or ""
                child_text = (event.get("text") or "").strip()
                child_reply_in_thread = event.get("reply_in_thread", False)
                child_display = get_bot_display_info(child_bot_id)
                child_identity: dict = {}
                if child_display.get("display_name"):
                    child_identity["username"] = child_display["display_name"]
                if child_display.get("icon_emoji"):
                    child_identity["icon_emoji"] = child_display["icon_emoji"]
                elif child_display.get("icon_url"):
                    child_identity["icon_url"] = child_display["icon_url"]
                try:
                    await client.chat_postMessage(
                        channel=thinking_channel,
                        text=format_response_for_slack(child_text),
                        thread_ts=thread_ts if child_reply_in_thread else None,
                        **child_identity,
                    )
                except Exception:
                    pass
                # Handle child bot's client_actions (e.g. image uploads)
                child_actions = event.get("client_actions") or []
                if child_actions:
                    await _handle_client_actions(client, thinking_channel, child_actions,
                                                thread_ts=thread_ts, identity=child_identity)
            elif etype == "response":
                reply = (event.get("text") or "").strip()
                client_actions = event.get("client_actions") or []

                # If the final response is empty but we already posted intermediate
                # messages, just delete the trailing thinking placeholder.
                if not reply and _assistant_texts_posted:
                    try:
                        await client.chat_delete(
                            channel=thinking_channel,
                            ts=thinking_ts,
                        )
                    except Exception:
                        pass
                    # Clear thinking_ts so we don't try to update a deleted msg
                    thinking_ts = None
                else:
                    formatted = format_response_for_slack(reply)
                    chunks = split_for_slack(formatted)

                    if _delegation_posts_seen:
                        try:
                            await client.chat_delete(
                                channel=thinking_channel,
                                ts=thinking_ts,
                            )
                        except Exception:
                            pass
                        for chunk in chunks:
                            await client.chat_postMessage(
                                channel=thinking_channel,
                                text=chunk,
                                thread_ts=thread_ts,
                                **identity,
                            )
                    else:
                        # First chunk replaces the thinking placeholder.
                        await client.chat_update(
                            channel=thinking_channel,
                            ts=thinking_ts,
                            text=chunks[0],
                            **identity,
                        )
                        # Remaining chunks posted as follow-up messages.
                        for chunk in chunks[1:]:
                            await client.chat_postMessage(
                                channel=thinking_channel,
                                text=chunk,
                                thread_ts=thread_ts,
                                **identity,
                            )
        if thinking_channel:
            await _handle_client_actions(client, thinking_channel, client_actions,
                                        thread_ts=thread_ts, identity=identity)
    except Exception as e:
        logger.exception("Agent dispatch error for channel %s", channel)
        if thinking_ts and thinking_channel:
            await client.chat_update(
                channel=thinking_channel,
                ts=thinking_ts,
                text=f"_Error: {str(e)[:500]}_",
                **identity,
            )


async def dispatch(
    channel: str,
    user: str,
    text: str,
    say,
    client,
    files: list | None = None,
    thread_ts: str | None = None,
    mentioned: bool = False,
):
    text = (text or "").strip()

    config = get_channel_config(channel)
    state = get_channel_state(channel)
    bot_id = state["bot_id"] or config["bot_id"]
    client_id = slack_client_id(channel)

    # Ensure Channel row exists on the server (idempotent, best-effort)
    await ensure_channel(client_id, bot_id)

    appended, attachments, file_metadata = await _process_slack_files(files or [], user)

    if mentioned and not text and not appended and not attachments:
        text = "[@mention only, no user text — use channel context and respond.]"

    if not text and not appended and not attachments:
        return
    if not text and attachments and not appended:
        text = "(see attached image(s))"

    # Determine if this should be passive (stored but no agent run).
    # require_mention=True (default): only @mentions trigger the agent.
    # require_mention=False: all messages trigger the agent.
    is_passive = not mentioned and config["require_mention"]

    msg_metadata = {
        "passive": is_passive,
        "include_in_memory": config["passive_memory"],
        "trigger_rag": mentioned or not config["require_mention"],
        "source": "slack",
        "sender_type": "human",
        "sender_id": f"slack:{user}",
        "recipient_id": f"bot:{bot_id}" if mentioned else None,
    }

    full_message = f"[Slack channel:{channel} user:{user}] {text}{appended}"

    if is_passive:
        # Store message without running agent
        try:
            await store_passive_message_http(
                client_id=client_id,
                bot_id=bot_id,
                content=full_message,
                metadata=msg_metadata,
            )
        except Exception:
            logger.exception("Passive message storage failed for channel %s", channel)
        return

    dispatch_config = {
        "channel_id": channel,
        "thread_ts": thread_ts,
        "token": BOT_TOKEN,
    }
    identity = _get_identity(bot_id)
    payload = {
        "full_message": full_message,
        "bot_id": bot_id,
        "client_id": client_id,
        "attachments": attachments,
        "file_metadata": file_metadata,
        "dispatch_config": dispatch_config,
        "thread_ts": thread_ts,
        "msg_metadata": msg_metadata,
    }
    await _run_dispatch(channel, payload, client, identity)


def register_message_handlers(app):
    @app.event("message")
    async def on_message(event, say, client):
        st = event.get("subtype")
        is_bot_msg = st == "bot_message" or bool(event.get("bot_id"))

        if is_bot_msg:
            # Only pass through bot messages if the channel has opted in.
            config = get_channel_config(event.get("channel", ""))
            if not config.get("allow_bot_messages", False):
                return
            # Identify the sender as bot:<bot_id> or bot:<username>
            sender = event.get("bot_id") or event.get("username") or "unknown"
            user = f"bot:{sender}"
        else:
            # Most subtypes (channel_join, message_changed, …) are noise;
            # file uploads often use file_share.
            if st and st != "file_share":
                return
            if (event.get("text") or "").strip().startswith("<@"):
                return
            if (event.get("text") or "").strip().startswith("/"):
                return
            user = event.get("user", "")

        thread_ts = event.get("thread_ts") or event.get("ts")
        await dispatch(
            event["channel"],
            user,
            event.get("text", ""),
            say,
            client,
            event.get("files"),
            thread_ts=thread_ts,
            mentioned=False,
        )

    @app.event("app_mention")
    async def on_mention(event, say, client):
        if event.get("bot_id"):
            return
        text = (event.get("text") or "").split(">", 1)[-1].strip()
        thread_ts = event.get("thread_ts") or event.get("ts")
        await dispatch(
            event["channel"],
            event["user"],
            text,
            say,
            client,
            event.get("files"),
            thread_ts=thread_ts,
            mentioned=True,
        )
