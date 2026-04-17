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
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Tool registration — with standalone fallback
# ---------------------------------------------------------------------------

try:
    from app.tools.registry import register as register_tool  # noqa: F401
    from app.tools.registry import get_settings  # noqa: F401
except ImportError:

    def register_tool(schema, *, source_dir=None, safety_tier="readonly"):  # type: ignore[misc]
        """Stub register — attaches schema for later discovery."""

        def decorator(func):
            func._tool_schema = schema
            func._safety_tier = safety_tier
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
from app.domain.dispatch_target import DispatchTarget  # noqa: E402, F401
from app.domain import target_registry  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Renderer authoring
# ---------------------------------------------------------------------------

from app.integrations.renderer import ChannelRenderer, DeliveryReceipt, SimpleRenderer  # noqa: E402, F401
from app.integrations import renderer_registry  # noqa: E402, F401
from app.domain.capability import Capability  # noqa: E402, F401
from app.domain.channel_events import ChannelEvent, ChannelEventKind  # noqa: E402, F401
from app.domain.outbound_action import OutboundAction  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Hooks authoring
# ---------------------------------------------------------------------------

from app.agent.hooks import (  # noqa: E402, F401
    IntegrationMeta,
    HookContext,
    register_hook,
    register_integration,
)

# ---------------------------------------------------------------------------
# Runtime context
# ---------------------------------------------------------------------------

from app.agent.context import (  # noqa: E402, F401
    current_dispatch_config,
    current_dispatch_type,
)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

from app.services.integration_settings import get_value as get_setting  # noqa: E402, F401

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
    extract_tool_badges,
)

# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------

from app.db.engine import async_session  # noqa: E402, F401

# ---------------------------------------------------------------------------
# FastAPI dependencies (for router.py endpoints)
# ---------------------------------------------------------------------------

from app.dependencies import get_db  # noqa: E402, F401
from app.dependencies import verify_auth  # noqa: E402, F401
from app.dependencies import verify_admin_auth  # noqa: E402, F401
from app.dependencies import verify_auth_or_user  # noqa: E402, F401

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
from app.utils import safe_create_task  # noqa: E402, F401
from app.agent.bots import get_bot  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


# Compat alias — legacy code imports `sdk.register` (without the _tool suffix)
register = register_tool


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
