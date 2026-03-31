"""Discord message -> agent /chat streaming dispatch."""
import base64
import logging
import time

import discord

from agent_client import ensure_channel, store_passive_message_http, stream_chat, cancel_session
from formatting import format_response_for_discord, format_thinking_for_discord, format_tool_status, split_for_discord
from session_helpers import discord_client_id
from discord_settings import DISCORD_TOKEN, get_bot_display_info, get_channel_config
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


async def _process_discord_files(attachments: list[discord.Attachment], user: str = "") -> tuple[str, list[dict], list[dict]]:
    """Download Discord attachments: append text file bodies to the message; collect images for the API.

    Returns (text_parts_joined, vision_attachments, file_metadata_for_server).
    """
    text_parts: list[str] = []
    vision_attachments: list[dict] = []
    file_metadata: list[dict] = []
    for att in attachments or []:
        mime = att.content_type or ""
        name = att.filename or "attachment"
        size = att.size or 0
        try:
            data = await att.read()
        except Exception as e:
            text_parts.append(f"\n[Could not fetch {name}: {e}]")
            continue
        file_metadata.append({
            "url": att.url,
            "filename": name,
            "mime_type": mime,
            "size_bytes": size,
            "posted_by": f"discord:{user}" if user else None,
            "file_data": base64.b64encode(data).decode("ascii"),
        })
        if any(mime.startswith(t) for t in TEXT_MIMES) or mime.startswith("text/"):
            raw = data[:MAX_TEXT_FILE_BYTES]
            content = raw.decode("utf-8", errors="replace")
            truncated = len(data) > MAX_TEXT_FILE_BYTES
            suffix = "\n[...truncated]" if truncated else ""
            text_parts.append(f"\n\n[Attached file: {name}]\n```\n{content}{suffix}\n```")
        elif mime.startswith("image/"):
            vision_attachments.append({
                "type": "image",
                "content": base64.b64encode(data).decode("ascii"),
                "mime_type": mime,
                "name": name,
            })
    return "".join(text_parts), vision_attachments, file_metadata


_STREAM_FLUSH_INTERVAL = 1.0  # seconds between Discord message edits (stricter rate limit than Slack)
_STREAM_MAX_CHARS = 2000  # Discord message limit


class DiscordStreamBuffer:
    """Accumulates streaming text_delta tokens and flushes to Discord periodically."""

    def __init__(self, message: discord.Message, thinking_display: str):
        self._message = message
        self._thinking_display = thinking_display
        self._content: list[str] = []
        self._last_flush: float = 0.0
        self.has_streamed: bool = False

    def add_content(self, delta: str) -> None:
        self._content.append(delta)

    async def maybe_flush(self) -> None:
        now = time.monotonic()
        if now - self._last_flush >= _STREAM_FLUSH_INTERVAL:
            await self.flush()

    async def flush(self) -> None:
        text = self._build_display()
        if not text:
            return
        self.has_streamed = True
        self._last_flush = time.monotonic()
        try:
            await self._message.edit(content=text)
        except Exception:
            logger.debug("DiscordStreamBuffer flush failed", exc_info=True)

    def _build_display(self) -> str:
        content_text = "".join(self._content).lstrip()
        if not content_text:
            return ""
        result = content_text + " ..."
        if len(result) > _STREAM_MAX_CHARS:
            result = "..." + result[-(_STREAM_MAX_CHARS - 3):]
        return result


async def _handle_client_actions(channel: discord.TextChannel, actions: list) -> None:
    """Handle client_actions like image uploads."""
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
        filename = action.get("filename") or "generated.png"
        caption = action.get("caption") or ""
        try:
            file = discord.File(fp=__import__("io").BytesIO(img_bytes), filename=filename)
            await channel.send(content=caption or None, file=file)
        except Exception:
            logger.warning("_handle_client_actions: failed to upload file", exc_info=True)


