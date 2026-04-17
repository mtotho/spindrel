"""Phase 5: unit tests for cron-driven subscription scheduler (app.agent.tasks)."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCronUtils:
    def test_validate_cron_accepts_5_fields(self):
        from app.services.cron_utils import validate_cron
        validate_cron("0 2 * * *")
        validate_cron("*/15 * * * *")
        validate_cron("0 9 * * 1-5")

    def test_validate_cron_rejects_bad_shape(self):
        from app.services.cron_utils import validate_cron
        with pytest.raises(ValueError):
            validate_cron("")
        with pytest.raises(ValueError):
            validate_cron("* * * *")  # 4 fields
        with pytest.raises(ValueError):
            validate_cron("not a cron")

    def test_next_fire_at_advances(self):
        from app.services.cron_utils import next_fire_at
        base = datetime(2026, 4, 17, 1, 0, tzinfo=timezone.utc)
        nxt = next_fire_at("0 2 * * *", base)
        assert nxt > base
        assert nxt.hour == 2

    def test_next_n_fires_returns_sorted(self):
        from app.services.cron_utils import next_n_fires
        base = datetime(2026, 4, 17, 0, 0, tzinfo=timezone.utc)
        fires = next_n_fires("*/30 * * * *", base, n=3)
        assert len(fires) == 3
        assert all(fires[i] < fires[i + 1] for i in range(2))


class TestFireSubscription:
    """_fire_subscription advances next_fire_at and calls spawn_child_run."""

    @pytest.mark.asyncio
    async def test_fires_and_advances(self):
        from app.agent.tasks import _fire_subscription

        sub_id = uuid.uuid4()
        task_id = uuid.uuid4()
        channel_id = uuid.uuid4()

        sub = MagicMock()
        sub.id = sub_id
        sub.enabled = True
        sub.schedule = "0 2 * * *"
        sub.task_id = task_id
        sub.channel_id = channel_id
        sub.schedule_config = {"params": {"foo": "bar"}}

        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=sub)
        mock_session.commit = AsyncMock()

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        session_cm.__aexit__ = AsyncMock(return_value=None)

        spawn = AsyncMock()
        with (
            patch("app.agent.tasks.async_session", return_value=session_cm),
            patch("app.services.task_ops.spawn_child_run", spawn),
        ):
            await _fire_subscription(sub_id)

        spawn.assert_awaited_once()
        kwargs = spawn.call_args.kwargs
        assert kwargs["channel_id"] == channel_id
        assert kwargs["params"] == {"foo": "bar"}
        # Positional first arg is task_id
        assert spawn.call_args.args[0] == task_id
        assert sub.next_fire_at is not None
        assert sub.last_fired_at is not None

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        from app.agent.tasks import _fire_subscription

        sub = MagicMock()
        sub.enabled = False
        sub.schedule = "0 2 * * *"

        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=sub)
        mock_session.commit = AsyncMock()

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        session_cm.__aexit__ = AsyncMock(return_value=None)

        spawn = AsyncMock()
        with (
            patch("app.agent.tasks.async_session", return_value=session_cm),
            patch("app.services.task_ops.spawn_child_run", spawn),
        ):
            await _fire_subscription(uuid.uuid4())

        spawn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_no_schedule(self):
        from app.agent.tasks import _fire_subscription

        sub = MagicMock()
        sub.enabled = True
        sub.schedule = None

        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=sub)
        mock_session.commit = AsyncMock()

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        session_cm.__aexit__ = AsyncMock(return_value=None)

        spawn = AsyncMock()
        with (
            patch("app.agent.tasks.async_session", return_value=session_cm),
            patch("app.services.task_ops.spawn_child_run", spawn),
        ):
            await _fire_subscription(uuid.uuid4())

        spawn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_cron_clears_next_fire(self):
        from app.agent.tasks import _fire_subscription

        sub = MagicMock()
        sub.id = uuid.uuid4()
        sub.enabled = True
        sub.schedule = "this is not valid"
        sub.task_id = uuid.uuid4()
        sub.channel_id = uuid.uuid4()
        sub.schedule_config = None
        sub.next_fire_at = datetime.now(timezone.utc)

        mock_session = MagicMock()
        mock_session.get = AsyncMock(return_value=sub)
        mock_session.commit = AsyncMock()

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        session_cm.__aexit__ = AsyncMock(return_value=None)

        spawn = AsyncMock()
        with (
            patch("app.agent.tasks.async_session", return_value=session_cm),
            patch("app.services.task_ops.spawn_child_run", spawn),
        ):
            await _fire_subscription(uuid.uuid4())

        assert sub.next_fire_at is None
