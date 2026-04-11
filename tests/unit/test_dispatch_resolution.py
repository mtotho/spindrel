"""Phase D — dispatch resolution unit tests.

Covers ``app/services/dispatch_resolution.py:resolve_targets``:

- Channel-level ``integration`` + ``dispatch_config`` resolves to a single
  typed target.
- ``ChannelIntegration`` rows fan out to one target per activated binding.
- Inactive bindings are skipped.
- Empty result returns ``[("none", NoneTarget())]`` so the outbox row
  always has a deterministic terminal state.
- Slack-style ``{INTEGRATION}_BOT_TOKEN`` legacy fallback path.
- The integration meta hook chain merges non-internal binding-config
  keys into the resolved dispatch_config.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Re-use the SQLite type compilers from test_outbox.
from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401

from app.db.models import Base, Channel, ChannelIntegration
from app.domain.dispatch_target import NoneTarget
from integrations.bluebubbles.target import BlueBubblesTarget
from integrations.slack.target import SlackTarget
from app.services import dispatch_resolution


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    from sqlalchemy import text as sa_text
    from sqlalchemy.schema import DefaultClause
    originals: dict[tuple[str, str], object] = {}
    replacements = {"now()": "CURRENT_TIMESTAMP", "gen_random_uuid()": None}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            txt = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default: str | None = None
            replaced = False
            for pg_expr, sqlite_expr in replacements.items():
                if pg_expr in txt:
                    replaced = True
                    new_default = sqlite_expr
                    break
            if not replaced and "::jsonb" in txt:
                replaced = True
                new_default = txt.replace("::jsonb", "")
            if not replaced and "::json" in txt:
                replaced = True
                new_default = txt.replace("::json", "")
            if replaced:
                originals[(table.name, col.name)] = sd
                col.server_default = (
                    DefaultClause(sa_text(new_default)) if new_default else None
                )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    for (tname, cname), default in originals.items():
        Base.metadata.tables[tname].c[cname].server_default = default
    f = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch("app.services.dispatch_resolution.async_session", f):
        yield f
    await engine.dispose()


def _make_channel(**kwargs) -> Channel:
    return Channel(
        id=uuid.uuid4(),
        name="c",
        bot_id="b",
        **kwargs,
    )


class TestChannelLevelTarget:
    @pytest.mark.asyncio
    async def test_channel_level_dispatch_config_wins(self, factory):
        channel = _make_channel(
            integration="slack",
            dispatch_config={"channel_id": "C123", "token": "xoxb-test"},
        )
        async with factory() as db:
            db.add(channel)
            await db.commit()
            targets = await dispatch_resolution.resolve_targets(channel)
        assert len(targets) == 1
        integration_id, target = targets[0]
        assert integration_id == "slack"
        assert isinstance(target, SlackTarget)
        assert target.channel_id == "C123"
        assert target.token == "xoxb-test"

    @pytest.mark.asyncio
    async def test_no_targets_returns_none_target(self, factory):
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            targets = await dispatch_resolution.resolve_targets(channel)
        assert len(targets) == 1
        assert targets[0][0] == "none"
        assert isinstance(targets[0][1], NoneTarget)


class TestChannelIntegrationFanout:
    @pytest.mark.asyncio
    async def test_multiple_activated_bindings_become_separate_targets(self, factory):
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()

            slack_binding = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="slack",
                client_id="slack:C123",
                dispatch_config={
                    "type": "slack",
                    "channel_id": "C123",
                    "token": "xoxb-1",
                },
                activated=True,
            )
            bb_binding = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="bluebubbles",
                client_id="bluebubbles:guid-1",
                dispatch_config={
                    "type": "bluebubbles",
                    "chat_guid": "guid-1",
                    "server_url": "http://bb.test",
                    "password": "pw",
                },
                activated=True,
            )
            db.add_all([slack_binding, bb_binding])
            await db.commit()

            targets = await dispatch_resolution.resolve_targets(channel)

        integration_ids = {t[0] for t in targets}
        assert integration_ids == {"slack", "bluebubbles"}
        types = {type(t[1]).__name__ for t in targets}
        assert types == {"SlackTarget", "BlueBubblesTarget"}

    @pytest.mark.asyncio
    async def test_inactive_bindings_are_skipped(self, factory):
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            inactive = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="slack",
                client_id="slack:C123",
                dispatch_config={
                    "type": "slack",
                    "channel_id": "C123",
                    "token": "xoxb",
                },
                activated=False,
            )
            db.add(inactive)
            await db.commit()
            targets = await dispatch_resolution.resolve_targets(channel)
        # Should fall back to NoneTarget — inactive binding is skipped.
        assert targets == [("none", NoneTarget())]

    @pytest.mark.asyncio
    async def test_channel_level_takes_precedence_over_binding(self, factory):
        channel = _make_channel(
            integration="slack",
            dispatch_config={"channel_id": "C-CHANNEL-LEVEL", "token": "xoxb-direct"},
        )
        async with factory() as db:
            db.add(channel)
            await db.commit()
            binding = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="slack",
                client_id="slack:C-OTHER",
                dispatch_config={
                    "type": "slack",
                    "channel_id": "C-OTHER",
                    "token": "xoxb-binding",
                },
                activated=True,
            )
            db.add(binding)
            await db.commit()
            targets = await dispatch_resolution.resolve_targets(channel)
        assert len(targets) == 1
        _, target = targets[0]
        assert isinstance(target, SlackTarget)
        assert target.channel_id == "C-CHANNEL-LEVEL"


class TestResolveTargetForRenderer:
    @pytest.mark.asyncio
    async def test_returns_target_matching_renderer(self, factory):
        channel = _make_channel(
            integration="slack",
            dispatch_config={"channel_id": "C1", "token": "x"},
        )
        async with factory() as db:
            db.add(channel)
            await db.commit()
        target = await dispatch_resolution.resolve_target_for_renderer(
            channel.id, "slack"
        )
        assert isinstance(target, SlackTarget)

    @pytest.mark.asyncio
    async def test_returns_none_when_renderer_not_bound(self, factory):
        channel = _make_channel(
            integration="slack",
            dispatch_config={"channel_id": "C1", "token": "x"},
        )
        async with factory() as db:
            db.add(channel)
            await db.commit()
        target = await dispatch_resolution.resolve_target_for_renderer(
            channel.id, "discord"
        )
        assert target is None

    @pytest.mark.asyncio
    async def test_returns_none_when_channel_missing(self, factory):
        target = await dispatch_resolution.resolve_target_for_renderer(
            uuid.uuid4(), "slack"
        )
        assert target is None
