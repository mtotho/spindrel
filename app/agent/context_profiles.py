from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
    allow_plan_artifact: bool
    allow_conversation_sections: bool
    allow_memory_recent_logs: bool
    allow_channel_workspace: bool
    allow_channel_index_segments: bool
    allow_bot_knowledge_base: bool
    allow_workspace_rag: bool
    allow_temporal_context: bool
    allow_pinned_widgets: bool
    allow_tool_refusal_guard: bool
    allow_tool_index: bool
    allow_skill_index: bool
    mandatory_static_injections: tuple[str, ...] = ()
    optional_static_injections: tuple[str, ...] = ()
    memory_bootstrap_max_chars: int | None = None
    section_index_count_default: int | None = None
    section_index_verbosity_default: str | None = None
    # When set, overrides ``settings.IN_LOOP_PRUNING_KEEP_ITERATIONS`` for this
    # profile. Long-running task profiles (hygiene, skill review) need a larger
    # window than chat because they sweep many channels per run and otherwise
    # re-fetch pruned tool results via ``section="tool:<uuid>"``.
    keep_iterations_override: int | None = None

    def to_policy_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "live_history_turns": self.live_history_turns,
            "allow_plan_artifact": self.allow_plan_artifact,
            "allow_tool_index": self.allow_tool_index,
            "allow_skill_index": self.allow_skill_index,
            "keep_iterations_override": self.keep_iterations_override,
            "mandatory_static_injections": list(self.mandatory_static_injections),
            "optional_static_injections": list(self.optional_static_injections),
            "memory_bootstrap_max_chars": self.memory_bootstrap_max_chars,
            "section_index_count_default": self.section_index_count_default,
            "section_index_verbosity_default": self.section_index_verbosity_default,
        }


