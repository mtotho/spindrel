"""Unit tests for Google Workspace CLI tool: service extraction, validation, error handling."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.google_workspace.tools.gws import (
    _extract_service,
    _normalize_service,
    _build_credentials_json,
    _get_channel_allowed_services,
    gws,
)


# ---------------------------------------------------------------------------
# _extract_service
# ---------------------------------------------------------------------------


class TestExtractService:
    def test_drive_command(self):
        assert _extract_service("drive files list") == "drive"

    def test_gmail_shortcut(self):
        assert _extract_service("gmail +triage") == "gmail"

    def test_calendar_agenda(self):
        assert _extract_service("calendar +agenda") == "calendar"

    def test_sheets_with_params(self):
        assert _extract_service("sheets +read --params '{}'") == "sheets"

    def test_single_word(self):
        assert _extract_service("tasks") == "tasks"

    def test_empty_string(self):
        assert _extract_service("") is None

    def test_whitespace_only(self):
        assert _extract_service("   ") is None

    def test_leading_whitespace(self):
        assert _extract_service("  drive files list") == "drive"

    def test_uppercase_normalized(self):
        assert _extract_service("DRIVE files list") == "drive"

    def test_mixed_case(self):
        assert _extract_service("Gmail +send") == "gmail"


# ---------------------------------------------------------------------------
# _normalize_service
# ---------------------------------------------------------------------------


class TestNormalizeService:
    def test_known_alias(self):
        assert _normalize_service("wf") == "workflow"

    def test_reports_alias(self):
        assert _normalize_service("reports") == "admin-reports"

    def test_passthrough(self):
        assert _normalize_service("drive") == "drive"

    def test_unknown(self):
        assert _normalize_service("foobar") == "foobar"


# ---------------------------------------------------------------------------
# _build_credentials_json
# ---------------------------------------------------------------------------


class TestBuildCredentials:
    def test_all_present(self):
        with patch("integrations.google_workspace.tools.gws.setting") as mock_setting:
            mock_setting.side_effect = lambda key, default="": {
                "GWS_CLIENT_ID": "test-id",
                "GWS_CLIENT_SECRET": "test-secret",
                "GWS_REFRESH_TOKEN": "test-refresh",
            }.get(key, default)
            creds = _build_credentials_json()
            assert creds is not None
            assert creds["client_id"] == "test-id"
            assert creds["client_secret"] == "test-secret"
            assert creds["refresh_token"] == "test-refresh"

    def test_missing_client_id(self):
        with patch("integrations.google_workspace.tools.gws.setting") as mock_setting:
            mock_setting.side_effect = lambda key, default="": {
                "GWS_CLIENT_SECRET": "test-secret",
                "GWS_REFRESH_TOKEN": "test-refresh",
            }.get(key, default)
            assert _build_credentials_json() is None

    def test_missing_refresh_token(self):
        with patch("integrations.google_workspace.tools.gws.setting") as mock_setting:
            mock_setting.side_effect = lambda key, default="": {
                "GWS_CLIENT_ID": "test-id",
                "GWS_CLIENT_SECRET": "test-secret",
            }.get(key, default)
            assert _build_credentials_json() is None


# ---------------------------------------------------------------------------
# gws tool — error paths
# ---------------------------------------------------------------------------


class TestGwsTool:
    @pytest.mark.asyncio
    async def test_missing_binary(self):
        with patch("integrations.google_workspace.tools.gws.shutil") as mock_shutil:
            mock_shutil.which.return_value = None
            result = await gws("drive files list")
            assert "not found" in result.lower()
            assert "Install" in result

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        with (
            patch("integrations.google_workspace.tools.gws.shutil") as mock_shutil,
            patch("integrations.google_workspace.tools.gws._build_credentials_json", return_value=None),
        ):
            mock_shutil.which.return_value = "/usr/bin/gws"
            result = await gws("drive files list")
            assert "not connected" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_command(self):
        with (
            patch("integrations.google_workspace.tools.gws.shutil") as mock_shutil,
            patch("integrations.google_workspace.tools.gws._build_credentials_json", return_value={"key": "val"}),
        ):
            mock_shutil.which.return_value = "/usr/bin/gws"
            result = await gws("")
            assert "Empty command" in result

    @pytest.mark.asyncio
    async def test_integration_not_activated(self):
        """When channel has no ChannelIntegration for google_workspace."""
        with (
            patch("integrations.google_workspace.tools.gws.shutil") as mock_shutil,
            patch("integrations.google_workspace.tools.gws._build_credentials_json", return_value={"key": "val"}),
            patch("integrations.google_workspace.tools.gws._get_channel_allowed_services", new_callable=AsyncMock, return_value=None),
            patch("app.agent.context.current_channel_id") as mock_ctx,
        ):
            mock_shutil.which.return_value = "/usr/bin/gws"
            mock_ctx.get.return_value = uuid.uuid4()
            result = await gws("drive files list")
            assert "not activated" in result.lower()

    @pytest.mark.asyncio
    async def test_service_not_allowed(self):
        """When the channel only allows drive but user tries gmail."""
        with (
            patch("integrations.google_workspace.tools.gws.shutil") as mock_shutil,
            patch("integrations.google_workspace.tools.gws._build_credentials_json", return_value={"key": "val"}),
            patch("integrations.google_workspace.tools.gws._get_channel_allowed_services", new_callable=AsyncMock, return_value=["drive", "calendar"]),
            patch("app.agent.context.current_channel_id") as mock_ctx,
        ):
            mock_shutil.which.return_value = "/usr/bin/gws"
            mock_ctx.get.return_value = uuid.uuid4()
            result = await gws("gmail +triage")
            assert "not enabled" in result.lower()
            assert "drive" in result
            assert "calendar" in result

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Happy path: service allowed, binary found, credentials present."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"file1.txt\nfile2.pdf\n", b"")
        mock_proc.returncode = 0

        with (
            patch("integrations.google_workspace.tools.gws.shutil") as mock_shutil,
            patch("integrations.google_workspace.tools.gws._build_credentials_json") as mock_creds,
            patch("integrations.google_workspace.tools.gws._get_channel_allowed_services", new_callable=AsyncMock, return_value=["drive"]),
            patch("app.agent.context.current_channel_id") as mock_ctx,
            patch("integrations.google_workspace.tools.gws.asyncio") as mock_asyncio,
            patch("integrations.google_workspace.tools.gws.tempfile") as mock_tmp,
            patch("integrations.google_workspace.tools.gws.os") as mock_os,
        ):
            mock_shutil.which.return_value = "/usr/bin/gws"
            mock_creds.return_value = {"client_id": "x", "client_secret": "y", "refresh_token": "z"}
            mock_ctx.get.return_value = uuid.uuid4()
            mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_proc)
            mock_asyncio.wait_for = AsyncMock(return_value=(b"file1.txt\nfile2.pdf\n", b""))
            # Fake temp file
            fake_tmp = MagicMock()
            fake_tmp.name = "/tmp/gws_creds_abc.json"
            mock_tmp.NamedTemporaryFile.return_value = fake_tmp
            mock_os.environ.copy.return_value = {}
            mock_os.path.exists.return_value = True

            result = await gws("drive files list")
            assert "file1.txt" in result
            assert "file2.pdf" in result

    @pytest.mark.asyncio
    async def test_cli_error_returned(self):
        """CLI exits non-zero — error output should be returned."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Error: quota exceeded")
        mock_proc.returncode = 1

        with (
            patch("integrations.google_workspace.tools.gws.shutil") as mock_shutil,
            patch("integrations.google_workspace.tools.gws._build_credentials_json") as mock_creds,
            patch("integrations.google_workspace.tools.gws._get_channel_allowed_services", new_callable=AsyncMock, return_value=["drive"]),
            patch("app.agent.context.current_channel_id") as mock_ctx,
            patch("integrations.google_workspace.tools.gws.asyncio") as mock_asyncio,
            patch("integrations.google_workspace.tools.gws.tempfile") as mock_tmp,
            patch("integrations.google_workspace.tools.gws.os") as mock_os,
        ):
            mock_shutil.which.return_value = "/usr/bin/gws"
            mock_creds.return_value = {"client_id": "x", "client_secret": "y", "refresh_token": "z"}
            mock_ctx.get.return_value = uuid.uuid4()
            mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_proc)
            mock_asyncio.wait_for = AsyncMock(return_value=(b"", b"Error: quota exceeded"))
            fake_tmp = MagicMock()
            fake_tmp.name = "/tmp/gws_creds_abc.json"
            mock_tmp.NamedTemporaryFile.return_value = fake_tmp
            mock_os.environ.copy.return_value = {}
            mock_os.path.exists.return_value = True

            result = await gws("drive files list")
            assert "error" in result.lower()
            assert "quota exceeded" in result

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """CLI takes too long — timeout message should be returned."""
        import asyncio as real_asyncio

        with (
            patch("integrations.google_workspace.tools.gws.shutil") as mock_shutil,
            patch("integrations.google_workspace.tools.gws._build_credentials_json") as mock_creds,
            patch("integrations.google_workspace.tools.gws._get_channel_allowed_services", new_callable=AsyncMock, return_value=["drive"]),
            patch("app.agent.context.current_channel_id") as mock_ctx,
            patch("integrations.google_workspace.tools.gws.asyncio") as mock_asyncio,
            patch("integrations.google_workspace.tools.gws.tempfile") as mock_tmp,
            patch("integrations.google_workspace.tools.gws.os") as mock_os,
        ):
            mock_shutil.which.return_value = "/usr/bin/gws"
            mock_creds.return_value = {"client_id": "x", "client_secret": "y", "refresh_token": "z"}
            mock_ctx.get.return_value = uuid.uuid4()
            mock_asyncio.create_subprocess_exec = AsyncMock()
            mock_asyncio.wait_for = AsyncMock(side_effect=real_asyncio.TimeoutError())
            mock_asyncio.TimeoutError = real_asyncio.TimeoutError
            fake_tmp = MagicMock()
            fake_tmp.name = "/tmp/gws_creds_abc.json"
            mock_tmp.NamedTemporaryFile.return_value = fake_tmp
            mock_os.environ.copy.return_value = {}
            mock_os.path.exists.return_value = True

            result = await gws("drive files list --page-all")
            assert "timed out" in result.lower()


# ---------------------------------------------------------------------------
# OAuth router — scope mapping
# ---------------------------------------------------------------------------


class TestScopeMapping:
    def test_scope_string_build(self):
        from integrations.google_workspace.router import _build_scope_string
        scopes = _build_scope_string(["drive", "gmail"])
        assert "drive" in scopes
        assert "gmail.modify" in scopes
        assert "openid" in scopes

    def test_unknown_scope_skipped(self):
        from integrations.google_workspace.router import _build_scope_string
        scopes = _build_scope_string(["drive", "nonexistent"])
        assert "drive" in scopes
        assert "nonexistent" not in scopes

    def test_empty_scopes(self):
        from integrations.google_workspace.router import _build_scope_string
        scopes = _build_scope_string([])
        # Should still have openid + email
        assert "openid" in scopes


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_scope_map_completeness(self):
        from integrations.google_workspace.config import SCOPE_MAP, ALL_SERVICES
        # All services should be in the scope map
        for svc in ALL_SERVICES:
            assert svc in SCOPE_MAP

    def test_service_aliases(self):
        from integrations.google_workspace.config import SERVICE_ALIASES
        assert SERVICE_ALIASES["wf"] == "workflow"
        assert SERVICE_ALIASES["reports"] == "admin-reports"
