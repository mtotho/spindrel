"""Multi-bot channel logic: routing, mentions, rewriting, member bot execution."""
import asyncio
import copy
import logging
import uuid

# Use module imports (not `from X import Y`) so source-level patches
# like patch("app.agent.bots.get_bot") propagate through attribute access.
from app.agent import bots as _bots_mod
from app.agent import context as _ctx_mod
from app.agent import loop as _loop_mod
from app.services import sessions as _sessions_mod
from app.services.channel_throttle import is_throttled as _channel_throttled, record_run as _record_channel_run
from app.services import session_locks

from ._context import prepare_bot_context
from ._mirror import _mirror_to_integration

logger = logging.getLogger(__name__)

# Hold references to background asyncio tasks so they aren't GC'd before completion.
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


async def _maybe_route_to_member_bot(db, channel, bot, message: str):
    """Check if the user @-tagged a member bot and route to it.

    Returns (BotConfig, member_config_dict) — member_config_dict is {} for the primary bot.
    Uses the same session (shared history) — only the responding bot changes.
    """
    if not message:
        return bot, {}

    from app.agent.tags import _TAG_RE
    from app.db.models import ChannelBotMember
    from sqlalchemy import select

    # Quick regex scan — look for @bot:name or plain @name patterns
    tag_matches = _TAG_RE.findall(message)
    if not tag_matches:
        return bot, {}

    # Load channel member bot rows (with config)
    result = await db.execute(
        select(ChannelBotMember).where(ChannelBotMember.channel_id == channel.id)
    )
    member_rows = {row.bot_id: row for row in result.scalars().all()}
    if not member_rows:
        return bot, {}

    # Build case-insensitive reverse lookup: lowercase(bot_id) → bot_id,
    # lowercase(display_name) → bot_id.  Consistent with _detect_member_mentions.
    name_to_id: dict[str, str] = {}
    for bot_id in member_rows:
        name_to_id[bot_id.lower()] = bot_id
        try:
            _bot_cfg = _bots_mod.get_bot(bot_id)
            if _bot_cfg and _bot_cfg.name:
                name_to_id[_bot_cfg.name.lower()] = bot_id
        except Exception:
            pass

    # Check each tag for a member bot match
    for prefix, name in tag_matches:
        forced_type = prefix.rstrip(":") if prefix else None
        # Only consider bot-typed tags or untyped tags that match a member
        if forced_type and forced_type != "bot":
            continue
        resolved_id = name_to_id.get(name.lower())
        if resolved_id:
            try:
                member_bot = _bots_mod.get_bot(resolved_id)
                logger.info(
                    "Routing to member bot %r in channel %s (was primary %r)",
                    resolved_id, channel.id, bot.id,
                )
                return member_bot, member_rows[resolved_id].config or {}
            except Exception:
                logger.warning("Member bot %r not found in registry", resolved_id)

    return bot, {}


# ---------------------------------------------------------------------------
# Bot-to-bot @-mention: when a bot's response mentions another channel bot
# (member or primary), trigger a follow-up run so that bot responds.
# ---------------------------------------------------------------------------
_MEMBER_MENTION_MAX_DEPTH = 3


async def _detect_member_mentions(
    channel_id: uuid.UUID,
    responding_bot_id: str,
    response_text: str,
    *,
    _depth: int = 0,
) -> list[tuple[str, dict]]:
    """Detect which channel bots are @-mentioned in a response.

    Returns a list of (bot_id, config) tuples for mentioned bots.
    Includes both member bots AND the primary bot — so member bots can
    mention the primary bot back for back-and-forth conversation.
    """
    if _depth >= _MEMBER_MENTION_MAX_DEPTH:
        return []
    if not response_text:
        return []

    from app.agent.tags import _TAG_RE
    from app.db.engine import async_session as _async_session
    from app.db.models import Channel, ChannelBotMember
    from sqlalchemy import select

    tag_matches = _TAG_RE.findall(response_text)
    if not tag_matches:
        return []

    # Load member bots AND the primary bot for this channel
    async with _async_session() as db:
        rows = (await db.execute(
            select(ChannelBotMember).where(ChannelBotMember.channel_id == channel_id)
        )).scalars().all()
        channel = await db.get(Channel, channel_id)

    member_map = {r.bot_id: r.config or {} for r in rows}
    # Include primary bot as a valid mention target (enables back-and-forth)
    if channel and channel.bot_id and channel.bot_id not in member_map:
        member_map[channel.bot_id] = {}
    if not member_map:
        return []

    # Build case-insensitive reverse lookup: lowercase(bot_id) → bot_id,
    # lowercase(display_name) → bot_id.  This allows @Rolland to resolve to "qa-bot".
    name_to_id: dict[str, str] = {}
    for bot_id in member_map:
        name_to_id[bot_id.lower()] = bot_id
        try:
            _bot_cfg = _bots_mod.get_bot(bot_id)
            if _bot_cfg and _bot_cfg.name:
                name_to_id[_bot_cfg.name.lower()] = bot_id
        except Exception:
            pass

    # Deduplicate mentioned member bots (preserve order)
    mentioned: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for prefix, name in tag_matches:
        forced_type = prefix.rstrip(":") if prefix else None
        if forced_type and forced_type != "bot":
            continue
        resolved_id = name_to_id.get(name.lower())
        if resolved_id and resolved_id != responding_bot_id and resolved_id not in seen:
            mentioned.append((resolved_id, member_map[resolved_id]))
            seen.add(resolved_id)

    return mentioned


