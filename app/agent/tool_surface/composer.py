"""Tool-surface composer entry point.

Single seam that `context_assembly.assemble_context` calls to answer
"what tools does the LLM see this turn?". Internally selects the right
sub-pass — heartbeat (deterministic, retrieval-free), normal RAG
retrieval, or memory-flush/hygiene/review — based on the active context
profile and `bot.tool_retrieval`. After the selected pass populates
`state.pre_selected_tools` / `state.authorized_names`, finalization
runs unconditionally to merge dynamically injected tools, widget-handler
bridge tools, and the capability gate.

The composer is an `AsyncGenerator` so trace events flow through to the
caller unchanged. The terminal mutation lands on `state` (legacy contract
preserved) and on `result` if the caller passes one.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from app.agent.bots import BotConfig
from app.agent.tool_surface.finalize import _finalize_exposed_tools
from app.agent.tool_surface.retrieval import _run_tool_retrieval


_MEMORY_PROFILE_NAMES = frozenset({"memory_flush", "memory_hygiene", "skill_review"})


def _retrieval_gate(*, bot: BotConfig, context_profile: Any) -> bool:
    """Whether the retrieval pass should run for this turn.

    True when the bot opts into tool retrieval, or when the active context
    profile is one of the memory-management profiles that always need a
    targeted tool subset (and never the ambient surface).
    """
    if getattr(bot, "tool_retrieval", False):
        return True
    return getattr(context_profile, "name", None) in _MEMORY_PROFILE_NAMES


async def compose_stream(
    *,
    messages: list[dict[str, Any]],
    bot: BotConfig,
    user_message: str,
    ch_row: Any,
    channel_id: Any,
    correlation_id: Any,
    session_id: Any,
    client_id: Any,
    context_profile: Any,
    tool_surface_policy: str | None,
    required_tool_names: list[str] | None,
    state: Any,
    ledger: Any,
) -> AsyncGenerator[dict[str, Any], None]:
    """Compose the tool surface for one assembly turn.

    Yields trace events from the underlying retrieval pass (which itself
    may delegate to the heartbeat sub-pass). Mutates ``state`` in place
    with `pre_selected_tools`, `authorized_names`, `tool_discovery_info`.
    """
    if _retrieval_gate(bot=bot, context_profile=context_profile):
        async for evt in _run_tool_retrieval(
            messages=messages,
            bot=bot,
            user_message=user_message,
            ch_row=ch_row,
            correlation_id=correlation_id,
            session_id=session_id,
            client_id=client_id,
            context_profile=context_profile,
            tool_surface_policy=tool_surface_policy,
            required_tool_names=required_tool_names,
            state=state,
            ledger=ledger,
        ):
            yield evt

    await _finalize_exposed_tools(
        bot=bot,
        channel_id=channel_id,
        ch_row=ch_row,
        tool_surface_policy=tool_surface_policy,
        state=state,
    )
