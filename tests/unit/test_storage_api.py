"""Unit tests for storage breakdown and purge API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.dependencies import verify_admin_auth


def _mock_db_session():
    mock_db = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_ctx)
    return mock_factory, mock_db


@pytest.fixture(autouse=True)
def _bypass_auth():
    """Bypass admin auth for all tests in this module."""
    async def _noop():
        return None
    app.dependency_overrides[verify_admin_auth] = _noop
    yield
    app.dependency_overrides.pop(verify_admin_auth, None)


# ---------------------------------------------------------------------------
# GET /admin/storage/breakdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStorageBreakdown:
    async def test_returns_all_tables(self):
        from app.services.data_retention import RETENTION_TABLES

        purgeable = {table: 10 for table, _, _ in RETENTION_TABLES}

        async def mock_execute(sql, *args, **kwargs):
            result = MagicMock()
            sql_str = str(sql)
            if "COUNT" in sql_str:
                result.scalar = MagicMock(return_value=100)
            elif "pg_total_relation_size" in sql_str:
                result.scalar = MagicMock(return_value=1048576)
            elif "MIN" in sql_str:
                result.scalar = MagicMock(return_value=None)
            else:
                result.scalar = MagicMock(return_value=0)
            return result

        mock_factory, mock_db = _mock_db_session()
        mock_db.execute = mock_execute

        with (
            patch("app.routers.api_v1_admin.storage.get_purgeable_counts", new_callable=AsyncMock, return_value=purgeable),
            patch("app.routers.api_v1_admin.storage.async_session", mock_factory),
            patch("app.routers.api_v1_admin.storage.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 30
            mock_settings.DATA_RETENTION_SWEEP_INTERVAL_S = 86400

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/v1/admin/storage/breakdown", headers={"Authorization": "Bearer test-key"})

            assert resp.status_code == 200
            data = resp.json()
            assert len(data["tables"]) == len(RETENTION_TABLES)
            assert data["retention_days"] == 30
            assert data["sweep_interval_s"] == 86400

            for t in data["tables"]:
                assert "table" in t
                assert "row_count" in t
                assert "purgeable" in t
                assert t["purgeable"] == 10

    async def test_purgeable_counts_zero_when_disabled(self):
        """Purgeable counts are 0 when retention is disabled."""
        from app.services.data_retention import RETENTION_TABLES

        purgeable = {table: 0 for table, _, _ in RETENTION_TABLES}

        mock_factory, mock_db = _mock_db_session()

        async def mock_execute(sql, *args, **kwargs):
            result = MagicMock()
            sql_str = str(sql)
            if "COUNT" in sql_str:
                result.scalar = MagicMock(return_value=50)
            elif "pg_total_relation_size" in sql_str:
                raise Exception("not pg")
            elif "MIN" in sql_str:
                result.scalar = MagicMock(return_value=None)
            else:
                result.scalar = MagicMock(return_value=0)
            return result

        mock_db.execute = mock_execute

        with (
            patch("app.routers.api_v1_admin.storage.get_purgeable_counts", new_callable=AsyncMock, return_value=purgeable),
            patch("app.routers.api_v1_admin.storage.async_session", mock_factory),
            patch("app.routers.api_v1_admin.storage.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = None
            mock_settings.DATA_RETENTION_SWEEP_INTERVAL_S = 86400

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/v1/admin/storage/breakdown", headers={"Authorization": "Bearer test-key"})

            assert resp.status_code == 200
            data = resp.json()
            assert data["retention_days"] is None
            assert all(t["purgeable"] == 0 for t in data["tables"])


# ---------------------------------------------------------------------------
# POST /admin/storage/purge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestPurgeStorage:
    async def test_manual_purge_works(self):
        from app.services.data_retention import RETENTION_TABLES
        deleted = {table: 5 for table, _, _ in RETENTION_TABLES}

        with (
            patch("app.routers.api_v1_admin.storage.run_data_retention_sweep", new_callable=AsyncMock, return_value=deleted),
            patch("app.routers.api_v1_admin.storage.settings") as mock_settings,
        ):
            mock_settings.DATA_RETENTION_DAYS = 30

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/api/v1/admin/storage/purge", headers={"Authorization": "Bearer test-key"})

            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 5 * len(RETENTION_TABLES)
            assert len(data["deleted"]) == len(RETENTION_TABLES)

    async def test_purge_when_disabled_returns_empty(self):
        with patch("app.routers.api_v1_admin.storage.settings") as mock_settings:
            mock_settings.DATA_RETENTION_DAYS = None

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.post("/api/v1/admin/storage/purge", headers={"Authorization": "Bearer test-key"})

            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["deleted"] == {}
