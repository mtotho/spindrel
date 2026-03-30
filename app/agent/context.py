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

# Effective model/provider for the current agent run (after override resolution).
# Tools (e.g. delegate_to_harness) read these to propagate the model to callback tasks.
current_model_override: ContextVar[str | None] = ContextVar("current_model_override", default=None)
current_provider_id_override: ContextVar[str | None] = ContextVar("current_provider_id_override", default=None)

# Dynamically injected tool schemas (e.g. heartbeat_post_to_thread for channel_and_thread mode).
# Set explicitly in run_stream; NOT managed by set_agent_context.
current_injected_tools: ContextVar[list[dict] | None] = ContextVar("current_injected_tools", default=None)

current_session_depth: ContextVar[int] = ContextVar("current_session_depth", default=0)
current_root_session_id: ContextVar[uuid.UUID | None] = ContextVar("current_root_session_id", default=None)
current_ephemeral_delegates: ContextVar[list] = ContextVar("current_ephemeral_delegates", default=[])
current_ephemeral_skills: ContextVar[list] = ContextVar("current_ephemeral_skills", default=[])

# Accumulates child-bot Slack posts from immediate delegation so run_stream() can
# emit them as delegation_post events BEFORE the parent's response event.
# Set to a list by the outermost run_stream(); None means post immediately.
current_pending_delegation_posts: ContextVar[list | None] = ContextVar(
    "pending_delegation_posts", default=None
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
    client_id: str | None
    bot_id: str | None
    memory_cross_channel: bool | None
    memory_cross_client: bool | None
    memory_similarity_threshold: float | None
    memory_cross_bot: bool | None
    dispatch_type: str | None
    dispatch_config: dict | None
    injected_tools: list[dict] | None
    session_depth: int
    root_session_id: uuid.UUID | None
    ephemeral_delegates: list
    ephemeral_skills: list
    model_override: str | None
    provider_id_override: str | None


def snapshot_agent_context() -> AgentContextSnapshot:
    return AgentContextSnapshot(
        session_id=current_session_id.get(),
        channel_id=current_channel_id.get(),
        correlation_id=current_correlation_id.get(),
        client_id=current_client_id.get(),
        bot_id=current_bot_id.get(),
        memory_cross_channel=current_memory_cross_channel.get(),
        memory_cross_client=current_memory_cross_client.get(),
        memory_similarity_threshold=current_memory_similarity_threshold.get(),
        memory_cross_bot=current_memory_cross_bot.get(),
        dispatch_type=current_dispatch_type.get(),
        dispatch_config=current_dispatch_config.get(),
        injected_tools=current_injected_tools.get(),
        session_depth=current_session_depth.get(),
        root_session_id=current_root_session_id.get(),
        ephemeral_delegates=list(current_ephemeral_delegates.get() or []),
        ephemeral_skills=list(current_ephemeral_skills.get() or []),
        model_override=current_model_override.get(),
        provider_id_override=current_provider_id_override.get(),
    )


def restore_agent_context(snap: AgentContextSnapshot) -> None:
    current_session_id.set(snap.session_id)
    current_channel_id.set(snap.channel_id)
    current_correlation_id.set(snap.correlation_id)
    current_client_id.set(snap.client_id)
    current_bot_id.set(snap.bot_id)
    current_memory_cross_channel.set(snap.memory_cross_channel)
    current_memory_cross_client.set(snap.memory_cross_client)
    current_memory_similarity_threshold.set(snap.memory_similarity_threshold)
    current_memory_cross_bot.set(snap.memory_cross_bot)
    current_dispatch_type.set(snap.dispatch_type)
    current_dispatch_config.set(snap.dispatch_config)
    current_injected_tools.set(snap.injected_tools)
    current_session_depth.set(snap.session_depth)
    current_root_session_id.set(snap.root_session_id)
    current_ephemeral_delegates.set(list(snap.ephemeral_delegates))
    current_ephemeral_skills.set(list(snap.ephemeral_skills))
    current_model_override.set(snap.model_override)
    current_provider_id_override.set(snap.provider_id_override)
