"""Slack message and app_mention → agent /chat."""
import base64
import logging

from agent_client import http, ensure_channel, store_passive_message_http, submit_chat, cancel_session
from session_helpers import slack_client_id
from slack_settings import BOT_TOKEN, ensure_config_fresh, get_bot_display_info, get_channel_config
from state import get_channel_state

logger = logging.getLogger(__name__)

# Cache Slack user display names to avoid repeated API calls.
# Key: Slack user ID (e.g., "U0AN0N161B8"), Value: display name string.
_user_name_cache: dict[str, str] = {}


async def _resolve_slack_display_name(client, user_id: str) -> str:
    """Look up a Slack user's display name, with caching.

    Tries profile.display_name first, falls back to real_name, then user_id.
    """
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]

    try:
        resp = await client.users_info(user=user_id)
        if resp and resp.get("ok"):
            profile = resp.get("user", {}).get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or resp.get("user", {}).get("real_name")
                or user_id
            )
            _user_name_cache[user_id] = name
            return name
    except Exception:
        logger.debug("Failed to resolve Slack user %s display name", user_id, exc_info=True)

    _user_name_cache[user_id] = user_id
    return user_id


# Max parent-thread messages to fetch and prepend when the bot is replying
# into an existing thread. Keeps context cost bounded; the user's triggering
# message is already included separately via ``dispatch``.
_THREAD_PARENT_LIMIT = 15


