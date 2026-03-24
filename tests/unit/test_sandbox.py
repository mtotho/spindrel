"""Unit tests for sandbox service — config drift detection and docker arg building."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.sandbox import _build_docker_run_args


# ---------------------------------------------------------------------------
# _build_docker_run_args — port mapping
# ---------------------------------------------------------------------------


class TestBuildDockerRunArgs:
    def test_no_ports(self):
        args = _build_docker_run_args(
            image="python:3.12-slim",
            container_name="test",
            network_mode="none",
            read_only_root=False,
            create_options={},
            env={},
            labels={},
            mount_specs=[],
            port_mappings=[],
        )
        assert "-p" not in args

    def test_single_port_mapping(self):
        args = _build_docker_run_args(
            image="python:3.12-slim",
            container_name="test",
            network_mode="bridge",
            read_only_root=False,
            create_options={},
            env={},
            labels={},
            mount_specs=[],
            port_mappings=[{"host_port": 1388, "container_port": 80}],
        )
        idx = args.index("-p")
        assert args[idx + 1] == "1388:80"

    def test_multiple_port_mappings(self):
        args = _build_docker_run_args(
            image="python:3.12-slim",
            container_name="test",
            network_mode="bridge",
            read_only_root=False,
            create_options={},
            env={},
            labels={},
            mount_specs=[],
            port_mappings=[
                {"host_port": 8080, "container_port": 80},
                {"host_port": 4443, "container_port": 443},
            ],
        )
        port_args = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
        assert port_args == ["8080:80", "4443:443"]

    def test_udp_protocol(self):
        args = _build_docker_run_args(
            image="python:3.12-slim",
            container_name="test",
            network_mode="bridge",
            read_only_root=False,
            create_options={},
            env={},
            labels={},
            mount_specs=[],
            port_mappings=[{"host_port": 5353, "container_port": 53, "protocol": "udp"}],
        )
        idx = args.index("-p")
        assert args[idx + 1] == "5353:53/udp"

    def test_auto_assign_host_port(self):
        """host_port=0 means Docker auto-assigns."""
        args = _build_docker_run_args(
            image="python:3.12-slim",
            container_name="test",
            network_mode="bridge",
            read_only_root=False,
            create_options={},
            env={},
            labels={},
            mount_specs=[],
            port_mappings=[{"host_port": 0, "container_port": 80}],
        )
        idx = args.index("-p")
        assert args[idx + 1] == "80"


# ---------------------------------------------------------------------------
# _ensure_bot_local_profile — config change detection
# ---------------------------------------------------------------------------


class TestEnsureBotLocalProfileConfigChange:
    """Test that _ensure_bot_local_profile returns config_changed correctly."""

    @pytest.fixture
    def sandbox_service(self):
        from app.services.sandbox import SandboxService
        return SandboxService()

    @pytest.fixture
    def fake_config(self):
        from app.agent.bots import BotSandboxConfig
        return BotSandboxConfig(
            enabled=True,
            image="python:3.12-slim",
            network="none",
            ports=[{"host_port": 1388, "container_port": 80}],
        )

    @pytest.mark.asyncio
    async def test_new_profile_returns_not_changed(self, sandbox_service, fake_config):
        """First creation is not a 'change' — there's no existing container to recreate."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)  # no existing profile
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.sandbox.async_session", return_value=mock_session_ctx):
            profile_uuid, changed = await sandbox_service._ensure_bot_local_profile("test-bot", fake_config)

        assert isinstance(profile_uuid, uuid.UUID)
        assert changed is False

    @pytest.mark.asyncio
    async def test_unchanged_profile_returns_not_changed(self, sandbox_service, fake_config):
        """Existing profile with same config → no change."""
        existing = MagicMock()
        existing.image = "python:3.12-slim"
        existing.network_mode = "none"
        existing.env = {}
        existing.mount_specs = []
        existing.port_mappings = [{"host_port": 1388, "container_port": 80}]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=existing)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.sandbox.async_session", return_value=mock_session_ctx):
            _, changed = await sandbox_service._ensure_bot_local_profile("test-bot", fake_config)

        assert changed is False
        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_port_change_returns_changed(self, sandbox_service, fake_config):
        """Adding ports to a profile that had none → changed."""
        existing = MagicMock()
        existing.image = "python:3.12-slim"
        existing.network_mode = "none"
        existing.env = {}
        existing.mount_specs = []
        existing.port_mappings = []  # was empty, config has ports

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=existing)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.sandbox.async_session", return_value=mock_session_ctx):
            _, changed = await sandbox_service._ensure_bot_local_profile("test-bot", fake_config)

        assert changed is True
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_network_change_returns_changed(self, sandbox_service):
        """Changing network mode → changed."""
        from app.agent.bots import BotSandboxConfig
        config = BotSandboxConfig(enabled=True, network="bridge")

        existing = MagicMock()
        existing.image = "python:3.12-slim"
        existing.network_mode = "none"  # was none, config wants bridge
        existing.env = {}
        existing.mount_specs = []
        existing.port_mappings = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=existing)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session_ctx)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.get = mock_db.get
        mock_session_ctx.commit = mock_db.commit

        with patch("app.services.sandbox.async_session", return_value=mock_session_ctx):
            _, changed = await sandbox_service._ensure_bot_local_profile("test-bot", config)

        assert changed is True

    @pytest.mark.asyncio
    async def test_image_change_returns_changed(self, sandbox_service):
        """Changing image → changed."""
        from app.agent.bots import BotSandboxConfig
        config = BotSandboxConfig(enabled=True, image="node:20-slim")

        existing = MagicMock()
        existing.image = "python:3.12-slim"
        existing.network_mode = "none"
        existing.env = {}
        existing.mount_specs = []
        existing.port_mappings = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=existing)
        mock_db.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.sandbox.async_session", return_value=mock_session_ctx):
            _, changed = await sandbox_service._ensure_bot_local_profile("test-bot", config)

        assert changed is True


