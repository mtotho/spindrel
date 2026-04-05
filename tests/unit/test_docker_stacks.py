"""Unit tests for Docker Compose stack management — YAML sanitization,
ownership filtering, service methods with mocked Docker CLI."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.docker_stacks import (
    StackService,
    StackError,
    StackValidationError,
    StackLimitError,
    validate_compose,
    PROJECT_PREFIX,
    _image_matches,
    _stacks_base_dir,
)


# ---------------------------------------------------------------------------
# validate_compose — YAML sanitization
# ---------------------------------------------------------------------------

class TestValidateCompose:
    """Tests for Compose YAML validation and sanitization."""

    def test_valid_minimal_definition(self):
        definition = """
services:
  redis:
    image: redis:7
"""
        result = validate_compose(definition)
        assert "services" in result
        assert "redis" in result["services"]
        # Resource limits should be injected
        deploy = result["services"]["redis"]["deploy"]
        assert deploy["resources"]["limits"]["memory"] == "512m"

    def test_invalid_yaml_raises(self):
        with pytest.raises(StackValidationError, match="Invalid YAML"):
            validate_compose("{{not yaml}}: [")

    def test_not_a_mapping_raises(self):
        with pytest.raises(StackValidationError, match="must be a YAML mapping"):
            validate_compose("- just a list")

    def test_no_services_raises(self):
        with pytest.raises(StackValidationError, match="must have a 'services' section"):
            validate_compose("version: '3'\nnetworks:\n  default:")

    def test_privileged_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    privileged: true
"""
        with pytest.raises(StackValidationError, match="'privileged' is not allowed"):
            validate_compose(definition)

    def test_cap_add_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    cap_add:
      - SYS_ADMIN
"""
        with pytest.raises(StackValidationError, match="'cap_add' is not allowed"):
            validate_compose(definition)

    def test_devices_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    devices:
      - /dev/sda
"""
        with pytest.raises(StackValidationError, match="'devices' is not allowed"):
            validate_compose(definition)

    def test_host_network_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    network_mode: host
"""
        with pytest.raises(StackValidationError, match="network_mode 'host' is not allowed"):
            validate_compose(definition)

    def test_pid_host_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    pid: host
"""
        with pytest.raises(StackValidationError, match="'pid' is not allowed"):
            validate_compose(definition)

    def test_ipc_host_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    ipc: host
"""
        with pytest.raises(StackValidationError, match="'ipc' is not allowed"):
            validate_compose(definition)

    def test_security_opt_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    security_opt:
      - apparmor:unconfined
"""
        with pytest.raises(StackValidationError, match="'security_opt' is not allowed"):
            validate_compose(definition)

    def test_sysctls_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    sysctls:
      net.core.somaxconn: 1024
"""
        with pytest.raises(StackValidationError, match="'sysctls' is not allowed"):
            validate_compose(definition)

    def test_docker_socket_volume_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
"""
        with pytest.raises(StackValidationError, match="volume mount.*not allowed"):
            validate_compose(definition)

    def test_etc_volume_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    volumes:
      - /etc/passwd:/etc/passwd
"""
        with pytest.raises(StackValidationError, match="volume mount.*not allowed"):
            validate_compose(definition)

    def test_proc_volume_blocked(self):
        definition = """
services:
  evil:
    image: alpine
    volumes:
      - /proc:/host-proc
"""
        with pytest.raises(StackValidationError, match="volume mount.*not allowed"):
            validate_compose(definition)

    def test_restart_always_replaced(self):
        definition = """
services:
  web:
    image: nginx
    restart: always
"""
        result = validate_compose(definition)
        assert result["services"]["web"]["restart"] == "unless-stopped"

    def test_restart_unless_stopped_preserved(self):
        definition = """
services:
  web:
    image: nginx
    restart: unless-stopped
"""
        result = validate_compose(definition)
        assert result["services"]["web"]["restart"] == "unless-stopped"

    def test_labels_injected(self):
        definition = """
services:
  web:
    image: nginx
"""
        result = validate_compose(definition)
        assert result["services"]["web"]["labels"]["spindrel.managed"] == "true"

    def test_labels_list_format_converted(self):
        definition = """
