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
        get_setting,                           # settings
        register_tool, get_settings,           # tool registration
        inject_message, get_or_create_session, # session/document helpers
        ingest_document, search_documents,
        client_id,                             # utility
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

from app.integrations.renderer import ChannelRenderer, DeliveryReceipt  # noqa: E402, F401
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
)

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
