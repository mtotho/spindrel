from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.agent.prompt_sizing import message_prompt_tokens
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
    live_history_strategy: str = "turns"
    live_history_budget_ratio: float | None = None
    min_recent_turns: int = 0
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
    # Tool-observation controls tune the already-existing result capping and
    # in-loop pruning path by profile. ``always`` means prune after each tool
    # iteration once there is an older iteration to compact; ``pressure`` keeps
    # the historical context-window pressure gate.
    in_loop_pruning_mode: str | None = None
    tool_result_hard_cap: int | None = None
    tool_turn_aggregate_cap_chars: int | None = None

    def to_policy_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "live_history_turns": self.live_history_turns,
            "live_history_strategy": self.live_history_strategy,
            "live_history_budget_ratio": self.live_history_budget_ratio,
            "min_recent_turns": self.min_recent_turns,
            "allow_plan_artifact": self.allow_plan_artifact,
            "allow_tool_index": self.allow_tool_index,
            "allow_skill_index": self.allow_skill_index,
            "keep_iterations_override": self.keep_iterations_override,
            "mandatory_static_injections": list(self.mandatory_static_injections),
            "optional_static_injections": list(self.optional_static_injections),
            "memory_bootstrap_max_chars": self.memory_bootstrap_max_chars,
            "section_index_count_default": self.section_index_count_default,
            "section_index_verbosity_default": self.section_index_verbosity_default,
            "in_loop_pruning_mode": self.in_loop_pruning_mode,
            "tool_result_hard_cap": self.tool_result_hard_cap,
            "tool_turn_aggregate_cap_chars": self.tool_turn_aggregate_cap_chars,
        }


_PROFILES: dict[str, ContextProfile] = {
    "chat_lean": ContextProfile(
        name="chat_lean",
        live_history_turns=None,
        live_history_strategy="token_fit",
        live_history_budget_ratio=0.20,
        min_recent_turns=2,
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
        keep_iterations_override=2,
        in_loop_pruning_mode="always",
        tool_result_hard_cap=12000,
        tool_turn_aggregate_cap_chars=30000,
    ),
    "chat_standard": ContextProfile(
        name="chat_standard",
        live_history_turns=None,
        live_history_strategy="token_fit",
        live_history_budget_ratio=0.45,
        min_recent_turns=2,
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
        keep_iterations_override=2,
        in_loop_pruning_mode="always",
        tool_result_hard_cap=12000,
        tool_turn_aggregate_cap_chars=30000,
    ),
    "chat_rich": ContextProfile(
        name="chat_rich",
        live_history_turns=None,
        live_history_strategy="token_fit",
        live_history_budget_ratio=0.65,
        min_recent_turns=3,
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
        keep_iterations_override=2,
        in_loop_pruning_mode="always",
        tool_result_hard_cap=16000,
        tool_turn_aggregate_cap_chars=40000,
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
        live_history_turns=4,
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
        keep_iterations_override=2,
        in_loop_pruning_mode="always",
        tool_result_hard_cap=12000,
        tool_turn_aggregate_cap_chars=30000,
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
        in_loop_pruning_mode="pressure",
    ),
    "memory_flush": ContextProfile(
        name="memory_flush",
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
        keep_iterations_override=1,
        in_loop_pruning_mode="always",
        tool_result_hard_cap=6000,
        tool_turn_aggregate_cap_chars=12000,
    ),
    "memory_hygiene": ContextProfile(
        name="memory_hygiene",
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
        keep_iterations_override=1,
        in_loop_pruning_mode="always",
        tool_result_hard_cap=6000,
        tool_turn_aggregate_cap_chars=12000,
    ),
    "skill_review": ContextProfile(
        name="skill_review",
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
        keep_iterations_override=2,
        in_loop_pruning_mode="always",
        tool_result_hard_cap=8000,
        tool_turn_aggregate_cap_chars=16000,
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
        keep_iterations_override=1,
        in_loop_pruning_mode="always",
        tool_result_hard_cap=6000,
        tool_turn_aggregate_cap_chars=12000,
    ),
}

_PROFILES["chat"] = _PROFILES["chat_standard"]

