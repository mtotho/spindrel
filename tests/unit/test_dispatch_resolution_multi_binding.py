"""Phase F.5 — multi-actor seam: dispatch_resolution.resolve_targets

Pins the multi-binding selection contract under mid-turn binding drift:
DB failures, duplicate integration types, malformed configs, internal-key
exclusion, and stale-channel + live-delete races.

Seam class: multi-actor (multi-binding channel, concurrent binding changes)
Loose Ends: none confirmed as new bugs — contracts pinned as-is.
Reference: tests/unit/test_dispatch_resolution.py (Phase D happy-path coverage)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import DefaultClause
from sqlalchemy import text as sa_text

from tests.unit.test_outbox import _patch_pg_types_for_sqlite  # noqa: F401

from app.db.models import Base, Channel, ChannelIntegration
from app.domain.dispatch_target import NoneTarget
from integrations.slack.target import SlackTarget
from app.services import dispatch_resolution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
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
    return Channel(id=uuid.uuid4(), name="ch", bot_id="bot", **kwargs)


def _slack_binding(channel_id: uuid.UUID, client_suffix: str = "C1", **kwargs) -> ChannelIntegration:
    return ChannelIntegration(
        id=uuid.uuid4(),
        channel_id=channel_id,
        integration_type="slack",
        client_id=f"slack:{client_suffix}",
        dispatch_config={"type": "slack", "channel_id": client_suffix, "token": "xoxb-test"},
        activated=True,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# DB exception resilience
# ---------------------------------------------------------------------------

class TestDbExceptionSwallow:
    """DB failure in the binding query is silently swallowed — no crash."""

    @pytest.mark.asyncio
    async def test_when_binding_query_raises_then_channel_level_target_still_returned(self):
        """Contract: DB failure falls back to channel-level target, not a crash.

        Drift: if someone re-raises from the except clause, this test catches it.
        """
        channel = _make_channel(
            integration="slack",
            dispatch_config={"channel_id": "C-DIRECT", "token": "xoxb-direct"},
        )
        failing_ctx = AsyncMock()
        failing_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("db down"))

        def _failing_factory():
            return failing_ctx

        with patch("app.services.dispatch_resolution.async_session", _failing_factory):
            targets = await dispatch_resolution.resolve_targets(channel)

        assert len(targets) == 1
        assert targets[0][0] == "slack"
        assert isinstance(targets[0][1], SlackTarget)

    @pytest.mark.asyncio
    async def test_when_binding_query_raises_and_no_channel_level_then_none_target(self):
        """Contract: DB failure with no channel-level config → NoneTarget, no exception."""
        channel = _make_channel()
        failing_ctx = AsyncMock()
        failing_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("db down"))

        def _failing_factory():
            return failing_ctx

        with patch("app.services.dispatch_resolution.async_session", _failing_factory):
            targets = await dispatch_resolution.resolve_targets(channel)

        assert targets == [("none", NoneTarget())]


# ---------------------------------------------------------------------------
# Duplicate integration type dedup
# ---------------------------------------------------------------------------

class TestDuplicateIntegrationType:
    """Two bindings with the same integration_type → first-wins dedup."""

    @pytest.mark.asyncio
    async def test_when_two_bindings_same_type_then_first_wins(self, factory):
        """Drift pin: second binding with same integration_type is silently skipped.

        UniqueConstraint is on (channel_id, client_id), NOT (channel_id, integration_type),
        so two bindings with distinct client_ids but same integration_type are DB-valid.
        The resolver deduplicates them; only the first one (DB scan order) is returned.
        """
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            binding1 = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="slack",
                client_id="slack:C-FIRST",
                dispatch_config={"type": "slack", "channel_id": "C-FIRST", "token": "xoxb-1"},
                activated=True,
            )
            binding2 = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="slack",
                client_id="slack:C-SECOND",
                dispatch_config={"type": "slack", "channel_id": "C-SECOND", "token": "xoxb-2"},
                activated=True,
            )
            db.add_all([binding1, binding2])
            await db.commit()

            targets = await dispatch_resolution.resolve_targets(channel)

        slack_targets = [t for iid, t in targets if iid == "slack"]
        assert len(slack_targets) == 1, "second binding with same integration_type must be skipped"

    @pytest.mark.asyncio
    async def test_distinct_integration_types_each_appear_in_result(self, factory):
        """Sibling contract: different integration types each get their own entry."""
        from integrations.bluebubbles.target import BlueBubblesTarget
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            slack = _slack_binding(channel.id)
            bb = ChannelIntegration(
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
            db.add_all([slack, bb])
            await db.commit()

            targets = await dispatch_resolution.resolve_targets(channel)

        ids = {iid for iid, _ in targets}
        assert ids == {"slack", "bluebubbles"}


# ---------------------------------------------------------------------------
# Malformed binding config resilience
# ---------------------------------------------------------------------------

class TestMalformedBindingConfig:
    """_resolve_binding returns None for bindings that can't be parsed."""

    @pytest.mark.asyncio
    async def test_when_binding_dispatch_config_unparseable_then_fallthrough_to_none(self, factory):
        """Drift pin: ValueError from parse_dispatch_target is caught, binding excluded."""
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            bad = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="slack",
                client_id="slack:C-BAD",
                dispatch_config={"type": "unknown-bogus-type", "channel_id": "C-BAD"},
                activated=True,
            )
            db.add(bad)
            await db.commit()

            targets = await dispatch_resolution.resolve_targets(channel)

        assert targets == [("none", NoneTarget())]

    @pytest.mark.asyncio
    async def test_when_one_binding_valid_one_malformed_then_only_valid_returned(self, factory):
        """Good binding is included even when a sibling binding fails to parse."""
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            good = _slack_binding(channel.id)
            bad = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="bluebubbles",
                client_id="bluebubbles:bad",
                dispatch_config={"type": "unknown-bogus-type"},
                activated=True,
            )
            db.add_all([good, bad])
            await db.commit()

            targets = await dispatch_resolution.resolve_targets(channel)

        ids = {iid for iid, _ in targets}
        assert ids == {"slack"}, "valid binding returned; malformed sibling skipped"


