"""Admin tool: integration management for the orchestrator bot."""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.tools.registry import register

logger = logging.getLogger(__name__)

# Valid features that can be scaffolded
_VALID_FEATURES = {
    "tools",
    "skills",
    "hooks",
    "process",
    "workflows",
    "renderer",
}


def _get_scaffold_dir() -> Path | None:
    """Return the workspace integrations directory (first external path in INTEGRATION_DIRS)."""
    try:
        from app.config import settings
        extra = settings.INTEGRATION_DIRS
    except Exception:
        import os
        extra = os.environ.get("INTEGRATION_DIRS", "")
    if not extra:
        return None
    for p in extra.split(":"):
        p = p.strip()
        if not p:
            continue
        path = Path(p).expanduser().resolve()
        if path.is_dir():
            return path
    return None


def _camel_name(integration_id: str, suffix: str) -> str:
    return "".join(p.capitalize() for p in integration_id.split("_")) + suffix


@dataclass(frozen=True)
class _ScaffoldPlan:
    integration_id: str
    pretty_name: str
    integration_dir: Path
    features: list[str]
    feature_set: frozenset[str]
    target_class: str
    renderer_class: str


def _build_scaffold_plan(integration_id: str, features: list[str] | None) -> _ScaffoldPlan | dict:
    if not re.match(r"^[a-z][a-z0-9_]*$", integration_id):
        return {"error": f"Invalid integration ID '{integration_id}'. Must be lowercase alphanumeric + underscores, starting with a letter."}

    features = features or []
    invalid = set(features) - _VALID_FEATURES
    if invalid:
        return {"error": f"Unknown features: {sorted(invalid)}. Valid: {sorted(_VALID_FEATURES)}"}

    scaffold_dir = _get_scaffold_dir()
    if scaffold_dir is None:
        return {"error": "No writable integration directory found in INTEGRATION_DIRS. Is a shared workspace configured?"}

    integration_dir = scaffold_dir / integration_id
    if integration_dir.exists():
        return {"error": f"Integration directory already exists: {integration_dir}"}

    pretty_name = integration_id.replace("_", " ").title()
    return _ScaffoldPlan(
        integration_id=integration_id,
        pretty_name=pretty_name,
        integration_dir=integration_dir,
        features=features,
        feature_set=frozenset(features),
        target_class=_camel_name(integration_id, "Target"),
        renderer_class=_camel_name(integration_id, "Renderer"),
    )


def _write_base_scaffold_files(plan: _ScaffoldPlan) -> None:
    integration_id = plan.integration_id
    integration_dir = plan.integration_dir
    pretty_name = plan.pretty_name

    integration_dir.mkdir(parents=True)
    (integration_dir / "__init__.py").write_text("")
    (integration_dir / "integration.yaml").write_text(f'''id: {integration_id}
name: {pretty_name}
icon: Plug
description: "{pretty_name} integration."
version: "1.0"

settings: []
  # - key: {integration_id.upper()}_API_KEY
  #   type: string
  #   label: "API key for {pretty_name}"
  #   required: true
  #   secret: true

# dependencies:
#   python:
#     - package: some-package
#       import_name: some_package

# binding:
#   client_id_prefix: "{integration_id}:"

provides: []
''')

    # Always create router.py
    (integration_dir / "router.py").write_text(f'''"""Router for {pretty_name} integration."""
from fastapi import APIRouter

router = APIRouter(tags=["{pretty_name}"])


@router.get("/ping")
async def ping():
    return {{"status": "ok", "integration": "{integration_id}"}}
''')

    # Always create README.md
    (integration_dir / "README.md").write_text(f'''# {pretty_name}

Custom integration scaffolded via `manage_integration(action="scaffold")`.

## Setup

1. Edit `integration.yaml` to declare settings, dependencies, bindings
2. Add tools in `tools/` and skills in `skills/`
3. Run `manage_integration(action="reload")` to hot-load without restart

## Files

- `integration.yaml` — Declarative manifest (settings, dependencies, bindings)
- `router.py` — FastAPI endpoints (webhooks, APIs)
- `renderer.py` — Thin ChannelRenderer router (when scaffolded)
- `transport.py` — Receipt-shaped platform API calls (when scaffolded)
- `message_delivery.py` — Durable NEW_MESSAGE delivery policy (when scaffolded)
- `__init__.py` — Package marker
''')


