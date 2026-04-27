"""Single-source builder for ``TurnContext``.

Both the live turn worker and the native-compact path need a fully populated
``TurnContext`` with the same fields resolved the same way. Keeping the
construction centralized prevents drift when a new field is added to
``TurnContext``.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from app.db.engine import async_session as _default_session_factory
from app.services.agent_harnesses.base import (
    DbSessionFactory,
    HarnessContextHint,
    TurnContext,
)


def build_turn_context(
    *,
    spindrel_session_id: uuid.UUID,
    bot_id: str,
    turn_id: uuid.UUID,
    channel_id: uuid.UUID | None,
    workdir: str,
    harness_session_id: str | None,
    permission_mode: str,
    model: str | None = None,
    effort: str | None = None,
    runtime_settings: Mapping[str, Any] | None = None,
    context_hints: tuple[HarnessContextHint, ...] = (),
    ephemeral_tool_names: tuple[str, ...] = (),
    tagged_skill_ids: tuple[str, ...] = (),
    db_session_factory: DbSessionFactory | None = None,
) -> TurnContext:
    """Construct a ``TurnContext`` from already-resolved per-turn inputs.

    Callers pass workdir/mode/model/settings already resolved — this function
    does NOT load them — but it defaults the DB session factory so callers
    don't have to thread it everywhere.
    """
    return TurnContext(
        spindrel_session_id=spindrel_session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        turn_id=turn_id,
        workdir=workdir,
        harness_session_id=harness_session_id,
        permission_mode=permission_mode,
        db_session_factory=db_session_factory or _default_session_factory,
        model=model,
        effort=effort,
        runtime_settings=runtime_settings or {},
        context_hints=context_hints,
        ephemeral_tool_names=ephemeral_tool_names,
        tagged_skill_ids=tagged_skill_ids,
    )