# ---------------------------------------------------------------------------
# ensure_bot_local — config drift triggers recreation
# ---------------------------------------------------------------------------


class TestEnsureBotLocalConfigDrift:
    """Test that ensure_bot_local recreates containers when config changes."""

    @pytest.fixture
    def sandbox_service(self):
        from app.services.sandbox import SandboxService
        return SandboxService()

    @pytest.fixture
    def config_with_ports(self):
        from app.agent.bots import BotSandboxConfig
        return BotSandboxConfig(
            enabled=True,
            image="python:3.12-slim",
            network="bridge",
            ports=[{"host_port": 1388, "container_port": 80}],
        )

    @pytest.mark.asyncio
    async def test_config_change_triggers_recreate(self, sandbox_service, config_with_ports):
        """When config_changed=True and container is alive, it should stop+rm+recreate."""
        fake_instance = MagicMock()
        fake_instance.id = uuid.uuid4()
        fake_instance.container_id = "abc123"
        fake_instance.status = "running"
        fake_instance.image_id = "sha256:aaa"
        fake_instance.port_mappings = []

        new_instance = MagicMock()
        new_instance.id = uuid.uuid4()
        new_instance.container_id = None
        new_instance.status = "creating"

        # Mock the profile method to return config_changed=True
        sandbox_service._ensure_bot_local_profile = AsyncMock(
            return_value=(uuid.uuid4(), True)
        )
        sandbox_service._get_container_id_by_name = AsyncMock(return_value="abc123")
        sandbox_service._get_image_id = AsyncMock(return_value="sha256:aaa")
        sandbox_service._docker_stop = AsyncMock()
        sandbox_service._docker_rm = AsyncMock()
        sandbox_service._docker_run = AsyncMock(return_value=("newcontainer123", None))

        # Track calls across two async_session() contexts
        # async_session() is a sync call returning an async context manager
        call_count = 0

        def mock_session_factory():
            nonlocal call_count
            call_count += 1
            db = AsyncMock()

            if call_count == 1:
                # First session: finds existing instance, deletes it, creates new row
                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = fake_instance
                db.execute = AsyncMock(return_value=mock_result)
                db.delete = AsyncMock()
                db.commit = AsyncMock()
                db.add = MagicMock()
                db.refresh = AsyncMock()
            else:
                # Second session: updates the new instance after docker run
                db.get = AsyncMock(return_value=new_instance)
                db.commit = AsyncMock()
                db.refresh = AsyncMock()

            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=db)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        with patch("app.services.sandbox.async_session", side_effect=mock_session_factory):
            await sandbox_service.ensure_bot_local("test-bot", config_with_ports)

        # Should have stopped and removed the old container
        sandbox_service._docker_stop.assert_awaited_once_with("abc123")
        sandbox_service._docker_rm.assert_awaited_once_with("abc123")
        # Should have created a new one
        sandbox_service._docker_run.assert_awaited_once()
        run_args = sandbox_service._docker_run.call_args[0][0]
        assert "-p" in run_args
        idx = run_args.index("-p")
        assert run_args[idx + 1] == "1388:80"

    @pytest.mark.asyncio
    async def test_no_config_change_skips_recreate(self, sandbox_service, config_with_ports):
        """When config_changed=False and container is alive with correct image, return as-is."""
        fake_instance = MagicMock()
        fake_instance.id = uuid.uuid4()
        fake_instance.container_id = "abc123"
        fake_instance.status = "running"
        fake_instance.image_id = "sha256:aaa"

        sandbox_service._ensure_bot_local_profile = AsyncMock(
            return_value=(uuid.uuid4(), False)
        )
        sandbox_service._get_container_id_by_name = AsyncMock(return_value="abc123")
        sandbox_service._get_image_id = AsyncMock(return_value="sha256:aaa")
        sandbox_service._docker_stop = AsyncMock()
        sandbox_service._docker_rm = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = fake_instance
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.sandbox.async_session", return_value=mock_session_ctx):
            result = await sandbox_service.ensure_bot_local("test-bot", config_with_ports)

        assert result is fake_instance
        sandbox_service._docker_stop.assert_not_awaited()
        sandbox_service._docker_rm.assert_not_awaited()
