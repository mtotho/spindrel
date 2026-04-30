"""Tests for the ``preview_widget`` local tool.

Covers input-mode validation, library-ref resolution (happy + missing +
manifest error), inline html assembly, path-mode dry-run, and CSP
sanitizer error surfacing. preview_widget shares the resolution helpers
of ``emit_html_widget`` — the goal here is to pin the contract that the
wrapper returns ``{ok, envelope, errors}`` structured output instead of
the emit tool's ``{_envelope, llm}`` / ``{error}`` shape.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from app.agent.context import current_bot_id, current_channel_id
from app.tools.local.emit_html_widget import INTERACTIVE_HTML_CONTENT_TYPE
from app.tools.local.preview_widget import preview_widget


def _parse(result: str) -> dict:
    return json.loads(result)


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_no_mode_set_returns_input_error(self):
        out = _parse(await preview_widget())
        assert out["ok"] is False
        assert out["envelope"] is None
        assert out["errors"][0]["phase"] == "input"
        assert "exactly one" in out["errors"][0]["message"]

    @pytest.mark.asyncio
    async def test_multiple_modes_set_returns_input_error(self):
        out = _parse(await preview_widget(html="<p>x</p>", library_ref="context_tracker"))
        assert out["ok"] is False
        assert out["errors"][0]["phase"] == "input"

    @pytest.mark.asyncio
    async def test_invalid_display_mode_errors(self):
        out = _parse(await preview_widget(html="<p>x</p>", display_mode="massive"))
        assert out["ok"] is False
        assert out["errors"][0]["phase"] == "input"
        assert "display_mode" in out["errors"][0]["message"]

    @pytest.mark.asyncio
    async def test_invalid_runtime_errors(self):
        out = _parse(await preview_widget(html="<p>x</p>", runtime="solidjs"))
        assert out["ok"] is False
        assert out["errors"][0]["phase"] == "input"
        assert "runtime" in out["errors"][0]["message"]


class TestInlineMode:
    @pytest.mark.asyncio
    async def test_html_only_builds_envelope(self):
        out = _parse(await preview_widget(html="<p>hello</p>"))
        assert out["ok"] is True
        assert out["errors"] == []
        env = out["envelope"]
        assert env["content_type"] == INTERACTIVE_HTML_CONTENT_TYPE
        assert env["body"] == "<p>hello</p>"
        assert env["display"] == "inline"

    @pytest.mark.asyncio
    async def test_inline_assembles_js_and_css(self):
        out = _parse(
            await preview_widget(
                html="<div id=x></div>",
                js="window.x = 1;",
                css="#x { color: red; }",
                display_label="Demo",
            )
        )
        env = out["envelope"]
        body = env["body"]
        assert "<style>" in body and "color: red" in body
        assert "<script>" in body and "window.x = 1" in body
        assert "<div id=x></div>" in body
        assert env["display_label"] == "Demo"

    @pytest.mark.asyncio
    async def test_inline_panel_display_mode_round_trips(self):
        out = _parse(await preview_widget(html="<p>hi</p>", display_mode="panel"))
        env = out["envelope"]
        assert env["display_mode"] == "panel"

    @pytest.mark.asyncio
    async def test_inline_react_runtime_round_trips(self):
        out = _parse(await preview_widget(html='<div id="root"></div>', runtime="react"))
        env = out["envelope"]
        assert env["runtime"] == "react"

    @pytest.mark.asyncio
    async def test_explicit_html_runtime_omits_runtime_field(self):
        out = _parse(await preview_widget(html="<p>hi</p>", runtime="html"))
        assert "runtime" not in out["envelope"]

    @pytest.mark.asyncio
    async def test_inline_bakes_bot_and_channel_context(self):
        channel_id = uuid.uuid4()
        ctx_channel = current_channel_id.set(channel_id)
        ctx_bot = current_bot_id.set("crumb")
        try:
            out = _parse(await preview_widget(html="<p>x</p>"))
            env = out["envelope"]
            assert env["source_channel_id"] == str(channel_id)
            assert env["source_bot_id"] == "crumb"
        finally:
            current_channel_id.reset(ctx_channel)
            current_bot_id.reset(ctx_bot)


class TestLibraryRefMode:
    @pytest.mark.asyncio
    async def test_library_ref_old_context_tracker_html_is_gone(self):
        out = _parse(await preview_widget(library_ref="context_tracker"))
        assert out["ok"] is False
        assert out["envelope"] is None
        assert out["errors"][0]["phase"] == "library_ref"
        assert "not found" in out["errors"][0]["message"].lower()

    @pytest.mark.asyncio
    async def test_library_ref_resolves_bot_widget(self, tmp_path, monkeypatch):
        from app.tools.local import emit_html_widget as ehw

        (tmp_path / ".widget_library" / "scratchpad").mkdir(parents=True)
        (tmp_path / ".widget_library" / "scratchpad" / "index.html").write_text(
            "<p>scratch</p>"
        )
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )

        ctx = current_bot_id.set("crumb")
        try:
            out = _parse(await preview_widget(library_ref="bot/scratchpad"))
        finally:
            current_bot_id.reset(ctx)
        assert out["ok"] is True, out
        env = out["envelope"]
        assert env["source_library_ref"] == "bot/scratchpad"
        assert env["body"].strip()

    @pytest.mark.asyncio
    async def test_library_ref_missing_surfaces_structured_error(self):
        out = _parse(await preview_widget(library_ref="definitely_not_a_widget"))
        assert out["ok"] is False
        assert out["envelope"] is None
        err = out["errors"][0]
        assert err["phase"] == "library_ref"
        assert "not found" in err["message"].lower()

    @pytest.mark.asyncio
    async def test_library_ref_invalid_scope_surfaces_structured_error(self):
        out = _parse(await preview_widget(library_ref="bogus/foo"))
        assert out["ok"] is False
        assert out["errors"][0]["phase"] == "library_ref"
        assert "scope" in out["errors"][0]["message"].lower()

    @pytest.mark.asyncio
    async def test_library_ref_malformed_manifest_surfaces_manifest_error(
        self, tmp_path, monkeypatch,
    ):
        """A widget bundle with a broken widget.yaml should fail preview in
        the `manifest` phase — parse_manifest raises ManifestError on bad
        event kinds, bad CSP, missing name, etc."""
        from app.tools.local import emit_html_widget as ehw

        bundle = tmp_path / ".widget_library" / "broken"
        bundle.mkdir(parents=True)
        (bundle / "index.html").write_text("<p>hi</p>")
        # Missing required `name` — parse_manifest raises ManifestError.
        (bundle / "widget.yaml").write_text("description: missing name\n")
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )

        ctx = current_bot_id.set("crumb")
        try:
            out = _parse(await preview_widget(library_ref="bot/broken"))
        finally:
            current_bot_id.reset(ctx)
        assert out["ok"] is False
        assert out["envelope"] is None
        err = out["errors"][0]
        assert err["phase"] == "manifest"
        assert "name" in err["message"].lower()

    @pytest.mark.asyncio
    async def test_library_ref_no_manifest_is_fine(
        self, tmp_path, monkeypatch,
    ):
        """A bundle with only index.html (no widget.yaml) previews cleanly."""
        from app.tools.local import emit_html_widget as ehw

        bundle = tmp_path / ".widget_library" / "simple"
        bundle.mkdir(parents=True)
        (bundle / "index.html").write_text("<p>simple</p>")
        monkeypatch.setattr(
            ehw, "_resolve_scope_roots", lambda: (str(tmp_path), None),
        )

        ctx = current_bot_id.set("crumb")
        try:
            out = _parse(await preview_widget(library_ref="bot/simple"))
        finally:
            current_bot_id.reset(ctx)
        assert out["ok"] is True
        assert out["envelope"]["body"] == "<p>simple</p>"
        assert out["envelope"]["source_library_ref"] == "bot/simple"

    @pytest.mark.asyncio
    async def test_library_ref_carries_panel_title_metadata(
        self, tmp_path, monkeypatch,
    ):
        from app.tools.local import emit_html_widget as ehw

        bundle = tmp_path / ".widget_library" / "home_control"
        bundle.mkdir(parents=True)
        (bundle / "index.html").write_text("<p>simple</p>")
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
            out = _parse(await preview_widget(library_ref="bot/home_control"))
        finally:
            current_bot_id.reset(ctx)

        assert out["ok"] is True
        assert out["envelope"]["panel_title"] == "Home Command Center"
        assert out["envelope"]["show_panel_title"] is True


class TestCspValidation:
    @pytest.mark.asyncio
    async def test_bad_extra_csp_surfaces_csp_error(self):
        out = _parse(
            await preview_widget(
                html="<p>x</p>",
                extra_csp={"script_src": ["'self'"]},  # keywords are rejected
            )
        )
        assert out["ok"] is False
        assert out["errors"][0]["phase"] == "csp"

    @pytest.mark.asyncio
    async def test_valid_extra_csp_rides_through_to_envelope(self):
        out = _parse(
            await preview_widget(
                html="<p>x</p>",
                extra_csp={"script_src": ["https://example.com"]},
            )
        )
        assert out["ok"] is True
        assert out["envelope"]["extra_csp"] == {
            "script_src": ["https://example.com"]
        }


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
                     return_value="<html>ok</html>",
                 ):
                out = _parse(
                    await preview_widget(
                        path="dashboards/cpu.html",
                        display_label="CPU",
                    )
                )
        finally:
            current_channel_id.reset(ctx_channel)
            current_bot_id.reset(ctx_bot)
        assert out["ok"] is True
        env = out["envelope"]
        assert env["source_path"] == "dashboards/cpu.html"
        assert env["source_channel_id"] == str(channel_id)
        assert env["source_bot_id"] == "bot-abc"
        assert env["display_label"] == "CPU"

    @pytest.mark.asyncio
    async def test_path_missing_file_surfaces_path_error(self):
        channel_id = uuid.uuid4()
        ctx_channel = current_channel_id.set(channel_id)
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            with patch("app.agent.bots.get_bot", return_value=object()), \
                 patch(
                     "app.services.channel_workspace.read_workspace_file",
                     return_value=None,
                 ):
                out = _parse(
                    await preview_widget(path="does/not/exist.html")
                )
        finally:
            current_channel_id.reset(ctx_channel)
            current_bot_id.reset(ctx_bot)
        assert out["ok"] is False
        assert out["errors"][0]["phase"] == "path"

    @pytest.mark.asyncio
    async def test_path_without_channel_context_errors(self):
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            out = _parse(await preview_widget(path="rel.html"))
        finally:
            current_bot_id.reset(ctx_bot)
        assert out["ok"] is False
        assert out["errors"][0]["phase"] == "path"
        assert "channel context" in out["errors"][0]["message"]

    @pytest.mark.asyncio
    async def test_path_non_channel_absolute_path_errors(self):
        ctx_bot = current_bot_id.set("bot-abc")
        try:
            out = _parse(await preview_widget(path="/workspace/foo.html"))
        finally:
            current_bot_id.reset(ctx_bot)
        assert out["ok"] is False
        assert out["errors"][0]["phase"] == "path"
