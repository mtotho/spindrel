"""Tests for ``app.tools.local.forms.open_modal`` — binding-aware modal dispatch.

The tool must pick exactly one MODALS-capable binding (preferring the
origin of the triggering user message), post the "Open form" button to
that binding only, and return ``unsupported`` when no bound integration
can open a modal. The previous implementation fanned the button out to
every binding on the channel; web bindings would show a dead-end
button because the action handler is Slack-native.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.domain.capability import Capability
from app.integrations import renderer_registry
from app.tools.local import forms

pytestmark = pytest.mark.asyncio


CH_UUID = uuid.UUID("33333333-3333-3333-3333-333333333333")


class _FakeRenderer:
    def __init__(self, integration_id: str, caps: frozenset[Capability]):
        self.integration_id = integration_id
        self.capabilities = caps


class _FakeChannel:
    id = CH_UUID
    client_id = None


class _FakeDB:
    def __init__(self, *, channel=None, origin_source: str | None = None):
        self._channel = channel
        self._origin_source = origin_source

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, _model, _id):
        return self._channel

    async def execute(self, *_a, **_k):
        from types import SimpleNamespace

        msg = None
        if self._origin_source is not None:
            msg = SimpleNamespace(metadata_={"source": self._origin_source})
        return SimpleNamespace(scalar_one_or_none=lambda: msg)


@pytest.fixture(autouse=True)
def _clean_renderer_registry():
    before = dict(renderer_registry._registry)
    yield
    renderer_registry._registry.clear()
    renderer_registry._registry.update(before)


def _install_renderer(integration_id: str, caps: frozenset[Capability]):
    renderer_registry._registry[integration_id] = _FakeRenderer(integration_id, caps)


def _install_deps(monkeypatch, *, channel, targets, origin_source=None):
    def fake_session():
        return _FakeDB(channel=channel, origin_source=origin_source)
    monkeypatch.setattr(forms, "async_session", fake_session)

    async def fake_resolve(_channel):
        return list(targets)
    monkeypatch.setattr(forms, "resolve_targets", fake_resolve)


class TestPickModalTarget:
    async def test_prefers_origin_binding(self, monkeypatch):
        _install_deps(
            monkeypatch,
            channel=_FakeChannel(),
            targets=[("slack", object()), ("discord", object())],
            origin_source="slack",
        )
        _install_renderer("slack", frozenset({Capability.TEXT, Capability.MODALS}))
        _install_renderer("discord", frozenset({Capability.TEXT, Capability.MODALS}))

        pick = await forms._pick_modal_target(CH_UUID)
        assert pick == "slack"

    async def test_falls_back_when_origin_lacks_modals(self, monkeypatch):
        """User typed from web; web has no MODALS; fall back to a
        MODALS-capable binding rather than refuse."""
        _install_deps(
            monkeypatch,
            channel=_FakeChannel(),
            targets=[("web", object()), ("slack", object())],
            origin_source="web",
        )
        _install_renderer("web", frozenset({Capability.TEXT}))
        _install_renderer("slack", frozenset({Capability.TEXT, Capability.MODALS}))

        pick = await forms._pick_modal_target(CH_UUID)
        assert pick == "slack"

    async def test_returns_none_when_no_binding_has_modals(self, monkeypatch):
        _install_deps(
            monkeypatch,
            channel=_FakeChannel(),
            targets=[("web", object())],
            origin_source="web",
        )
        _install_renderer("web", frozenset({Capability.TEXT}))

        assert await forms._pick_modal_target(CH_UUID) is None

    async def test_returns_none_when_channel_missing(self, monkeypatch):
        _install_deps(
            monkeypatch,
            channel=None,
            targets=[],
        )
        assert await forms._pick_modal_target(CH_UUID) is None


class TestOpenModalTool:
    async def test_unsupported_when_no_modals_capable_binding(self, monkeypatch):
        from app.agent.context import current_channel_id
        token = current_channel_id.set(CH_UUID)
        try:
            _install_deps(
                monkeypatch,
                channel=_FakeChannel(),
                targets=[("web", object())],
                origin_source="web",
            )
            _install_renderer("web", frozenset({Capability.TEXT}))

            result = json.loads(
                await forms.open_modal(
                    title="Bug report",
                    schema={"summary": {"type": "text", "label": "Summary"}},
                )
            )
        finally:
            current_channel_id.reset(token)

        assert result["ok"] is False
        assert result["unsupported"] is True
        assert "conversationally" in result["error"]

    async def test_no_channel_returns_error(self):
        result = json.loads(await forms.open_modal(title="x", schema={}))
        assert result["ok"] is False
        assert "no channel" in result["error"]