async def _fetch_thread_parent_summary(
    client, channel: str, thread_ts: str, current_ts: str | None
) -> str:
    """Summarize the parent thread so the agent has conversation context.

    Returns an empty string when no fetch is warranted (thread root equals
    the current message, API failure, or empty thread). Otherwise returns a
    compact text block: one line per prior message with sender + truncated
    text.
    """
    if not thread_ts or thread_ts == current_ts:
        return ""
    try:
        resp = await client.conversations_replies(
            channel=channel, ts=thread_ts, limit=_THREAD_PARENT_LIMIT,
        )
    except Exception:
        logger.debug(
            "conversations_replies failed for channel=%s ts=%s",
            channel, thread_ts, exc_info=True,
        )
        return ""
    if not resp or not resp.get("ok"):
        return ""

    lines: list[str] = []
    for msg in (resp.get("messages") or []):
        ts = msg.get("ts")
        if ts and current_ts and ts == current_ts:
            continue
        sender_id = msg.get("user") or msg.get("bot_id") or "unknown"
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        if len(text) > 400:
            text = text[:400].rstrip() + "…"
        if sender_id.startswith("B") or msg.get("bot_id"):
            sender_label = f"bot:{sender_id}"
        else:
            name = await _resolve_slack_display_name(client, sender_id)
            sender_label = f"{name} (<@{sender_id}>)"
        lines.append(f"- {sender_label}: {text}")

    if not lines:
        return ""
    return "[Thread context — prior messages in this thread, newest last]\n" + "\n".join(lines)

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
        # Track file metadata for server-side attachment persistence (includes bytes).
        # posted_by must be None for user uploads so that persist_turn's orphan-
        # linking associates them with the user message (not the assistant message).
        file_metadata.append({
            "url": url,
            "filename": name,
            "mime_type": mime,
            "size_bytes": size,
            "posted_by": None,
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


# NOTE — Phase F of the Integration Delivery refactor:
#
# ``SlackStreamBuffer``, ``_handle_client_actions``, ``_run_dispatch``, and
# the in-subprocess long-poll path that drove ``stream_chat`` are all
# DELETED. The Slack subprocess no longer posts to Slack itself — it
# just enqueues turns via ``submit_chat`` (POST /chat → 202) and the
# main-process ``SlackRenderer``
# (``integrations/slack/renderer.py``) consumes the channel-events bus
# to render the response, with a single shared rate limiter and a 0.8s
# coalesce window. That eliminated the rapid ``chat.update`` storm that
# caused Slack mobile clients to occasionally never refresh.
#
# The legacy versions of these functions remain in git history at
# commit d4567e59 (or earlier on `master`) if you need to compare.


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


async def dispatch(
    channel: str,
    user: str,
    text: str,
    say,
    client,
    files: list | None = None,
    thread_ts: str | None = None,
    mentioned: bool = False,
    message_ts: str | None = None,
):
    await ensure_config_fresh()
    text = (text or "").strip()

    config = get_channel_config(channel)
    state = get_channel_state(channel)
    bot_id = state["bot_id"] or config["bot_id"]
    client_id = slack_client_id(channel)

    # Approval gate: if enabled and channel is unknown, prompt for approval
    if _should_gate_channel(channel):
        from channel_approval import check_or_prompt_approval
        allowed = await check_or_prompt_approval(channel, bot_id, client, mentioned)
        if not allowed:
            return

    # Ensure Channel row exists on the server (idempotent, best-effort)
    await ensure_channel(client_id, bot_id)

    # STOP intercept: cancel in-progress agent loop (works regardless of require_mention)
    if text.upper() == "STOP":
        try:
            result = await cancel_session(client_id, bot_id)
            if result.get("cancelled") or result.get("queued_tasks_cancelled", 0) > 0:
                parts = []
                if result.get("cancelled"):
                    parts.append("active request cancelled")
                q = result.get("queued_tasks_cancelled", 0)
                if q:
                    parts.append(f"{q} queued message(s) cancelled")
                await client.chat_postMessage(
                    channel=channel,
                    text=f"_Cancellation requested: {', '.join(parts)}._",
                    thread_ts=thread_ts,
                )
            else:
                await client.chat_postMessage(
                    channel=channel,
                    text="_Nothing running to cancel._",
                    thread_ts=thread_ts,
                )
        except Exception:
            logger.exception("STOP cancel failed for channel %s", channel)
            await client.chat_postMessage(
                channel=channel,
                text="_Failed to cancel — server may be unreachable._",
                thread_ts=thread_ts,
            )
        return

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
    # allow_bot_messages=True: bot messages are always active (bypass require_mention).
    is_bot_sender = user.startswith("bot:")
    is_passive = not mentioned and config["require_mention"] and not (is_bot_sender and config.get("allow_bot_messages"))

    # Resolve Slack user's display name for attribution
    _slack_display_name = user
    if not is_bot_sender:
        _slack_display_name = await _resolve_slack_display_name(client, user)

    thread_summary = ""
    if thread_ts:
        thread_summary = await _fetch_thread_parent_summary(
            client, channel, thread_ts, message_ts,
        )

    # Per the ingest contract (docs/integrations/message-ingest-contract.md):
    # content is the raw user text; identity/routing/thread context lives in
    # metadata. The assembly layer composes the LLM-facing "[Name (<@U…>)]:"
    # prefix and injects thread_context as a system block adjacent to the turn.
    msg_metadata = {
        "passive": is_passive,
        "include_in_memory": config["passive_memory"],
        "trigger_rag": mentioned or not config["require_mention"] or (is_bot_sender and config.get("allow_bot_messages")),
        "source": "slack",
        "sender_type": "bot" if is_bot_sender else "human",
        "sender_id": f"slack:{user}",
        "sender_display_name": _slack_display_name,
        "channel_external_id": channel,
        # Only humans get a mention token — Slack bot users don't have one.
        "mention_token": None if is_bot_sender else f"<@{user}>",
        "thread_context": thread_summary or None,
        "recipient_id": f"bot:{bot_id}" if mentioned else None,
        # Persist the Slack-side identifiers so downstream consumers (thread
        # resolution, anchor linkage, outbound thread mirroring) can walk
        # from a Spindrel Message back to the Slack message it represents
        # without a dispatch_config lookup.
        "slack_channel": channel,
        "slack_ts": message_ts,
        "slack_thread_ts": thread_ts,
    }

    full_message = f"{text}{appended}"

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

    # Phase F: enqueue the turn on the server (POST /chat → 202) and
    # let the main-process SlackRenderer drive delivery via the bus.
    # The Slack subprocess no longer streams or posts to Slack itself.
    dispatch_config = {
        "channel_id": channel,
        "thread_ts": thread_ts,
        "message_ts": message_ts,
        "token": BOT_TOKEN,
        "reply_in_thread": bool(thread_ts),
    }
    try:
        await submit_chat(
            message=full_message,
            bot_id=bot_id,
            client_id=client_id,
            attachments=attachments if attachments else None,
            file_metadata=file_metadata if file_metadata else None,
            dispatch_type="slack",
            dispatch_config=dispatch_config,
            msg_metadata=msg_metadata,
        )
    except Exception:
        logger.exception("submit_chat failed for Slack channel %s", channel)
        try:
            await client.chat_postMessage(
                channel=channel,
                text="_Failed to enqueue request — server may be unreachable._",
                thread_ts=thread_ts,
            )
        except Exception:
            pass
        return

    # React with hourglass on the user's message so they know we got it.
    if message_ts:
        try:
            await client.reactions_add(
                channel=channel,
                name="hourglass_flowing_sand",
                timestamp=message_ts,
            )
        except Exception:
            logger.debug("Failed to add hourglass reaction", exc_info=True)


def _should_gate_channel(channel: str) -> bool:
    """Check if the channel should be gated by approval.

    Returns True if approval is enabled AND the channel is not already known
    in the config cache (i.e., not bound via legacy or modern binding).
    """
    from slack_settings import get_slack_config
    try:
        from app.services.integration_settings import get_value
        enabled = get_value("slack", "SLACK_REQUIRE_CHANNEL_APPROVAL", "false")
    except ImportError:
        import os
        enabled = os.environ.get("SLACK_REQUIRE_CHANNEL_APPROVAL", "false")
    if enabled.lower() not in ("true", "1", "yes"):
        return False
    # If channel is already in the config cache, it's known — no gate needed
    cfg = get_slack_config()
    known_channels = cfg.get("channels", {})
    return channel not in known_channels


def _handle_bot_message(event):
    """Check if a bot message should be processed. Returns (user, should_process)."""
    config = get_channel_config(event.get("channel", ""))
    if not config.get("allow_bot_messages", False):
        return None, False
    sender = event.get("bot_id") or event.get("username") or "unknown"
    return f"bot:{sender}", True


def register_message_handlers(app):
    # Slack Bolt only matches messages with NO subtype via @app.event("message").
    # Bot messages have subtype="bot_message" and need a dedicated handler.
    @app.event({"type": "message", "subtype": "bot_message"})
    async def on_bot_message(event, say, client):
        user, ok = _handle_bot_message(event)
        if not ok:
            return
        thread_ts = event.get("thread_ts")
        await dispatch(
            event["channel"],
            user,
            event.get("text", ""),
            say,
            client,
            event.get("files"),
            thread_ts=thread_ts,
            mentioned=False,
            message_ts=event.get("ts"),
        )

    @app.event("message")
    async def on_message(event, say, client):
        st = event.get("subtype")
        is_bot_msg = bool(event.get("bot_id"))

        if is_bot_msg:
            # Bot messages without subtype="bot_message" (rare but possible).
            user, ok = _handle_bot_message(event)
            if not ok:
                return
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

        thread_ts = event.get("thread_ts")
        await dispatch(
            event["channel"],
            user,
            event.get("text", ""),
            say,
            client,
            event.get("files"),
            thread_ts=thread_ts,
            mentioned=False,
            message_ts=event.get("ts"),
        )

    @app.event("app_mention")
    async def on_mention(event, say, client):
        if event.get("bot_id"):
            return
        text = (event.get("text") or "").split(">", 1)[-1].strip()
        thread_ts = event.get("thread_ts")
        await dispatch(
            event["channel"],
            event["user"],
            text,
            say,
            client,
            event.get("files"),
            thread_ts=thread_ts,
            mentioned=True,
            message_ts=event.get("ts"),
        )
