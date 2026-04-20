"""Widget Python handlers — Phase B.2 of the Widget SDK track.

Widgets can declare Python handlers in ``<bundle>/widget.py`` and dispatch
them from iframe JS via ``spindrel.callHandler(name, args)``. Handlers run
in-process under the pin's bot scope — same policy + approval pipeline as
LLM-driven tool dispatch.

Public surface
--------------
on_action(name=None, *, timeout=30)           — decorator, register a JS-callable handler
on_cron(name, *, timeout=300)                  — decorator, wire via scheduler (B.3)
on_event(kind, *, timeout=30)                  — decorator, wire via channel event bus (B.4)
ctx                                            — per-invocation context object (db, tool, pin, ...)
load_module(widget_py_path)                    — import (and hot-reload) a widget.py
invoke_action(pin, handler_name, args)         — resolve + call an @on_action handler
invoke_cron(pin, cron_name)                    — resolve + call an @on_cron handler (no args)
invoke_event(pin, event_kind, handler, payload) — resolve + call an @on_event handler
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import logging
import uuid
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models import WidgetDashboardPin
    from app.services.widget_manifest import WidgetManifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ContextVars — carry per-invocation state so ``ctx`` methods resolve correctly
# ---------------------------------------------------------------------------

_current_pin: ContextVar[Any] = ContextVar("_widget_current_pin", default=None)
_current_manifest: ContextVar[Any] = ContextVar("_widget_current_manifest", default=None)


# ---------------------------------------------------------------------------
# Decorators — attach metadata to handler functions at module-import time
# ---------------------------------------------------------------------------


def on_action(name: str | Callable | None = None, *, timeout: int = 30):
    """Register a JS-callable handler.

    Usage::

        @on_action("save_item")
        async def save(args): ...

        @on_action  # name defaults to function name
        def tick(args): ...
    """

    def _attach(func: Callable, action_name: str, t: int) -> Callable:
        func._spindrel_action_name = action_name  # type: ignore[attr-defined]
        func._spindrel_action_timeout = t  # type: ignore[attr-defined]
        return func

    # ``@on_action`` without parens: ``name`` is the function.
    if callable(name) and not isinstance(name, str):
        fn = name
        return _attach(fn, fn.__name__, timeout)

    def decorator(func: Callable) -> Callable:
        return _attach(func, name or func.__name__, timeout)

    return decorator


def on_cron(name: str, *, timeout: int = 300):
    """Mark a handler as cron-triggered.

    ``timeout`` is generous by default (5 min) — cron work tends to do real
    I/O (``ctx.tool`` fetches, DB writes) that can take longer than an
    interactive ``@on_action``. Widget authors can lower or raise it per
    handler.
    """

    def decorator(func: Callable) -> Callable:
        func._spindrel_cron_name = name  # type: ignore[attr-defined]
        func._spindrel_cron_timeout = timeout  # type: ignore[attr-defined]
        return func

    return decorator


def on_event(kind: str, *, timeout: int = 30):
    """Mark a handler as event-triggered.

    When a pin's channel publishes a matching ``ChannelEvent``, the
    subscriber task in ``app/services/widget_events.py`` invokes the
    decorated handler with a single ``payload`` argument (JSON-serialised
    dict derived from the event's typed payload). Handlers run under the
    pin's ``source_bot_id``.

    ``timeout`` (seconds, default 30) bounds the per-event handler run.
    One buggy handler cannot stall the subscriber loop — the loop catches
    exceptions (including ``asyncio.TimeoutError``) and keeps listening.
    """

    def decorator(func: Callable) -> Callable:
        func._spindrel_event_kind = kind  # type: ignore[attr-defined]
        func._spindrel_event_timeout = timeout  # type: ignore[attr-defined]
        return func

    return decorator


# ---------------------------------------------------------------------------
# ctx — per-invocation surface. Implemented via ContextVar reads; a single
# module-level ``ctx`` is shared across handlers but resolves correctly per
# invocation.
# ---------------------------------------------------------------------------


class _WidgetDb:
    """``ctx.db`` — thin async wrapper over ``widget_db.acquire_db``."""

    async def query(self, sql: str, params: list | tuple | None = None) -> list[dict]:
        pin = _require_pin("ctx.db.query")
        manifest = _current_manifest.get()
        return await _run_query(pin, manifest, sql, params or [])

    async def execute(self, sql: str, params: list | tuple | None = None) -> dict:
        pin = _require_pin("ctx.db.execute")
        manifest = _current_manifest.get()
        return await _run_execute(pin, manifest, sql, params or [])


class _WidgetCtx:
    """Per-invocation surface exposed to handlers as ``spindrel.widget.ctx``."""

    db = _WidgetDb()

    @property
    def pin(self) -> Any:
        return _current_pin.get()

    @property
    def bot_id(self) -> str | None:
        pin = _current_pin.get()
        return getattr(pin, "source_bot_id", None) if pin else None

    @property
    def channel_id(self) -> uuid.UUID | None:
        pin = _current_pin.get()
        return getattr(pin, "source_channel_id", None) if pin else None

    async def tool(self, name: str, **kwargs) -> Any:
        """Invoke a tool through the normal policy pipeline under the pin's bot.

        Enforces the widget's manifest ``permissions.tools`` allowlist (if a
        manifest declared any), then defers to ``_check_tool_policy`` — the
        same gate LLM-driven dispatch uses. Raises ``PermissionError`` on
        deny / approval-required; the handler's exception propagates to the
        dispatch endpoint which serialises it as ``{ok: false, error: ...}``.
        """
        pin = _require_pin("ctx.tool")
        manifest = _current_manifest.get()
        bot_id = getattr(pin, "source_bot_id", None)
        if not bot_id:
            raise RuntimeError("pin has no source_bot_id; cannot dispatch tool")

        if manifest is not None and manifest.permissions.tools:
            if name not in manifest.permissions.tools:
                raise PermissionError(
                    f"widget.yaml does not declare tool {name!r} in permissions.tools"
                )

        from app.agent.context import current_bot_id, current_channel_id
        from app.agent.tool_dispatch import _check_tool_policy
        from app.tools.mcp import call_mcp_tool, is_mcp_tool, resolve_mcp_tool_name
        from app.tools.registry import call_local_tool, is_local_tool

        correlation_id = str(uuid.uuid4())
        decision = await _check_tool_policy(
            bot_id, name, kwargs, correlation_id=correlation_id,
        )
        if decision is not None:
            if decision.action == "deny":
                raise PermissionError(
                    f"scope_denied: {decision.reason or 'denied by policy'}"
                )
            if decision.action == "require_approval":
                raise PermissionError(
                    f"approval_required: {decision.reason or 'handler cannot wait for approval'}"
                )

        resolved = name
        if not is_local_tool(resolved):
            mcp_name = resolve_mcp_tool_name(resolved)
            if mcp_name:
                resolved = mcp_name

        bot_token = current_bot_id.set(bot_id)
        ch_token = (
            current_channel_id.set(pin.source_channel_id)
            if pin.source_channel_id else None
        )
        try:
            if is_local_tool(resolved):
                raw = await call_local_tool(resolved, json.dumps(kwargs))
            elif is_mcp_tool(resolved):
                raw = await call_mcp_tool(resolved, json.dumps(kwargs))
            else:
                raise RuntimeError(f"Unknown tool: {name}")
        finally:
            current_bot_id.reset(bot_token)
            if ch_token is not None:
                current_channel_id.reset(ch_token)

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def notify_reload(self) -> None:
        """Tell the pin's iframe to re-run its reload handler.

        Publishes a ``ChannelEventKind.WIDGET_RELOAD`` event on the pin's
        channel carrying ``pin_id``. The iframe preamble auto-subscribes
        to this kind, filters by ``pin_id === self.dashboardPinId``, and
        invokes whatever callback the widget registered via
        ``spindrel.onReload(cb)`` / ``spindrel.autoReload(renderFn)``.

        Peer pins of the same bundle on the same channel do *not* reload
        automatically — the filter is strict-equality on ``pin_id``. If
        you need cross-pin sync, publish on ``spindrel.bus`` from a peer's
        ``onReload`` callback.

        Fire-and-forget: returns after the event is queued on the bus. If
        the widget's channel_id is missing (shouldn't happen for a real
        pin), raises ``RuntimeError`` — callers should let it propagate.
        """
        pin = _require_pin("ctx.notify_reload")
        channel_id = getattr(pin, "source_channel_id", None)
        if not channel_id:
            raise RuntimeError(
                "ctx.notify_reload: pin has no source_channel_id; nothing to notify"
            )
        pin_id = getattr(pin, "id", None)
        if pin_id is None:
            raise RuntimeError("ctx.notify_reload: pin has no id")

        from app.domain.channel_events import ChannelEvent, ChannelEventKind
        from app.domain.payloads import WidgetReloadPayload
        from app.services.channel_events import publish_typed

        event = ChannelEvent(
            channel_id=channel_id,
            kind=ChannelEventKind.WIDGET_RELOAD,
            payload=WidgetReloadPayload(pin_id=pin_id),
        )
        publish_typed(channel_id, event)


ctx = _WidgetCtx()


def _require_pin(caller: str):
    pin = _current_pin.get()
    if pin is None:
        raise RuntimeError(f"{caller} called outside of a widget handler invocation")
    return pin


async def _run_query(pin, manifest, sql: str, params) -> list[dict]:
    from app.services.widget_db import acquire_db, resolve_db_path

    db_config = manifest.db if manifest is not None else None
    path = resolve_db_path(pin, manifest)
    async with acquire_db(path, db_config) as conn:
        def _q():
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
        return await asyncio.to_thread(_q)


async def _run_execute(pin, manifest, sql: str, params) -> dict:
    from app.services.widget_db import acquire_db, resolve_db_path

    db_config = manifest.db if manifest is not None else None
    path = resolve_db_path(pin, manifest)
    async with acquire_db(path, db_config) as conn:
        def _e():
            cur = conn.execute(sql, params)
            conn.commit()
            return {
                "lastInsertRowid": cur.lastrowid,
                "rowsAffected": cur.rowcount,
            }
        return await asyncio.to_thread(_e)


# ---------------------------------------------------------------------------
# Module loader — imports widget.py, harvests decorated handlers, hot-reloads
# on file mtime change.
# ---------------------------------------------------------------------------


# Cache: widget.py absolute path → (mtime, module)
_MODULE_CACHE: dict[str, tuple[float, ModuleType]] = {}


def _module_name_for(path: Path) -> str:
    digest = hashlib.md5(str(path).encode("utf-8")).hexdigest()[:12]
    return f"spindrel_widget_{digest}"


def _harvest(module: ModuleType) -> None:
    """Scan the module for decorated handlers and populate registries.

    ``_spindrel_events`` is keyed as ``{event_kind: {handler_name: fn}}``
    so B.4's ``invoke_event(pin, event_kind, handler_name, payload)`` can
    resolve the exact function row the DB subscription row referenced.
    Multiple handlers for the same ``kind`` are supported as long as each
    has a distinct function name (Python's module namespace already
    enforces this).
    """
    actions: dict[str, Callable] = {}
    crons: dict[str, Callable] = {}
    events: dict[str, dict[str, Callable]] = {}

    for attr in dir(module):
        fn = getattr(module, attr, None)
        if not callable(fn):
            continue
        action_name = getattr(fn, "_spindrel_action_name", None)
        if action_name is not None:
            if action_name in actions:
                raise ValueError(
                    f"duplicate @on_action({action_name!r}) in {module.__name__}"
                )
            actions[action_name] = fn
        cron_name = getattr(fn, "_spindrel_cron_name", None)
        if cron_name is not None:
            if cron_name in crons:
                raise ValueError(
                    f"duplicate @on_cron({cron_name!r}) in {module.__name__}"
                )
            crons[cron_name] = fn
        event_kind = getattr(fn, "_spindrel_event_kind", None)
        if event_kind is not None:
            handler_name = getattr(fn, "__name__", attr)
            bucket = events.setdefault(event_kind, {})
            bucket[handler_name] = fn

    module._spindrel_actions = actions  # type: ignore[attr-defined]
    module._spindrel_crons = crons  # type: ignore[attr-defined]
    module._spindrel_events = events  # type: ignore[attr-defined]


def load_module(widget_py_path: str | Path) -> ModuleType:
    """Import a widget.py (or return cached copy). Hot-reloads on mtime bump.

    Raises ``FileNotFoundError`` if the path doesn't exist, ``ValueError`` on
    duplicate handler names, or any exception the module raises at import.
    """
    path = Path(widget_py_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"widget.py not found: {path}")

    mtime = path.stat().st_mtime
    cached = _MODULE_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]

    spec = importlib.util.spec_from_file_location(_module_name_for(path), str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"could not create spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _harvest(module)
    _MODULE_CACHE[str(path)] = (mtime, module)
    return module


def clear_module_cache() -> None:
    """Test hook — drop all cached widget modules so a fresh import runs."""
    _MODULE_CACHE.clear()


# ---------------------------------------------------------------------------
# Invoke
# ---------------------------------------------------------------------------


def _resolve_bundle_dir(pin) -> Path:
    """Return the pin's on-disk bundle directory (pre-redirect).

    Mirrors ``widget_db.resolve_db_path`` minus the built-in DB redirect —
    widget.py always lives in the source bundle, even for built-in widgets.
    """
    envelope = pin.envelope or {}
    source_path: str | None = envelope.get("source_path")
    if not source_path:
        raise ValueError(
            "inline widgets cannot have widget.py handlers — only path-mode "
            "bundles (emit_html_widget path=...) support @on_action"
        )
    channel_id = (
        str(pin.source_channel_id) if pin.source_channel_id else envelope.get("source_channel_id")
    )
    bot_id = pin.source_bot_id or envelope.get("source_bot_id")
    if not channel_id:
        raise ValueError("pin missing source_channel_id — cannot resolve bundle dir")
    if not bot_id:
        raise ValueError("pin missing source_bot_id — cannot resolve bundle dir")

    from app.agent.bots import get_bot
    from app.services.channel_workspace import get_channel_workspace_root

    bot = get_bot(bot_id)
    if bot is None:
        raise ValueError(f"bot {bot_id!r} not found — cannot resolve bundle dir")

    ws_root = Path(get_channel_workspace_root(channel_id, bot)).resolve()
    bundle_dir = (ws_root / source_path).resolve().parent

    try:
        bundle_dir.relative_to(ws_root)
    except ValueError:
        raise ValueError(
            f"source_path {source_path!r} resolves outside the channel workspace "
            f"(workspace_root={ws_root})"
        )
    return bundle_dir


def _load_pin_module(pin) -> tuple[Path, ModuleType, Any]:
    """Resolve ``<bundle>/widget.py`` + parse manifest for a pin.

    Returns ``(py_path, module, manifest_or_None)``. Raises
    ``FileNotFoundError`` if no widget.py, ``ValueError`` on manifest parse
    errors, and propagates import errors from ``load_module``.
    """
    from app.services.widget_manifest import ManifestError, parse_manifest

    bundle_dir = _resolve_bundle_dir(pin)
    py_path = bundle_dir / "widget.py"
    if not py_path.is_file():
        raise FileNotFoundError(f"widget.py not found in bundle {bundle_dir}")

    manifest = None
    yaml_path = bundle_dir / "widget.yaml"
    if yaml_path.is_file():
        try:
            manifest = parse_manifest(yaml_path)
        except ManifestError as exc:
            raise ValueError(f"widget.yaml invalid: {exc}") from exc

    module = load_module(py_path)
    return py_path, module, manifest


async def _run_handler(pin, manifest, handler, call_args: tuple, timeout: int) -> Any:
    """Set ContextVars, call handler, await coroutines with timeout, cleanup."""
    pin_tok = _current_pin.set(pin)
    man_tok = _current_manifest.set(manifest)
    try:
        result = handler(*call_args)
        if inspect.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=timeout)
        return result
    finally:
        _current_pin.reset(pin_tok)
        _current_manifest.reset(man_tok)


async def invoke_action(pin, handler_name: str, args: dict | None = None) -> Any:
    """Resolve and run the ``@on_action(handler_name)`` handler on a pin's widget.py.

    ContextVars set for the call: ``_current_pin`` and ``_current_manifest``
    (from the bundle's widget.yaml if present). Sync handlers run inline;
    async handlers are awaited with the per-action timeout.

    Raises ``FileNotFoundError`` / ``KeyError`` / ``ValueError`` / ``PermissionError``
    / ``asyncio.TimeoutError`` for the dispatch router to serialise.
    """
    py_path, module, manifest = _load_pin_module(pin)

    handler = module._spindrel_actions.get(handler_name)  # type: ignore[attr-defined]
    if handler is None:
        raise KeyError(f"no @on_action({handler_name!r}) in {py_path}")

    timeout = getattr(handler, "_spindrel_action_timeout", 30)
    return await _run_handler(pin, manifest, handler, ((args or {}),), timeout)


async def invoke_cron(pin, cron_name: str) -> Any:
    """Resolve and run the ``@on_cron(cron_name)`` handler on a pin's widget.py.

    Called by the task scheduler when ``WidgetCronSubscription.next_fire_at``
    falls due. Runs under the pin's ``source_bot_id`` (same identity flow as
    ``invoke_action``); cron handlers take no args.

    Raises ``FileNotFoundError`` / ``KeyError`` / ``ValueError`` /
    ``PermissionError`` / ``asyncio.TimeoutError`` — the scheduler catches
    and logs; the next scheduled fire still runs.
    """
    py_path, module, manifest = _load_pin_module(pin)

    handler = module._spindrel_crons.get(cron_name)  # type: ignore[attr-defined]
    if handler is None:
        raise KeyError(f"no @on_cron({cron_name!r}) in {py_path}")

    timeout = getattr(handler, "_spindrel_cron_timeout", 300)
    return await _run_handler(pin, manifest, handler, (), timeout)


async def invoke_event(
    pin, event_kind: str, handler_name: str, payload: dict,
) -> Any:
    """Resolve and run an ``@on_event(event_kind)`` handler on a pin's widget.py.

    Called by the event subscriber loop in ``app/services/widget_events.py``
    when a matching ``ChannelEvent`` is received. Runs under the pin's
    ``source_bot_id`` (same identity flow as ``invoke_action`` / ``invoke_cron``).
    The handler receives ``payload`` as its single argument.

    Raises ``FileNotFoundError`` / ``KeyError`` / ``ValueError`` /
    ``PermissionError`` / ``asyncio.TimeoutError`` — the subscriber loop
    catches and logs; future events on the subscription continue to fire.
    """
    py_path, module, manifest = _load_pin_module(pin)

    kind_bucket = module._spindrel_events.get(event_kind, {})  # type: ignore[attr-defined]
    handler = kind_bucket.get(handler_name)
    if handler is None:
        raise KeyError(
            f"no @on_event({event_kind!r}) handler named {handler_name!r} in {py_path}"
        )

    timeout = getattr(handler, "_spindrel_event_timeout", 30)
    return await _run_handler(pin, manifest, handler, (payload,), timeout)
