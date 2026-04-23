"""Internal deterministic turn supervisors.

This is deliberately separate from app.agent.hooks: lifecycle hooks are
best-effort and externally observable, while supervisors enforce runtime
contracts that must run before a turn is finalized.
"""
from __future__ import annotations

import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.db.engine import async_session
from app.db.models import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnEndContext:
    session_id: uuid.UUID
    bot_id: str
    turn_id: uuid.UUID
    correlation_id: uuid.UUID
    channel_id: uuid.UUID | None = None
    result: str | None = None
    error: str | None = None
    client_actions: list[Any] = field(default_factory=list)


TurnSupervisor = Callable[[TurnEndContext], Awaitable[None] | None]
_turn_supervisors: list[TurnSupervisor] = []


def register_turn_supervisor(supervisor: TurnSupervisor) -> None:
    if supervisor not in _turn_supervisors:
        _turn_supervisors.append(supervisor)


async def run_turn_supervisors(ctx: TurnEndContext) -> None:
    for supervisor in list(_turn_supervisors):
        try:
            result = supervisor(ctx)
            if inspect.isawaitable(result):
                await result  # type: ignore[misc]
        except Exception:
            logger.warning(
                "Turn supervisor %s failed for turn %s",
                getattr(supervisor, "__qualname__", supervisor),
                ctx.turn_id,
                exc_info=True,
            )


async def _plan_mode_turn_supervisor(ctx: TurnEndContext) -> None:
    if ctx.error:
        return
    from app.services.session_plan_mode import mark_plan_turn_outcome_pending, publish_session_plan_event

    async with async_session() as db:
        session = await db.get(Session, ctx.session_id)
        if session is None:
            return
        pending = mark_plan_turn_outcome_pending(
            session,
            turn_id=str(ctx.turn_id),
            correlation_id=str(ctx.correlation_id),
            reason="missing_turn_outcome",
            assistant_summary=ctx.result,
        )
        if pending is None:
            return
        await db.commit()
        publish_session_plan_event(session, "turn_outcome_pending")


register_turn_supervisor(_plan_mode_turn_supervisor)
