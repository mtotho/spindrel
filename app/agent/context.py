"""Request-scoped context for the agent loop (e.g. session_id, client_id for tools)."""
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

current_session_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_session_id", default=None
)
current_channel_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_channel_id", default=None
)
current_correlation_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_correlation_id", default=None
)
# Set by ``turn_worker.run_turn`` (and any other publisher of TURN_STARTED)
# to the per-turn UUID. Read by ``tool_dispatch._notify_approval_request`` so
# ``ApprovalRequestedPayload.turn_id`` carries the right routing key — without
# it, an approval requested by a member-bot turn while the primary turn is
# still active would land in the primary's "most recent in-flight" UI slot.
current_turn_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_turn_id", default=None
)
current_client_id: ContextVar[str | None] = ContextVar(
    "current_client_id", default=None
)
current_bot_id: ContextVar[str | None] = ContextVar(
    "current_bot_id", default=None
)

# Used by search_memories tool; set when memory.enabled so retrieval uses bot's scope/threshold.
current_memory_cross_channel: ContextVar[bool | None] = ContextVar(
    "current_memory_cross_channel", default=None
)
current_memory_cross_client: ContextVar[bool | None] = ContextVar(
    "current_memory_cross_client", default=None
)
current_memory_similarity_threshold: ContextVar[float | None] = ContextVar(
    "current_memory_similarity_threshold", default=None
)
current_memory_cross_bot: ContextVar[bool | None] = ContextVar(
    "current_memory_cross_bot", default=None
)

current_dispatch_type: ContextVar[str | None] = ContextVar("current_dispatch_type", default=None)
current_dispatch_config: ContextVar[dict | None] = ContextVar("current_dispatch_config", default=None)

# Origin of the current agent run — drives per-context policy gating so
# autonomous runs (heartbeat/task/subagent/hygiene) can default-require-approval
# on mutating ops even when interactive chat allows them outright.
# Values: "chat" | "heartbeat" | "task" | "subagent" | "hygiene".
# Default None is treated as "chat" by policy (least-restrictive, interactive).
current_run_origin: ContextVar[str | None] = ContextVar("current_run_origin", default=None)

# Effective model/provider for the current agent run (after override resolution).
# Tools read these to propagate the model to callback tasks.
current_model_override: ContextVar[str | None] = ContextVar("current_model_override", default=None)
current_provider_id_override: ContextVar[str | None] = ContextVar("current_provider_id_override", default=None)

# Dynamically injected tool schemas (e.g. heartbeat_post_to_thread for channel_and_thread mode).
# Set explicitly in run_stream; NOT managed by set_agent_context.
current_injected_tools: ContextVar[list[dict] | None] = ContextVar("current_injected_tools", default=None)

# Tools activated mid-loop by get_tool_info. The agent loop initializes this to
# an empty list at the start of run_agent_tool_loop and re-checks it at the top
# of each iteration, merging any appended schemas into tools_param so the LLM
# can actually invoke tools it looked up. Without this, the text hint "call
# get_tool_info(...) to load it" is a lie — get_tool_info returns the schema
# but the tool remains absent from the tools array and uncallable.
current_activated_tools: ContextVar[list[dict] | None] = ContextVar("current_activated_tools", default=None)

current_allowed_secrets: ContextVar[list[str] | None] = ContextVar("current_allowed_secrets", default=None)

# Set by the bot_invoke evaluator to swap the bot's system_prompt per-case
# without mutating the bot row. Read by ``_effective_system_prompt`` — when
# set, it replaces the entire effective prompt (no base prompt, no memory
# scheme layer), so experiments can measure the exact variant text in
# isolation. Unset means "use the bot's configured prompt" (normal path).
current_system_prompt_override: ContextVar[str | None] = ContextVar(
    "current_system_prompt_override", default=None,
)

# Per-request task creation counter (capped to prevent runaway loops)
task_creation_count: ContextVar[int] = ContextVar("task_creation_count", default=0)