services:
  web:
    image: nginx
    labels:
      - com.example.env=production
"""
        result = validate_compose(definition)
        labels = result["services"]["web"]["labels"]
        assert isinstance(labels, dict)
        assert labels["com.example.env"] == "production"
        assert labels["spindrel.managed"] == "true"

    def test_resource_limits_injected_default(self):
        definition = """
services:
  web:
    image: nginx
"""
        result = validate_compose(definition)
        limits = result["services"]["web"]["deploy"]["resources"]["limits"]
        assert "cpus" in limits
        assert "memory" in limits

    def test_existing_resource_limits_preserved(self):
        definition = """
services:
  web:
    image: nginx
    deploy:
      resources:
        limits:
          cpus: "0.5"
          memory: 256m
"""
        result = validate_compose(definition)
        limits = result["services"]["web"]["deploy"]["resources"]["limits"]
        assert limits["cpus"] == "0.5"
        assert limits["memory"] == "256m"

    def test_image_allowlist_blocks_unlisted(self):
        definition = """
services:
  db:
    image: mysql:8
"""
        with pytest.raises(StackValidationError, match="not in allowed list"):
            validate_compose(definition, allowed_images=["postgres:16", "redis:7"])

    def test_image_allowlist_allows_listed(self):
        definition = """
services:
  db:
    image: postgres:16
"""
        result = validate_compose(definition, allowed_images=["postgres:16", "redis:7"])
        assert result["services"]["db"]["image"] == "postgres:16"

    def test_image_allowlist_name_only_matches_any_tag(self):
        definition = """
services:
  db:
    image: postgres:15
"""
        result = validate_compose(definition, allowed_images=["postgres"])
        assert result["services"]["db"]["image"] == "postgres:15"

    def test_multiple_services_all_validated(self):
        definition = """
services:
  web:
    image: nginx
  db:
    image: postgres:16
  cache:
    image: redis:7
"""
        result = validate_compose(definition)
        assert len(result["services"]) == 3
        for svc in result["services"].values():
            assert "deploy" in svc
            assert svc["labels"]["spindrel.managed"] == "true"

    def test_safe_volumes_allowed(self):
        definition = """
services:
  db:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data
      - /tmp/mydata:/data
volumes:
  pgdata:
