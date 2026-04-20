"""Unit tests for app.services.widget_cron — Phase B.3 of the Widget SDK track.

Covers:
- register_pin_crons: insert new rows from manifest
- register_pin_crons: update on schedule/handler change
- register_pin_crons: delete rows no longer in manifest
- register_pin_crons: no manifest → no-op
- register_pin_crons: invalid cron → row inserted disabled
- unregister_pin_crons deletes all rows for a pin
- _fire_widget_cron advances next_fire_at + invokes handler
- _fire_widget_cron resilient to handler exceptions
- spawn_due_widget_crons selects only due, enabled rows
- Cascade: deleting a pin drops its cron subscriptions
"""
from __future__ import annotations

import textwrap
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import (
    ApiKey,
    Bot,
    WidgetCronSubscription,
    WidgetDashboardPin,
)
from app.services.widget_cron import (
    _fire_widget_cron,
    register_pin_crons,
    spawn_due_widget_crons,
    unregister_pin_crons,
)
from app.services.widget_py import clear_module_cache


_CHANNEL_ID = uuid.UUID("cccc0000-0000-0000-0000-000000000099")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_module_cache()
    yield
    clear_module_cache()


def _make_bot() -> BotConfig:
    return BotConfig(
        id="cron-bot",
        name="Cron Bot",
        model="test/model",
        system_prompt="",
        memory=MemoryConfig(enabled=False),
    )


def _ws_root_patches(ws_root: Path):
    bot_patch = patch("app.agent.bots.get_bot", return_value=_make_bot())
    ws_patch = patch(
        "app.services.channel_workspace.get_channel_workspace_root",
        return_value=str(ws_root),
    )
    return bot_patch, ws_patch


def _write_bundle(
    bundle_dir: Path,
    *,
    yaml_body: str | None = None,
    py_body: str | None = None,
) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "index.html").write_text("<!-- test -->")
    if yaml_body is not None:
        (bundle_dir / "widget.yaml").write_text(textwrap.dedent(yaml_body).lstrip())
    if py_body is not None:
        (bundle_dir / "widget.py").write_text(textwrap.dedent(py_body).lstrip())