current_session_depth: ContextVar[int] = ContextVar("current_session_depth", default=0)
current_root_session_id: ContextVar[uuid.UUID | None] = ContextVar("current_root_session_id", default=None)
current_ephemeral_delegates: ContextVar[list] = ContextVar("current_ephemeral_delegates", default=[])
current_ephemeral_skills: ContextVar[list] = ContextVar("current_ephemeral_skills", default=[])
# All skill IDs available to the bot after bot/channel enrollment resolution.
# Set by context_assembly; read by get_skill to authorize enrolled skills.
current_resolved_skill_ids: ContextVar[set | None] = ContextVar("current_resolved_skill_ids", default=None)
current_skills_in_context: ContextVar[list[dict] | None] = ContextVar(
    "current_skills_in_context", default=None,
)

# Channel-level model tier overrides (sparse dict, e.g. {"fast": {"model": "...", "provider_id": null}}).
# Set from context_assembly; read by delegation tools.
current_channel_model_tier_overrides: ContextVar[dict | None] = ContextVar(
    "current_channel_model_tier_overrides", default=None
)

# Accumulates child-bot Slack posts from immediate delegation so run_stream() can
# emit them as delegation_post events BEFORE the parent's response event.
# Set to a list by the outermost run_stream(); None means post immediately.
current_pending_delegation_posts: ContextVar[list | None] = ContextVar(
    "pending_delegation_posts", default=None
)

# Anti-loop: tracks which bots have already responded in the current user turn.
# Reset at the start of each outermost run_stream(); checked in delegation.
current_turn_responded_bots: ContextVar[set | None] = ContextVar(
    "current_turn_responded_bots", default=None
)

# Tracks member bots already invoked during the current turn (via auto-mention
# detection), so post-completion @-mention scan doesn't re-trigger them.
current_invoked_member_bots: ContextVar[set | None] = ContextVar(
    "current_invoked_member_bots", default=None
)


def set_agent_context(
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    bot_id: str | None = None,
    correlation_id: uuid.UUID | None = None,
    *,
    channel_id: uuid.UUID | None = None,
    memory_cross_channel: bool | None = None,
    memory_cross_client: bool | None = None,
    memory_cross_bot: bool | None = None,
    memory_similarity_threshold: float | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
    session_depth: int | None = None,
    root_session_id: uuid.UUID | None = None,
) -> None:
    """Set the current agent context. Call at the start of run_stream."""
    current_session_id.set(session_id)
    current_channel_id.set(channel_id)
    current_client_id.set(client_id)
    current_bot_id.set(bot_id)
    current_correlation_id.set(correlation_id)
    if memory_cross_channel is not None:
        current_memory_cross_channel.set(memory_cross_channel)
    if memory_cross_client is not None:
        current_memory_cross_client.set(memory_cross_client)
    if memory_similarity_threshold is not None:
        current_memory_similarity_threshold.set(memory_similarity_threshold)
    if memory_cross_bot is not None:
        current_memory_cross_bot.set(memory_cross_bot)
    current_dispatch_type.set(dispatch_type)
    current_dispatch_config.set(dispatch_config)
    current_channel_model_tier_overrides.set(None)
    if session_depth is not None:
        current_session_depth.set(session_depth)
    if root_session_id is not None:
        current_root_session_id.set(root_session_id)


def set_ephemeral_delegates(bot_ids: list[str]) -> None:
    """Set ephemeral @-tagged bot IDs that bypass delegation allowlist for this request."""
    current_ephemeral_delegates.set(list(bot_ids))


def set_ephemeral_skills(skill_ids: list[str]) -> None:
    """Set ephemeral @-tagged skill IDs that bypass bot skill allowlist for this request."""
    current_ephemeral_skills.set(list(skill_ids))