"""
        result = validate_compose(definition)
        assert len(result["services"]["db"]["volumes"]) == 2


# ---------------------------------------------------------------------------
# _image_matches
# ---------------------------------------------------------------------------

class TestImageMatches:

    def test_exact_match(self):
        assert _image_matches("postgres:16", "postgres:16") is True

    def test_name_only_pattern_matches_any_tag(self):
        assert _image_matches("postgres:15", "postgres") is True

    def test_different_name_no_match(self):
        assert _image_matches("mysql:8", "postgres:16") is False

    def test_same_name_different_tag_with_tag_pattern(self):
        assert _image_matches("postgres:15", "postgres:16") is False

    def test_no_tag_matches_no_tag(self):
        assert _image_matches("redis", "redis") is True


# ---------------------------------------------------------------------------
# StackService — unit tests with mocked DB and Docker CLI
# ---------------------------------------------------------------------------

class TestStackService:
    """Tests for StackService methods with mocked dependencies."""

    @pytest.fixture
    def service(self):
        return StackService()

    @pytest.fixture
    def mock_stack(self):
        stack = MagicMock()
        stack.id = uuid.uuid4()
        stack.name = "test-stack"
        stack.project_name = f"{PROJECT_PREFIX}abc123def456"
        stack.compose_definition = "services:\n  redis:\n    image: redis:7\n"
        stack.status = "running"
        stack.created_by_bot = "test-bot"
        stack.channel_id = None
        stack.network_name = f"{PROJECT_PREFIX}abc123def456_default"
        stack.container_ids = {"redis": "abc123"}
        stack.exposed_ports = {}
        stack.error_message = None
        return stack

    @pytest.mark.asyncio
    async def test_compose_cmd_rejects_invalid_prefix(self, service, mock_stack):
        mock_stack.project_name = "evil-project"
        with pytest.raises(StackError, match="Invalid project name prefix"):
            await service._compose_cmd(mock_stack, ["ps"])

    @pytest.mark.asyncio
    async def test_compose_cmd_accepts_valid_prefix(self, service, mock_stack):
        """Valid prefix doesn't raise prefix error (will fail on actual docker call)."""
        assert mock_stack.project_name.startswith(PROJECT_PREFIX)
        # The actual docker command will fail since docker isn't available in test,
        # but the prefix check should pass
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"")
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc
            result = await service._compose_cmd(mock_stack, ["ps"])
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_exec_in_service_rejects_stopped_stack(self, service, mock_stack):
        mock_stack.status = "stopped"
        with pytest.raises(StackError, match="must be running"):
            await service.exec_in_service(mock_stack, "redis", "echo hello")

    @pytest.mark.asyncio
    async def test_get_status_returns_empty_on_failure(self, service, mock_stack):
        with patch.object(service, "_compose_cmd") as mock_cmd:
            mock_cmd.return_value = MagicMock(exit_code=1, stdout="", stderr="error")
            result = await service.get_status(mock_stack)
            assert result == []

    @pytest.mark.asyncio
    async def test_get_status_parses_json_output(self, service, mock_stack):
        json_output = json.dumps({
            "Service": "redis",
            "State": "running",
            "Health": "healthy",
            "Publishers": [
                {"PublishedPort": 6379, "TargetPort": 6379, "Protocol": "tcp"}
            ],
        })
        with patch.object(service, "_compose_cmd") as mock_cmd:
            mock_cmd.return_value = MagicMock(exit_code=0, stdout=json_output)
            result = await service.get_status(mock_stack)
            assert len(result) == 1
            assert result[0].name == "redis"
            assert result[0].state == "running"
            assert result[0].health == "healthy"
            assert len(result[0].ports) == 1

    @pytest.mark.asyncio
    async def test_get_logs_delegates_to_compose_cmd(self, service, mock_stack):
        with patch.object(service, "_compose_cmd") as mock_cmd:
            mock_cmd.return_value = MagicMock(exit_code=0, stdout="log line 1\nlog line 2\n", stderr="")
            logs = await service.get_logs(mock_stack, service="redis", tail=50)
            assert "log line 1" in logs
            mock_cmd.assert_called_once()
            args = mock_cmd.call_args[0][1]
            assert "logs" in args
            assert "redis" in args
            assert "50" in args

    @pytest.mark.asyncio
    async def test_update_definition_rejects_running_stack(self, service, mock_stack):
        mock_stack.status = "running"
        with pytest.raises(StackError, match="must be stopped"):
            await service.update_definition(mock_stack, "services:\n  web:\n    image: nginx\n")

    @pytest.mark.asyncio
    async def test_list_for_bot_with_none_channel_id(self, service):
        """When channel_id is None, list_for_bot should NOT match other bots' channel-less stacks."""
        from sqlalchemy import or_

        with patch("app.services.docker_stacks.async_session") as mock_session_ctx:
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db.execute.return_value = mock_result

            await service.list_for_bot("test-bot", channel_id=None)

            # Verify the query was called — extract the where clause
            call_args = mock_db.execute.call_args[0][0]
            # The compiled SQL should only filter by created_by_bot, not include
            # an IS NULL clause that would match other bots' channel-less stacks
            compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
            assert "channel_id IS NULL" not in compiled

    @pytest.mark.asyncio
    async def test_list_for_bot_with_real_channel_id(self, service):
        """When channel_id is provided, list_for_bot should include channel filter."""
        test_channel = uuid.uuid4()

        with patch("app.services.docker_stacks.async_session") as mock_session_ctx:
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db.execute.return_value = mock_result

            await service.list_for_bot("test-bot", channel_id=test_channel)

            # With a real channel_id, the query should include an OR for channel matching
            call_args = mock_db.execute.call_args[0][0]
            compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
            assert "channel_id" in compiled

    @pytest.mark.asyncio
    async def test_create_enforces_stack_limit(self, service):
        with patch("app.services.docker_stacks.async_session") as mock_session_ctx:
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # Mock count query to return limit
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = 5
            mock_db.execute.return_value = mock_result

            with pytest.raises(StackLimitError, match="limit reached"):
                await service.create(
                    bot_id="test-bot",
                    name="overflow",
                    compose_definition="services:\n  redis:\n    image: redis:7\n",
                    max_stacks=5,
                )


