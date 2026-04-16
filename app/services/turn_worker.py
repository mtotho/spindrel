"""Background turn worker — drives the agent loop after start_turn() returns 202.

Phase E of the Integration Delivery refactor. The HTTP /chat handler used
to be a 250-line ``event_generator`` that drove ``run_stream`` in-band and
yielded raw SSE bytes back to the client. That coupled the request lifetime
to the agent run, mixed transport with domain logic, and double-published
every event (once to the long-poll, once to the channel-events bus).

This module is the proper home for the agent-loop side of the chat
lifecycle. It runs as a background asyncio task spawned by
``app/services/turns.py:start_turn``. It owns its own DB session, sets the
agent ContextVars (per-task scoping), drives ``run_stream``, maps each event
to a typed ``ChannelEvent``, and publishes onto the channel-events bus.
``persist_turn`` lands the messages and enqueues outbox rows for the drainer
to fan out to integration renderers.

Subscribers (web UI, future Slack/Discord renderers via ``subscribe_all``)
tail the bus. The HTTP request returned 202 long ago.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from datetime import datetime, timezone

from app.agent.bots import BotConfig, get_bot
from app.agent.context import (
    current_invoked_member_bots,
    set_agent_context,
)
from app.agent.loop import run_stream
from app.db.engine import async_session
from app.db.models import Message as MessageModel
from app.domain.actor import ActorRef
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    MessagePayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamToolResultPayload,
)
from app.routers.chat._context import BotContext
from app.routers.chat._multibot import (
    _background_tasks,
    _detect_member_mentions,
    _run_member_bot_reply,
    _trigger_member_bot_replies,
)
from app.routers.chat._schemas import ChatRequest
from app.services import session_locks
from app.services.channel_events import publish_typed
from app.services.compaction import maybe_compact
from app.services.delegation import delegation_service as _ds
from app.services.sessions import persist_turn
from app.services.turn_event_emit import emit_run_stream_events
from app.services.turns import TurnHandle

logger = logging.getLogger(__name__)


async def run_turn(
    handle: TurnHandle,
    *,
    bot: BotConfig,
    primary_bot_id: str,
    messages: list[dict],
    user_message: str,
    ctx: BotContext,
    req: ChatRequest,
    user,
    audio_data: str | None,
    audio_format: str | None,
    att_payload: list[dict] | None,
) -> None:
    """Drive a single agent turn to completion in the background.

    Publishes typed ``ChannelEvent``s for the entire lifecycle:

    * ``NEW_MESSAGE`` (user message, pre-persisted)
    * ``TURN_STARTED``
    * ``TURN_STREAM_TOKEN`` / ``TURN_STREAM_TOOL_START`` / ``TURN_STREAM_TOOL_RESULT``
    * ``APPROVAL_REQUESTED`` / ``APPROVAL_RESOLVED``
    * ``NEW_MESSAGE`` (assistant message, via persist_turn)
    * ``TURN_ENDED``

    Releases the session lock unconditionally on the way out.
    """
    channel_id = handle.channel_id
    session_id = handle.session_id
    turn_id = handle.turn_id
    correlation_id = turn_id  # turn_id IS the correlation_id — threads through SSE→synthetic→DB for reliable dedup
    response_text = ""
    response_actions: list | None = None
    _intermediate_texts: list[str] = []
    _budget_utilization: float | None = None
    was_cancelled = False
    error_text: str | None = None
    pre_user_msg_id: uuid.UUID | None = None

    try:
        # Per-task ContextVars — safe because asyncio tasks each see their
        # own ContextVar copy.
        set_agent_context(
            session_id=session_id,
            client_id=req.client_id,
            bot_id=bot.id,
            correlation_id=correlation_id,
            channel_id=channel_id,
            memory_cross_channel=None,
            memory_cross_client=None,
            memory_cross_bot=None,
            memory_similarity_threshold=None,
            dispatch_type=None,
            dispatch_config=None,
        )
        # ``current_turn_id`` is set separately because ``set_agent_context``
        # doesn't know the turn_id (it's a per-task value, not a request
        # value). Tool-dispatch reads this when publishing
        # APPROVAL_REQUESTED so the UI can route the approval back to the
        # right in-flight turn slot.
        from app.agent.context import current_turn_id
        current_turn_id.set(turn_id)

        # 1. Pre-persist the user message and publish NEW_MESSAGE so the bus
        #    sees the user input before the agent starts emitting tokens.
        _meta = req.msg_metadata or {}
        _pre_id_str = _meta.pop("_pre_user_msg_id", None)
        pre_user_msg_id = await _persist_and_publish_user_message(
            session_id=session_id,
            channel_id=channel_id,
            text=user_message,
            correlation_id=correlation_id,
            metadata=_meta,
            pre_allocated_id=uuid.UUID(_pre_id_str) if _pre_id_str else None,
        )

        # 2. Publish TURN_STARTED so renderers can post a "thinking…" placeholder.
        publish_typed(
            channel_id,
            ChannelEvent(
                channel_id=channel_id,
                kind=ChannelEventKind.TURN_STARTED,
                payload=TurnStartedPayload(
                    bot_id=bot.id,
                    turn_id=turn_id,
                    reason="user_message",
                ),
            ),
        )

        # 3. Detect parallel multi-bot @-mentions BEFORE the primary bot
        #    starts so the auto-invoked bots run lock-free in parallel.
        _user_mentioned: list[tuple[str, dict]] = []
        if user_message:
            _user_mentioned = await _detect_member_mentions(
                channel_id, bot.id, user_message, _depth=0,
            )
            if _user_mentioned:
                _user_snap = ctx.raw_snapshot
                _auto_invoked_ids: set[str] = set()
                for _um_bot_id, _um_config in _user_mentioned:
                    _um_task = asyncio.create_task(
                        _run_member_bot_reply(
                            channel_id, session_id, _um_bot_id, _um_config,
                            bot.id, _depth=1,
                            messages_snapshot=_user_snap,
                            turn_id=uuid.uuid4(),
                        )
                    )
                    _background_tasks.add(_um_task)
                    _um_task.add_done_callback(_background_tasks.discard)
                    _auto_invoked_ids.add(_um_bot_id)

                current_invoked_member_bots.set(_auto_invoked_ids)

                _auto_names = []
                for _ai_id, _ in _user_mentioned:
                    try:
                        _ai_bot = get_bot(_ai_id)
                        _auto_names.append(f"{_ai_bot.name} (@{_ai_id})")
                    except Exception:
                        _auto_names.append(f"@{_ai_id}")
                messages.append({
                    "role": "system",
                    "content": (
                        f"The following bots were auto-invoked by the user's @-mentions and are "
                        f"already responding in parallel: {', '.join(_auto_names)}. "
                        f"Do NOT @-mention them again in your response."
                    ),
                })

        # 4. Drive run_stream and map events onto the typed bus.
        from_index = len(messages)
        _effective_model_override = req.model_override or ctx.model_override

        _run_stream_iter = run_stream(
            messages, bot, user_message,
            session_id=session_id,
            client_id=req.client_id,
            audio_data=audio_data,
            audio_format=audio_format,
            attachments=att_payload,
            correlation_id=correlation_id,
            dispatch_type=None,
            dispatch_config=None,
            channel_id=channel_id,
            model_override=_effective_model_override,
            provider_id_override=req.model_provider_id_override,
            system_preamble=ctx.system_preamble,
        )
        _auto_injected_skills: list[dict] = []
        _llm_retries: int = 0
        _llm_fallback_model: str | None = None
        _vision_fallback: bool = False
        async for event in emit_run_stream_events(
            _run_stream_iter,
            channel_id=channel_id,
            bot_id=bot.id,
            turn_id=turn_id,
        ):
            etype = event.get("type")

            if etype == "auto_inject":
                _auto_injected_skills.append({
                    "skill_id": event.get("skill_id", ""),
                    "skill_name": event.get("skill_name", ""),
                    "similarity": event.get("similarity", 0.0),
                    "source": event.get("source", ""),
                })
                continue

            if etype == "cancelled":
                was_cancelled = True
                messages.append({"role": "user", "content": "[STOP]"})
                messages.append({"role": "assistant", "content": "[Cancelled by user]"})
                # Surface cancellation on TURN_ENDED so the UI can render a
                # cancelled state instead of an empty graceful turn. The
                # ``error`` field is the only payload slot that distinguishes
                # cancel from a successful empty response.
                error_text = "cancelled"
                break

            if etype == "context_budget":
                _budget_utilization = event.get("utilization")
                continue

            if etype == "response":
                final_text = event.get("text", "")
                if not (final_text or "").strip() and _intermediate_texts:
                    response_text = "\n\n".join(_intermediate_texts)
                else:
                    response_text = final_text
                response_actions = event.get("client_actions")
                continue

            if etype == "assistant_text":
                _intermediate_texts.append(event.get("text", ""))
                continue

            if etype == "delegation_post":
                try:
                    await _ds.post_child_response(
                        channel_id=channel_id,
                        text=event.get("text", ""),
                        bot_id=event.get("bot_id") or "",
                        reply_in_thread=event.get("reply_in_thread", False),
                    )
                except Exception as exc:
                    # Surface the failure on the bus so the UI / future
                    # renderers can render an error chip. The legacy path
                    # would have surfaced this via the dispatcher mirror;
                    # the typed bus needs the explicit publish.
                    logger.exception(
                        "turn_worker: delegation_post failed for bot %s",
                        event.get("bot_id"),
                    )
                    publish_typed(
                        channel_id,
                        ChannelEvent(
                            channel_id=channel_id,
                            kind=ChannelEventKind.TURN_STREAM_TOOL_RESULT,
                            payload=TurnStreamToolResultPayload(
                                bot_id=bot.id,
                                turn_id=turn_id,
                                tool_name="delegation_post",
                                result_summary=(
                                    f"delegation_post failed for "
                                    f"{event.get('bot_id') or 'unknown'}: "
                                    f"{type(exc).__name__}: {str(exc)[:300]}"
                                ),
                                is_error=True,
                            ),
                        ),
                    )
                continue

            if etype == "llm_retry":
                _llm_retries += 1
                if event.get("reason") == "vision_not_supported":
                    _vision_fallback = True
                continue

            if etype == "llm_fallback":
                _llm_fallback_model = event.get("to_model")
                continue

            if etype == "llm_cooldown_skip":
                _llm_fallback_model = event.get("using")
                continue

            # Anything else (transcript, thinking_content, warning, fallback,
            # context_pruning, rate_limit_wait) — forwarded but no caller-side
            # action needed.

        # 4b. Tag the last assistant message with auto-injected skill info
        #     so persist_turn can carry it into the DB row's metadata.
        if _auto_injected_skills:
            for _m in reversed(messages[from_index:]):
                if _m.get("role") == "assistant":
                    _m["_auto_injected_skills"] = _auto_injected_skills
                    break

        # 4c. Tag the last assistant message with LLM retry/fallback info
        #     so persist_turn can carry it into the DB row's metadata.
        if _llm_retries > 0 or _llm_fallback_model or _vision_fallback:
            _llm_info: dict = {}
            if _llm_retries > 0:
                _llm_info["retries"] = _llm_retries
            if _llm_fallback_model:
                _llm_info["fallback_model"] = _llm_fallback_model
            if _vision_fallback:
                _llm_info["vision_fallback"] = True
            for _m in reversed(messages[from_index:]):
                if _m.get("role") == "assistant":
                    _m["_llm_status"] = _llm_info
                    break

        # 5. Persist the turn (DB write + outbox enqueue + bus publish).
        #    Runs unconditionally — cancelled turns must persist the [STOP] /
        #    [Cancelled by user] markers that the cancellation branch above
        #    appended to ``messages``, so the conversation history reflects
        #    the cancellation. The legacy event_generator (deleted in Phase E)
        #    called persist_turn unconditionally for the same reason.
        try:
            async with async_session() as db:
                await persist_turn(
                    db, session_id, bot, messages, from_index,
                    correlation_id=correlation_id,
                    msg_metadata=req.msg_metadata,
                    channel_id=channel_id,
                    pre_user_msg_id=pre_user_msg_id,
                )
        except Exception:
            logger.exception(
                "turn_worker: persist_turn failed for session %s — messages will be lost",
                session_id,
            )
            error_text = "persist_turn failed"

        # 6. Trigger compaction in the background.
        maybe_compact(
            session_id, bot, messages,
            correlation_id=correlation_id,
            budget_utilization=_budget_utilization,
        )

        # 7. Bot-to-bot @-mention chain: trigger member bot replies for
        #    bots the primary bot mentioned in its response.
        if not was_cancelled and response_text:
            _already_invoked = set(current_invoked_member_bots.get() or ())
            if _user_mentioned:
                _already_invoked.update(bid for bid, _ in _user_mentioned)
            _messages_snapshot = copy.deepcopy(ctx.raw_snapshot) if ctx.raw_snapshot else []
            _messages_snapshot.append({
                "role": "assistant",
                "content": response_text,
                "_metadata": {
                    "sender_id": f"bot:{bot.id}",
                    "sender_display_name": bot.name,
                },
            })
            try:
                await _trigger_member_bot_replies(
                    channel_id, session_id, bot.id, response_text,
                    _depth=1,
                    messages_snapshot=_messages_snapshot,
                    already_invoked=_already_invoked,
                )
            except Exception:
                logger.warning(
                    "turn_worker: member-bot fanout failed for channel %s",
                    channel_id, exc_info=True,
                )

    except Exception as exc:
        logger.exception(
            "turn_worker: turn %s failed for session %s",
            turn_id, session_id,
        )
        error_text = f"{type(exc).__name__}: {str(exc)[:500]}"
    finally:
        # 8. Always publish TURN_ENDED. Subscribers (renderers + UI) rely
        #    on it to finalize their per-turn state.
        try:
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.TURN_ENDED,
                    payload=TurnEndedPayload(
                        bot_id=bot.id,
                        turn_id=turn_id,
                        result=response_text or None,
                        # Always surface error_text. The legacy guard
                        # `if not response_text else None` swallowed
                        # persist_turn / fanout failures whenever the
                        # agent had already produced a response, so the
                        # UI saw a green turn while the messages were
                        # actually lost. Renderers + UI handle result
                        # and error being independent.
                        error=error_text or None,
                        client_actions=list(response_actions or []),
                        extra_metadata=(
                            {"auto_injected_skills": _auto_injected_skills}
                            if _auto_injected_skills else {}
                        ),
                    ),
                ),
            )
        except Exception:
            logger.warning(
                "turn_worker: failed to publish TURN_ENDED for turn %s",
                turn_id, exc_info=True,
            )

        # 9. Always release the session lock so the next turn can run.
        session_locks.release(session_id)


async def _persist_and_publish_user_message(
    *,
    session_id: uuid.UUID,
    channel_id: uuid.UUID,
    text: str,
    correlation_id: uuid.UUID,
    metadata: dict,
    pre_allocated_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Insert the user message row and publish a NEW_MESSAGE event.

    Returns the row id so ``persist_turn`` can avoid double-inserting it.
    A failure here is logged and swallowed — persist_turn will create a
    fresh row and the bus subscriber sees a (delayed) NEW_MESSAGE later.

    If *pre_allocated_id* is set (e.g. because attachments were already
    linked to this ID), the message row will use that UUID instead of
    auto-generating one.
    """
    try:
        async with async_session() as db:
            kw: dict = dict(
                session_id=session_id,
                role="user",
                content=text,
                correlation_id=correlation_id,
                metadata_=metadata,
                created_at=datetime.now(timezone.utc),
            )
            if pre_allocated_id:
                kw["id"] = pre_allocated_id
            row = MessageModel(**kw)
            db.add(row)
            await db.commit()
            await db.refresh(row)

            domain_msg = DomainMessage(
                id=row.id,
                session_id=session_id,
                role="user",
                content=text,
                created_at=row.created_at,
                actor=ActorRef.user(
                    metadata.get("sender_id", "user"),
                    display_name=metadata.get("sender_display_name"),
                ),
                metadata=dict(metadata),
                correlation_id=correlation_id,
                channel_id=channel_id,
            )
            # NEW_MESSAGE is outbox-durable: enqueue an outbox row so the
            # drainer is the single delivery path to renderers, and call
            # publish_typed so SSE subscribers (web UI) still see the
            # event live. The Slack renderer's echo filter then catches
            # this on the outbox path the same way it would on the bus
            # path.
            from app.services.outbox_publish import enqueue_new_message_for_channel
            await enqueue_new_message_for_channel(channel_id, domain_msg)
            publish_typed(
                channel_id,
                ChannelEvent(
                    channel_id=channel_id,
                    kind=ChannelEventKind.NEW_MESSAGE,
                    payload=MessagePayload(message=domain_msg),
                ),
            )
            return row.id
    except Exception:
        logger.warning(
            "turn_worker: failed to pre-persist user message for session %s",
            session_id, exc_info=True,
        )
        return None