_PROFILES: dict[str, ContextProfile] = {
    "chat_lean": ContextProfile(
        name="chat_lean",
        live_history_turns=4,
        include_compaction_summary=True,
        allow_plan_artifact=False,
        allow_conversation_sections=True,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_bot_knowledge_base=False,
        allow_workspace_rag=False,
        allow_temporal_context=True,
        allow_pinned_widgets=True,
        allow_tool_refusal_guard=True,
        allow_tool_index=False,
        allow_skill_index=False,
        mandatory_static_injections=("memory_bootstrap",),
        optional_static_injections=(
            "section_index",
            "temporal_context",
            "pinned_widgets",
            "tool_refusal_guard",
        ),
        memory_bootstrap_max_chars=4000,
        section_index_count_default=8,
        section_index_verbosity_default="compact",
    ),
    "chat_standard": ContextProfile(
        name="chat_standard",
        live_history_turns=8,
        include_compaction_summary=True,
        allow_plan_artifact=False,
        allow_conversation_sections=True,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_bot_knowledge_base=True,
        allow_workspace_rag=True,
        allow_temporal_context=True,
        allow_pinned_widgets=True,
        allow_tool_refusal_guard=True,
        allow_tool_index=False,
        allow_skill_index=True,
        mandatory_static_injections=("memory_bootstrap",),
        optional_static_injections=(
            "bot_knowledge_base",
            "conversation_sections",
            "section_index",
            "workspace_rag",
            "temporal_context",
            "pinned_widgets",
            "tool_refusal_guard",
        ),
        memory_bootstrap_max_chars=8000,
        section_index_count_default=10,
        section_index_verbosity_default="standard",
    ),
    "chat_rich": ContextProfile(
        name="chat_rich",
        live_history_turns=8,
        include_compaction_summary=True,
        allow_plan_artifact=False,
        allow_conversation_sections=True,
        allow_memory_recent_logs=True,
        allow_channel_workspace=True,
        allow_channel_index_segments=True,
        allow_bot_knowledge_base=True,
        allow_workspace_rag=True,
        allow_temporal_context=True,
        allow_pinned_widgets=True,
        allow_tool_refusal_guard=True,
        allow_tool_index=False,
        allow_skill_index=True,
        mandatory_static_injections=("memory_bootstrap",),
        optional_static_injections=(
            "memory_housekeeping",
            "memory_nudge",
            "channel_workspace",
            "bot_knowledge_base",
            "conversation_sections",
            "section_index",
            "workspace_rag",
            "temporal_context",
            "pinned_widgets",
            "tool_refusal_guard",
        ),
    ),
    "planning": ContextProfile(
        name="planning",
        live_history_turns=2,
        include_compaction_summary=True,
        allow_plan_artifact=True,
        allow_conversation_sections=True,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_bot_knowledge_base=False,
        allow_workspace_rag=False,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=False,
        allow_tool_index=True,
        allow_skill_index=True,
        mandatory_static_injections=("plan_artifact", "conversation_sections", "section_index"),
        optional_static_injections=("context_profile_note", "tool_index"),
    ),
    "executing": ContextProfile(
        name="executing",
        live_history_turns=4,
        include_compaction_summary=True,
        allow_plan_artifact=True,
        allow_conversation_sections=True,
        allow_memory_recent_logs=False,
        allow_channel_workspace=True,
        allow_channel_index_segments=True,
        allow_bot_knowledge_base=True,
        allow_workspace_rag=True,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=True,
        allow_tool_index=True,
        allow_skill_index=True,
        mandatory_static_injections=("plan_artifact", "conversation_sections", "section_index"),
        optional_static_injections=(
            "context_profile_note",
            "channel_workspace",
            "channel_index_segments",
            "bot_knowledge_base",
            "workspace_rag",
            "tool_index",
            "tool_refusal_guard",
        ),
    ),
    "task_recent": ContextProfile(
        name="task_recent",
        live_history_turns=None,
        include_compaction_summary=True,
        allow_plan_artifact=False,
        allow_conversation_sections=True,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_bot_knowledge_base=False,
        allow_workspace_rag=False,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=False,
        allow_tool_index=True,
        allow_skill_index=True,
        mandatory_static_injections=("conversation_sections", "section_index"),
        optional_static_injections=("context_profile_note", "tool_index"),
    ),
    "task_none": ContextProfile(
        name="task_none",
        live_history_turns=0,
        include_compaction_summary=False,
        allow_plan_artifact=False,
        allow_conversation_sections=False,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_bot_knowledge_base=False,
        allow_workspace_rag=False,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=False,
        allow_tool_index=False,
        allow_skill_index=False,
        optional_static_injections=("context_profile_note",),
        keep_iterations_override=8,
    ),
    "heartbeat": ContextProfile(
        name="heartbeat",
        live_history_turns=0,
        include_compaction_summary=False,
        allow_plan_artifact=False,
        allow_conversation_sections=False,
        allow_memory_recent_logs=False,
        allow_channel_workspace=False,
        allow_channel_index_segments=False,
        allow_bot_knowledge_base=False,
        allow_workspace_rag=False,
        allow_temporal_context=False,
        allow_pinned_widgets=False,
        allow_tool_refusal_guard=False,
        allow_tool_index=False,
        allow_skill_index=False,
        optional_static_injections=("context_profile_note",),
    ),
}

_PROFILES["chat"] = _PROFILES["chat_lean"]

_NATIVE_CONTEXT_POLICY_TO_PROFILE = {
    "lean": "chat_lean",
    "standard": "chat_standard",
    "rich": "chat_rich",
}


def normalize_native_context_policy(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in {"lean", "standard", "rich"}:
        return raw
    return None


def resolve_native_context_policy(*, channel: Any | None = None) -> str:
    if channel is not None:
        cfg = getattr(channel, "config", None) or {}
        channel_policy = normalize_native_context_policy(cfg.get("native_context_policy"))
        if channel_policy:
            return channel_policy

    from app.config import settings

    return normalize_native_context_policy(getattr(settings, "NATIVE_CONTEXT_POLICY_DEFAULT", "lean")) or "lean"


def resolve_native_chat_profile(*, channel: Any | None = None) -> ContextProfile:
    policy = resolve_native_context_policy(channel=channel)
    return get_context_profile(_NATIVE_CONTEXT_POLICY_TO_PROFILE[policy])


def get_context_profile(name: str) -> ContextProfile:
    return _PROFILES.get(name, _PROFILES["chat"])


def resolve_context_profile(
    *,
    session: Session | None = None,
    profile_name: str | None = None,
    origin: str | None = None,
    channel: Any | None = None,
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

    return resolve_native_chat_profile(channel=channel)


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
