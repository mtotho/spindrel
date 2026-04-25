"""Tests for the ``emit_html_widget`` local tool.

Covers:
- Inline-mode happy path (html only, html + js, html + css + js).
- Path-mode happy path (returns envelope with source_path + source_channel_id).
- Validation: neither / both of html/path → error envelope.
- ``_build_envelope_from_optin`` carries source_path + source_channel_id
  through to the ``ToolResultEnvelope`` and its ``compact_dict()``.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from app.agent.context import current_bot_id, current_channel_id
from app.agent.tool_dispatch import (
    ToolResultEnvelope,
    _build_envelope_from_optin,
)
from app.tools.local.emit_html_widget import (
    INTERACTIVE_HTML_CONTENT_TYPE,
    emit_html_widget,
)


def _parse(result: str) -> dict:
    return json.loads(result)


def _envelope(result: str) -> dict:
    return _parse(result)["_envelope"]


class TestInlineMode:
    @pytest.mark.asyncio
    async def test_html_only(self):
        # No channel context set — channel_id stays out of the envelope.
        result = await emit_html_widget(html="<p>hello</p>")
        env = _envelope(result)
        assert env["content_type"] == INTERACTIVE_HTML_CONTENT_TYPE
        assert env["body"] == "<p>hello</p>"
        assert env["display"] == "inline"
        # No display_label → not emitted
        assert "display_label" not in env
        # No source_path in inline mode
        assert "source_path" not in env
        # No channel context in this test → source_channel_id omitted
        assert "source_channel_id" not in env
        assert env["plain_body"].startswith("HTML widget (")

    @pytest.mark.asyncio
    async def test_inline_mode_bakes_channel_id_for_dashboard_pins(self):
        # When emitted inside a channel, the channel id MUST be persisted so
        # that a pinned widget on the dashboard (no channel context) still
        # knows its origin channel for window.spindrel.channelId.
        channel_id = uuid.uuid4()
        ctx = current_channel_id.set(channel_id)
        try:
            result = await emit_html_widget(html="<p>hi</p>", display_label="x")
            env = _envelope(result)
            assert env["source_channel_id"] == str(channel_id)
            # source_path is NOT set in inline mode — only the channel origin.
            assert "source_path" not in env
        finally:
            current_channel_id.reset(ctx)

    @pytest.mark.asyncio
    async def test_inline_mode_bakes_source_bot_id(self):
        # source_bot_id drives the widget-auth mint so the iframe runs with
        # the emitting bot's scopes — missing it = widget can't auth.
        ctx = current_bot_id.set("crumb")
        try:
            result = await emit_html_widget(html="<p>x</p>")
            env = _envelope(result)
            assert env["source_bot_id"] == "crumb"
        finally:
            current_bot_id.reset(ctx)

    @pytest.mark.asyncio
    async def test_inline_mode_omits_source_bot_id_without_context(self):
        # Absent bot context → field omitted (not stamped as "None").
        result = await emit_html_widget(html="<p>x</p>")
        env = _envelope(result)
        assert "source_bot_id" not in env

    @pytest.mark.asyncio
    async def test_html_with_js_and_css(self):
        result = await emit_html_widget(
            html="<div id=x></div>",
            js="document.getElementById('x').textContent='hi';",
            css="#x { color: red; }",
            display_label="Demo widget",
        )
        env = _envelope(result)
        body = env["body"]
        assert "<style>" in body and "color: red" in body
        assert "<script>" in body and "document.getElementById" in body
        assert "<div id=x></div>" in body
        # Order: css, html, js
        assert body.index("<style>") < body.index("<div id=x>")
        assert body.index("<div id=x>") < body.index("<script>")
        assert env["display_label"] == "Demo widget"
        assert env["plain_body"] == "HTML widget: Demo widget"

    @pytest.mark.asyncio
    async def test_html_ignores_empty_js_and_css(self):
        result = await emit_html_widget(html="<p>plain</p>", js="", css="")
        body = _envelope(result)["body"]
        assert "<script>" not in body
        assert "<style>" not in body
        assert body == "<p>plain</p>"


class TestValidation:
    @pytest.mark.asyncio
    async def test_neither_html_nor_path_errors(self):
        result = await emit_html_widget()
        assert _parse(result).get("error")
        assert "exactly one" in _parse(result)["error"]

    @pytest.mark.asyncio
    async def test_both_html_and_path_errors(self):
        result = await emit_html_widget(html="<p>x</p>", path="foo.html")
        assert _parse(result).get("error")
        assert "exactly one" in _parse(result)["error"]

    @pytest.mark.asyncio
    async def test_whitespace_html_counts_as_unset(self):
        # Empty-whitespace html + real path should route as path mode, not
        # trigger the both-set error.
        channel_id = uuid.uuid4()
        ctx_channel = current_channel_id.set(channel_id)
        ctx_bot = current_bot_id.set("bot-xyz")
        try:
            with patch("app.agent.bots.get_bot", return_value=object()), \
                 patch(
                     "app.services.channel_workspace.read_workspace_file",
                     return_value="<html><body>ok</body></html>",
                 ):
                result = await emit_html_widget(html="   ", path="dash.html")
            env = _envelope(result)
            assert env["source_path"] == "dash.html"
        finally:
            current_channel_id.reset(ctx_channel)
            current_bot_id.reset(ctx_bot)


class TestPathMode:
    @pytest.mark.asyncio
    async def test_path_happy_path(self):
        channel_id = uuid.uuid4()
        ctx_channel = current_channel_id.set(channel_id)
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            with patch("app.agent.bots.get_bot", return_value=object()), \
                 patch(
                     "app.services.channel_workspace.read_workspace_file",
                     return_value="<html>contents</html>",
                 ):
                result = await emit_html_widget(
                    path="dashboards/cpu.html",
                    display_label="CPU",
                )
            env = _envelope(result)
            assert env["content_type"] == INTERACTIVE_HTML_CONTENT_TYPE
            assert env["body"] == ""
            assert env["source_path"] == "dashboards/cpu.html"
            assert env["source_channel_id"] == str(channel_id)
            assert env["source_bot_id"] == "bot-abc"
            # Freshness is owned by the renderer's useQuery poll, not the
            # WidgetCard state_poll machinery — envelope deliberately omits
            # `refreshable`. See emit_html_widget path-mode comment.
            assert "refreshable" not in env
            assert env["display_label"] == "CPU"
            assert env["plain_body"] == "HTML widget: CPU"
        finally:
            current_channel_id.reset(ctx_channel)
            current_bot_id.reset(ctx_bot)

    @pytest.mark.asyncio
    async def test_path_no_channel_context_errors(self):
        # No channel context — tool should refuse.
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            result = await emit_html_widget(path="dashboards/foo.html")
            assert _parse(result).get("error")
        finally:
            current_bot_id.reset(ctx_bot)

    @pytest.mark.asyncio
    async def test_path_file_not_found_errors(self):
        channel_id = uuid.uuid4()
        ctx_channel = current_channel_id.set(channel_id)
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            with patch("app.agent.bots.get_bot", return_value=object()), \
                 patch(
                     "app.services.channel_workspace.read_workspace_file",
                     return_value=None,
                 ):
                result = await emit_html_widget(path="does/not/exist.html")
            err = _parse(result).get("error", "")
            assert "not found" in err or "escapes" in err
        finally:
            current_channel_id.reset(ctx_channel)
            current_bot_id.reset(ctx_bot)


class TestAbsoluteChannelPath:
    """Absolute /workspace/channels/<uuid>/... overrides the current-channel
    scope so bots can emit widgets from outside a channel context (cron, tasks,
    autoresearch) or target a different channel than the emitting one."""

    @pytest.mark.asyncio
    async def test_absolute_path_works_without_channel_context(self):
        # No current_channel_id — absolute path carries its own target.
        ctx_bot = current_bot_id.set("bot-abc")
        target = "00000000-0000-0000-0000-000000000042"
        try:
            with patch("app.agent.bots.get_bot", return_value=object()), \
                 patch(
                     "app.services.channel_workspace.read_workspace_file",
                     return_value="<html>ok</html>",
                 ) as read_mock:
                result = await emit_html_widget(
                    path=f"/workspace/channels/{target}/data/widgets/foo/index.html",
                    display_label="Foo",
                )
            env = _envelope(result)
            assert env["source_channel_id"] == target
            # Resolved path has the /workspace/channels/<id>/ prefix stripped.
            assert env["source_path"] == "data/widgets/foo/index.html"
            # read_workspace_file was called with parsed channel + stripped path.
            read_mock.assert_called_once()
            args = read_mock.call_args[0]
            assert args[0] == target
            assert args[2] == "data/widgets/foo/index.html"
        finally:
            current_bot_id.reset(ctx_bot)

    @pytest.mark.asyncio
    async def test_absolute_path_overrides_emitting_channel(self):
        # Bot IS in a channel, but uses an absolute path targeting a different
        # channel — envelope should carry the parsed channel, not the emitting.
        emitting = uuid.uuid4()
        target = "11111111-1111-1111-1111-111111111111"
        ctx_channel = current_channel_id.set(emitting)
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            with patch("app.agent.bots.get_bot", return_value=object()), \
                 patch(
                     "app.services.channel_workspace.read_workspace_file",
                     return_value="<html>ok</html>",
                 ):
                result = await emit_html_widget(
                    path=f"/workspace/channels/{target}/data/widgets/foo/index.html",
                )
            env = _envelope(result)
            assert env["source_channel_id"] == target
            assert env["source_channel_id"] != str(emitting)
        finally:
            current_channel_id.reset(ctx_channel)
            current_bot_id.reset(ctx_bot)

    @pytest.mark.asyncio
    async def test_absolute_path_without_file_portion_errors(self):
        # "/workspace/channels/<uuid>" with no trailing file part is ambiguous.
        ctx_bot = current_bot_id.set("bot-abc")
        target = "00000000-0000-0000-0000-000000000001"
        try:
            result = await emit_html_widget(
                path=f"/workspace/channels/{target}",
            )
            assert _parse(result).get("error")
            assert "point at a file" in _parse(result)["error"]
        finally:
            current_bot_id.reset(ctx_bot)

    @pytest.mark.asyncio
    async def test_non_channel_absolute_rejected(self):
        # /workspace/widgets/... is DX-5b territory — not resolvable yet. Tool
        # rejects with a clear pointer instead of silently misresolving.
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            result = await emit_html_widget(
                path="/workspace/widgets/shared/index.html",
            )
            err = _parse(result).get("error", "")
            assert "/workspace/channels/" in err
        finally:
            current_bot_id.reset(ctx_bot)

    @pytest.mark.asyncio
    async def test_relative_path_still_requires_channel_context(self):
        # Relative paths keep the old behavior — they need current_channel_id
        # to scope against.
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            result = await emit_html_widget(path="data/widgets/foo/index.html")
            err = _parse(result).get("error", "")
            assert "absolute path" in err.lower() or "channel context" in err.lower()
        finally:
            current_bot_id.reset(ctx_bot)


class TestEnvelopeRoundTrip:
    def test_source_fields_round_trip_through_optin(self):
        env = _build_envelope_from_optin(
            {
                "content_type": INTERACTIVE_HTML_CONTENT_TYPE,
                "body": "",
                "plain_body": "HTML widget: live",
                "display": "inline",
                "source_path": "dashboards/cpu.html",
                "source_channel_id": "abc-123",
                "refreshable": True,
                "display_label": "CPU live",
            },
            raw_text="",
        )
        assert isinstance(env, ToolResultEnvelope)
        assert env.source_path == "dashboards/cpu.html"
        assert env.source_channel_id == "abc-123"
        assert env.refreshable is True
        assert env.display_label == "CPU live"

        d = env.compact_dict()
        assert d["source_path"] == "dashboards/cpu.html"
        assert d["source_channel_id"] == "abc-123"
        assert d["refreshable"] is True
        assert d["display_label"] == "CPU live"

    def test_absent_source_fields_not_emitted(self):
        env = _build_envelope_from_optin(
            {
                "content_type": "text/plain",
                "body": "hi",
                "plain_body": "hi",
                "display": "badge",
            },
            raw_text="hi",
        )
        d = env.compact_dict()
        assert "source_path" not in d
        assert "source_channel_id" not in d


class TestDisplayMode:
    """``display_mode`` kwarg — P10 panel-mode pinning hint."""

    @pytest.mark.asyncio
    async def test_inline_default_omits_display_mode(self):
        # The hint is opt-in: absent kwarg → not stamped, so existing pins +
        # consumers don't see a new field where they didn't before.
        result = await emit_html_widget(html="<p>x</p>")
        env = _envelope(result)
        assert "display_mode" not in env

    @pytest.mark.asyncio
    async def test_panel_stamps_display_mode_inline_path(self):
        result = await emit_html_widget(
            html="<p>x</p>", display_mode="panel",
        )
        env = _envelope(result)
        assert env["display_mode"] == "panel"

    @pytest.mark.asyncio
    async def test_invalid_display_mode_errors(self):
        result = await emit_html_widget(
            html="<p>x</p>", display_mode="huge",
        )
        err = _parse(result).get("error", "")
        assert "display_mode" in err

    def test_panel_round_trips_through_optin_envelope(self):
        env = _build_envelope_from_optin(
            {
                "content_type": INTERACTIVE_HTML_CONTENT_TYPE,
                "body": "",
                "plain_body": "panel",
                "display": "inline",
                "display_mode": "panel",
            },
            raw_text="",
        )
        assert env.display_mode == "panel"
        d = env.compact_dict()
        assert d["display_mode"] == "panel"

    def test_inline_display_mode_not_serialized(self):
        # When the value is the default we don't pollute the wire format.
        env = _build_envelope_from_optin(
            {
                "content_type": INTERACTIVE_HTML_CONTENT_TYPE,
                "body": "",
                "plain_body": "x",
                "display": "inline",
                "display_mode": "inline",
            },
            raw_text="",
        )
        d = env.compact_dict()
        assert "display_mode" not in d


class TestRuntimeFlavor:
    """``runtime`` kwarg — selects html (default) vs the React + Babel
    iframe preamble. Default and `html` must NOT stamp the field so existing
    envelopes stay byte-identical; only `react` flips it on."""

    @pytest.mark.asyncio
    async def test_default_omits_runtime(self):
        result = await emit_html_widget(html="<p>x</p>")
        env = _envelope(result)
        assert "runtime" not in env

    @pytest.mark.asyncio
    async def test_explicit_html_omits_runtime(self):
        # Backward-compat: the wire shape only carries the field when the
        # value diverges from the default. Renderer treats absent === html.
        result = await emit_html_widget(html="<p>x</p>", runtime="html")
        env = _envelope(result)
        assert "runtime" not in env

    @pytest.mark.asyncio
    async def test_react_stamps_envelope(self):
        result = await emit_html_widget(
            html='<div id="root"></div>', runtime="react",
        )
        env = _envelope(result)
        assert env["runtime"] == "react"

    @pytest.mark.asyncio
    async def test_invalid_runtime_errors(self):
        result = await emit_html_widget(html="<p>x</p>", runtime="solidjs")
        err = _parse(result).get("error", "")
        assert "runtime" in err


class TestLibraryRefMode:
    """``library_ref`` mode — render a named widget from the core library."""

    @pytest.mark.asyncio
    async def test_library_ref_old_context_tracker_html_is_gone(self):
        # ``context_tracker`` is now a native widget, not an HTML library bundle.
        result = await emit_html_widget(library_ref="context_tracker")
        parsed = _parse(result)
        assert "error" in parsed
        assert "not found" in parsed["error"]

    @pytest.mark.asyncio
    async def test_library_ref_explicit_core_context_tracker_is_gone(self):
        result = await emit_html_widget(library_ref="core/context_tracker")
        parsed = _parse(result)
        assert "error" in parsed
        assert "core/context_tracker" in parsed["error"]

    @pytest.mark.asyncio
    async def test_library_ref_picks_up_display_label_from_yaml(self, tmp_path, monkeypatch):
        from app.tools.local import emit_html_widget as ehw

        bundle = tmp_path / ".widget_library" / "scratchpad"
        bundle.mkdir(parents=True)
        (bundle / "index.html").write_text("<p>scratch</p>")
        (bundle / "widget.yaml").write_text("name: Scratchpad\n")
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )

        ctx = current_bot_id.set("crumb")
        try:
            result = await emit_html_widget(library_ref="bot/scratchpad")
        finally:
            current_bot_id.reset(ctx)
        assert _envelope(result)["display_label"] == "Scratchpad"

    @pytest.mark.asyncio
    async def test_library_ref_caller_display_label_wins(self, tmp_path, monkeypatch):
        from app.tools.local import emit_html_widget as ehw

        bundle = tmp_path / ".widget_library" / "scratchpad"
        bundle.mkdir(parents=True)
        (bundle / "index.html").write_text("<p>scratch</p>")
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )

        ctx = current_bot_id.set("crumb")
        try:
            result = await emit_html_widget(
                library_ref="bot/scratchpad", display_label="My Context"
            )
            env = _envelope(result)
            assert env["display_label"] == "My Context"
        finally:
            current_bot_id.reset(ctx)

    @pytest.mark.asyncio
    async def test_library_ref_bot_scope_renders_authored_widget(
        self, tmp_path, monkeypatch,
    ):
        """A bot that wrote widget://bot/foo/index.html can emit it by ref."""
        from app.tools.local import emit_html_widget as ehw

        (tmp_path / ".widget_library" / "foo").mkdir(parents=True)
        (tmp_path / ".widget_library" / "foo" / "index.html").write_text(
            "<p>authored</p>"
        )
        (tmp_path / ".widget_library" / "foo" / "widget.yaml").write_text(
            "display_label: Foo Widget\n"
        )
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )

        ctx = current_bot_id.set("crumb")
        try:
            result = await emit_html_widget(library_ref="bot/foo")
            env = _envelope(result)
            assert env["body"] == "<p>authored</p>"
            assert env["source_library_ref"] == "bot/foo"
            assert env["display_label"] == "Foo Widget"
        finally:
            current_bot_id.reset(ctx)

    @pytest.mark.asyncio
    async def test_library_ref_carries_panel_title_metadata(
        self, tmp_path, monkeypatch,
    ):
        from app.tools.local import emit_html_widget as ehw

        bundle = tmp_path / ".widget_library" / "home_control"
        bundle.mkdir(parents=True)
        (bundle / "index.html").write_text("<p>authored</p>")
        (bundle / "widget.yaml").write_text(
            "name: Home Control\n"
            "panel_title: Home Command Center\n"
            "show_panel_title: true\n"
        )
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )

        ctx = current_bot_id.set("crumb")
        try:
            env = _envelope(await emit_html_widget(library_ref="bot/home_control"))
        finally:
            current_bot_id.reset(ctx)

        assert env["panel_title"] == "Home Command Center"
        assert env["show_panel_title"] is True

    @pytest.mark.asyncio
    async def test_library_ref_workspace_scope_renders_shared_widget(
        self, tmp_path, monkeypatch,
    ):
        from app.tools.local import emit_html_widget as ehw

        shared = tmp_path / "shared"
        (shared / ".widget_library" / "team").mkdir(parents=True)
        (shared / ".widget_library" / "team" / "index.html").write_text(
            "<p>shared</p>"
        )
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots",
            lambda: (str(shared / "bots" / "b1"), str(shared)),
        )

        ctx = current_bot_id.set("crumb")
        try:
            result = await emit_html_widget(library_ref="workspace/team")
            env = _envelope(result)
            assert env["body"] == "<p>shared</p>"
            assert env["source_library_ref"] == "workspace/team"
        finally:
            current_bot_id.reset(ctx)

    @pytest.mark.asyncio
    async def test_library_ref_implicit_prefers_bot_over_core(
        self, tmp_path, monkeypatch,
    ):
        """Implicit ref (no scope prefix) walks bot → workspace → core."""
        from app.tools.local import emit_html_widget as ehw

        (tmp_path / ".widget_library" / "context_tracker").mkdir(parents=True)
        (tmp_path / ".widget_library" / "context_tracker" / "index.html").write_text(
            "<p>bot context</p>"
        )
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )

        ctx = current_bot_id.set("crumb")
        try:
            # The native core context tracker has no HTML bundle, but an
            # authored bot HTML widget with the same name still resolves.
            result = await emit_html_widget(library_ref="context_tracker")
            env = _envelope(result)
            assert env["body"] == "<p>bot context</p>"
            assert env["source_library_ref"] == "bot/context_tracker"
        finally:
            current_bot_id.reset(ctx)

    @pytest.mark.asyncio
    async def test_library_ref_explicit_bot_miss_hints_scope(
        self, tmp_path, monkeypatch,
    ):
        """`bot/nonexistent` surfaces a scope-specific not-found message."""
        from app.tools.local import emit_html_widget as ehw
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )
        ctx = current_bot_id.set("crumb")
        try:
            result = await emit_html_widget(library_ref="bot/nope")
            err = _parse(result).get("error", "")
            assert "bot/nope" in err
            assert 'scope="bot"' in err
        finally:
            current_bot_id.reset(ctx)

    @pytest.mark.asyncio
    async def test_library_ref_unknown_widget_errors(self):
        result = await emit_html_widget(library_ref="nonexistent_widget_xyz")
        err = _parse(result).get("error", "")
        assert "not found" in err
        assert "widget_library_list" in err  # guide bot to the listing tool

    @pytest.mark.asyncio
    async def test_library_ref_rejects_path_traversal(self):
        result = await emit_html_widget(library_ref="../secret")
        err = _parse(result).get("error", "")
        assert "Invalid" in err

    @pytest.mark.asyncio
    async def test_library_ref_rejects_invalid_scope(self):
        result = await emit_html_widget(library_ref="rogue/thing")
        err = _parse(result).get("error", "")
        assert "Invalid library_ref scope" in err

    @pytest.mark.asyncio
    async def test_library_ref_mutually_exclusive_with_html(self):
        result = await emit_html_widget(
            library_ref="context_tracker", html="<p>x</p>",
        )
        err = _parse(result).get("error", "")
        assert "exactly one" in err

    @pytest.mark.asyncio
    async def test_library_ref_mutually_exclusive_with_path(self):
        result = await emit_html_widget(
            library_ref="context_tracker", path="foo.html",
        )
        err = _parse(result).get("error", "")
        assert "exactly one" in err

    @pytest.mark.asyncio
    async def test_library_ref_bakes_bot_and_channel_context(self, tmp_path, monkeypatch):
        from app.tools.local import emit_html_widget as ehw

        (tmp_path / ".widget_library" / "scratchpad").mkdir(parents=True)
        (tmp_path / ".widget_library" / "scratchpad" / "index.html").write_text(
            "<p>scratch</p>"
        )
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )
        channel_id = uuid.uuid4()
        ctx_chan = current_channel_id.set(channel_id)
        ctx_bot = current_bot_id.set("crumb")
        try:
            result = await emit_html_widget(library_ref="bot/scratchpad")
            env = _envelope(result)
            assert env["source_channel_id"] == str(channel_id)
            assert env["source_bot_id"] == "crumb"
        finally:
            current_channel_id.reset(ctx_chan)
            current_bot_id.reset(ctx_bot)