async def _run_dispatch(
    channel: discord.TextChannel,
    payload: dict,
) -> None:
    """Run one full agent dispatch cycle: post thinking placeholder, stream response, update/replace."""
    full_message = payload["full_message"]
    bot_id = payload["bot_id"]
    client_id = payload["client_id"]
    attachments = payload["attachments"]
    file_metadata = payload.get("file_metadata") or []
    dispatch_config = payload["dispatch_config"]
    msg_metadata = payload["msg_metadata"]
    thinking_display = payload.get("thinking_display", "append")
    user_message_id = payload.get("user_message_id")
    logger.info("Channel %s thinking_display=%s", channel.id, thinking_display)

    # Defer posting the thinking placeholder until we know the server is actually
    # running the agent.
    thinking_msg: discord.Message | None = None

    async def _ensure_thinking() -> None:
        nonlocal thinking_msg
        if thinking_msg is None:
            thinking_msg = await channel.send("\u23f3 *thinking...*")

    try:
        client_actions: list = []
        _delegation_posts_seen = False
        _assistant_texts_posted = False
        stream_buffer: DiscordStreamBuffer | None = None
        async for event in stream_chat(
            message=full_message,
            bot_id=bot_id,
            client_id=client_id,
            attachments=attachments if attachments else None,
            file_metadata=file_metadata if file_metadata else None,
            dispatch_type="discord",
            dispatch_config=dispatch_config,
            msg_metadata=msg_metadata,
        ):
            etype = event.get("type")
            if etype == "queued":
                # Server queued the message — response will arrive later via task dispatcher.
                # React with hourglass so user knows it's queued.
                if user_message_id:
                    try:
                        user_msg = await channel.fetch_message(int(user_message_id))
                        await user_msg.add_reaction("\u23f3")
                    except Exception:
                        logger.debug("Failed to add queued reaction", exc_info=True)
                return
            await _ensure_thinking()
            if etype == "text_delta":
                if stream_buffer is None:
                    stream_buffer = DiscordStreamBuffer(thinking_msg, thinking_display)
                stream_buffer.add_content(event.get("delta", ""))
                await stream_buffer.maybe_flush()
            elif etype == "thinking":
                pass
            elif etype == "thinking_content":
                _tc_text = (event.get("text") or "").strip()
                if _tc_text and thinking_display != "hidden":
                    _assistant_texts_posted = True
                    formatted_tc = format_thinking_for_discord(_tc_text)
                    chunks_tc = split_for_discord(formatted_tc)
                    if thinking_display == "replace":
                        await thinking_msg.edit(content=chunks_tc[0])
                    else:
                        # Append mode
                        await thinking_msg.edit(content=chunks_tc[0])
                        for chunk in chunks_tc[1:]:
                            await channel.send(chunk)
                        thinking_msg = await channel.send("\u23f3 *working...*")
            elif etype == "tool_start":
                # Force flush any streaming content before showing tool status
                if stream_buffer and stream_buffer.has_streamed:
                    await stream_buffer.flush()
                    _assistant_texts_posted = True
                    stream_buffer = None
                    if thinking_display == "append":
                        thinking_msg = await channel.send("\u23f3 *working...*")
                tool = event.get("tool", "tool")
                status = format_tool_status(tool, event.get("args"))
                await thinking_msg.edit(content=status)
            elif etype == "assistant_text":
                if stream_buffer and stream_buffer.has_streamed:
                    _assistant_texts_posted = True
                    await stream_buffer.flush()
                    stream_buffer = None
                    if thinking_display == "append":
                        thinking_msg = await channel.send("\u23f3 *working...*")
                    continue

                _at_text = (event.get("text") or "").strip()
                if _at_text:
                    if thinking_display == "hidden":
                        await thinking_msg.edit(content="\u23f3 *working...*")
                    elif thinking_display == "replace":
                        _assistant_texts_posted = True
                        formatted_at = format_thinking_for_discord(_at_text)
                        chunks_at = split_for_discord(formatted_at)
                        await thinking_msg.edit(content=chunks_at[0])
                    else:
                        # Append mode (default)
                        _assistant_texts_posted = True
                        formatted_at = format_thinking_for_discord(_at_text)
                        chunks_at = split_for_discord(formatted_at)
                        await thinking_msg.edit(content=chunks_at[0])
                        for chunk in chunks_at[1:]:
                            await channel.send(chunk)
                        thinking_msg = await channel.send("\u23f3 *working...*")
            elif etype == "tool_result":
                tool = event.get("tool", "tool")
                error = event.get("error")
                if error:
                    status = f"\u26a0\ufe0f {tool}: *{error[:100]}*"
                else:
                    status = f"\u2705 *{tool} done*"
                try:
                    await thinking_msg.edit(content=status)
                except Exception:
                    pass
            elif etype == "llm_retry":
                attempt = event.get("attempt", "?")
                max_att = event.get("max_retries", "?")
                reason = event.get("reason", "timeout")
                status = f"\u23f3 *LLM {reason}, retrying ({attempt}/{max_att})...*"
                try:
                    await thinking_msg.edit(content=status)
                except Exception:
                    pass
            elif etype == "llm_fallback":
                fallback_model = event.get("to_model", "fallback")
                status = f"\u23f3 *Switching to fallback model ({fallback_model})...*"
                try:
                    await thinking_msg.edit(content=status)
                except Exception:
                    pass
            elif etype == "approval_request":
                tool = event.get("tool", "tool")
                reason = event.get("reason", "")
                status = f"\U0001f512 *{tool}* needs approval"
                if reason:
                    status += f": {reason[:100]}"
                try:
                    await thinking_msg.edit(content=status)
                except Exception:
                    pass
            elif etype == "approval_resolved":
                verdict = event.get("verdict", "unknown")
                tool = event.get("tool", "tool")
                if verdict == "approved":
                    status = f"\u2705 *{tool}* approved \u2014 running..."
                else:
                    status = f"\u274c *{tool}* {verdict}"
                try:
                    await thinking_msg.edit(content=status)
                except Exception:
                    pass
            elif etype == "cancelled":
                if thinking_msg:
                    await thinking_msg.edit(content="*Cancelled.*")
                return
            elif etype == "warning":
                _warn_code = event.get("code", "unknown")
                _warn_msg = event.get("message", "")
                logger.warning("Agent warning for channel %s: [%s] %s", channel.id, _warn_code, _warn_msg)
                await thinking_msg.edit(content=f"\u26a0\ufe0f *{_warn_msg}*")
            elif etype == "error":
                _err_code = event.get("code", "")
                _err_msg = event.get("message") or event.get("detail") or "Unknown error"
                logger.error("Agent error for channel %s: [%s] %s", channel.id, _err_code, _err_msg)
                _err_display = f"\u26a0\ufe0f *{_err_msg[:500]}*"
                if thinking_msg:
                    await thinking_msg.edit(content=_err_display)
                else:
                    await channel.send(_err_display)
                thinking_msg = None
                return
            elif etype == "delegation_post":
                _delegation_posts_seen = True
                child_bot_id = event.get("bot_id") or ""
                child_text = (event.get("text") or "").strip()
                child_display = get_bot_display_info(child_bot_id)
                child_name = child_display.get("display_name") or child_bot_id
                _parent_name = get_bot_display_info(bot_id).get("display_name") or bot_id
                _attributed_text = f"*Delegated by {_parent_name}*\n{format_response_for_discord(child_text)}"
                try:
                    for chunk in split_for_discord(_attributed_text):
                        await channel.send(chunk)
                except Exception:
                    pass
                child_actions = event.get("client_actions") or []
                if child_actions:
                    await _handle_client_actions(channel, child_actions)
            elif etype == "response":
                if stream_buffer and stream_buffer.has_streamed:
                    stream_buffer = None

                reply = (event.get("text") or "").strip()
                client_actions = event.get("client_actions") or []

                if not reply and _assistant_texts_posted:
                    if thinking_display == "replace":
                        pass  # Leave last thought in place
                    else:
                        try:
                            await thinking_msg.delete()
                        except Exception:
                            pass
                        thinking_msg = None
                elif not reply and not _assistant_texts_posted:
                    try:
                        await thinking_msg.delete()
                    except Exception:
                        pass
                    thinking_msg = None
                else:
                    formatted = format_response_for_discord(reply)
                    chunks = split_for_discord(formatted)

                    if _delegation_posts_seen:
                        try:
                            await thinking_msg.delete()
                        except Exception:
                            pass
                        for chunk in chunks:
                            await channel.send(chunk)
                    else:
                        await thinking_msg.edit(content=chunks[0])
                        for chunk in chunks[1:]:
                            await channel.send(chunk)
        if client_actions:
            await _handle_client_actions(channel, client_actions)
    except Exception as e:
        logger.exception("Agent dispatch error for channel %s", channel.id)
        if thinking_msg:
            await thinking_msg.edit(content=f"*Error: {str(e)[:500]}*")