# ---------------------------------------------------------------------------
# Tool function — integration-style tests
# ---------------------------------------------------------------------------

class TestManageDockerStackTool:
    """Tests for the manage_docker_stack tool function."""

    @pytest.mark.asyncio
    async def test_disabled_returns_error(self):
        from app.tools.local.docker_stacks import manage_docker_stack
        with patch("app.config.settings") as mock_settings:
            mock_settings.DOCKER_STACKS_ENABLED = False
            result = json.loads(await manage_docker_stack(action="list"))
            assert "error" in result
            assert "not enabled" in result["error"]

    @pytest.mark.asyncio
    async def test_bot_disabled_returns_error(self):
        from app.tools.local.docker_stacks import manage_docker_stack
        from app.agent.bots import DockerStackConfig

        mock_bot = MagicMock()
        mock_bot.docker_stacks = DockerStackConfig(enabled=False)

        with patch("app.config.settings") as mock_settings, \
             patch("app.agent.context.current_bot_id") as mock_bid, \
             patch("app.agent.context.current_channel_id") as mock_cid, \
             patch("app.agent.bots.get_bot", return_value=mock_bot):
            mock_settings.DOCKER_STACKS_ENABLED = True
            mock_bid.get.return_value = "test-bot"
            mock_cid.get.return_value = None
            result = json.loads(await manage_docker_stack(action="list"))
            assert "error" in result
            assert "not enabled for bot" in result["error"]

    @pytest.mark.asyncio
    async def test_create_missing_name_returns_error(self):
        from app.tools.local.docker_stacks import manage_docker_stack
        from app.agent.bots import DockerStackConfig

        mock_bot = MagicMock()
        mock_bot.docker_stacks = DockerStackConfig(enabled=True)

        with patch("app.config.settings") as mock_settings, \
             patch("app.agent.context.current_bot_id") as mock_bid, \
             patch("app.agent.context.current_channel_id") as mock_cid, \
             patch("app.agent.bots.get_bot", return_value=mock_bot):
            mock_settings.DOCKER_STACKS_ENABLED = True
            mock_bid.get.return_value = "test-bot"
            mock_cid.get.return_value = None
            result = json.loads(await manage_docker_stack(action="create"))
            assert "error" in result
            assert "name is required" in result["error"]

    @pytest.mark.asyncio
    async def test_exec_missing_service_returns_error(self):
        from app.tools.local.docker_stacks import manage_docker_stack
        from app.agent.bots import DockerStackConfig

        mock_bot = MagicMock()
        mock_bot.docker_stacks = DockerStackConfig(enabled=True)
        mock_stack = MagicMock()
        mock_stack.created_by_bot = "test-bot"
        mock_stack.status = "running"

        mock_svc = AsyncMock()
        mock_svc.get_by_id.return_value = mock_stack

        with patch("app.config.settings") as mock_settings, \
             patch("app.agent.context.current_bot_id") as mock_bid, \
             patch("app.agent.context.current_channel_id") as mock_cid, \
             patch("app.agent.bots.get_bot", return_value=mock_bot), \
             patch("app.services.docker_stacks.stack_service", mock_svc):
            mock_settings.DOCKER_STACKS_ENABLED = True
            mock_bid.get.return_value = "test-bot"
            mock_cid.get.return_value = None
            result = json.loads(await manage_docker_stack(
                action="exec", stack_id=str(uuid.uuid4()),
            ))
            assert "error" in result
            assert "service is required" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        from app.tools.local.docker_stacks import manage_docker_stack
        from app.agent.bots import DockerStackConfig

        mock_bot = MagicMock()
        mock_bot.docker_stacks = DockerStackConfig(enabled=True)

        with patch("app.config.settings") as mock_settings, \
             patch("app.agent.context.current_bot_id") as mock_bid, \
             patch("app.agent.context.current_channel_id") as mock_cid, \
             patch("app.agent.bots.get_bot", return_value=mock_bot):
            mock_settings.DOCKER_STACKS_ENABLED = True
            mock_bid.get.return_value = "test-bot"
            mock_cid.get.return_value = None
            result = json.loads(await manage_docker_stack(action="nonexistent"))
            assert "error" in result
            assert "Unknown action" in result["error"]


