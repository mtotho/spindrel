"""Phase E.10 — multi-row sync seam: channel integration activate / deactivate

Pins the ChannelIntegration row lifecycle managed by ``activate_integration``
and ``deactivate_integration``. These endpoints share a multi-row sync surface:
activating an integration with an ``includes`` list activates child integrations
atomically, and deactivating one must cascade to children unless another active
parent still needs them.

``get_activation_manifests`` is mocked at the ``integrations`` module boundary
(it reads YAML from disk and has no DB surface). All ChannelIntegration DB
reads/writes use the real SQLite fixture.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models import Channel, ChannelIntegration
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.services.channel_integrations import (
    adopt_channel_integration,
    activate_channel_integration,
    bind_channel_integration,
    deactivate_channel_integration,
    update_activation_config,
)

pytestmark = pytest.mark.asyncio

# Minimal manifests covering the test surface.
_MANIFESTS = {
    "simple-int": {"description": "Simple, no includes"},
    "parent-int": {"description": "Parent with child", "includes": ["child-int"]},
    "child-int": {"description": "Included child"},
    "other-parent": {"description": "Another parent that also includes child", "includes": ["child-int"]},
}


def _mock_manifests():
    return patch("integrations.get_activation_manifests", return_value=_MANIFESTS)


async def _seed_channel(db_session) -> uuid.UUID:
    channel_id = uuid.uuid4()
    db_session.add(Channel(id=channel_id, name=f"ch-{channel_id.hex[:6]}", bot_id="bot"))
    await db_session.commit()
    return channel_id


async def _active_rows(db_session, channel_id: uuid.UUID) -> list[ChannelIntegration]:
    rows = (await db_session.execute(
        select(ChannelIntegration).where(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.activated == True,  # noqa: E712
        )
    )).scalars().all()
    return list(rows)


async def _all_rows(db_session, channel_id: uuid.UUID) -> list[ChannelIntegration]:
    rows = (await db_session.execute(
        select(ChannelIntegration).where(ChannelIntegration.channel_id == channel_id)
    )).scalars().all()
    return list(rows)


class TestBindingContracts:
    async def test_bind_duplicate_client_id_raises_conflict(self, db_session):
        channel_id = await _seed_channel(db_session)
        await bind_channel_integration(
            db_session,
            channel_id=channel_id,
            integration_type="slack",
            client_id="slack:C123",
        )
        await db_session.commit()

        with pytest.raises(ConflictError) as exc:
            await bind_channel_integration(
                db_session,
                channel_id=channel_id,
                integration_type="slack",
                client_id="slack:C123",
            )
        assert exc.value.http_status == 409

    async def test_bind_missing_channel_raises_not_found(self, db_session):
        with pytest.raises(NotFoundError) as exc:
            await bind_channel_integration(
                db_session,
                channel_id=uuid.uuid4(),
                integration_type="slack",
                client_id="slack:C123",
            )
        assert exc.value.http_status == 404

    async def test_adopt_missing_target_raises_validation(self, db_session):
        channel_id = await _seed_channel(db_session)
        binding = await bind_channel_integration(
            db_session,
            channel_id=channel_id,
            integration_type="slack",
            client_id="slack:C123",
        )
        await db_session.commit()

        with pytest.raises(ValidationError) as exc:
            await adopt_channel_integration(
                db_session,
                channel_id=channel_id,
                binding_id=binding.id,
                target_channel_id=uuid.uuid4(),
            )
        assert exc.value.http_status == 400

    async def test_update_activation_config_merges_existing_values(self, db_session):
        channel_id = await _seed_channel(db_session)
        db_session.add(ChannelIntegration(
            channel_id=channel_id,
            integration_type="simple-int",
            client_id=f"mc-activated:simple-int:{channel_id}",
            activated=True,
            activation_config={"keep": True, "replace": "old"},
        ))
        await db_session.commit()

        out = await update_activation_config(
            db_session,
            channel_id=channel_id,
            integration_type="simple-int",
            config={"replace": "new", "add": 1},
        )

        assert out["activation_config"] == {"keep": True, "replace": "new", "add": 1}


class TestActivateContracts:
    async def test_activate_creates_new_row_when_none_exists(self, db_session):
        channel_id = await _seed_channel(db_session)
        with _mock_manifests():
            out = await activate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",
                db=db_session,
            )
        assert out.activated is True
        rows = await _active_rows(db_session, channel_id)
        assert any(r.integration_type == "simple-int" for r in rows)

    async def test_activate_idempotent_when_row_already_active(self, db_session):
        channel_id = await _seed_channel(db_session)
        db_session.add(ChannelIntegration(
            channel_id=channel_id,
            integration_type="simple-int",
            client_id=f"mc-activated:simple-int:{channel_id}",
            activated=True,
        ))
        await db_session.commit()

        with _mock_manifests():
            out = await activate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",
                db=db_session,
            )

        assert out.activated is True
        rows = await _all_rows(db_session, channel_id)
        assert len([r for r in rows if r.integration_type == "simple-int"]) == 1

    async def test_activate_reuses_inactive_row_instead_of_creating_duplicate(self, db_session):
        channel_id = await _seed_channel(db_session)
        db_session.add(ChannelIntegration(
            channel_id=channel_id,
            integration_type="simple-int",
            client_id=f"mc-activated:simple-int:{channel_id}",
            activated=False,
        ))
        await db_session.commit()

        with _mock_manifests():
            await activate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",
                db=db_session,
            )

        rows = await _all_rows(db_session, channel_id)
        assert len(rows) == 1
        assert rows[0].activated is True

    async def test_activate_preserves_real_binding_client_id(self, db_session):
        """A real binding (e.g. bb:chat_guid) must not have its client_id
        overwritten when reactivated — only mc-activated stubs are refreshed."""
        channel_id = await _seed_channel(db_session)
        real_client_id = "bb:real-guid-12345"
        db_session.add(ChannelIntegration(
            channel_id=channel_id,
            integration_type="simple-int",
            client_id=real_client_id,
            activated=False,
        ))
        await db_session.commit()

        with _mock_manifests():
            await activate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",
                db=db_session,
            )

        rows = await _all_rows(db_session, channel_id)
        assert len(rows) == 1
        assert rows[0].client_id == real_client_id

    async def test_activate_unknown_integration_raises_404(self, db_session):
        channel_id = await _seed_channel(db_session)
        with _mock_manifests():
            with pytest.raises(NotFoundError) as exc:
                await activate_channel_integration(
                    channel_id=channel_id,
                    integration_type="nonexistent-int",
                    db=db_session,
                )
        assert exc.value.http_status == 404

    async def test_activate_cascades_to_included_integrations(self, db_session):
        """Activating a parent with ``includes: [child-int]`` must also create
        an active ChannelIntegration row for child-int."""
        channel_id = await _seed_channel(db_session)
        with _mock_manifests():
            out = await activate_channel_integration(
                channel_id=channel_id,
                integration_type="parent-int",
                db=db_session,
            )
        assert out.activated is True
        rows = await _active_rows(db_session, channel_id)
        active_types = {r.integration_type for r in rows}
        assert "parent-int" in active_types
        assert "child-int" in active_types

    async def test_activate_cascade_skips_already_active_child(self, db_session):
        """If child-int is already active, activating parent-int must not
        create a duplicate child row."""
        channel_id = await _seed_channel(db_session)
        db_session.add(ChannelIntegration(
            channel_id=channel_id,
            integration_type="child-int",
            client_id="existing-child-client",
            activated=True,
        ))
        await db_session.commit()

        with _mock_manifests():
            await activate_channel_integration(
                channel_id=channel_id,
                integration_type="parent-int",
                db=db_session,
            )

        rows = await _all_rows(db_session, channel_id)
        child_rows = [r for r in rows if r.integration_type == "child-int"]
        assert len(child_rows) == 1


class TestDeactivateContracts:
    async def test_deactivate_sets_activated_false_on_active_row(self, db_session):
        channel_id = await _seed_channel(db_session)
        db_session.add(ChannelIntegration(
            channel_id=channel_id,
            integration_type="simple-int",
            client_id=f"mc-activated:simple-int:{channel_id}",
            activated=True,
        ))
        await db_session.commit()

        with _mock_manifests():
            out = await deactivate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",
                db=db_session,
            )

        assert out["activated"] is False
        rows = await _active_rows(db_session, channel_id)
        assert not any(r.integration_type == "simple-int" for r in rows)

    async def test_deactivate_cascades_to_included_child(self, db_session):
        """Deactivating parent-int must also deactivate child-int when no
        other active integration includes it."""
        channel_id = await _seed_channel(db_session)
        for int_type, client_id in [
            ("parent-int", f"mc-activated:parent-int:{channel_id}"),
            ("child-int", f"mc-activated:child-int:{channel_id}"),
        ]:
            db_session.add(ChannelIntegration(
                channel_id=channel_id,
                integration_type=int_type,
                client_id=client_id,
                activated=True,
            ))
        await db_session.commit()

        with _mock_manifests():
            await deactivate_channel_integration(
                channel_id=channel_id,
                integration_type="parent-int",
                db=db_session,
            )

        rows = await _active_rows(db_session, channel_id)
        active_types = {r.integration_type for r in rows}
        assert "parent-int" not in active_types
        assert "child-int" not in active_types

    async def test_deactivate_skips_cascade_when_child_still_needed(self, db_session):
        """child-int is included by both parent-int and other-parent. Deactivating
        parent-int must NOT deactivate child-int because other-parent is still active."""
        channel_id = await _seed_channel(db_session)
        for int_type, client_id in [
            ("parent-int", f"mc-activated:parent-int:{channel_id}"),
            ("other-parent", f"mc-activated:other-parent:{channel_id}"),
            ("child-int", f"mc-activated:child-int:{channel_id}"),
        ]:
            db_session.add(ChannelIntegration(
                channel_id=channel_id,
                integration_type=int_type,
                client_id=client_id,
                activated=True,
            ))
        await db_session.commit()

        with _mock_manifests():
            await deactivate_channel_integration(
                channel_id=channel_id,
                integration_type="parent-int",
                db=db_session,
            )

        rows = await _active_rows(db_session, channel_id)
        active_types = {r.integration_type for r in rows}
        assert "parent-int" not in active_types
        assert "child-int" in active_types, "child-int must stay active: other-parent still needs it"
        assert "other-parent" in active_types

    async def test_deactivate_nonexistent_type_returns_ok_with_no_rows_changed(self, db_session):
        """Deactivating an integration type with no active rows is a no-op,
        not an error — callers must be able to deactivate idempotently."""
        channel_id = await _seed_channel(db_session)
        with _mock_manifests():
            out = await deactivate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",  # No row exists for this channel
                db=db_session,
            )
        assert out["ok"] is True
        assert out["activated"] is False

    async def test_activate_then_deactivate_leaves_row_inactive_not_deleted(self, db_session):
        """Deactivate must set activated=False, not delete the row. A subsequent
        activate should reuse the existing row, not create a new one."""
        channel_id = await _seed_channel(db_session)
        with _mock_manifests():
            await activate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",
                db=db_session,
            )
            await deactivate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",
                db=db_session,
            )

        all_rows = await _all_rows(db_session, channel_id)
        simple_rows = [r for r in all_rows if r.integration_type == "simple-int"]
        assert len(simple_rows) == 1
        assert simple_rows[0].activated is False

        # Reactivate — must reuse, not duplicate.
        with _mock_manifests():
            await activate_channel_integration(
                channel_id=channel_id,
                integration_type="simple-int",
                db=db_session,
            )

        all_rows = await _all_rows(db_session, channel_id)
        simple_rows = [r for r in all_rows if r.integration_type == "simple-int"]
        assert len(simple_rows) == 1
        assert simple_rows[0].activated is True
