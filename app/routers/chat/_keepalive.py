"""SSE keepalive wrapper for streaming responses."""
import asyncio
from collections.abc import AsyncGenerator
from typing import Any


SSE_KEEPALIVE_INTERVAL = 15  # seconds


async def _with_keepalive(
    agen: AsyncGenerator[dict[str, Any], None],
    interval: float = SSE_KEEPALIVE_INTERVAL,
) -> AsyncGenerator[dict[str, Any] | None, None]:
    """Wrap an async generator, yielding None as a keepalive signal when no
    event arrives within *interval* seconds.  Prevents idle SSE connections
    from being dropped by React Native's XHR layer.

    IMPORTANT: Each ``ensure_future(__anext__())`` runs the generator step in a
    new asyncio Task that copies the *parent's* ContextVars.  Changes made
    inside the generator (e.g. ``current_resolved_skill_ids`` set by
    ``assemble_context``) are lost when the Task ends.  To bridge them, we
    capture the child Task's context-var values after each step and restore
    them in the parent so the next Task inherits the updated state.
    """
    from app.agent.context import (
        current_resolved_skill_ids,
        current_model_override,
        current_provider_id_override,
        current_channel_model_tier_overrides,
        current_injected_tools,
        current_ephemeral_skills,
        current_ephemeral_delegates,
        current_allowed_secrets,
        task_creation_count,
        current_pending_delegation_posts,
        current_invoked_member_bots,
    )

    # Context vars that are set *inside* the generator (by assemble_context /
    # run_stream) and read by tools or inner loops.  We capture their values
    # after each generator step and restore them in the parent context.
    _BRIDGE_VARS = [
        current_resolved_skill_ids,
        current_model_override,
        current_provider_id_override,
        current_channel_model_tier_overrides,
        current_injected_tools,
        current_ephemeral_skills,
        current_ephemeral_delegates,
        current_allowed_secrets,
        task_creation_count,
        current_pending_delegation_posts,
        current_invoked_member_bots,
    ]

    _bridge: dict = {}  # ContextVar -> value, shared with child Task

    async def _next():
        result = await agen.__anext__()
        # Capture context vars from the child Task so we can restore them
        for var in _BRIDGE_VARS:
            _bridge[var] = var.get()
        return result

    pending = asyncio.ensure_future(_next())
    try:
        while True:
            try:
                event = await asyncio.wait_for(asyncio.shield(pending), timeout=interval)
                # Restore child's context changes into the parent so the
                # next ensure_future() inherits them.
                for var, val in _bridge.items():
                    var.set(val)
                yield event
                pending = asyncio.ensure_future(_next())
            except asyncio.TimeoutError:
                yield None
            except StopAsyncIteration:
                break
    finally:
        pending.cancel()