# ---------------------------------------------------------------------------
# Integration stack features
# ---------------------------------------------------------------------------

class TestProjectPrefix:
    """Verify broadened prefix accepts both bot and integration stacks."""

    def test_prefix_is_spindrel(self):
        assert PROJECT_PREFIX == "spindrel-"

    def test_bot_stacks_still_match(self):
        """Old bot stack names (spindrel-stack-*) still start with the prefix."""
        assert "spindrel-stack-abc123".startswith(PROJECT_PREFIX)

    def test_integration_stacks_match(self):
        assert "spindrel-web-search".startswith(PROJECT_PREFIX)

    @pytest.mark.asyncio
    async def test_compose_cmd_accepts_integration_prefix(self):
        service = StackService()
        mock_stack = MagicMock()
        mock_stack.id = uuid.uuid4()
        mock_stack.project_name = "spindrel-web-search"
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b"", b"")
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc
            result = await service._compose_cmd(mock_stack, ["ps"])
            assert result.exit_code == 0


class TestDestroyGuard:
    """Integration stacks cannot be destroyed."""

    @pytest.mark.asyncio
    async def test_destroy_raises_for_integration_stack(self):
        service = StackService()
        mock_stack = MagicMock()
        mock_stack.source = "integration"
        mock_stack.network_name = None
        with pytest.raises(StackError, match="Integration stacks cannot be destroyed"):
            await service.destroy(mock_stack)

    @pytest.mark.asyncio
    async def test_destroy_allows_bot_stack(self):
        """Bot stacks can be destroyed (would proceed to docker compose down)."""
        service = StackService()
        mock_stack = MagicMock()
        mock_stack.id = uuid.uuid4()
        mock_stack.source = "bot"
        mock_stack.network_name = "test_default"
        mock_stack.project_name = "spindrel-stack-abc123"
        mock_stack.created_by_bot = "test-bot"
        # Mock the compose command + DB session to avoid real Docker calls
        with patch.object(service, "_compose_cmd") as mock_cmd, \
             patch.object(service, "_disconnect_workspace") as mock_disc, \
             patch("app.services.docker_stacks.async_session") as mock_session_ctx, \
             patch("os.path.exists", return_value=False):
            mock_cmd.return_value = MagicMock(exit_code=0)
            mock_disc.return_value = None
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_db.get.return_value = mock_stack
            await service.destroy(mock_stack)


class TestSyncIntegrationStack:
    """Tests for sync_integration_stack upsert behavior."""

    @pytest.mark.asyncio
    async def test_creates_new_integration_stack(self):
        service = StackService()
        compose_yaml = "services:\n  searxng:\n    image: searxng/searxng\n"

        with patch("app.services.docker_stacks.async_session") as mock_session_ctx, \
             patch.object(service, "_materialize") as mock_mat, \
             patch.object(service, "_materialize_file") as mock_mat_file:
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # No existing row
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = mock_result

            # db.add() is synchronous in SQLAlchemy — use MagicMock for it
            added_rows = []
            def capture_add(row):
                row.id = uuid.uuid4()
                added_rows.append(row)
            mock_db.add = MagicMock(side_effect=capture_add)

            result = await service.sync_integration_stack(
                integration_id="web_search",
                name="SearXNG + Playwright",
                compose_definition=compose_yaml,
                project_name="spindrel-web-search",
                description="Web search containers",
                connect_networks=["agent-server_default"],
                config_files={"config/searxng/settings.yml": "use_default_settings: true\n"},
            )

            # Verify row was created with correct fields
            assert len(added_rows) == 1
            row = added_rows[0]
            assert row.source == "integration"
            assert row.integration_id == "web_search"
            assert row.created_by_bot == "_integration"
            assert row.connect_networks == ["agent-server_default"]
            assert row.project_name == "spindrel-web-search"

            # Verify files materialized
            mock_mat.assert_called_once()
            mock_mat_file.assert_called_once_with(
                str(row.id),
                "config/searxng/settings.yml",
                "use_default_settings: true\n",
            )

    @pytest.mark.asyncio
    async def test_updates_existing_integration_stack(self):
        service = StackService()
        old_yaml = "services:\n  old:\n    image: old:1\n"
        new_yaml = "services:\n  new:\n    image: new:2\n"

        existing = MagicMock()
        existing.id = uuid.uuid4()
        existing.compose_definition = old_yaml
        existing.connect_networks = []
        existing.name = "Old Name"
        existing.description = "Old desc"
        existing.project_name = "spindrel-web-search"

        with patch("app.services.docker_stacks.async_session") as mock_session_ctx, \
             patch.object(service, "_materialize") as mock_mat:
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = existing
            mock_db.execute.return_value = mock_result

            await service.sync_integration_stack(
                integration_id="web_search",
                name="New Name",
                compose_definition=new_yaml,
                project_name="spindrel-web-search",
            )

            # Verify compose was updated
            assert existing.compose_definition == new_yaml
            assert existing.name == "New Name"