_NATIVE_CONTEXT_POLICY_TO_PROFILE = {
    "lean": "chat_lean",
    "standard": "chat_standard",
    "rich": "chat_rich",
    "manual": "chat_standard",
}


def normalize_native_context_policy(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in {"lean", "standard", "rich", "manual"}:
        return raw
    return None


def resolve_native_context_policy(*, channel: Any | None = None) -> str:
    if channel is not None:
        cfg = getattr(channel, "config", None) or {}
        channel_policy = normalize_native_context_policy(cfg.get("native_context_policy"))
        if channel_policy:
            return channel_policy

    from app.config import settings

    return normalize_native_context_policy(getattr(settings, "NATIVE_CONTEXT_POLICY_DEFAULT", "standard")) or "standard"


def resolve_native_chat_profile(*, channel: Any | None = None) -> ContextProfile:
    policy = resolve_native_context_policy(channel=channel)
    return get_context_profile(_NATIVE_CONTEXT_POLICY_TO_PROFILE[policy])


def resolve_chat_live_history_policy(
    profile: ContextProfile,
    *,
    channel: Any | None = None,
) -> tuple[float | None, int]:
    """Return live-history token-fit ratio and minimum recent turns.

    Manual channel overrides live in ``Channel.config`` so deployments do not
    need schema churn for tuning knobs.
    """
    ratio = profile.live_history_budget_ratio
    min_turns = profile.min_recent_turns
    if channel is not None:
        cfg = getattr(channel, "config", None) or {}
        if normalize_native_context_policy(cfg.get("native_context_policy")) == "manual":
            try:
                manual_ratio = float(cfg.get("native_context_live_history_ratio"))
                if 0.01 <= manual_ratio <= 0.95:
                    ratio = manual_ratio
            except (TypeError, ValueError):
                pass
            try:
                manual_min = int(cfg.get("native_context_min_recent_turns"))
                if manual_min >= 0:
                    min_turns = manual_min
            except (TypeError, ValueError):
                pass
    return ratio, min_turns


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


def trim_messages_to_token_budget(
    messages: list[dict],
    *,
    max_tokens: int,
    min_recent_turns: int = 2,
) -> list[dict]:
    """Trim replay history newest-first by complete user-started turns.

    System prefix is preserved. The newest ``min_recent_turns`` are kept even
    when they exceed the target so normal chat does not lose immediate
    continuity. Final tool-pair sanitization still runs after loading.
    """
    if max_tokens <= 0:
        return trim_messages_to_recent_turns(messages, min_recent_turns)

    sys_prefix: list[dict] = []
    body: list[dict] = []
    in_body = False
    for msg in messages:
        if not in_body and msg.get("role") == "system":
            sys_prefix.append(msg)
        else:
            in_body = True
            body.append(msg)
    if not body:
        return sys_prefix

    turn_starts = [idx for idx, msg in enumerate(body) if msg.get("role") == "user"]
    if not turn_starts:
        return sys_prefix + body if sum(message_prompt_tokens(m) for m in body) <= max_tokens else sys_prefix

    turns: list[list[dict]] = []
    leading = body[:turn_starts[0]]
    if leading:
        turns.append(leading)
    for pos, start in enumerate(turn_starts):
        end = turn_starts[pos + 1] if pos + 1 < len(turn_starts) else len(body)
        turns.append(body[start:end])

    kept_reversed: list[list[dict]] = []
    used = 0
    user_turns_kept = 0
    for turn in reversed(turns):
        is_user_turn = any(msg.get("role") == "user" for msg in turn)
        turn_tokens = sum(message_prompt_tokens(msg) for msg in turn)
        must_keep = is_user_turn and user_turns_kept < min_recent_turns
        if must_keep or used + turn_tokens <= max_tokens:
            kept_reversed.append(turn)
            used += turn_tokens
            if is_user_turn:
                user_turns_kept += 1
        elif is_user_turn and user_turns_kept >= min_recent_turns:
            continue

    kept: list[dict] = []
    for turn in reversed(kept_reversed):
        kept.extend(turn)
    return sys_prefix + kept
