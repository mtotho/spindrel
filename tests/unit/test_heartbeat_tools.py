"""Tests for the get_last_heartbeat tool (heartbeat_tools.py)."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.local.heartbeat_tools import get_last_heartbeat


def _make_heartbeat_run(*, result=None, error=None, status="complete"):
    """Create a mock HeartbeatRun-like object."""
    run = MagicMock()
    run.id = uuid.uuid4()
    run.status = status
    run.run_at = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
    run.completed_at = datetime(2026, 3, 30, 12, 1, 0, tzinfo=timezone.utc)
    run.result = result
    run.error = error
    return run


def _make_scalar_result(value):
    """Mock for a query result that needs .scalar()."""
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _make_scalars_result(items):
    """Mock for a query result that needs .scalars().all()."""
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _make_db_session(execute_returns):
    """Build an async session mock with given execute return values."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=execute_returns)
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session


@pytest.mark.asyncio
class TestGetLastHeartbeat:
    async def test_no_channel_context_returns_error(self):
        with patch("app.tools.local.heartbeat_tools.current_channel_id") as mock_ctx:
            mock_ctx.get.return_value = None
            result = await get_last_heartbeat()
        assert "No channel context" in result

    async def test_no_heartbeat_configured(self):
        channel_id = uuid.uuid4()
        session = _make_db_session([_make_scalar_result(None)])

        with (
            patch("app.tools.local.heartbeat_tools.current_channel_id") as mock_ctx,
            patch("app.tools.local.heartbeat_tools.async_session", return_value=session),
        ):
            mock_ctx.get.return_value = channel_id
            result = await get_last_heartbeat()
        assert "No heartbeat configured" in result

    async def test_no_runs_returns_message(self):
        channel_id = uuid.uuid4()
        hb_id = uuid.uuid4()
        session = _make_db_session([
            _make_scalar_result(hb_id),
            _make_scalars_result([]),
        ])

        with (
            patch("app.tools.local.heartbeat_tools.current_channel_id") as mock_ctx,
            patch("app.tools.local.heartbeat_tools.async_session", return_value=session),
        ):
            mock_ctx.get.return_value = channel_id
            result = await get_last_heartbeat()
        assert "No completed heartbeat runs" in result

    async def test_returns_heartbeat_run_fields(self):
        channel_id = uuid.uuid4()
        hb_id = uuid.uuid4()
        run = _make_heartbeat_run(result="All systems nominal.")
        session = _make_db_session([
            _make_scalar_result(hb_id),
            _make_scalars_result([run]),
        ])

        with (
            patch("app.tools.local.heartbeat_tools.current_channel_id") as mock_ctx,
            patch("app.tools.local.heartbeat_tools.async_session", return_value=session),
        ):
            mock_ctx.get.return_value = channel_id
            result = await get_last_heartbeat()

        parsed = json.loads(result)
        assert parsed["run_id"] == str(run.id)
        assert parsed["status"] == "complete"
        assert parsed["result"] == "All systems nominal."
        assert "run_at" in parsed
        assert "completed_at" in parsed

    async def test_error_field_included_when_present(self):
        channel_id = uuid.uuid4()
        hb_id = uuid.uuid4()
        run = _make_heartbeat_run(result=None, error="Timed out", status="failed")
        session = _make_db_session([
            _make_scalar_result(hb_id),
            _make_scalars_result([run]),
        ])

        with (
            patch("app.tools.local.heartbeat_tools.current_channel_id") as mock_ctx,
            patch("app.tools.local.heartbeat_tools.async_session", return_value=session),
        ):
            mock_ctx.get.return_value = channel_id
            result = await get_last_heartbeat()

        parsed = json.loads(result)
        assert parsed["error"] == "Timed out"
        assert parsed["status"] == "failed"

    async def test_limit_parameter_respected(self):
        channel_id = uuid.uuid4()
        hb_id = uuid.uuid4()
        runs = [_make_heartbeat_run(result=f"Run {i}") for i in range(3)]
        session = _make_db_session([
            _make_scalar_result(hb_id),
            _make_scalars_result(runs),
        ])

        with (
            patch("app.tools.local.heartbeat_tools.current_channel_id") as mock_ctx,
            patch("app.tools.local.heartbeat_tools.async_session", return_value=session),
        ):
            mock_ctx.get.return_value = channel_id
            result = await get_last_heartbeat(limit=3)

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 3