async def dispatch(
    message: discord.Message,
    *,
    mentioned: bool = False,
):
    """Main entry point for processing a Discord message."""
    channel = message.channel
    user = str(message.author.id)
    text = (message.content or "").strip()
    channel_id = str(channel.id)

    config = get_channel_config(channel_id)
    state = get_channel_state(channel_id)
    bot_id = state["bot_id"] or config["bot_id"]
    client_id = discord_client_id(channel_id)

    # Ensure Channel row exists on the server
    await ensure_channel(client_id, bot_id)

    # Strip the bot mention from the text if present
    if mentioned and message.mentions:
        for m in message.mentions:
            text = text.replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "").strip()

    # STOP intercept
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
                await channel.send(f"*Cancellation requested: {', '.join(parts)}.*")
            else:
                await channel.send("*Nothing running to cancel.*")
        except Exception:
            logger.exception("STOP cancel failed for channel %s", channel_id)
            await channel.send("*Failed to cancel \u2014 server may be unreachable.*")
        return

    appended, attachments, file_metadata = await _process_discord_files(
        message.attachments, user
    )

    if mentioned and not text and not appended and not attachments:
        text = "[@mention only, no user text \u2014 use channel context and respond.]"

    if not text and not appended and not attachments:
        return
    if not text and attachments and not appended:
        text = "(see attached image(s))"

    # Determine active vs passive
    is_bot_sender = message.author.bot
    is_passive = not mentioned and config["require_mention"] and not (is_bot_sender and config.get("allow_bot_messages"))

    msg_metadata = {
        "passive": is_passive,
        "include_in_memory": config["passive_memory"],
        "trigger_rag": mentioned or not config["require_mention"] or (is_bot_sender and config.get("allow_bot_messages")),
        "source": "discord",
        "sender_type": "bot" if is_bot_sender else "human",
        "sender_id": f"discord:{user}",
        "recipient_id": f"bot:{bot_id}" if mentioned else None,
    }

    full_message = f"[Discord channel:{channel_id} user:{message.author.display_name}] {text}{appended}"

    if is_passive:
        try:
            await store_passive_message_http(
                client_id=client_id,
                bot_id=bot_id,
                content=full_message,
                metadata=msg_metadata,
            )
        except Exception:
            logger.exception("Passive message storage failed for channel %s", channel_id)
        return

    dispatch_config = {
        "channel_id": channel_id,
        "user_message_id": str(message.id),
        "token": DISCORD_TOKEN,
    }
    payload = {
        "full_message": full_message,
        "bot_id": bot_id,
        "client_id": client_id,
        "attachments": attachments,
        "file_metadata": file_metadata,
        "dispatch_config": dispatch_config,
        "msg_metadata": msg_metadata,
        "thinking_display": config.get("thinking_display", "append"),
        "user_message_id": str(message.id),
    }
    await _run_dispatch(channel, payload)