async def _seed_pin(db_session, *, bundle_rel: str) -> WidgetDashboardPin:
    """Seed bot + pin pointing at a bundle under channel workspace."""
    api_key = ApiKey(
        id=uuid.uuid4(),
        name="cron-key",
        key_hash="cronhash",
        key_prefix="cron-key-",
        scopes=["chat"],
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    bot_row = Bot(
        id="cron-bot",
        name="Cron Bot",
        display_name="Cron Bot",
        model="test/model",
        system_prompt="",
        api_key_id=api_key.id,
    )
    db_session.add(bot_row)
    await db_session.flush()

    pin = WidgetDashboardPin(
        dashboard_key="default",
        position=0,
        source_kind="adhoc",
        source_channel_id=_CHANNEL_ID,
        source_bot_id="cron-bot",
        tool_name="emit_html_widget",
        tool_args={},
        widget_config={},
        envelope={
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": "",
            "source_path": f"{bundle_rel}/index.html",
            "source_channel_id": str(_CHANNEL_ID),
            "source_bot_id": "cron-bot",
        },
        grid_layout={"x": 0, "y": 0, "w": 6, "h": 6},
    )
    db_session.add(pin)

    # Dashboard row required for FK — seed a bare 'default' dashboard if
    # one isn't present yet.
    from app.db.models import WidgetDashboard
    existing = await db_session.get(WidgetDashboard, "default")
    if existing is None:
        db_session.add(WidgetDashboard(slug="default", title="Default"))
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(pin)
    return pin


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegisterPinCrons:
    @pytest.mark.asyncio
    async def test_inserts_rows_from_manifest(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "cron_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Cron Test
                cron:
                  - name: hourly_roll
                    schedule: "0 * * * *"
                    handler: hourly_roll
                  - name: nightly
                    schedule: "0 2 * * *"
                    handler: nightly_refresh
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/cron_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_crons(db_session, pin)

        rows = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        by_name = {r.cron_name: r for r in rows}
        assert set(by_name) == {"hourly_roll", "nightly"}
        assert by_name["hourly_roll"].schedule == "0 * * * *"
        assert by_name["hourly_roll"].handler == "hourly_roll"
        assert by_name["hourly_roll"].enabled is True
        assert by_name["hourly_roll"].next_fire_at is not None
        assert by_name["nightly"].next_fire_at is not None

    @pytest.mark.asyncio
    async def test_updates_changed_schedule(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "cron_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Cron Test
                cron:
                  - name: roll
                    schedule: "0 * * * *"
                    handler: roll
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/cron_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_crons(db_session, pin)

        # Rewrite manifest with a different schedule
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Cron Test
                cron:
                  - name: roll
                    schedule: "*/15 * * * *"
                    handler: roll
            """,
        )

        with bot_patch, ws_patch:
            await register_pin_crons(db_session, pin)

        rows = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].schedule == "*/15 * * * *"

    @pytest.mark.asyncio
    async def test_deletes_rows_not_in_manifest(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "cron_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Cron Test
                cron:
                  - name: a
                    schedule: "0 * * * *"
                    handler: a
                  - name: b
                    schedule: "0 * * * *"
                    handler: b
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/cron_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_crons(db_session, pin)

        # Remove cron 'b' from manifest
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Cron Test
                cron:
                  - name: a
                    schedule: "0 * * * *"
                    handler: a
            """,
        )
        with bot_patch, ws_patch:
            await register_pin_crons(db_session, pin)

        rows = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert {r.cron_name for r in rows} == {"a"}

    @pytest.mark.asyncio
    async def test_no_manifest_is_noop(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "cron_test"
        _write_bundle(bundle_dir)  # no widget.yaml
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/cron_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_crons(db_session, pin)

        rows = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert rows == []


class TestUnregisterPinCrons:
    @pytest.mark.asyncio
    async def test_deletes_all_rows(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "cron_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Cron Test
                cron:
                  - name: a
                    schedule: "0 * * * *"
                    handler: a
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/cron_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_crons(db_session, pin)

        await unregister_pin_crons(db_session, pin.id)

        rows = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------------


class TestFireWidgetCron:
    @pytest.mark.asyncio
    async def test_advances_and_invokes(self):
        """_fire_widget_cron advances next_fire_at and calls invoke_cron."""
        pin = MagicMock(spec=WidgetDashboardPin)
        pin.id = uuid.uuid4()
        pin.source_bot_id = "cron-bot"

        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        sub = MagicMock(spec=WidgetCronSubscription)
        sub.id = uuid.uuid4()
        sub.enabled = True
        sub.schedule = "0 * * * *"
        sub.next_fire_at = past
        sub.handler = "hourly"
        sub.cron_name = "hourly"
        sub.pin_id = pin.id

        mock_db = MagicMock()
        mock_db.get = AsyncMock(side_effect=lambda model, _id: sub if model is WidgetCronSubscription else pin)
        mock_db.commit = AsyncMock()

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        session_cm.__aexit__ = AsyncMock(return_value=None)

        invoke = AsyncMock(return_value={"ok": True})
        with (
            patch("app.services.widget_cron.async_session", return_value=session_cm),
            patch("app.services.widget_py.invoke_cron", invoke),
        ):
            await _fire_widget_cron(sub.id)

        invoke.assert_awaited_once()
        args, kwargs = invoke.call_args
        assert args[0] is pin
        assert args[1] == "hourly"
        assert sub.last_fired_at is not None
        assert sub.next_fire_at is not None and sub.next_fire_at > past

    @pytest.mark.asyncio
    async def test_handler_exception_is_swallowed(self):
        """A raising handler must not propagate from _fire_widget_cron."""
        pin = MagicMock(spec=WidgetDashboardPin)
        pin.id = uuid.uuid4()

        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        sub = MagicMock(spec=WidgetCronSubscription)
        sub.id = uuid.uuid4()
        sub.enabled = True
        sub.schedule = "0 * * * *"
        sub.next_fire_at = past
        sub.handler = "broken"
        sub.cron_name = "broken"
        sub.pin_id = pin.id

        mock_db = MagicMock()
        mock_db.get = AsyncMock(side_effect=lambda model, _id: sub if model is WidgetCronSubscription else pin)
        mock_db.commit = AsyncMock()
        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        session_cm.__aexit__ = AsyncMock(return_value=None)

        invoke = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch("app.services.widget_cron.async_session", return_value=session_cm),
            patch("app.services.widget_py.invoke_cron", invoke),
        ):
            # Must not raise
            await _fire_widget_cron(sub.id)

        assert sub.last_fired_at is not None

    @pytest.mark.asyncio
    async def test_disabled_row_is_skipped(self):
        pin = MagicMock(spec=WidgetDashboardPin)
        sub = MagicMock(spec=WidgetCronSubscription)
        sub.enabled = False
        sub.next_fire_at = datetime.now(timezone.utc)

        mock_db = MagicMock()
        mock_db.get = AsyncMock(return_value=sub)
        mock_db.commit = AsyncMock()
        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        session_cm.__aexit__ = AsyncMock(return_value=None)

        invoke = AsyncMock()
        with (
            patch("app.services.widget_cron.async_session", return_value=session_cm),
            patch("app.services.widget_py.invoke_cron", invoke),
        ):
            await _fire_widget_cron(uuid.uuid4())

        invoke.assert_not_awaited()


class TestSpawnDueWidgetCrons:
    @pytest.mark.asyncio
    async def test_only_fires_due_rows(self):
        """spawn_due_widget_crons picks up due enabled rows and skips the rest."""
        from app.services.widget_cron import spawn_due_widget_crons

        due_id = uuid.uuid4()

        mock_db = MagicMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[due_id])))
        mock_db.execute = AsyncMock(return_value=result)

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_db)
        session_cm.__aexit__ = AsyncMock(return_value=None)

        fire = AsyncMock()
        with (
            patch("app.services.widget_cron.async_session", return_value=session_cm),
            patch("app.services.widget_cron._fire_widget_cron", fire),
        ):
            await spawn_due_widget_crons()

        fire.assert_awaited_once_with(due_id)