@dataclass
class AgentContextSnapshot:
    """Full copy of agent ContextVars for save/restore around nested runs (e.g. delegation)."""

    session_id: uuid.UUID | None
    channel_id: uuid.UUID | None
    correlation_id: uuid.UUID | None
    turn_id: uuid.UUID | None
    client_id: str | None
    bot_id: str | None
    memory_cross_channel: bool | None
    memory_cross_client: bool | None
    memory_similarity_threshold: float | None
    memory_cross_bot: bool | None
    dispatch_type: str | None
    dispatch_config: dict | None
    injected_tools: list[dict] | None
    activated_tools: list[dict] | None
    session_depth: int
    root_session_id: uuid.UUID | None
    ephemeral_delegates: list
    ephemeral_skills: list
    model_override: str | None
    provider_id_override: str | None
    channel_model_tier_overrides: dict | None
    resolved_skill_ids: set | None
    skills_in_context: list[dict] | None
    turn_responded_bots: set | None
    run_origin: str | None


def snapshot_agent_context() -> AgentContextSnapshot:
    return AgentContextSnapshot(
        session_id=current_session_id.get(),
        channel_id=current_channel_id.get(),
        correlation_id=current_correlation_id.get(),
        turn_id=current_turn_id.get(),
        client_id=current_client_id.get(),
        bot_id=current_bot_id.get(),
        memory_cross_channel=current_memory_cross_channel.get(),
        memory_cross_client=current_memory_cross_client.get(),
        memory_similarity_threshold=current_memory_similarity_threshold.get(),
        memory_cross_bot=current_memory_cross_bot.get(),
        dispatch_type=current_dispatch_type.get(),
        dispatch_config=current_dispatch_config.get(),
        injected_tools=current_injected_tools.get(),
        activated_tools=current_activated_tools.get(),
        session_depth=current_session_depth.get(),
        root_session_id=current_root_session_id.get(),
        ephemeral_delegates=list(current_ephemeral_delegates.get() or []),
        ephemeral_skills=list(current_ephemeral_skills.get() or []),
        model_override=current_model_override.get(),
        provider_id_override=current_provider_id_override.get(),
        channel_model_tier_overrides=current_channel_model_tier_overrides.get(),
        resolved_skill_ids=current_resolved_skill_ids.get(),
        skills_in_context=current_skills_in_context.get(),
        turn_responded_bots=current_turn_responded_bots.get(),
        run_origin=current_run_origin.get(),
    )


def restore_agent_context(snap: AgentContextSnapshot) -> None:
    current_session_id.set(snap.session_id)
    current_channel_id.set(snap.channel_id)
    current_correlation_id.set(snap.correlation_id)
    current_turn_id.set(snap.turn_id)
    current_client_id.set(snap.client_id)
    current_bot_id.set(snap.bot_id)
    current_memory_cross_channel.set(snap.memory_cross_channel)
    current_memory_cross_client.set(snap.memory_cross_client)
    current_memory_similarity_threshold.set(snap.memory_similarity_threshold)
    current_memory_cross_bot.set(snap.memory_cross_bot)
    current_dispatch_type.set(snap.dispatch_type)
    current_dispatch_config.set(snap.dispatch_config)
    current_injected_tools.set(snap.injected_tools)
    current_activated_tools.set(snap.activated_tools)
    current_session_depth.set(snap.session_depth)
    current_root_session_id.set(snap.root_session_id)
    current_ephemeral_delegates.set(list(snap.ephemeral_delegates))
    current_ephemeral_skills.set(list(snap.ephemeral_skills))
    current_model_override.set(snap.model_override)
    current_provider_id_override.set(snap.provider_id_override)
    current_channel_model_tier_overrides.set(snap.channel_model_tier_overrides)
    current_resolved_skill_ids.set(snap.resolved_skill_ids)
    current_skills_in_context.set(snap.skills_in_context)
    current_turn_responded_bots.set(snap.turn_responded_bots)
    current_run_origin.set(snap.run_origin)