def _write_tools_scaffold(plan: _ScaffoldPlan) -> None:
    integration_id = plan.integration_id
    pretty_name = plan.pretty_name
    tools_dir = plan.integration_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / f"{integration_id}_tools.py").write_text(f'''"""Tools for {pretty_name} integration."""
from app.tools.registry import register, get_settings

setting = get_settings()


@register({{
    "type": "function",
    "function": {{
        "name": "{integration_id}_example",
        "description": "Example tool for {pretty_name}. Replace with your implementation.",
        "parameters": {{
            "type": "object",
            "properties": {{
                "query": {{
                    "type": "string",
                    "description": "Input query.",
                }},
            }},
            "required": ["query"],
        }},
    }},
}})
async def {integration_id}_example(query: str) -> str:
    return f"Hello from {pretty_name}! Query: {{query}}"
''')


def _write_skills_scaffold(plan: _ScaffoldPlan) -> None:
    integration_id = plan.integration_id
    pretty_name = plan.pretty_name
    skills_dir = plan.integration_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / f"{integration_id}-guide.md").write_text(f'''---
name: {integration_id}-guide
description: "Guide for using the {pretty_name} integration"
---

# {pretty_name} Guide

Describe when and how to use this integration here.
''')


def _write_renderer_scaffold(plan: _ScaffoldPlan) -> None:
    integration_id = plan.integration_id
    integration_dir = plan.integration_dir
    pretty_name = plan.pretty_name
    target_class = plan.target_class
    renderer_class = plan.renderer_class

    # ``target.py`` — typed dispatch destination, self-registers with
    # ``app.domain.target_registry`` at module import. The integration
    # discovery loop auto-imports this before ``renderer.py``.
    (integration_dir / "target.py").write_text(f'''"""{target_class} — typed dispatch destination for the {pretty_name} integration.

Self-registers with ``app.domain.target_registry`` at module import.
The integration discovery loop auto-imports this module before
``renderer.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from integrations.sdk import BaseTarget, target_registry


@dataclass(frozen=True)
class {target_class}(BaseTarget):
    """{pretty_name} dispatch destination.

    Add the fields your renderer needs to actually deliver a message
    (channel id, auth token, thread/comment id, etc.). Optional fields
    must have defaults — required fields are validated by
    ``parse_dispatch_target``.
    """

    type: ClassVar[Literal["{integration_id}"]] = "{integration_id}"
    integration_id: ClassVar[str] = "{integration_id}"

    # Required fields:
    # channel_id: str
    # token: str

    # Optional fields (must have defaults):
    # thread_id: str | None = None


target_registry.register({target_class})
''')

    # ``transport.py`` — receipt-shaped platform API calls for renderer
    # delivery. Keep this separate from tools, which often want
    # exception-shaped API helpers instead.
    (integration_dir / "transport.py").write_text(f'''"""{pretty_name} renderer transport.

Renderer delivery wants receipt-shaped API results so the outbox drainer
can decide whether to retry. Replace the placeholder URL/body mapping
with the platform's real API.
"""
from __future__ import annotations

import logging

import httpx

from integrations.sdk import DeliveryReceipt

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=30.0)


class {renderer_class}CallResult:
    """Success/failure carrier for {pretty_name} renderer API calls."""

    __slots__ = ("success", "data", "error", "retryable")

    def __init__(
        self,
        success: bool,
        *,
        data: dict | None = None,
        error: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.success = success
        self.data = data
        self.error = error
        self.retryable = retryable

    @classmethod
    def ok(cls, data: dict | None = None) -> "{renderer_class}CallResult":
        return cls(True, data=data or {{}})

    @classmethod
    def failed(
        cls,
        error: str,
        *,
        retryable: bool,
    ) -> "{renderer_class}CallResult":
        return cls(False, error=error, retryable=retryable)

    def to_receipt(self) -> DeliveryReceipt:
        if self.success:
            external_id = (self.data or {{}}).get("id")
            return DeliveryReceipt.ok(external_id=external_id)
        return DeliveryReceipt.failed(
            self.error or "unknown",
            retryable=self.retryable,
        )


async def call_platform(
    method: str,
    token: str,
    body: dict,
) -> {renderer_class}CallResult:
    """Make one {pretty_name} API call for renderer delivery."""
    if not token:
        return {renderer_class}CallResult.failed(
            "{integration_id} target missing token",
            retryable=False,
        )

    # TODO: map method/body to the platform's real endpoint.
    url = f"https://api.example.invalid/{integration_id}/{{method}}"
    try:
        response = await _http.post(
            url,
            json=body,
            headers={{"Authorization": f"Bearer {{token}}"}},
        )
    except httpx.RequestError as exc:
        logger.warning("{integration_id} transport: %s connection error: %s", method, exc)
        return {renderer_class}CallResult.failed(
            f"connection error: {{exc}}",
            retryable=True,
        )

    try:
        data = response.json()
    except ValueError:
        data = {{}}

    if not response.is_success:
        return {renderer_class}CallResult.failed(
            f"{integration_id} {{method}} HTTP {{response.status_code}}",
            retryable=response.status_code >= 500,
        )
    return {renderer_class}CallResult.ok(data)


__all__ = ["{renderer_class}CallResult", "call_platform"]
''')

    # ``message_delivery.py`` — owns durable NEW_MESSAGE delivery policy.
    # The renderer delegates here rather than growing per-kind handlers.
    (integration_dir / "message_delivery.py").write_text(f'''"""{pretty_name} durable NEW_MESSAGE delivery."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from integrations.sdk import ChannelEvent, DeliveryReceipt
from integrations.{integration_id}.target import {target_class}

PlatformCall = Callable[[str, str, dict], Awaitable[Any]]


class {renderer_class}MessageDelivery:
    """Deliver durable ``NEW_MESSAGE`` events for {pretty_name}."""

    def __init__(self, *, call_platform: PlatformCall) -> None:
        self._call_platform = call_platform

    async def render(
        self,
        event: ChannelEvent,
        target: {target_class},
    ) -> DeliveryReceipt:
        payload = event.payload
        msg = getattr(payload, "message", None)
        if msg is None:
            return DeliveryReceipt.skipped("new_message without message payload")

        role = getattr(msg, "role", "") or ""
        if role in ("tool", "system"):
            return DeliveryReceipt.skipped(
                f"{integration_id} skips internal role={{role}}"
            )

        text = (getattr(msg, "content", "") or "").strip()
        if not text:
            return DeliveryReceipt.skipped("new_message with empty content")

        channel_id = getattr(target, "channel_id", "") or ""
        token = getattr(target, "token", "") or ""
        if not channel_id or not token:
            return DeliveryReceipt.failed(
                "{integration_id} target missing channel_id or token",
                retryable=False,
            )

        return (await self._call_platform(
            "send_message",
            token,
            {{"channel_id": channel_id, "text": text}},
        )).to_receipt()


__all__ = ["{renderer_class}MessageDelivery"]
''')

    # ``renderer.py`` — thin router over deep delivery modules. Slack's
    # renderer is the canonical example for richer integrations.
    (integration_dir / "renderer.py").write_text(f'''"""{renderer_class} — channel renderer for {pretty_name} delivery.

Subscribes to the channel-events bus via the renderer registry. The
outbox drainer (``app/services/outbox_drainer.py``) calls
``render(event, target)`` for each {integration_id}-bound row.
NEW_MESSAGE events reach this renderer ONLY via the outbox drainer
because ``ChannelEventKind.is_outbox_durable`` is True for that kind —
the in-memory bus path (``IntegrationDispatcherTask``) short-circuits
outbox-durable kinds. Streaming kinds (TURN_STREAM_*, TURN_STARTED,
TURN_ENDED) still flow via the bus.
"""
from __future__ import annotations

import logging
from typing import ClassVar

from integrations.sdk import (
    Capability,
    ChannelEvent,
    ChannelEventKind,
    DeliveryReceipt,
    DispatchTarget,
    OutboundAction,
    renderer_registry,
)
from integrations.{integration_id}.message_delivery import {renderer_class}MessageDelivery
from integrations.{integration_id}.target import {target_class}
from integrations.{integration_id}.transport import call_platform

logger = logging.getLogger(__name__)


class {renderer_class}:
    """Channel renderer for {pretty_name} delivery.

    Declare every capability the integration supports. The dispatcher
    only delivers events whose ``required_capabilities()`` is a subset
    of this set, so unsupported kinds never reach ``render()``.
    """

    integration_id: ClassVar[str] = "{integration_id}"
    capabilities: ClassVar[frozenset[Capability]] = frozenset({{
        Capability.TEXT,
        # Capability.RICH_TEXT,
        # Capability.STREAMING_EDIT,
        # Capability.ATTACHMENTS,
        # Capability.APPROVAL_BUTTONS,
    }})
    tool_result_rendering = None

    def __init__(self) -> None:
        self._messages = {renderer_class}MessageDelivery(
            call_platform=call_platform,
        )

    async def render(
        self,
        event: ChannelEvent,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        if not isinstance(target, {target_class}):
            return DeliveryReceipt.failed(
                f"{renderer_class} received non-{integration_id} target: "
                f"{{type(target).__name__}}",
                retryable=False,
            )

        kind = event.kind
        try:
            if kind == ChannelEventKind.NEW_MESSAGE:
                return await self._messages.render(event, target)
        except Exception as exc:
            logger.exception(
                "{renderer_class}.render: unexpected failure for %s",
                kind.value,
            )
            return DeliveryReceipt.failed(f"unexpected: {{exc}}", retryable=True)

        # Anything else is silently skipped — the outbox drainer marks
        # the row delivered with the skip reason.
        return DeliveryReceipt.skipped(
            f"{integration_id} does not handle {{kind.value}}"
        )

    async def handle_outbound_action(
        self,
        action: OutboundAction,
        target: DispatchTarget,
    ) -> DeliveryReceipt:
        return DeliveryReceipt.skipped(
            "{integration_id} outbound actions are not implemented"
        )

    async def delete_attachment(
        self,
        attachment_metadata: dict,
        target: DispatchTarget,
    ) -> bool:
        return False


def _register() -> None:
    """Self-register at module import. Idempotent."""
    if renderer_registry.get({renderer_class}.integration_id) is None:
        renderer_registry.register({renderer_class}())


_register()
''')