class TestStartNetworkConnect:
    """Test that start() calls _connect_network for connect_networks."""

    @pytest.mark.asyncio
    async def test_start_connects_extra_networks(self):
        service = StackService()
        mock_stack = MagicMock()
        mock_stack.id = uuid.uuid4()
        mock_stack.project_name = "spindrel-web-search"
        mock_stack.compose_definition = "services:\n  s:\n    image: x\n"
        mock_stack.status = "stopped"
        mock_stack.created_by_bot = "_integration"
        mock_stack.connect_networks = ["agent-server_default"]
        mock_stack.network_name = None

        with patch.object(service, "_compose_cmd") as mock_cmd, \
             patch.object(service, "_inspect_stack") as mock_inspect, \
             patch.object(service, "_materialize"), \
             patch.object(service, "_connect_workspace"), \
             patch.object(service, "_connect_network") as mock_cn, \
             patch.object(service, "_get") as mock_get, \
             patch("app.services.docker_stacks.async_session") as mock_session_ctx:
            mock_cmd.return_value = MagicMock(exit_code=0)
            mock_inspect.return_value = ({"searxng": "abc123", "playwright": "def456"}, {}, "spindrel-web-search_default")
            mock_get.return_value = mock_stack

            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await service.start(mock_stack)

            # Should connect each container to each connect_network
            assert mock_cn.call_count == 2
            calls = [c.args for c in mock_cn.call_args_list]
            assert ("agent-server_default", "abc123") in calls
            assert ("agent-server_default", "def456") in calls


class TestDiscoverDockerComposeStacks:
    """Tests for discover_docker_compose_stacks integration discovery."""

    def test_discovers_web_search(self):
        from integrations import discover_docker_compose_stacks
        results = discover_docker_compose_stacks()
        # web_search declares a docker_compose block
        web_search = [r for r in results if r["integration_id"] == "web_search"]
        assert len(web_search) == 1
        info = web_search[0]
        assert info["project_name"] == "spindrel-web-search"
        assert info["enabled_setting"] == "WEB_SEARCH_CONTAINERS"
        assert "agent-server_default" in info["connect_networks"]
        assert "config/searxng/settings.yml" in info["config_files"]
        assert info["compose_definition"]  # non-empty

    def test_config_files_loaded(self):
        from integrations import discover_docker_compose_stacks
        results = discover_docker_compose_stacks()
        web_search = [r for r in results if r["integration_id"] == "web_search"]
        assert len(web_search) == 1
        config_content = web_search[0]["config_files"].get("config/searxng/settings.yml", "")
        assert "use_default_settings" in config_content


class TestMaterializeFile:
    """Test the _materialize_file helper."""

    def test_creates_nested_dirs(self, tmp_path):
        service = StackService()
        stack_id = str(uuid.uuid4())
        # Temporarily override the stacks base dir
        with patch("app.services.docker_stacks._stack_dir", return_value=str(tmp_path / stack_id)):
            service._materialize_file(stack_id, "config/searxng/settings.yml", "test: true")
            target = tmp_path / stack_id / "config" / "searxng" / "settings.yml"
            assert target.exists()
            assert target.read_text() == "test: true"