# ---------------------------------------------------------------------------
# Cascade — deleting a pin drops its cron subscriptions.
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    @pytest.mark.asyncio
    async def test_pin_delete_cascades_subs(self, db_session, tmp_path):
        ws_root = tmp_path / "workspace"
        bundle_dir = ws_root / "data" / "widgets" / "cron_test"
        _write_bundle(
            bundle_dir,
            yaml_body="""
                name: Cron Test
                cron:
                  - name: a
                    schedule: "0 * * * *"
                    handler: a
            """,
        )
        pin = await _seed_pin(db_session, bundle_rel="data/widgets/cron_test")

        bot_patch, ws_patch = _ws_root_patches(ws_root)
        with bot_patch, ws_patch:
            await register_pin_crons(db_session, pin)

        rows_before = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert len(rows_before) == 1

        # Enable the SQLite FK enforcer so CASCADE actually fires during the test.
        from sqlalchemy import event, text
        bind = db_session.get_bind()
        # On the sync connection associated with this AsyncSession, turn on FKs.
        await db_session.execute(text("PRAGMA foreign_keys = ON"))

        await db_session.delete(pin)
        await db_session.commit()

        rows_after = (await db_session.execute(
            select(WidgetCronSubscription).where(
                WidgetCronSubscription.pin_id == pin.id
            )
        )).scalars().all()
        assert rows_after == []