def _write_hooks_scaffold(plan: _ScaffoldPlan) -> None:
    (plan.integration_dir / "hooks.py").write_text(f'''"""Hooks for {plan.pretty_name} — lifecycle event handlers."""
from app.agent.hooks import register_hook


async def on_after_response(event):
    """Called after the agent produces a response."""
    pass


register_hook("after_response", on_after_response)
''')


def _write_process_scaffold(plan: _ScaffoldPlan) -> None:
    integration_id = plan.integration_id
    pretty_name = plan.pretty_name
    (plan.integration_dir / "process.py").write_text(f'''"""Background process for {pretty_name} integration."""

# Command to run (list of strings)
# Uncomment and point to your worker module after creating it:
# CMD = ["python", "-m", "integrations.{integration_id}.worker"]
CMD = None  # Set to a command list to enable this process

# Env vars that must be set for this process to start
REQUIRED_ENV = [
    # "{integration_id.upper()}_API_KEY",
]

DESCRIPTION = "{pretty_name} background worker"

# Optional: paths to watch for auto-reload
# WATCH_PATHS = ["integrations/{integration_id}"]
''')


def _write_workflows_scaffold(plan: _ScaffoldPlan) -> None:
    integration_id = plan.integration_id
    pretty_name = plan.pretty_name
    workflows_dir = plan.integration_dir / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / f"{integration_id}-example.yaml").write_text(f'''id: {integration_id}-example
name: "{pretty_name} Example Workflow"
description: "Example workflow for {pretty_name}"

params:
  - name: input
    description: "Input for the workflow"
    required: true

steps:
  - id: process
    name: "Process input"
    prompt: |
      Process this input: {{{{input}}}}
''')


