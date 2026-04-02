"""Tests for heartbeat smart sleep calculation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.services.heartbeat import _seconds_until_next_heartbeat


class TestSecondsUntilNextHeartbeat:
    @pytest.mark.asyncio
    async def test_no_heartbeats_returns_30(self):
        """When no heartbeats are scheduled, fall back to 30s."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.heartbeat.async_session", return_value=mock_db):
            result = await _seconds_until_next_heartbeat()
        assert result == 30.0

    @pytest.mark.asyncio
    async def test_future_heartbeat_returns_delta(self):
        """When next heartbeat is 15s away, return ~15."""
        now = datetime.now(timezone.utc)
        future = now + timedelta(seconds=15)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = future
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.heartbeat.async_session", return_value=mock_db):
            result = await _seconds_until_next_heartbeat()
        # Allow small timing margin
        assert 13.0 <= result <= 16.0

    @pytest.mark.asyncio
    async def test_overdue_heartbeat_returns_minimum(self):
        """When next heartbeat is already past due, return the 1s floor."""
        past = datetime.now(timezone.utc) - timedelta(seconds=60)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = past
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.heartbeat.async_session", return_value=mock_db):
            result = await _seconds_until_next_heartbeat()
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_far_future_capped_at_30(self):
        """When next heartbeat is far in the future, cap at 30s."""
        far_future = datetime.now(timezone.utc) + timedelta(hours=1)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = far_future
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.heartbeat.async_session", return_value=mock_db):
            result = await _seconds_until_next_heartbeat()
        assert result == 30.0

    @pytest.mark.asyncio
    async def test_db_error_returns_30(self):
        """On DB error, fall back to 30s."""
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(side_effect=Exception("DB down"))

        with patch("app.services.heartbeat.async_session", return_value=mock_db):
            result = await _seconds_until_next_heartbeat()
        assert result == 30.0
