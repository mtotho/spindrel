"""Integration SDK — single-import convenience module.

Everything an integration needs to build targets, renderers, hooks, and
tools, importable from one place::

    from integrations.sdk import (
        BaseTarget, target_registry,           # target authoring
        ChannelRenderer, DeliveryReceipt,      # renderer authoring
        renderer_registry, Capability,
        ChannelEvent, ChannelEventKind,
        DispatchTarget, OutboundAction,
        IntegrationMeta, HookContext,          # hooks authoring
        register_hook, register_integration,
        current_dispatch_config,               # runtime context
        current_dispatch_type,
        current_bot_id, current_channel_id,
        get_setting,                           # settings
        register_tool, get_settings,           # tool registration
        inject_message, get_or_create_session, # session/document helpers
        ingest_document, search_documents,
        emit_integration_event,               # event trigger emission
        async_session,                         # database
        get_db, verify_auth,                   # FastAPI dependencies
        verify_admin_auth, verify_auth_or_user,
        resolve_all_channels_by_client_id,     # channel helpers
        ensure_active_session,
        sanitize_unicode, safe_create_task,    # utilities
        get_bot, client_id,
    )

Works for in-repo integrations, packages/, and external INTEGRATION_DIRS.
When running standalone (outside the server), provides compatible stubs
for tool registration so integrations can be developed independently.

Message ingest contract (REQUIRED READING FOR INTEGRATION AUTHORS)
------------------------------------------------------------------

When your integration receives a user-authored message and submits it to
the agent (via ``submit_chat``, ``inject_message``, or
``store_passive_message_http``), follow this rule:

    ``content`` = the raw text the human typed.
    ``msg_metadata`` / ``extra_metadata`` = everything else.

Do NOT concatenate ``[Source channel:… user:…]`` or ``[Name]:`` or thread
summaries into ``content``. The assembly layer composes the LLM-facing
attribution prefix from metadata and injects thread context as a system
block — having integrations do their own formatting produces double
attribution, fragile UI strippers, and drift between what the human
actually said and what we store.

Metadata shape (see ``app.routers.chat._schemas.IngestMessageMetadata``)::

    {
        "source": "slack",                         # required
        "sender_id": "slack:U06STGBF4Q0",          # required, namespaced
        "sender_display_name": "Olivia",           # required
        "sender_type": "human",                    # required ("human" | "bot")
        "channel_external_id": "C06RY3YBSLE",      # optional
        "mention_token": "<@U06STGBF4Q0>",         # optional; platform-native
                                                   #  tag syntax so the agent
                                                   #  can echo it back verbatim
        "thread_context": "[Thread context — …]",  # optional; multi-line,
                                                   #  LLM-ready prior-message
                                                   #  summary
        "is_from_me": False,                       # optional; BlueBubbles
        "passive": False,                          # optional
        "trigger_rag": True,                       # optional
        "recipient_id": "bot:calc-bot",            # optional
    }

Worked example — Slack inbound::

    msg_metadata = {
        "source": "slack",
        "sender_id": f"slack:{user}",
        "sender_display_name": display_name,
        "sender_type": "human",
        "channel_external_id": channel,
        "mention_token": f"<@{user}>",      # required for outbound @-tags
        "thread_context": thread_summary or None,
    }
    await submit_chat(
        message=text,                       # RAW user text — nothing else
        bot_id=bot_id, client_id=client_id,
        msg_metadata=msg_metadata,
        dispatch_type="slack", dispatch_config={...},
    )

See ``docs/integrations/message-ingest-contract.md`` for the full
rationale and the walkthrough for Discord / BlueBubbles / etc.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Tool registration — with standalone fallback
# ---------------------------------------------------------------------------

try:
    from app.tools.registry import register as register_tool  # noqa: F401
    from app.tools.registry import get_settings  # noqa: F401
except ImportError:

    def register_tool(schema, *, source_dir=None, safety_tier="readonly", execution_policy="normal", returns=None, **kwargs):  # type: ignore[misc]
        """Stub register — attaches schema for later discovery."""

        def decorator(func):
            func._tool_schema = schema
            func._safety_tier = safety_tier
            func._execution_policy = execution_policy
            return func

        return decorator

    def get_settings():  # type: ignore[misc]
        """Stub get_settings — returns a function that reads env vars."""
        import os
        return lambda key, default="": os.environ.get(key, default)


# ---------------------------------------------------------------------------
# Target authoring
# ---------------------------------------------------------------------------

from app.domain.dispatch_target import _BaseTarget as BaseTarget  # noqa: E402, F401
from app.domain.dispatch_target import DispatchTarget, parse_dispatch_target  # noqa: E402, F401
from app.domain import target_registry  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Renderer authoring
# ---------------------------------------------------------------------------

from app.integrations.renderer import ChannelRenderer, DeliveryReceipt, SimpleRenderer  # noqa: E402, F401
from app.integrations import renderer_registry  # noqa: E402, F401
from app.domain.capability import Capability  # noqa: E402, F401
from app.domain.actor import ActorRef  # noqa: E402, F401
from app.domain.channel_events import ChannelEvent, ChannelEventKind  # noqa: E402, F401
from app.domain.message import Message as DomainMessage  # noqa: E402, F401
from app.domain.outbound_action import OutboundAction, UploadFile, UploadImage  # noqa: E402, F401
from app.domain.payloads import MessagePayload  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Hooks authoring
# ---------------------------------------------------------------------------

from app.agent.hooks import (  # noqa: E402, F401
    IntegrationMeta,
    HookContext,
    get_integration_meta,
    register_hook,
    register_integration,
)

# ---------------------------------------------------------------------------
# Runtime context
# ---------------------------------------------------------------------------

from app.agent.context import (  # noqa: E402, F401
    current_client_id,
    current_correlation_id,
    current_dispatch_config,
    current_dispatch_type,
    current_model_override,
    current_provider_id_override,
    current_session_id,
    current_user_id,
)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

from app.services.integration_settings import (  # noqa: E402, F401
    delete_setting,
    get_status,
    get_value,
    get_value as get_setting,
    set_status,
    update_settings,
)

# ---------------------------------------------------------------------------
# Session / document helpers (re-exported from integrations.utils)
# ---------------------------------------------------------------------------

from integrations.utils import (  # noqa: E402, F401
    inject_message,
    get_or_create_session,
    ingest_document,
    search_documents,
    emit_integration_event,
)

# ---------------------------------------------------------------------------
# Tool-output rendering helpers (shared across renderers)
# ---------------------------------------------------------------------------

from integrations.tool_output import (  # noqa: E402, F401
    ToolBadge,
    ToolOutputDisplay,
    ToolOutputDisplayValue,
    ToolResultCard,
    ToolResultCode,
    ToolResultField,
    ToolResultImage,
    ToolResultLink,
    ToolResultPresentation,
    ToolResultRenderingSupport,
    ToolResultTable,
    build_tool_result_presentation,
    extract_tool_badges,
)

# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------

from app.db.engine import async_session  # noqa: E402, F401
from app.db.models import (  # noqa: E402, F401
    Attachment,
    Bot as BotRow,
    Channel,
    ChannelIntegration,
    IntegrationDocument,
    IntegrationSetting,
    Message,
    Session,
    Task,
)

# ---------------------------------------------------------------------------
# FastAPI dependencies (for router.py endpoints)
# ---------------------------------------------------------------------------

from app.dependencies import get_db  # noqa: E402, F401
from app.dependencies import verify_auth  # noqa: E402, F401
from app.dependencies import verify_admin_auth  # noqa: E402, F401
from app.dependencies import verify_auth_or_user  # noqa: E402, F401
from app.schemas.binding_suggestions import BindingSuggestion  # noqa: E402, F401
from app.services.api_keys import has_scope, validate_api_key  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Channel / session helpers
# ---------------------------------------------------------------------------

from app.services.channels import (  # noqa: E402, F401
    resolve_all_channels_by_client_id,
    ensure_active_session,
    get_channel_for_integration,
)
from app.services.outbox import (  # noqa: E402, F401
    count_pending_outbox,
)
from app.services.machine_control import (  # noqa: E402, F401
    _utc_now_iso as machine_utc_now_iso,
    get_provider,
    get_target_by_id,
)

# ---------------------------------------------------------------------------
# Agent context (runtime ContextVars available inside tool/hook callbacks)
# ---------------------------------------------------------------------------

from app.agent.context import (  # noqa: E402, F401
    current_bot_id,
    current_channel_id,
)

# ---------------------------------------------------------------------------
# Common utilities
# ---------------------------------------------------------------------------

from app.security.prompt_sanitize import sanitize_unicode  # noqa: E402, F401
from app.security.audit import log_outbound_request  # noqa: E402, F401
from app.utils import safe_create_task  # noqa: E402, F401
from app.utils.url_validation import pin_url, resolve_and_pin, validate_url  # noqa: E402, F401
from app.agent.bots import get_bot  # noqa: E402, F401
from app.config import settings as app_settings  # noqa: E402, F401
from app.services.approval_suggestions import build_suggestions  # noqa: E402, F401
from app.services.attachments import create_widget_backed_attachment  # noqa: E402, F401
from app.services.prompt_resolution import resolve_prompt  # noqa: E402, F401
from app.services.sandbox import sandbox_service, workspace_to_sandbox_config  # noqa: E402, F401
from app.services.sessions import load_or_create, store_passive_message  # noqa: E402, F401
from app.services.time_coercion import to_iso_z_or_none  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Agent harnesses — runtime contract + approvals helper
# ---------------------------------------------------------------------------
# Integration-side harnesses (claude_code, future codex, ...) plug into the
# Spindrel turn pipeline through this surface. The boundary test in
# tests/unit/test_integration_import_boundary.py forbids direct app.* imports
# from harness modules — they go through these re-exports instead.

from app.services.agent_harnesses.base import (  # noqa: E402, F401
    AuthStatus,
    ChannelEventEmitter,
    HarnessCompactResult,
    HarnessContextHint,
    HarnessModelOption,
    HarnessRuntime,
    HarnessSlashCommandPolicy,
    RuntimeCapabilities,
    TurnContext,
    TurnResult,
)
from app.services.agent_harnesses import register_runtime  # noqa: E402, F401
from app.services.agent_harnesses.approvals import (  # noqa: E402, F401
    AllowDeny,
    grant_turn_bypass,
    request_harness_approval,
    revoke_turn_bypass,
)
from app.services.agent_harnesses.settings import (  # noqa: E402, F401
    HARNESS_SETTINGS_KEY,
    HarnessSettings,
    load_session_settings,
    patch_session_settings,
)
from app.services.agent_harnesses.session_state import (  # noqa: E402, F401
    HarnessStatus,
    add_context_hint,
    clear_consumed_context_hints,
    compact_harness_session,
    load_context_hints,
    load_latest_harness_metadata,
)
from app.services.agent_harnesses.interactions import (  # noqa: E402, F401
    HarnessQuestionAnswer,
    HarnessQuestionResult,
    request_harness_question,
)
from app.services.agent_harnesses.tools import (  # noqa: E402, F401
    HarnessBridgeInventory,
    HarnessToolSpec,
    execute_harness_spindrel_tool,
    list_harness_spindrel_tools,
    list_harness_spindrel_tools_for,
    resolve_harness_bridge_inventory,
)

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


# Compat alias — legacy code imports `sdk.register` (without the _tool suffix)
register = register_tool


def get_setting_value(integration_id: str, key: str) -> str | None:
    """Read an integration setting when present, returning ``None`` for empty/missing."""
    value = get_setting(integration_id, key, "")
    return value if value else None


def resolve_task_timeout(task) -> int:
    """Resolve a task timeout without importing the agent task module at SDK import time."""
    from app.agent.tasks import resolve_task_timeout as _resolve_task_timeout

    return _resolve_task_timeout(task)


def get_widget_template(tool_name: str):
    """Look up a widget template without importing widget rendering at SDK import time."""
    from app.services.widget_templates import get_widget_template as _get_widget_template

    return _get_widget_template(tool_name)


def client_id(prefix: str, raw_id: str) -> str:
    """Build a prefixed client_id.

    >>> client_id("slack", "C01ABC123")
    'slack:C01ABC123'
    """
    return f"{prefix}:{raw_id}"


def make_settings(integration_id: str, keys: dict[str, str]) -> type:
    """Generate a DB-backed settings class for an integration.

    Each key becomes a ``@property`` that reads from DB cache > env var > default.
    Returns the class (instantiate it yourself as ``settings = make_settings(...)()``).

    Usage::

        from integrations.sdk import make_settings

        _Settings = make_settings("github", {
            "GITHUB_TOKEN": "",
            "GITHUB_WEBHOOK_SECRET": "",
            "GITHUB_BOT_LOGIN": "",
        })
        settings = _Settings()

        # settings.GITHUB_TOKEN reads from DB > env > ""

    For non-string types, subclass the result and override specific properties::

        class _Settings(make_settings("frigate", {"FRIGATE_URL": "", ...})):
            @property
            def FRIGATE_MQTT_PORT(self) -> int:
                return int(self._get("FRIGATE_MQTT_PORT", "1883"))

            @property
            def FRIGATE_MQTT_CAMERAS(self) -> list[str]:
                val = self._get("FRIGATE_MQTT_CAMERAS")
                return [c.strip() for c in val.split(",") if c.strip()] if val else []
    """
    import os as _os

    def _get_value(key: str, default: str = "") -> str:
        try:
            from app.services.integration_settings import get_value
            return get_value(integration_id, key, default)
        except ImportError:
            return _os.environ.get(key, default)

    def _make_prop(key: str, default: str) -> property:
        return property(lambda self: _get_value(key, default))

    attrs: dict = {"_get": staticmethod(_get_value)}
    for key, default in keys.items():
        attrs[key] = _make_prop(key, default)

    return type("_Settings", (), attrs)
