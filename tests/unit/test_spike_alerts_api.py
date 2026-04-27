"""Tests for spike alert API endpoints."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Minimal fixtures (adapted from integration conftest)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    from app.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    from sqlalchemy import text as sa_text
    originals = {}
    _REPLACEMENTS = {
        "now()": "CURRENT_TIMESTAMP",
        "gen_random_uuid()": None,
    }
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            sd_text = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default = None
            needs_replace = False
            for pg_expr, sqlite_expr in _REPLACEMENTS.items():
                if pg_expr in sd_text:
                    needs_replace = True
                    new_default = sqlite_expr
                    break
            if not needs_replace and "::jsonb" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::jsonb", "")
            if not needs_replace and "::json" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::json", "")
            if needs_replace:
                originals[(table.name, col.name)] = sd
                if new_default:
                    from sqlalchemy.schema import DefaultClause
                    col.server_default = DefaultClause(sa_text(new_default))
                else:
                    col.server_default = None

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for (tname, cname), default in originals.items():
        table = Base.metadata.tables[tname]
        table.c[cname].server_default = default

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    from fastapi import FastAPI
    from app.routers.api_v1_admin.spike_alerts import router
    from app.dependencies import get_db, verify_auth

    app = FastAPI()
    # Mount under /admin prefix to match real registration
    from fastapi import APIRouter
    admin_router = APIRouter(prefix="/admin")
    admin_router.include_router(router)
    app.include_router(admin_router)

    async def _override_get_db():
        yield db_session

    async def _override_verify_auth():
        return "test-key"

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth] = _override_verify_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetConfig:
    async def test_auto_creates_default(self, client):
        """GET /config should auto-create a default config if none exists."""
        with patch("app.routers.api_v1_admin.spike_alerts.load_spike_config", new_callable=AsyncMock):
            r = await client.get("/admin/spike-alerts/config", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is False
        assert data["window_minutes"] == 30
        assert data["relative_threshold"] == 2.0
        assert data["targets"] == []
        assert data["target_ids"] == []

    async def test_returns_existing(self, client, db_session):
        """GET /config should return existing config."""
        from app.db.models import UsageSpikeConfig
        cfg = UsageSpikeConfig(
            id=uuid.uuid4(),
            enabled=True,
            window_minutes=15,
            relative_threshold=3.0,
        )
        db_session.add(cfg)
        await db_session.commit()

        r = await client.get("/admin/spike-alerts/config", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert data["window_minutes"] == 15
        assert data["relative_threshold"] == 3.0


class TestUpdateConfig:
    async def test_update_fields(self, client):
        """PUT /config should update specified fields."""
        # First create
        with patch("app.routers.api_v1_admin.spike_alerts.load_spike_config", new_callable=AsyncMock):
            await client.get("/admin/spike-alerts/config", headers=AUTH_HEADERS)

        with patch("app.routers.api_v1_admin.spike_alerts.load_spike_config", new_callable=AsyncMock):
            r = await client.put(
                "/admin/spike-alerts/config",
                headers=AUTH_HEADERS,
                json={"enabled": True, "window_minutes": 15, "relative_threshold": 3.0},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert data["window_minutes"] == 15
        assert data["relative_threshold"] == 3.0

    async def test_invalid_window(self, client):
        """PUT /config with window_minutes < 1 should fail."""
        with patch("app.routers.api_v1_admin.spike_alerts.load_spike_config", new_callable=AsyncMock):
            await client.get("/admin/spike-alerts/config", headers=AUTH_HEADERS)

        r = await client.put(
            "/admin/spike-alerts/config",
            headers=AUTH_HEADERS,
            json={"window_minutes": 0},
        )
        assert r.status_code == 400


class TestHistory:
    async def test_empty_history(self, client):
        """GET /history should return empty list when no alerts."""
        r = await client.get("/admin/spike-alerts/history", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["alerts"] == []

    async def test_with_alerts(self, client, db_session):
        """GET /history should return alerts in reverse chronological order."""
        from app.db.models import UsageSpikeAlert
        for i in range(3):
            db_session.add(UsageSpikeAlert(
                id=uuid.uuid4(),
                window_rate_usd_per_hour=float(i + 1),
                baseline_rate_usd_per_hour=0.5,
                trigger_reason="relative",
                targets_attempted=1,
                targets_succeeded=1,
            ))
        await db_session.commit()

        r = await client.get("/admin/spike-alerts/history", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert len(data["alerts"]) == 3


class TestStatus:
    async def test_disabled_status(self, client):
        """GET /status should return disabled status when no config."""
        with patch("app.routers.api_v1_admin.spike_alerts.get_spike_status",
                    new_callable=AsyncMock,
                    return_value={
                        "enabled": False, "spiking": False,
                        "window_rate": 0, "baseline_rate": 0,
                        "spike_ratio": None, "cooldown_active": False,
                        "cooldown_remaining_seconds": 0,
                    }):
            r = await client.get("/admin/spike-alerts/status", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is False
        assert data["spiking"] is False


class TestAvailableTargets:
    async def test_empty_when_no_channels(self, client):
        """GET /targets/available should return options and integrations."""
        r = await client.get("/admin/spike-alerts/targets/available", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["options"] == []
        assert isinstance(data["integrations"], list)

    async def test_includes_channels_with_integration(self, client, db_session):
        """GET /targets/available should include channels with integration set."""
        from app.db.models import Channel
        ch_id = uuid.uuid4()
        db_session.add(Channel(
            id=ch_id,
            name="test-slack",
            bot_id="test-bot",
            integration="slack",
            dispatch_config={"channel": "C123"},
        ))
        await db_session.commit()

        r = await client.get("/admin/spike-alerts/targets/available", headers=AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        options = data["options"]
        assert len(options) >= 1
        assert options[0]["type"] == "channel"
        assert options[0]["channel_id"] == str(ch_id)
        assert "slack" in options[0]["label"]


class TestTestAlert:
    async def test_no_config_returns_404(self, client):
        """POST /test should return 404 when no config exists."""
        r = await client.post("/admin/spike-alerts/test", headers=AUTH_HEADERS)
        assert r.status_code == 404

    async def test_fires_test_alert(self, client, db_session):
        """POST /test should fire a test alert."""
        from app.db.models import UsageSpikeConfig
        cfg = UsageSpikeConfig(id=uuid.uuid4())
        db_session.add(cfg)
        await db_session.commit()

        mock_alert = MagicMock()
        mock_alert.id = uuid.uuid4()
        mock_alert.targets_attempted = 1
        mock_alert.targets_succeeded = 1

        with patch("app.routers.api_v1_admin.spike_alerts.check_for_spike",
                    new_callable=AsyncMock, return_value=mock_alert):
            r = await client.post("/admin/spike-alerts/test", headers=AUTH_HEADERS)

        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["targets_attempted"] == 1