def _write_feature_scaffolds(plan: _ScaffoldPlan) -> None:
    if "tools" in plan.feature_set:
        _write_tools_scaffold(plan)
    if "skills" in plan.feature_set:
        _write_skills_scaffold(plan)
    if "renderer" in plan.feature_set:
        _write_renderer_scaffold(plan)
    if "hooks" in plan.feature_set:
        _write_hooks_scaffold(plan)
    if "process" in plan.feature_set:
        _write_process_scaffold(plan)
    if "workflows" in plan.feature_set:
        _write_workflows_scaffold(plan)


def _scaffold_result(plan: _ScaffoldPlan) -> dict:
    capabilities = ["router", "setup"]
    capabilities.extend(plan.features)

    return {
        "ok": True,
        "integration_id": plan.integration_id,
        "path": str(plan.integration_dir),
        "capabilities": capabilities,
        "message": (
            f"Scaffolded integration '{plan.integration_id}' at {plan.integration_dir}. "
            f"Edit the files, then run manage_integration(action='reload') to hot-load it."
        ),
    }


def _scaffold_integration(integration_id: str, features: list[str] | None) -> dict:
    """Create a new integration directory with boilerplate files."""
    plan = _build_scaffold_plan(integration_id, features)
    if isinstance(plan, dict):
        return plan
    _write_base_scaffold_files(plan)
    _write_feature_scaffolds(plan)
    return _scaffold_result(plan)


