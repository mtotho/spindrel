"""Publisher-side ephemeral dispatch — strict-deliver, no broadcast fallback.

See ``vault/Projects/agent-server/Architecture Decisions.md`` (Channel
binding model) and ``app/services/ephemeral_dispatch.py`` docstring.
"""
from __future__ import annotations

import uuid

import pytest

from app.agent import hooks as agent_hooks
from app.agent.hooks import IntegrationMeta, claims_user_id, register_integration
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEventKind
from app.integrations import renderer_registry
from app.services import ephemeral_dispatch

pytestmark = pytest.mark.asyncio


CH_UUID = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeChannel:
    def __init__(self, client_id: str | None = None):
        self.id = CH_UUID
        self.client_id = client_id


class _FakeDB:
    """Stand-in for AsyncSession — only ``db.get`` is exercised."""

    def __init__(self, channel: _FakeChannel | None):
        self._channel = channel

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, _model, _id):
        return self._channel


@pytest.fixture(autouse=True)
def _clean_registry():
    before = dict(renderer_registry._registry)
    meta_before = dict(agent_hooks._meta_registry)
    # Register the production claims_user_id predicates so the routing
    # contract stays live in tests without pulling in each integration's
    # full hooks.py (which would require httpx, zeroconf, etc.).
    register_integration(IntegrationMeta(
        integration_type="slack",
        client_id_prefix="slack:",
        claims_user_id=lambda u: u[:1] in ("U", "W") and u.isalnum(),
        attachment_file_id_key="slack_file_id",
    ))
    register_integration(IntegrationMeta(
        integration_type="discord",
        client_id_prefix="discord:",
        claims_user_id=lambda u: u.isdigit(),
    ))
    register_integration(IntegrationMeta(
        integration_type="bluebubbles",
        client_id_prefix="bb:",
        claims_user_id=lambda u: "@" in u or u.startswith("+"),
    ))
    yield
    renderer_registry._registry.clear()
    renderer_registry._registry.update(before)
    agent_hooks._meta_registry.clear()
    agent_hooks._meta_registry.update(meta_before)


class _FakeRenderer:
    def __init__(self, integration_id: str, caps: frozenset[Capability]):
        self.integration_id = integration_id
        self.capabilities = caps


def _install_channel(monkeypatch, channel: _FakeChannel | None):
    def fake_session():
        return _FakeDB(channel)
    monkeypatch.setattr(ephemeral_dispatch, "async_session", fake_session)


def _install_targets(monkeypatch, targets):
    async def fake_resolve(_channel):
        return list(targets)
    monkeypatch.setattr(ephemeral_dispatch, "resolve_targets", fake_resolve)


def _install_renderer(integration_id: str, caps: frozenset[Capability]):
    renderer_registry._registry[integration_id] = _FakeRenderer(integration_id, caps)


class TestStrictDeliver:
    async def test_publishes_with_scoped_target_when_slack_bound(self, monkeypatch):
        _install_channel(monkeypatch, _FakeChannel())
        _install_targets(monkeypatch, [("slack", object()), ("web", object())])
        _install_renderer("slack", frozenset({Capability.TEXT, Capability.EPHEMERAL}))
        _install_renderer("web", frozenset({Capability.TEXT}))

        published: list[tuple] = []
        monkeypatch.setattr(
            ephemeral_dispatch, "publish_typed",
            lambda cid, ev: published.append((cid, ev)) or 1,
        )

        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1",
            recipient_user_id="UALICE", text="secret",
        )

        assert result == {"mode": "ephemeral", "integration_id": "slack"}
        assert len(published) == 1
        _, event = published[0]
        assert event.kind == ChannelEventKind.EPHEMERAL_MESSAGE
        assert event.payload.target_integration_id == "slack"
        assert event.payload.recipient_user_id == "UALICE"
        assert event.payload.message.content == "secret"

    async def test_returns_unsupported_when_no_binding_has_ephemeral(self, monkeypatch):
        """Channel with only web bound → tool returns unsupported. No broadcast,
        no publish. Previously this path silently posted the "private" reply to
        the whole channel with a visibility marker — a privacy violation."""
        _install_channel(monkeypatch, _FakeChannel())
        _install_targets(monkeypatch, [("web", object())])
        _install_renderer("web", frozenset({Capability.TEXT}))

        published: list = []
        monkeypatch.setattr(
            ephemeral_dispatch, "publish_typed",
            lambda cid, ev: published.append((cid, ev)) or 1,
        )

        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1",
            recipient_user_id="UBOB", text="hi bob",
        )

        assert result["mode"] == "unsupported"
        assert "ask the user conversationally" in result["error"]
        assert published == []

    async def test_picks_slack_binding_for_slack_native_user_id(self, monkeypatch):
        """Even with multiple EPHEMERAL-capable bindings, a Slack U-prefix id
        routes to the slack binding. This is the seam where full cross-
        integration identity resolution will eventually live — today it's a
        regex heuristic, but the test locks the routing contract in place."""
        _install_channel(monkeypatch, _FakeChannel())
        _install_targets(monkeypatch, [("web", object()), ("slack", object())])
        _install_renderer("web", frozenset({Capability.TEXT, Capability.EPHEMERAL}))
        _install_renderer("slack", frozenset({Capability.TEXT, Capability.EPHEMERAL}))

        published: list = []
        monkeypatch.setattr(
            ephemeral_dispatch, "publish_typed",
            lambda cid, ev: published.append(ev) or 1,
        )

        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1",
            recipient_user_id="UALICE", text="secret",
        )

        assert result["integration_id"] == "slack"
        assert published[0].payload.target_integration_id == "slack"


class TestDeliverEphemeralErrors:
    async def test_empty_text_returns_error(self):
        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1", recipient_user_id="U", text="   ",
        )
        assert result["mode"] == "error"
        assert "empty" in result["error"].lower()

    async def test_missing_channel_returns_error(self, monkeypatch):
        _install_channel(monkeypatch, None)
        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1", recipient_user_id="UX", text="hi",
        )
        assert result["mode"] == "error"
        assert "not found" in result["error"]


class TestClaimsUserId:
    """The predicate itself lives on each integration's IntegrationMeta now
    (registered in ``integrations/<id>/hooks.py``). These tests verify the
    central ``claims_user_id`` lookup dispatches to the right registrant."""

    async def test_slack_claims_u_prefix(self):
        assert claims_user_id("slack", "UALICE")
        assert claims_user_id("slack", "W01ABC")
        assert not claims_user_id("slack", "123456789")
        assert not claims_user_id("slack", "")

    async def test_discord_claims_numeric_snowflake(self):
        assert claims_user_id("discord", "123456789012345678")
        assert not claims_user_id("discord", "UALICE")

    async def test_bluebubbles_claims_phone_or_email(self):
        assert claims_user_id("bluebubbles", "+15551234")
        assert claims_user_id("bluebubbles", "alice@example.com")
        assert not claims_user_id("bluebubbles", "UALICE")

    async def test_unregistered_integration_safe_default(self):
        """Removing an integration from the registry should return False,
        not raise ``NameError``/``KeyError``. Matches the plan's per-site
        verification: unregistered integration id → safe fallback."""
        assert not claims_user_id("nonexistent", "UALICE")
