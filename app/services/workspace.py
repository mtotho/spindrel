"""Workspace service — unified execution layer wrapping sandbox + host_exec."""
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.agent.bots import (
    BotSandboxConfig,
    HostExecConfig,
    HostExecCommandEntry,
    WorkspaceConfig,
)
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    duration_ms: int
    workspace_type: str  # "docker" | "host"


class WorkspaceError(Exception):
    pass


class WorkspaceService:
    def get_workspace_root(self, bot_id: str) -> str:
        """Return the host-side workspace path for a bot."""
        base = os.path.expanduser(settings.WORKSPACE_BASE_DIR)
        return os.path.join(base, bot_id)

    def ensure_host_dir(self, bot_id: str) -> str:
        """Create the workspace directory on the host. Returns the path."""
        root = self.get_workspace_root(bot_id)
        os.makedirs(root, exist_ok=True)
        return root

    async def exec(
        self,
        bot_id: str,
        command: str,
        workspace: WorkspaceConfig,
        working_dir: str = "",
    ) -> ExecResult:
        """Execute a command in the workspace, routing to Docker or host."""
        if not workspace.enabled:
            raise WorkspaceError("Workspace is not enabled for this bot.")

        if workspace.type == "docker":
            return await self._exec_docker(bot_id, command, workspace, working_dir)
        elif workspace.type == "host":
            return await self._exec_host(bot_id, command, workspace, working_dir)
        else:
            raise WorkspaceError(f"Unknown workspace type: {workspace.type!r}")

    async def _exec_docker(
        self,
        bot_id: str,
        command: str,
        workspace: WorkspaceConfig,
        working_dir: str,
    ) -> ExecResult:
        """Execute via the sandbox service's bot-local container."""
        from app.services.sandbox import sandbox_service

        host_root = self.ensure_host_dir(bot_id)

        # Build a BotSandboxConfig from the workspace docker config
        docker = workspace.docker
        # Ensure the workspace volume mount is included
        workspace_mount = {
            "host_path": host_root,
            "container_path": "/workspace",
            "mode": "rw",
        }
        mounts = list(docker.mounts or [])
        # Don't add duplicate workspace mount
        if not any(m.get("container_path") == "/workspace" for m in mounts):
            mounts.insert(0, workspace_mount)

        sandbox_config = BotSandboxConfig(
            enabled=True,
            unrestricted=True,
            image=docker.image,
            network=docker.network,
            env=docker.env,
            ports=docker.ports,
            mounts=mounts,
            user=docker.user,
        )

        # Default working_dir to /workspace inside the container
        if not working_dir:
            working_dir = "/workspace"
        # Prefix the command with cd to working_dir if it's not /workspace
        if working_dir != "/workspace":
            command = f"cd {working_dir} && {command}"
        elif working_dir == "/workspace":
            command = f"cd /workspace && {command}"

        timeout = workspace.timeout
        max_bytes = workspace.max_output_bytes

        result = await sandbox_service.exec_bot_local(
            bot_id, command, sandbox_config,
            timeout=timeout,
            max_bytes=max_bytes,
        )
        return ExecResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            truncated=result.truncated,
            duration_ms=result.duration_ms,
            workspace_type="docker",
        )

    async def _exec_host(
        self,
        bot_id: str,
        command: str,
        workspace: WorkspaceConfig,
        working_dir: str,
    ) -> ExecResult:
        """Execute on the host via the host_exec service."""
        from app.services.host_exec import host_exec_service

        host_cfg = workspace.host
        root = host_cfg.root or self.get_workspace_root(bot_id)
        self.ensure_host_dir(bot_id) if not host_cfg.root else None

        # Default working_dir to workspace root
        if not working_dir:
            working_dir = root

        # Build HostExecConfig from workspace host config
        exec_config = HostExecConfig(
            enabled=True,
            dry_run=False,
            working_dirs=[root],  # Restrict to workspace root
            commands=host_cfg.commands,
            blocked_patterns=host_cfg.blocked_patterns,
            env_passthrough=host_cfg.env_passthrough,
            timeout=workspace.timeout,
            max_output_bytes=workspace.max_output_bytes,
        )

        result = await host_exec_service.run(command, working_dir, exec_config)
        return ExecResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            truncated=result.truncated,
            duration_ms=result.duration_ms,
            workspace_type="host",
        )

    def translate_path(self, bot_id: str, bot_path: str, workspace: WorkspaceConfig) -> str:
        """Map a bot-side path to a host-side path.

        Docker: /workspace/foo → ~/.agent-workspaces/<bot_id>/foo
        Host: identity (path is already on host)
        """
        if workspace.type == "docker":
            host_root = self.get_workspace_root(bot_id)
            if bot_path.startswith("/workspace/"):
                return os.path.join(host_root, bot_path[len("/workspace/"):])
            elif bot_path == "/workspace":
                return host_root
            return bot_path
        return bot_path

    async def recreate(self, bot_id: str) -> None:
        """Destroy and recreate the Docker container for a workspace."""
        from app.services.sandbox import sandbox_service
        await sandbox_service.recreate_bot_local(bot_id)


workspace_service = WorkspaceService()
