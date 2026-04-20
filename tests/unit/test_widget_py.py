"""Unit tests for app.services.widget_py — Phase B.2 of the Widget SDK track.

Covers:
- load_module: importing a widget.py from an arbitrary path
- Hot-reload on mtime bump
- Decorator registries: @on_action, @on_cron, @on_event
- Duplicate handler name detection
- invoke_action: sync + async handlers, per-handler timeout, context cleanup
- ctx.db round-trip (real SQLite)
- ctx.tool enforcement: manifest permissions allowlist refuses undeclared tools
"""
from __future__ import annotations

import asyncio
import textwrap
import time
import unittest.mock as mock
import uuid
from pathlib import Path

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.services.widget_py import (
    clear_module_cache,
    ctx,
    invoke_action,
    invoke_event,
    load_module,
    on_action,
    on_cron,
    on_event,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_widget_py(bundle_dir: Path, body: str) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    path = bundle_dir / "widget.py"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def _make_pin(*, bundle_source_path: str, channel_id: uuid.UUID, bot_id: str = "test-bot"):
    """Build a MagicMock that looks like a WidgetDashboardPin."""
    from app.db.models import WidgetDashboardPin

    pin = mock.MagicMock(spec=WidgetDashboardPin)
    pin.envelope = {"source_path": bundle_source_path}
    pin.source_channel_id = channel_id
    pin.source_bot_id = bot_id
    return pin


def _make_bot() -> BotConfig:
    return BotConfig(
        id="test-bot",
        name="Test",
        model="test/model",
        system_prompt="",
        memory=MemoryConfig(enabled=False),
    )


def _ws_root_patches(ws_root: Path):
    bot_patch = mock.patch("app.agent.bots.get_bot", return_value=_make_bot())
    ws_patch = mock.patch(
        "app.services.channel_workspace.get_channel_workspace_root",
        return_value=str(ws_root),
    )
    return bot_patch, ws_patch


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_module_cache()
    yield
    clear_module_cache()


# ---------------------------------------------------------------------------
# Decorator metadata
# ---------------------------------------------------------------------------


class TestDecorators:
    def test_on_action_with_name(self):
        @on_action("save")
        def fn(args):
            return args

        assert fn._spindrel_action_name == "save"
        assert fn._spindrel_action_timeout == 30

    def test_on_action_without_parens_uses_func_name(self):
        @on_action
        def tick(args):
            return None

        assert tick._spindrel_action_name == "tick"

    def test_on_action_custom_timeout(self):
        @on_action("slow", timeout=120)
        def fn(args):
            pass

        assert fn._spindrel_action_timeout == 120

    def test_on_cron_attaches_name(self):
        @on_cron("rollup")
        def fn():
            pass

        assert fn._spindrel_cron_name == "rollup"

    def test_on_event_attaches_kind(self):
        @on_event("new_message")
        def fn(evt):
            pass

        assert fn._spindrel_event_kind == "new_message"

    def test_on_event_custom_timeout(self):
        @on_event("turn_ended", timeout=90)
        def fn(evt):
            pass

        assert fn._spindrel_event_timeout == 90

    def test_on_event_default_timeout(self):
        @on_event("new_message")
        def fn(evt):
            pass

        assert fn._spindrel_event_timeout == 30

    def test_harvests_events_keyed_by_kind_and_handler(self, tmp_path):
        path = _write_widget_py(tmp_path, """
            from spindrel.widget import on_event

            @on_event("new_message")
            def on_msg(evt): return None

            @on_event("new_message")
            def on_msg_also(evt): return None

            @on_event("turn_ended")
            def on_turn(evt): return None
        """)
        module = load_module(path)
        assert set(module._spindrel_events.keys()) == {"new_message", "turn_ended"}
        assert set(module._spindrel_events["new_message"].keys()) == {
            "on_msg", "on_msg_also",
        }
        assert set(module._spindrel_events["turn_ended"].keys()) == {"on_turn"}


# ---------------------------------------------------------------------------
# load_module
# ---------------------------------------------------------------------------


class TestLoadModule:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_module(tmp_path / "nope.py")

    def test_harvests_action_registry(self, tmp_path):
        path = _write_widget_py(tmp_path, """
            from spindrel.widget import on_action

            @on_action("save")
            def save(args):
                return {"saved": True}

            @on_action("remove")
            def remove(args):
                return {"removed": True}
        """)
        module = load_module(path)
        assert set(module._spindrel_actions.keys()) == {"save", "remove"}

    def test_duplicate_action_name_raises(self, tmp_path):
        path = _write_widget_py(tmp_path, """
            from spindrel.widget import on_action

            @on_action("save")
            def a(args): return 1

            @on_action("save")
            def b(args): return 2
        """)
        with pytest.raises(ValueError, match="duplicate @on_action"):
            load_module(path)

    def test_hot_reload_on_mtime_bump(self, tmp_path):
        path = _write_widget_py(tmp_path, """
            from spindrel.widget import on_action

            @on_action("v")
            def v(args): return "first"
        """)
        first = load_module(path)
        assert first._spindrel_actions["v"]({}) == "first"

        # Bump mtime forward and rewrite.
        time.sleep(0.01)
        _write_widget_py(tmp_path, """
            from spindrel.widget import on_action

            @on_action("v")
            def v(args): return "second"
        """)
        # Ensure mtime actually changed (some filesystems have 1s resolution).
        import os
        new_mtime = path.stat().st_mtime + 10
        os.utime(path, (new_mtime, new_mtime))

        second = load_module(path)
        assert second._spindrel_actions["v"]({}) == "second"
        assert second is not first

    def test_cache_hit_when_mtime_unchanged(self, tmp_path):
        path = _write_widget_py(tmp_path, """
            from spindrel.widget import on_action

            @on_action("same")
            def same(args): return 1
        """)
        a = load_module(path)
        b = load_module(path)
        assert a is b


# ---------------------------------------------------------------------------
# invoke_action — dispatch layer
# ---------------------------------------------------------------------------


class TestInvokeAction:
    def test_inline_widget_raises(self):
        from app.db.models import WidgetDashboardPin
        pin = mock.MagicMock(spec=WidgetDashboardPin)
        pin.envelope = {}  # no source_path
        pin.source_channel_id = uuid.uuid4()
        pin.source_bot_id = "test-bot"
        with pytest.raises(ValueError, match="inline widgets"):
            asyncio.run(invoke_action(pin, "anything"))

    def test_missing_widget_py_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "empty"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")

        pin = _make_pin(
            bundle_source_path="data/widgets/empty/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            with pytest.raises(FileNotFoundError, match="widget.py not found"):
                asyncio.run(invoke_action(pin, "anything"))

    def test_unknown_handler_raises_keyerror(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "notes"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_action

            @on_action("save")
            def save(args): return True
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/notes/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            with pytest.raises(KeyError, match="missing"):
                # message contains handler_name
                asyncio.run(invoke_action(pin, "missing"))

    def test_sync_handler_returns_value(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "notes"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_action

            @on_action("echo")
            def echo(args):
                return {"got": args}
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/notes/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            result = asyncio.run(invoke_action(pin, "echo", {"hello": "world"}))
        assert result == {"got": {"hello": "world"}}

    def test_async_handler_returns_value(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "notes"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_action

            @on_action("aecho")
            async def aecho(args):
                return {"async_got": args}
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/notes/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            result = asyncio.run(invoke_action(pin, "aecho", {"x": 1}))
        assert result == {"async_got": {"x": 1}}

    def test_async_handler_timeout(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "slow"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            import asyncio
            from spindrel.widget import on_action

            @on_action("hang", timeout=1)
            async def hang(args):
                await asyncio.sleep(5)
                return "unreachable"
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/slow/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            with pytest.raises(asyncio.TimeoutError):
                asyncio.run(invoke_action(pin, "hang"))

    def test_context_cleanup_after_handler(self, tmp_path):
        """ContextVars must reset even when the handler raises."""
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "boom"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_action

            @on_action("boom")
            def boom(args):
                raise RuntimeError("kaboom")
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/boom/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            with pytest.raises(RuntimeError, match="kaboom"):
                asyncio.run(invoke_action(pin, "boom"))

        # After the run, ctx.pin is back to None (outside any invocation).
        assert ctx.pin is None
        assert ctx.bot_id is None


# ---------------------------------------------------------------------------
# ctx.db round-trip
# ---------------------------------------------------------------------------


class TestCtxDb:
    def test_db_execute_and_query_through_handler(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "items"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_action, ctx

            @on_action("insert_and_count")
            async def insert(args):
                await ctx.db.execute(
                    "create table if not exists items (id integer primary key, text text)"
                )
                await ctx.db.execute(
                    "insert into items(text) values (?)", [args["t"]]
                )
                rows = await ctx.db.query("select count(*) as n from items")
                return {"count": rows[0]["n"]}
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/items/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            r1 = asyncio.run(invoke_action(pin, "insert_and_count", {"t": "one"}))
            r2 = asyncio.run(invoke_action(pin, "insert_and_count", {"t": "two"}))
        assert r1 == {"count": 1}
        assert r2 == {"count": 2}

    def test_ctx_db_outside_handler_raises(self):
        """Accessing ctx.db outside invoke_action fails loud."""
        async def _call():
            await ctx.db.query("select 1")
        with pytest.raises(RuntimeError, match="outside of a widget handler"):
            asyncio.run(_call())


# ---------------------------------------------------------------------------
# ctx.tool permission gating
# ---------------------------------------------------------------------------


class TestCtxTool:
    def test_manifest_allowlist_refuses_undeclared_tool(self, tmp_path):
        """If permissions.tools is declared, ctx.tool rejects anything not in it."""
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "scoped"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        (bundle_dir / "widget.yaml").write_text(textwrap.dedent("""
            name: Scoped
            version: 1.0.0
            permissions:
              tools: [fetch_url]
        """).strip())
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_action, ctx

            @on_action("call_forbidden")
            async def call_forbidden(args):
                return await ctx.tool("send_push_notification", title="x", body="y")
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/scoped/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            with pytest.raises(PermissionError, match="does not declare tool"):
                asyncio.run(invoke_action(pin, "call_forbidden"))

    def test_no_manifest_tools_allows_any(self, tmp_path):
        """When permissions.tools is empty/missing, ctx.tool falls through to policy.

        Policy check is what decides — and with TOOL_POLICY_ENABLED off the
        check returns None (allow).  We mock call_local_tool to verify the
        tool dispatch path is actually reached.
        """
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "open"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_action, ctx

            @on_action("ping")
            async def ping(args):
                return await ctx.tool("echo_tool", msg="hi")
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/open/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        # Policy returns None (allow); is_local_tool returns True; call_local_tool returns JSON.
        with bot_patch, ws_patch, \
             mock.patch("app.agent.tool_dispatch._check_tool_policy",
                        new=mock.AsyncMock(return_value=None)), \
             mock.patch("app.tools.registry.is_local_tool", return_value=True), \
             mock.patch("app.tools.registry.call_local_tool",
                        new=mock.AsyncMock(return_value='{"echoed": "hi"}')):
            result = asyncio.run(invoke_action(pin, "ping"))
        assert result == {"echoed": "hi"}


class TestInvokeEvent:
    def test_dispatches_payload_to_handler(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "evt"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_event

            CALLS = []

            @on_event("new_message")
            def on_msg(payload):
                CALLS.append(payload)
                return {"seen": True}
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/evt/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            result = asyncio.run(
                invoke_event(pin, "new_message", "on_msg", {"a": 1}),
            )
        assert result == {"seen": True}

    def test_unknown_handler_raises_keyerror(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "evt"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_event

            @on_event("new_message")
            def on_msg(payload): return None
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/evt/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            with pytest.raises(KeyError):
                asyncio.run(
                    invoke_event(pin, "new_message", "does_not_exist", {}),
                )

    def test_unknown_kind_raises_keyerror(self, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "evt"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "index.html").write_text("")
        _write_widget_py(bundle_dir, """
            from spindrel.widget import on_event

            @on_event("new_message")
            def on_msg(payload): return None
        """)

        pin = _make_pin(
            bundle_source_path="data/widgets/evt/index.html",
            channel_id=uuid.uuid4(),
        )
        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            with pytest.raises(KeyError):
                asyncio.run(
                    invoke_event(pin, "turn_ended", "on_msg", {}),
                )
