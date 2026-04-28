from unittest.mock import AsyncMock, patch

import pytest

from app.domain.errors import UnprocessableError, ValidationError
from app.services import integration_admin


@pytest.mark.asyncio
async def test_set_integration_status_rejects_invalid_target():
    with pytest.raises(ValidationError):
        await integration_admin.set_integration_status("demo", "needs_setup")


@pytest.mark.asyncio
async def test_update_settings_rejects_unknown_keys():
    with patch("app.services.integration_admin.get_setup_vars", return_value=[{"key": "TOKEN"}]):
        with pytest.raises(UnprocessableError) as exc:
            await integration_admin.update_integration_settings("demo", {"BAD": "x"}, db=object())

    assert "Unknown setting keys: BAD" in str(exc.value)


@pytest.mark.asyncio
async def test_update_settings_runs_host_side_followups():
    db = object()
    update_settings = AsyncMock(return_value={"TOKEN": "applied"})
    runtime_sync = AsyncMock()
    docker_sync = AsyncMock()
    api_key_sync = AsyncMock()
    mcp_refresh = AsyncMock()

    with (
        patch("app.services.integration_admin.get_setup_vars", return_value=[{"key": "TOKEN"}]),
        patch("app.services.integration_settings.update_settings", update_settings),
        patch("app.services.integration_admin._sync_runtime_providers_after_settings_update", runtime_sync),
        patch("app.services.integration_admin.sync_docker_compose_stack", docker_sync),
        patch("app.services.integration_admin._provision_api_key_if_needed", api_key_sync),
        patch("app.services.integration_admin._refresh_mcp_after_settings_update", mcp_refresh),
    ):
        result = await integration_admin.update_integration_settings("demo", {"TOKEN": "x"}, db=db)

    assert result == {"applied": {"TOKEN": "applied"}}
    update_settings.assert_awaited_once_with("demo", {"TOKEN": "x"}, [{"key": "TOKEN"}], db)
    runtime_sync.assert_awaited_once_with("demo")
    docker_sync.assert_awaited_once_with("demo")
    api_key_sync.assert_awaited_once_with("demo", db)
    mcp_refresh.assert_awaited_once_with()