# ---------------------------------------------------------------------------
# Mid-turn binding deletion
# ---------------------------------------------------------------------------

class TestMidTurnBindingDeletion:
    """Fresh DB query means binding deletions during a turn are immediately visible."""

    @pytest.mark.asyncio
    async def test_when_binding_deleted_after_channel_loaded_then_absent_from_result(self, factory):
        """Drift pin: resolve_targets re-queries bindings live — no stale-read window.

        A stale Channel object (pre-loaded before the delete) does not cause
        the deleted binding to resurface in the result. The resolver holds no
        cache of binding rows.
        """
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            binding = _slack_binding(channel.id)
            db.add(binding)
            await db.commit()
            binding_id = binding.id

        # Simulate mid-turn deletion in a separate session.
        async with factory() as db:
            to_delete = await db.get(ChannelIntegration, binding_id)
            await db.delete(to_delete)
            await db.commit()

        # Channel object is "stale" but the binding is gone — result must be NoneTarget.
        targets = await dispatch_resolution.resolve_targets(channel)
        assert targets == [("none", NoneTarget())], (
            "fresh binding query sees the deletion; no stale-read artifact"
        )


# ---------------------------------------------------------------------------
# _INTERNAL_KEYS exclusion via meta hook path
# ---------------------------------------------------------------------------

class TestInternalKeyExclusion:
    """_INTERNAL_KEYS values in binding_config are NOT merged into meta-resolved config."""

    @pytest.mark.asyncio
    async def test_when_binding_config_has_token_then_not_merged_over_meta_resolved_token(self, factory):
        """Drift pin: 'token' is an _INTERNAL_KEY — stale binding token must not override meta.

        If someone removes 'token' from _INTERNAL_KEYS, the binding's stale
        dispatch_config['token'] would silently override the freshly-resolved
        token from the meta hook, breaking auth for all messages in the turn.
        """
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            binding = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="slack",
                client_id="slack:C-META",
                # binding_config contains only a stale token (_INTERNAL_KEY).
                # Non-SlackTarget fields must NOT be added here — parse_dispatch_target
                # rejects unknown kwargs. The point of this test is _INTERNAL_KEYS exclusion.
                dispatch_config={
                    "token": "stale-binding-token",   # _INTERNAL_KEY — must NOT override
                },
                activated=True,
            )
            db.add(binding)
            await db.commit()

        meta_mock = MagicMock()
        meta_mock.resolve_dispatch_config = lambda client_id: {
            "type": "slack",
            "channel_id": "C-META",
            "token": "xoxb-fresh-from-meta",
        }

        with patch("app.agent.hooks.get_integration_meta", return_value=meta_mock):
            targets = await dispatch_resolution.resolve_targets(channel)

        assert len(targets) == 1
        _, target = targets[0]
        assert isinstance(target, SlackTarget)
        assert target.token == "xoxb-fresh-from-meta", (
            "_INTERNAL_KEY 'token' in binding_config must not override meta-resolved token"
        )

    @pytest.mark.asyncio
    async def test_when_binding_config_has_thread_ts_then_not_merged_into_dispatch(self, factory):
        """Drift pin: 'thread_ts' is an _INTERNAL_KEY — per-event thread must not persist.

        If thread_ts leaked from a previous event's binding_config into the
        dispatch_config, all subsequent messages would be posted in the wrong
        thread regardless of whether the current turn started one.
        """
        channel = _make_channel()
        async with factory() as db:
            db.add(channel)
            await db.commit()
            binding = ChannelIntegration(
                id=uuid.uuid4(),
                channel_id=channel.id,
                integration_type="slack",
                client_id="slack:C-THREAD",
                dispatch_config={"thread_ts": "stale-thread-999.000"},
                activated=True,
            )
            db.add(binding)
            await db.commit()

        meta_mock = MagicMock()
        meta_mock.resolve_dispatch_config = lambda client_id: {
            "type": "slack",
            "channel_id": "C-THREAD",
            "token": "xoxb-ok",
        }

        with patch("app.agent.hooks.get_integration_meta", return_value=meta_mock):
            targets = await dispatch_resolution.resolve_targets(channel)

        assert len(targets) == 1
        _, target = targets[0]
        assert isinstance(target, SlackTarget)
        assert target.thread_ts is None, (
            "_INTERNAL_KEY 'thread_ts' in binding_config must not bleed into resolved target"
        )