_reload_lock = asyncio.Lock()


async def _reload_integrations(app=None) -> dict:
    """Reload integrations: discover new ones, load tools, re-index.

    Can be called from the tool or the API endpoint.
    If app is None, attempts to get it from the running server.
    Serialized via _reload_lock to prevent concurrent reloads.
    """
    async with _reload_lock:
        return await _reload_integrations_inner(app)


async def _reload_integrations_inner(app=None) -> dict:
    from integrations import load_new_integrations, discover_sidebar_sections, discover_activation_manifests

    if app is None:
        # Get app from the running server
        try:
            from app.main import app as _app
            app = _app
        except ImportError:
            return {"error": "Cannot access running application"}

    # 1. Discover and register new integrations
    newly_loaded = load_new_integrations(app)

    if not newly_loaded:
        return {
            "ok": True,
            "loaded": [],
            "message": "No new integrations found. Changed code in existing integrations requires a server restart.",
        }

    # Steps 2-6 are individually guarded so a failure in one doesn't block the rest.
    errors: list[str] = []

    # 2. Load tools from new integrations
    all_new_tools: list[str] = []
    try:
        from app.tools.loader import load_integration_tools
        for integration_id, integration_dir in newly_loaded:
            new_tools = load_integration_tools(integration_dir)
            all_new_tools.extend(new_tools)
    except Exception as e:
        logger.exception("Failed to load integration tools")
        errors.append(f"tool loading: {e}")

    # 3. Re-index tool embeddings
    try:
        from app.agent.tools import index_local_tools
        await index_local_tools()
    except Exception as e:
        logger.exception("Failed to re-index tools")
        errors.append(f"tool indexing: {e}")

    # 4. Sync file-sourced skills/prompts/workflows
    try:
        from app.services import file_sync
        await file_sync.sync_all_files()
    except Exception as e:
        logger.exception("Failed to sync files")
        errors.append(f"file sync: {e}")

    # 5. Reload in-memory registries
    try:
        from app.agent.skills import load_skills
        await load_skills()
    except Exception as e:
        logger.exception("Failed to reload skills")
        errors.append(f"skills: {e}")

    try:
        from app.services.workflows import load_workflows
        await load_workflows()
    except Exception as e:
        logger.exception("Failed to reload workflows")
        errors.append(f"workflows: {e}")

    # 6. Refresh caches
    try:
        discover_sidebar_sections(refresh=True)
        discover_activation_manifests()
    except Exception as e:
        logger.exception("Failed to refresh caches")
        errors.append(f"cache refresh: {e}")

    loaded_info = []
    for integration_id, integration_dir in newly_loaded:
        capabilities = []
        if (integration_dir / "router.py").exists():
            capabilities.append("router")
        if (integration_dir / "tools").is_dir():
            capabilities.append("tools")
        if (integration_dir / "skills").is_dir():
            capabilities.append("skills")
        if (integration_dir / "dispatcher.py").exists():
            capabilities.append("dispatcher")
        if (integration_dir / "hooks.py").exists():
            capabilities.append("hooks")
        loaded_info.append({
            "id": integration_id,
            "path": str(integration_dir),
            "capabilities": capabilities,
        })

    result = {
        "ok": not errors,
        "loaded": loaded_info,
        "new_tools": all_new_tools,
        "message": f"Loaded {len(newly_loaded)} new integration(s): {', '.join(i for i, _ in newly_loaded)}",
    }
    if errors:
        result["errors"] = errors
        result["message"] += f" (with {len(errors)} error(s): {'; '.join(errors)})"
    return result


