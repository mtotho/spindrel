"""Unit tests for data retention: sweep + purgeable counts."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_db_session():
    """Create a mock async_session context manager."""
    mock_db = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_ctx)
    return mock_factory, mock_db


# ---------------------------------------------------------------------------
# _build_where helper
# ---------------------------------------------------------------------------

class TestBuildWhere:
    def test_date_only(self):
        from app.services.data_retention import _build_where
        result = _build_where("created_at", 30, None)
        assert "created_at < now()" in result
        assert "30 days" in result

    def test_with_status_filter(self):
        from app.services.data_retention import _build_where
        result = _build_where("run_at", 7, "status != 'running'")
        assert "run_at < now()" in result
        assert "7 days" in result
        assert "status != 'running'" in result


# ---------------------------------------------------------------------------
# run_data_retention_sweep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunDataRetentionSweep:
    async def test_deletes_old_rows(self):
        """Sweep executes DELETE for each table and commits each independently."""
        mock_factory, mock_db = _mock_db_session()

        result_mock = MagicMock()
        result_mock.rowcount = 3
        mock_db.execute = AsyncMock(return_value=result_mock)

        with (
            patch("app.services.data_retention.async_session", mock_factory),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 30

            from app.services.data_retention import run_data_retention_sweep, RETENTION_TABLES
            deleted = await run_data_retention_sweep()

            # One session per table (each opens its own transaction)
            assert mock_factory.call_count == len(RETENTION_TABLES)
            # Each table committed independently
            assert mock_db.commit.call_count == len(RETENTION_TABLES)
            # Each table deleted 3 rows
            for table, _, _ in RETENTION_TABLES:
                assert deleted[table] == 3

    async def test_preserves_recent_rows(self):
        """Sweep SQL includes date filter — recent rows are not deleted."""
        mock_factory, mock_db = _mock_db_session()

        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_db.execute = AsyncMock(return_value=result_mock)

        with (
            patch("app.services.data_retention.async_session", mock_factory),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 90

            from app.services.data_retention import run_data_retention_sweep, RETENTION_TABLES
            deleted = await run_data_retention_sweep()

            assert all(v == 0 for v in deleted.values())
            assert len(deleted) == len(RETENTION_TABLES)

    async def test_status_filter_in_sql(self):
        """Tables with status filters include them in the DELETE query."""
        mock_factory, mock_db = _mock_db_session()

        calls = []
        result_mock = MagicMock()
        result_mock.rowcount = 0

        async def capture_execute(sql, *args, **kwargs):
            calls.append(str(sql))
            return result_mock

        mock_db.execute = capture_execute

        with (
            patch("app.services.data_retention.async_session", mock_factory),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 7

            from app.services.data_retention import run_data_retention_sweep
            await run_data_retention_sweep()

            sql_text = " ".join(calls)
            assert "status != 'running'" in sql_text  # heartbeat_runs
            assert "status IN ('completed', 'failed', 'cancelled')" in sql_text  # workflow_runs
            assert "status IN ('complete', 'failed', 'cancelled')" in sql_text  # tasks

    async def test_disabled_when_none(self):
        """Sweep returns empty dict when DATA_RETENTION_DAYS is None."""
        with patch("app.services.data_retention.settings") as mock_settings:
            mock_settings.DATA_RETENTION_DAYS = None

            from app.services.data_retention import run_data_retention_sweep
            deleted = await run_data_retention_sweep()

            assert deleted == {}

    async def test_explicit_retention_days_override(self):
        """Explicit retention_days parameter overrides settings."""
        mock_factory, mock_db = _mock_db_session()

        calls = []
        result_mock = MagicMock()
        result_mock.rowcount = 1

        async def capture_execute(sql, *args, **kwargs):
            calls.append(str(sql))
            return result_mock

        mock_db.execute = capture_execute

        with (
            patch("app.services.data_retention.async_session", mock_factory),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = None  # disabled globally

            from app.services.data_retention import run_data_retention_sweep
            deleted = await run_data_retention_sweep(retention_days=14)

            assert len(calls) > 0
            assert "14 days" in " ".join(calls)

    async def test_one_table_failure_does_not_block_others(self):
        """If one table's DELETE fails, the rest still succeed (separate transactions)."""
        call_count = 0

        def make_session():
            nonlocal call_count
            call_count += 1
            current_call = call_count

            mock_db = AsyncMock()

            async def maybe_fail(sql, *args, **kwargs):
                if current_call == 1:
                    raise RuntimeError("table locked")
                result = MagicMock()
                result.rowcount = 2
                return result

            mock_db.execute = maybe_fail

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            return mock_ctx

        with (
            patch("app.services.data_retention.async_session", side_effect=make_session),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 30

            from app.services.data_retention import run_data_retention_sweep, RETENTION_TABLES
            deleted = await run_data_retention_sweep()

            # First table failed (count=0), rest succeeded (count=2)
            assert deleted[RETENTION_TABLES[0][0]] == 0
            assert all(deleted[t] == 2 for t, _, _ in RETENTION_TABLES[1:])

    async def test_tables_without_status_get_no_status_clause(self):
        """Tables without status filters don't have AND status... in SQL."""
        mock_factory, mock_db = _mock_db_session()

        calls = []
        result_mock = MagicMock()
        result_mock.rowcount = 0

        async def capture_execute(sql, *args, **kwargs):
            calls.append(str(sql))
            return result_mock

        mock_db.execute = capture_execute

        with (
            patch("app.services.data_retention.async_session", mock_factory),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 7

            from app.services.data_retention import run_data_retention_sweep
            await run_data_retention_sweep()

            # trace_events (first table, no status filter) should not have "status" in its SQL
            assert "status" not in calls[0]
            # tool_calls (second table, no status filter)
            assert "status" not in calls[1]


# ---------------------------------------------------------------------------
# get_purgeable_counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetPurgeableCounts:
    async def test_returns_counts_per_table(self):
        mock_factory, mock_db = _mock_db_session()

        result_mock = MagicMock()
        result_mock.scalar = MagicMock(return_value=42)
        mock_db.execute = AsyncMock(return_value=result_mock)

        with (
            patch("app.services.data_retention.async_session", mock_factory),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 30

            from app.services.data_retention import get_purgeable_counts, RETENTION_TABLES
            counts = await get_purgeable_counts()

            assert len(counts) == len(RETENTION_TABLES)
            for table, _, _ in RETENTION_TABLES:
                assert counts[table] == 42

    async def test_returns_zeros_when_disabled(self):
        with patch("app.services.data_retention.settings") as mock_settings:
            mock_settings.DATA_RETENTION_DAYS = None

            from app.services.data_retention import get_purgeable_counts, RETENTION_TABLES
            counts = await get_purgeable_counts()

            assert all(v == 0 for v in counts.values())
            assert len(counts) == len(RETENTION_TABLES)

    async def test_explicit_override(self):
        mock_factory, mock_db = _mock_db_session()

        calls = []
        result_mock = MagicMock()
        result_mock.scalar = MagicMock(return_value=5)

        async def capture_execute(sql, *args, **kwargs):
            calls.append(str(sql))
            return result_mock

        mock_db.execute = capture_execute

        with (
            patch("app.services.data_retention.async_session", mock_factory),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = None

            from app.services.data_retention import get_purgeable_counts
            counts = await get_purgeable_counts(retention_days=7)

            assert len(calls) > 0
            assert "7 days" in " ".join(calls)
            assert all(v == 5 for v in counts.values())

    async def test_handles_count_error(self):
        """If counting one table fails, it returns 0 for that table."""
        mock_factory, mock_db = _mock_db_session()

        call_idx = 0

        async def sometimes_fail(sql, *args, **kwargs):
            nonlocal call_idx
            call_idx += 1
            if call_idx == 1:
                raise RuntimeError("permission denied")
            result = MagicMock()
            result.scalar = MagicMock(return_value=10)
            return result

        mock_db.execute = sometimes_fail

        with (
            patch("app.services.data_retention.async_session", mock_factory),
            patch("app.services.data_retention.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 30

            from app.services.data_retention import get_purgeable_counts, RETENTION_TABLES
            counts = await get_purgeable_counts()

            # First table errored → 0, rest → 10
            assert counts[RETENTION_TABLES[0][0]] == 0
            assert all(counts[t] == 10 for t, _, _ in RETENTION_TABLES[1:])
