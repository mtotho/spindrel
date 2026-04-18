"""Tests for the App Home view builder + event dispatch."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import app_home
from app_home import _build_home_view, on_app_home_opened_for_tests


def _install_config(monkeypatch, *, channels: dict | None = None, bots: dict | None = None):
    def fake_cfg():
        return {"channels": channels or {}, "bots": bots or {}}
    monkeypatch.setattr(app_home, "get_slack_config", fake_cfg)


class TestBuildHomeView:
    def test_empty_state_when_no_bindings(self, monkeypatch):
        _install_config(monkeypatch, channels={})
        view = _build_home_view()
        assert view["type"] == "home"
        texts = [
            b["text"]["text"] for b in view["blocks"]
            if b.get("type") == "section" and "text" in b
        ]
        assert any("No Slack channels are bound" in t for t in texts)

    def test_lists_bound_channels(self, monkeypatch):
        _install_config(
            monkeypatch,
            channels={
                "C01": {"bot_id": "alpha"},
                "C02": "beta",  # legacy string form
            },
            bots={"alpha": {"display_name": "Alpha Bot"}},
        )
        view = _build_home_view()
        section_texts = [
            b["text"]["text"] for b in view["blocks"]
            if b.get("type") == "section" and "text" in b
        ]
        joined = "\n".join(section_texts)
        assert "<#C01>" in joined and "Alpha Bot" in joined
        assert "<#C02>" in joined and "beta" in joined  # legacy bot_id string

    def test_truncates_long_channel_lists(self, monkeypatch):
        channels = {f"C{i:03d}": {"bot_id": f"b{i}"} for i in range(25)}
        _install_config(monkeypatch, channels=channels, bots={})
        view = _build_home_view()
        context_blocks = [b for b in view["blocks"] if b.get("type") == "context"]
        assert any(
            "10 more" in el["text"]
            for b in context_blocks for el in b.get("elements", [])
        )

    def test_has_quick_ask_button(self, monkeypatch):
        _install_config(monkeypatch)
        view = _build_home_view()
        actions = [b for b in view["blocks"] if b.get("type") == "actions"]
        assert actions
        action_ids = [el.get("action_id") for el in actions[0]["elements"]]
        assert "home_quick_ask" in action_ids


class TestOnAppHomeOpened:
    @pytest.mark.asyncio
    async def test_publishes_home_view(self, monkeypatch):
        _install_config(monkeypatch)
        client = AsyncMock()
        client.views_publish = AsyncMock()
        await on_app_home_opened_for_tests({"user": "UALICE", "tab": "home"}, client)
        client.views_publish.assert_awaited_once()
        kwargs = client.views_publish.await_args.kwargs
        assert kwargs["user_id"] == "UALICE"
        assert kwargs["view"]["type"] == "home"

    @pytest.mark.asyncio
    async def test_skips_messages_tab(self, monkeypatch):
        _install_config(monkeypatch)
        client = AsyncMock()
        client.views_publish = AsyncMock()
        await on_app_home_opened_for_tests({"user": "UALICE", "tab": "messages"}, client)
        client.views_publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_missing_user(self, monkeypatch):
        _install_config(monkeypatch)
        client = AsyncMock()
        client.views_publish = AsyncMock()
        await on_app_home_opened_for_tests({}, client)
        client.views_publish.assert_not_awaited()
