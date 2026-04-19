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
        result = await emit_html_widget(html="<p>hello</p>")
        env = _envelope(result)
        assert env["content_type"] == INTERACTIVE_HTML_CONTENT_TYPE
        assert env["body"] == "<p>hello</p>"
        assert env["display"] == "inline"
        # No display_label → not emitted
        assert "display_label" not in env
        # No source_path in inline mode
        assert "source_path" not in env
        assert env["plain_body"].startswith("HTML widget (")

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
            assert env["refreshable"] is True
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
