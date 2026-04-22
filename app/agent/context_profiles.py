from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.session_plan_mode import (
    PLAN_MODE_BLOCKED,
    PLAN_MODE_DONE,
    PLAN_MODE_EXECUTING,
    PLAN_MODE_PLANNING,
    get_session_plan_mode,
)

if TYPE_CHECKING:
    from app.db.models import Session


@dataclass(frozen=True)
class ContextProfile:
    name: str
    live_history_turns: int | None
    include_compaction_summary: bool
    allow_conversation_sections: bool
    allow_memory_recent_logs: bool
    allow_channel_workspace: bool
    allow_channel_index_segments: bool
    allow_workspace_rag: bool
    allow_temporal_context: bool
    allow_pinned_widgets: bool
    allow_tool_refusal_guard: bool
    allow_tool_index: bool


_PROFILES: dict[str, ContextProfile] = {
    "chat": ContextProfile(
        name="chat",
        live_history_turns=None,
        include_compaction_summary=True,
        allow_conversation_sections=True,
        allow_memory_recent_logs=True,
        allow_channel_workspace=True,
        allow_channel_index_segments=True,
        allow_workspace_rag=True,
        allow_temporal_context=True,
        allow_pinned_widgets=True,
        allow_tool_refusal_guard=True,
        allow_tool_index=True,
    ),
    "planning": ContextProfile(
        name="planning",
        live_history_turns=2,
        include_compaction_summary=True,
        allow_conversation_sections=True,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_workspace_rag=False,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=False,
        allow_tool_index=True,
    ),
    "executing": ContextProfile(
        name="executing",
        live_history_turns=4,
        include_compaction_summary=True,
        allow_conversation_sections=True,
        allow_memory_recent_logs=False,
        allow_channel_workspace=True,
        allow_channel_index_segments=True,
        allow_workspace_rag=True,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=True,
        allow_tool_index=True,
    ),
    "task_recent": ContextProfile(
        name="task_recent",
        live_history_turns=None,
        include_compaction_summary=True,
        allow_conversation_sections=True,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_workspace_rag=False,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=False,
        allow_tool_index=True,
    ),
    "task_none": ContextProfile(
        name="task_none",
        live_history_turns=0,
        include_compaction_summary=False,
        allow_conversation_sections=False,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_workspace_rag=False,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=False,
        allow_tool_index=False,
    ),
    "heartbeat": ContextProfile(
        name="heartbeat",
        live_history_turns=0,
        include_compaction_summary=False,
        allow_conversation_sections=False,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_workspace_rag=False,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=False,
        allow_tool_index=False,
    ),
}


def get_context_profile(name: str) -> ContextProfile:
    return _PROFILES.get(name, _PROFILES["chat"])


def resolve_context_profile(
    *,
    session: Session | None = None,
    profile_name: str | None = None,
    origin: str | None = None,
) -> ContextProfile:
    if profile_name:
        return get_context_profile(profile_name)

    if session is not None:
        mode = get_session_plan_mode(session)
        if mode == PLAN_MODE_PLANNING:
            return _PROFILES["planning"]
        if mode in {PLAN_MODE_EXECUTING, PLAN_MODE_BLOCKED, PLAN_MODE_DONE}:
            return _PROFILES["executing"]

    if origin == "heartbeat":
        return _PROFILES["heartbeat"]
    if origin in {"subagent", "hygiene"}:
        return _PROFILES["task_none"]
    if origin == "task":
        return _PROFILES["task_recent"]

    return _PROFILES["chat"]


def trim_messages_to_recent_turns(messages: list[dict], max_turns: int | None) -> list[dict]:
    """Trim to the last N user-started turns while preserving any system prefix."""
    if max_turns is None or max_turns < 0:
        return list(messages)

    sys_prefix: list[dict] = []
    body: list[dict] = []
    in_body = False
    for msg in messages:
        if not in_body and msg.get("role") == "system":
            sys_prefix.append(msg)
        else:
            in_body = True
            body.append(msg)

    if max_turns == 0 or not body:
        return sys_prefix

    turn_starts = [idx for idx, msg in enumerate(body) if msg.get("role") == "user"]
    if not turn_starts:
        return sys_prefix + body

    keep_from = turn_starts[-max_turns] if max_turns <= len(turn_starts) else 0
    return sys_prefix + body[keep_from:]
