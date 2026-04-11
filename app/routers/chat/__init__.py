"""Chat router package — re-exports for backward compatibility.

All external code (tests, etc.) can continue to
``from app.routers.chat import X`` without changes.
"""
# --- Router ---
from ._routes import router  # noqa: F401

# --- Schemas ---
from ._schemas import (  # noqa: F401
    Attachment,
    FileMetadata,
    ChatRequest,
    CancelRequest,
    CancelResponse,
    ChatResponse,
    SecretCheckRequest,
    SecretCheckResponse,
    ToolResultRequest,
)

# --- Helpers ---
from ._helpers import (  # noqa: F401
    _is_integration_client,
    _extract_user,
    _create_attachments_from_metadata,
    _resolve_channel_and_session,
    _resolve_audio_native,
    _transcribe_audio_data,
)

# --- Keepalive ---
from ._keepalive import SSE_KEEPALIVE_INTERVAL, _with_keepalive  # noqa: F401

# --- Context ---
from ._context import (  # noqa: F401
    BotContext,
    prepare_bot_context,
    _build_identity_preamble,
    _apply_user_attribution,
    _rewrite_history_for_member_bot,
    _inject_member_config,
)

# --- Multibot ---
from ._multibot import (  # noqa: F401
    _background_tasks,
    _maybe_route_to_member_bot,
    _MEMBER_MENTION_MAX_DEPTH,
    _detect_member_mentions,
    _trigger_member_bot_replies,
    _run_member_bot_reply,
)

# --- Names used by test patch targets that resolve through this module ---
# These are imported in submodules and patched via "app.routers.chat.X" in tests.
# Re-exporting them here ensures `from app.routers.chat import X` works,
# but patches must target the actual submodule (e.g. "app.routers.chat._routes.run").
from app.agent.bots import get_bot  # noqa: F401
from app.agent.loop import run, run_stream  # noqa: F401
from app.agent.context import set_agent_context  # noqa: F401
from app.services.sessions import persist_turn  # noqa: F401
from app.services.compaction import maybe_compact  # noqa: F401
from app.services import session_locks  # noqa: F401
from app.services.channel_throttle import (  # noqa: F401
    is_throttled as _channel_throttled,
    record_run as _record_channel_run,
)
