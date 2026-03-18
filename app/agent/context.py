"""Request-scoped context for the agent loop (e.g. session_id, client_id for tools)."""
import uuid
from contextvars import ContextVar

current_session_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_session_id", default=None
)
current_client_id: ContextVar[str | None] = ContextVar(
    "current_client_id", default=None
)

# Used by search_memories tool; set when memory.enabled so retrieval uses bot's scope/threshold.
current_memory_cross_session: ContextVar[bool | None] = ContextVar(
    "current_memory_cross_session", default=None
)
current_memory_cross_client: ContextVar[bool | None] = ContextVar(
    "current_memory_cross_client", default=None
)
current_memory_similarity_threshold: ContextVar[float | None] = ContextVar(
    "current_memory_similarity_threshold", default=None
)


def set_agent_context(
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    *,
    memory_cross_session: bool | None = None,
    memory_cross_client: bool | None = None,
    memory_similarity_threshold: float | None = None,
) -> None:
    """Set the current agent context. Call at the start of run_stream."""
    current_session_id.set(session_id)
    current_client_id.set(client_id)
    if memory_cross_session is not None:
        current_memory_cross_session.set(memory_cross_session)
    if memory_cross_client is not None:
        current_memory_cross_client.set(memory_cross_client)
    if memory_similarity_threshold is not None:
        current_memory_similarity_threshold.set(memory_similarity_threshold)