@register({
    "type": "function",
    "function": {
        "name": "manage_integration",
        "description": (
            "Discover, configure, control, scaffold, and hot-reload integrations. "
            "Actions: list, get_settings, update_settings, start_process, "
            "stop_process, restart_process, scaffold, reload."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list", "get_settings", "update_settings",
                        "start_process", "stop_process", "restart_process",
                        "scaffold", "reload",
                    ],
                    "description": "The action to perform.",
                },
                "integration_id": {
                    "type": "string",
                    "description": "Integration ID (required for all actions except list and reload).",
                },
                "settings": {
                    "type": "object",
                    "description": (
                        "Key-value pairs for update_settings. "
                        "Keys are env var names (e.g. SLACK_BOT_TOKEN)."
                    ),
                },
                "features": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(_VALID_FEATURES)},
                    "description": (
                        "For scaffold: optional features to include. "
                        "Choices: dispatcher, hooks, process, skills, tools, workflows."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}, safety_tier="control_plane", returns={
    "type": "object",
    "properties": {
        "integrations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "status": {"type": "string"},
                    "has_process": {"type": "boolean"},
                    "process_status": {"type": ["string", "null"]},
                    "env_vars": {"type": "array"},
                },
            },
        },
        "ok": {"type": "boolean"},
        "loaded": {"type": "array"},
        "new_tools": {"type": "array"},
        "integration_id": {"type": "string"},
        "settings": {"type": "object"},
        "path": {"type": "string"},
        "capabilities": {"type": "array"},
        "message": {"type": "string"},
        "errors": {"type": "array"},
        "error": {"type": "string"},
    },
})
async def manage_integration(
    action: str,
    integration_id: str | None = None,
    settings: dict | None = None,
    features: list[str] | None = None,
) -> str:
    if action == "list":
        try:
            from integrations import discover_setup_status
            integrations = discover_setup_status()
            return json.dumps({"integrations": [
                {
                    "id": i["id"],
                    "name": i.get("name", i["id"]),
                    "status": i.get("status", "unknown"),
                    "has_process": i.get("has_process", False),
                    "process_status": i.get("process_status", {}).get("status") if i.get("process_status") else None,
                    "env_vars": [
                        {"key": v["key"], "required": v.get("required", False), "is_set": v.get("is_set", False)}
                        for v in i.get("env_vars", [])
                    ],
                }
                for i in integrations
            ]}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"Failed to discover integrations: {e}"}, ensure_ascii=False)

    if action == "reload":
        try:
            result = await _reload_integrations()
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.exception("Failed to reload integrations")
            return json.dumps({"error": f"Reload failed: {e}"}, ensure_ascii=False)

    if action == "scaffold":
        if not integration_id:
            return json.dumps({"error": "integration_id is required for scaffold"}, ensure_ascii=False)
        try:
            result = _scaffold_integration(integration_id, features)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            logger.exception("Failed to scaffold integration")
            return json.dumps({"error": f"Scaffold failed: {e}"}, ensure_ascii=False)

    if not integration_id:
        return json.dumps({"error": "integration_id is required for this action"}, ensure_ascii=False)

    if action == "get_settings":
        from app.services.integration_settings import get_all_for_integration
        from app.services.integration_manifests import get_manifest
        # Get env_vars from manifest cache
        setup_vars = []
        manifest = get_manifest(integration_id)
        if manifest:
            setup_vars = [
                {"key": s["key"], "required": s.get("required", False),
                 "secret": s.get("secret", False), "description": s.get("label", s["key"])}
                for s in manifest.get("settings", [])
            ]
        all_settings = get_all_for_integration(integration_id, setup_vars)
        return json.dumps({
            "integration_id": integration_id,
            "settings": all_settings,
        }, ensure_ascii=False)

    if action == "update_settings":
        if not settings:
            return json.dumps({"error": "settings dict is required for update_settings"}, ensure_ascii=False)
        from app.services.integration_settings import update_settings as _update
        from app.services.integration_manifests import get_manifest
        from app.db.engine import async_session
        # Get env_vars from manifest cache
        setup_vars = []
        manifest = get_manifest(integration_id)
        if manifest:
            setup_vars = [
                {"key": s["key"], "required": s.get("required", False),
                 "secret": s.get("secret", False), "description": s.get("label", s["key"])}
                for s in manifest.get("settings", [])
            ]
        async with async_session() as db:
            await _update(integration_id, settings, setup_vars, db)
        return json.dumps({"ok": True, "message": f"Updated {len(settings)} setting(s) for '{integration_id}'"}, ensure_ascii=False)

    if action in ("start_process", "stop_process", "restart_process"):
        from app.services.integration_processes import process_manager
        if action == "start_process":
            ok = await process_manager.start(integration_id)
            if not ok:
                return json.dumps({"error": f"Failed to start process for '{integration_id}'. Check env vars and logs."}, ensure_ascii=False)
            return json.dumps({"ok": True, "message": f"Process started for '{integration_id}'"}, ensure_ascii=False)
        elif action == "stop_process":
            await process_manager.stop(integration_id)
            return json.dumps({"ok": True, "message": f"Process stopped for '{integration_id}'"}, ensure_ascii=False)
        else:
            await process_manager.restart(integration_id)
            return json.dumps({"ok": True, "message": f"Process restarted for '{integration_id}'"}, ensure_ascii=False)

    return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)
