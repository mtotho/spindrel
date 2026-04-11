"""start_turn — public entry point for the chat 202 lifecycle.

Phase E of the Integration Delivery refactor. The HTTP chat handler in
``app/routers/chat/_routes.py`` no longer drives the agent loop directly.
Instead it calls ``start_turn(...)``, which:

1. Acquires the per-session lock so concurrent posts queue correctly.
2. Constructs a ``TurnHandle`` (turn_id, stream_id) for the new turn.
3. Spawns ``turn_worker.run_turn(...)`` as a background asyncio task via
   ``safe_create_task`` (uncaught exceptions log instead of vanishing).
4. Returns the handle immediately so the request handler can return 202.

The lock is released by the worker when the turn completes (success,
error, or cancellation). Subscribers tail the channel-events bus via
``GET /api/v1/channels/{id}/events?since=N`` to observe the turn.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services import session_locks
from app.utils import safe_create_task

if TYPE_CHECKING:
    from app.agent.bots import BotConfig
    from app.routers.chat._context import BotContext
    from app.routers.chat._schemas import ChatRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnHandle:
    """Identifiers returned to the HTTP client when a turn is enqueued.

    The client subscribes to ``/api/v1/channels/{channel_id}/events?since=N``
    and filters events by ``turn_id`` (carried on every TURN_* payload).
    """

    session_id: uuid.UUID
    channel_id: uuid.UUID
    turn_id: uuid.UUID


class SessionBusyError(Exception):
    """Raised when ``start_turn`` cannot acquire the session lock.

    The HTTP layer should translate this into a 202 with a ``queued`` flag
    or surface the queue position. Phase E keeps the legacy "queue as a
    Task row" behavior for now — see ``_routes.py`` for the policy.
    """


async def start_turn(
    *,
    channel_id: uuid.UUID,
    session_id: uuid.UUID,
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
) -> TurnHandle:
    """Acquire the session lock and schedule a turn worker for the channel.

    Returns a ``TurnHandle`` immediately. The caller (HTTP handler) does
    NOT await the worker; it returns 202 to the client and the worker
    drives ``run_stream(...)`` to completion in the background, publishing
    typed ``ChannelEvent``s onto the bus as it goes.

    Raises ``SessionBusyError`` if the per-session lock is already held.
    The caller is responsible for translating that into a queued response.
    """
    if not session_locks.acquire(session_id):
        raise SessionBusyError(f"session {session_id} is already running a turn")

    handle = TurnHandle(
        session_id=session_id,
        channel_id=channel_id,
        turn_id=uuid.uuid4(),
    )

    # Import inside the function to avoid an import cycle:
    # turn_worker imports from sessions / loop / multibot which transitively
    # touch routers that import this module.
    from app.services.turn_worker import run_turn

    safe_create_task(
        run_turn(
            handle,
            bot=bot,
            primary_bot_id=primary_bot_id,
            messages=messages,
            user_message=user_message,
            ctx=ctx,
            req=req,
            user=user,
            audio_data=audio_data,
            audio_format=audio_format,
            att_payload=att_payload,
        ),
        name=f"turn:{handle.turn_id}",
    )
    logger.info(
        "start_turn scheduled: session=%s channel=%s bot=%s turn=%s",
        session_id, channel_id, bot.id, handle.turn_id,
    )
    return handle
