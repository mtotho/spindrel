import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from integrations.arr.tools import overview


@pytest.mark.asyncio
async def test_arr_heartbeat_snapshot_reports_all_configured_services(monkeypatch):
    monkeypatch.setattr(overview, "sonarr_queue", AsyncMock(return_value=json.dumps({"count": 1, "items": [{"id": 1}]})))
    monkeypatch.setattr(overview, "sonarr_wanted", AsyncMock(return_value=json.dumps({"count": 2, "items": []})))
    monkeypatch.setattr(overview, "sonarr_calendar", AsyncMock(return_value=json.dumps({"count": 3, "episodes": []})))
    monkeypatch.setattr(overview, "radarr_queue", AsyncMock(return_value=json.dumps({"count": 0, "items": []})))
    monkeypatch.setattr(overview, "radarr_movies", AsyncMock(return_value=json.dumps({"count": 1, "movies": [{"id": 2}]})))

    result = json.loads(await overview.arr_heartbeat_snapshot(include_services=["sonarr", "radarr"]))

    assert result["status"] == "ok"
    assert result["services"] == {"sonarr": "ok", "radarr": "ok"}
    assert result["sonarr"]["queue"]["count"] == 1
    assert result["radarr"]["wanted"]["count"] == 1


@pytest.mark.asyncio
async def test_arr_heartbeat_snapshot_keeps_running_when_one_service_fails(monkeypatch):
    monkeypatch.setattr(overview, "sonarr_queue", AsyncMock(return_value=json.dumps({"error": "Cannot connect to Sonarr at http://sonarr:8989"})))
    monkeypatch.setattr(overview, "sonarr_wanted", AsyncMock(return_value=json.dumps({"count": 0, "items": []})))
    monkeypatch.setattr(overview, "sonarr_calendar", AsyncMock(return_value=json.dumps({"count": 0, "episodes": []})))
    monkeypatch.setattr(overview, "radarr_queue", AsyncMock(return_value=json.dumps({"count": 0, "items": []})))
    monkeypatch.setattr(overview, "radarr_movies", AsyncMock(return_value=json.dumps({"count": 0, "movies": []})))

    result = json.loads(await overview.arr_heartbeat_snapshot(include_services=["sonarr", "radarr"]))

    assert result["status"] == "partial"
    assert result["services"]["sonarr"] == "unavailable"
    assert result["services"]["radarr"] == "ok"
    assert result["sonarr"]["queue"]["error"].startswith("Cannot connect")


@pytest.mark.asyncio
async def test_arr_heartbeat_snapshot_marks_missing_service_config_without_failing(monkeypatch):
    monkeypatch.delenv("RADARR_API_KEY", raising=False)
    monkeypatch.setattr(overview, "sonarr_queue", AsyncMock(return_value=json.dumps({"count": 0, "items": []})))
    monkeypatch.setattr(overview, "sonarr_wanted", AsyncMock(return_value=json.dumps({"count": 0, "items": []})))
    monkeypatch.setattr(overview, "sonarr_calendar", AsyncMock(return_value=json.dumps({"count": 0, "episodes": []})))

    result = json.loads(await overview.arr_heartbeat_snapshot(include_services=["sonarr", "radarr"]))

    assert result["status"] == "partial"
    assert result["services"] == {"sonarr": "ok", "radarr": "not_configured"}
    assert result["radarr"]["error"] == "radarr is not configured"


@pytest.mark.asyncio
async def test_arr_heartbeat_snapshot_reports_unavailable_when_no_services_configured(monkeypatch):
    for key in (
        "SONARR_URL",
        "SONARR_API_KEY",
        "RADARR_URL",
        "RADARR_API_KEY",
        "QBIT_URL",
        "QBIT_USERNAME",
        "QBIT_PASSWORD",
        "JELLYFIN_URL",
        "JELLYFIN_API_KEY",
        "JELLYSEERR_URL",
        "JELLYSEERR_API_KEY",
        "PROWLARR_URL",
        "PROWLARR_API_KEY",
        "BAZARR_URL",
        "BAZARR_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    result = json.loads(await overview.arr_heartbeat_snapshot(include_services=["sonarr", "radarr", "qbit"]))

    assert result["status"] == "unavailable"
    assert result["services"] == {
        "sonarr": "not_configured",
        "radarr": "not_configured",
        "qbit": "not_configured",
    }


@pytest.mark.asyncio
async def test_arr_heartbeat_snapshot_classifies_service_timeout(monkeypatch):
    async def slow_tool():
        await asyncio.sleep(0.05)
        return json.dumps({"count": 0, "items": []})

    monkeypatch.setattr(overview, "SERVICE_TIMEOUT_S", 0.001)
    monkeypatch.setattr(overview, "sonarr_queue", slow_tool)
    monkeypatch.setattr(overview, "sonarr_wanted", AsyncMock(return_value=json.dumps({"count": 0, "items": []})))
    monkeypatch.setattr(overview, "sonarr_calendar", AsyncMock(return_value=json.dumps({"count": 0, "episodes": []})))

    result = json.loads(await overview.arr_heartbeat_snapshot(include_services=["sonarr"]))

    assert result["status"] == "unavailable"
    assert result["services"]["sonarr"] == "unavailable"
    assert result["sonarr"]["queue"]["error"]