async def _trigger_member_bot_replies(
    channel_id: uuid.UUID,
    session_id: uuid.UUID,
    responding_bot_id: str,
    response_text: str,
    *,
    _depth: int = 0,
    messages_snapshot: list[dict] | None = None,
    already_invoked: set[str] | None = None,
) -> list[tuple[str, dict]]:
    """Parse a bot response for @-mentions of channel member bots and fire replies.

    Returns the list of (bot_id, config) tuples that were triggered (for dedup).
    Skips any bot_id in *already_invoked* (e.g. invoked via tool mid-turn).
    """
    try:
        mentioned = await _detect_member_mentions(channel_id, responding_bot_id, response_text, _depth=_depth)
    except Exception:
        logger.exception("Failed to detect member mentions in channel %s", channel_id)
        return []
    # Filter out bots already invoked (e.g. via auto-mention detection)
    if already_invoked:
        mentioned = [(bid, cfg) for bid, cfg in mentioned if bid not in already_invoked]
    for bot_id, member_config in mentioned:
        stream_id = str(uuid.uuid4())
        task = asyncio.create_task(
            _run_member_bot_reply(
                channel_id, session_id, bot_id, member_config,
                responding_bot_id, _depth=_depth + 1,
                messages_snapshot=messages_snapshot,
                stream_id=stream_id,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    return mentioned


async def _run_member_bot_reply(
    channel_id: uuid.UUID,
    session_id: uuid.UUID,
    member_bot_id: str,
    member_config: dict,
    mentioning_bot_id: str,
    *,
    _depth: int = 1,
    messages_snapshot: list[dict] | None = None,
    stream_id: str | None = None,
    invocation_message: str = "",
) -> None:
    """Execute a member bot's reply after being @-mentioned or invoked.

    When *messages_snapshot* is provided the bot runs against that snapshot
    without acquiring the session lock — enabling parallel execution.
    """
    from app.db.engine import async_session as _async_session
    from app.db.models import Channel, Session
    from app.services.channel_events import publish as _publish_event
    from sqlalchemy import update as _sql_update

    # Anti-loop: channel throttle (uses module-level imports)
    if _channel_throttled(str(channel_id)):
        logger.info("Member bot %s reply skipped: channel %s throttled", member_bot_id, channel_id)
        return

    _sid = stream_id or str(uuid.uuid4())
    _use_snapshot = messages_snapshot is not None

    if not _use_snapshot:
        # Legacy path: wait for session lock
        acquired = False
        for _ in range(30):
            if session_locks.acquire(session_id):
                acquired = True
                break
            await asyncio.sleep(1)
        if not acquired:
            logger.warning("Member bot %s timed out waiting for session lock in channel %s", member_bot_id, channel_id)
            return

    response_text = ""
    try:
        _record_channel_run(str(channel_id))

        member_bot = _bots_mod.get_bot(member_bot_id)

        # Look up primary bot ID for this channel
        _primary_bot_id: str | None = None
        async with _async_session() as db:
            _ch = await db.get(Channel, channel_id)
            if _ch and _ch.bot_id:
                _primary_bot_id = _ch.bot_id

        # Prepare messages: either from snapshot or load from DB
        if _use_snapshot:
            messages = [m for m in copy.deepcopy(messages_snapshot) if m.get("role") != "system"]
        else:
            # Legacy path: load session with metadata for rewriting
            async with _async_session() as db:
                _, messages = await _sessions_mod.load_or_create(
                    db, session_id, "member-mention", member_bot_id,
                    channel_id=channel_id,
                    preserve_metadata=True,
                )

        # Use prepare_bot_context for unified context preparation
        async with _async_session() as db:
            ctx = await prepare_bot_context(
                messages=messages,
                bot=member_bot,
                primary_bot_id=_primary_bot_id or member_bot_id,
                channel_id=channel_id,
                member_config=member_config,
                db=db,
                from_snapshot=_use_snapshot,
                mentioning_bot_id=mentioning_bot_id,
                invocation_message=invocation_message,
            )

        correlation_id = uuid.uuid4()
        from_index = len(ctx.messages)

        prompt = ctx.extracted_user_prompt
        model_override = ctx.model_override

        # Set agent context so run_stream internals have proper metadata
        _ctx_mod.set_agent_context(
            session_id=session_id,
            client_id="member-mention",
            bot_id=member_bot_id,
            correlation_id=correlation_id,
            channel_id=channel_id,
        )

        # Stream the reply so the UI shows typing indicators for the member bot.
        _publish_event(channel_id, "stream_start", {
            "stream_id": _sid,
            "responding_bot_id": member_bot_id,
            "responding_bot_name": member_bot.name,
        })

        async for event in _loop_mod.run_stream(
            ctx.messages, member_bot, prompt,
            session_id=session_id,
            client_id="member-mention",
            correlation_id=correlation_id,
            channel_id=channel_id,
            model_override=model_override,
            system_preamble=ctx.system_preamble,
        ):
            if event.get("type") == "response":
                response_text = event.get("text", "")
            event_with_session = {**event, "session_id": str(session_id)}
            _publish_event(channel_id, "stream_event", {
                "stream_id": _sid,
                "event": event_with_session,
            })

        # Persist with metadata so UI knows this is a bot-triggered turn
        msg_metadata = {
            "trigger": "member_mention",
            "sender_type": "bot",
            "sender_display_name": _bots_mod.get_bot(mentioning_bot_id).name,
            "mentioning_bot_id": mentioning_bot_id,
            "hidden": True,
        }
        async with _async_session() as db:
            # If we extracted the user message from history to place at end
            # of context, skip re-persisting it (it's already in the session).
            _skip_user = uuid.UUID(int=0) if ctx.extracted_user_prompt else None
            await _sessions_mod.persist_turn(
                db, session_id, member_bot, ctx.messages, from_index,
                correlation_id=correlation_id,
                channel_id=channel_id,
                msg_metadata=msg_metadata,
                pre_user_msg_id=_skip_user,
            )

        # Notify UI that streaming ended (after persist so data is committed).
        # The new_message events for the persisted rows are emitted by
        # `persist_turn` itself — no separate publish here. The previous
        # explicit `_publish_event(..., "new_message")` was a double-publish
        # that worked only because invalidation was idempotent.
        _publish_event(channel_id, "stream_end", {"stream_id": _sid})

        # Mirror to integration
        if response_text:
            async with _async_session() as db:
                channel = await db.get(Channel, channel_id)
            if channel:
                await _mirror_to_integration(
                    channel, response_text, bot_id=member_bot_id,
                )

        # Restore session bot_id to the channel's primary bot
        if not _use_snapshot:
            async with _async_session() as db:
                channel = await db.get(Channel, channel_id)
                if channel and channel.bot_id:
                    await db.execute(
                        _sql_update(Session)
                        .where(Session.id == session_id)
                        .values(bot_id=channel.bot_id)
                    )
                    await db.commit()

        logger.info(
            "Member bot %s replied in channel %s (mentioned by %s, depth=%d, stream=%s)",
            member_bot_id, channel_id, mentioning_bot_id, _depth, _sid,
        )

    except Exception:
        logger.exception("Member bot %s reply failed in channel %s", member_bot_id, channel_id)
        # Ensure streaming ends even on error so UI doesn't stay in streaming state
        _publish_event(channel_id, "stream_end", {"stream_id": _sid})
    finally:
        if not _use_snapshot:
            session_locks.release(session_id)

    # Chain: check if member bot's response mentions another member bot.
    # Always pass a snapshot so chained bots run lock-free.
    if response_text:
        _chain_snapshot = copy.deepcopy(ctx.raw_snapshot) if ctx.raw_snapshot else None
        if _chain_snapshot is not None:
            _chain_snapshot.append({
                "role": "assistant",
                "content": response_text,
                "_metadata": {"sender_id": f"bot:{member_bot_id}", "sender_display_name": member_bot.name},
            })
        await _trigger_member_bot_replies(
            channel_id, session_id, member_bot_id, response_text,
            _depth=_depth,
            messages_snapshot=_chain_snapshot,
        )
