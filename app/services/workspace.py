"""Workspace service — unified execution layer wrapping shared workspaces + host_exec."""
import logging
import os
from dataclasses import dataclass
from typing import Callable

from app.agent.bots import (
    BotConfig,
    HostExecConfig,
    WorkspaceConfig,
)
from app.config import settings
from app.services.paths import local_workspace_base

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    duration_ms: int
    workspace_type: str  # "host" | "shared"


class WorkspaceError(Exception):
    pass


class WorkspaceService:
    def get_workspace_root(self, bot_id: str, bot: BotConfig | None = None) -> str:
        """Return the host-side workspace path for a bot."""
        if bot and bot.shared_workspace_id:
            from app.services.shared_workspace import shared_workspace_service
            sw_root = shared_workspace_service.get_host_root(bot.shared_workspace_id)
            return os.path.join(sw_root, "bots", bot_id)
        base = local_workspace_base()
        return os.path.join(base, bot_id)

    def ensure_host_dir(self, bot_id: str, bot: BotConfig | None = None) -> str:
        """Create the workspace directory on the host. Returns the path."""
        if bot and bot.shared_workspace_id:
            from app.services.shared_workspace import shared_workspace_service
            shared_workspace_service.ensure_host_dirs(bot.shared_workspace_id)
        root = self.get_workspace_root(bot_id, bot)
        os.makedirs(root, exist_ok=True)
        # Convention: every bot gets a knowledge-base/ folder that is auto-indexed,
        # searchable via search_bot_knowledge, and eligible for implicit retrieval.
        os.makedirs(os.path.join(root, "knowledge-base"), exist_ok=True)
        return root

    def get_bot_knowledge_base_root(self, bot: BotConfig) -> str:
        """Returns the host path for this bot's knowledge-base/ folder."""
        return os.path.join(self.get_workspace_root(bot.id, bot), "knowledge-base")

    def get_bot_knowledge_base_index_prefix(self, bot: BotConfig) -> str:
        """Returns the file_path prefix used by filesystem_chunks for bot KB content.

        For shared-workspace bots files live under bots/{id}/knowledge-base/
        (relative to the shared workspace root).  For standalone bots the root
        is the bot's own workspace, so the prefix is just knowledge-base/.
        """
        if bot.shared_workspace_id:
            return f"bots/{bot.id}/knowledge-base"
        return "knowledge-base"

    async def exec(
        self,
        bot_id: str,
        command: str,
        workspace: WorkspaceConfig,
        working_dir: str = "",
        bot: BotConfig | None = None,
        extra_env: dict[str, str] | None = None,
        redact_output: Callable[[str], str] | None = None,
    ) -> ExecResult:
        """Execute a command in the workspace via subprocess."""
        if bot and bot.shared_workspace_id:
            return await self._exec_shared(bot, command, working_dir, extra_env=extra_env, redact_output=redact_output)

        if not workspace.enabled:
            raise WorkspaceError("Workspace is not enabled for this bot.")

        # All workspace types execute in the same process environment —
        # the "docker" vs "host" distinction is legacy.
        return await self._exec_host(bot_id, command, workspace, working_dir, extra_env=extra_env, redact_output=redact_output)

    async def _exec_shared(
        self,
        bot: BotConfig,
        command: str,
        working_dir: str,
        extra_env: dict[str, str] | None = None,
        redact_output: Callable[[str], str] | None = None,
    ) -> ExecResult:
        """Execute via subprocess in the shared workspace directory."""
        from app.services.shared_workspace import shared_workspace_service
        from app.db.engine import async_session
        from app.db.models import SharedWorkspace

        async with async_session() as db:
            ws = await db.get(SharedWorkspace, bot.shared_workspace_id)
        if ws is None:
            raise WorkspaceError(f"Shared workspace {bot.shared_workspace_id} not found")

        result = await shared_workspace_service.exec(
            ws, bot.id, command, working_dir=working_dir,
            timeout=bot.workspace.timeout,
            max_bytes=bot.workspace.max_output_bytes,
            extra_env=extra_env,
            redact_output=redact_output,
        )
        return ExecResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            truncated=result.truncated,
            duration_ms=result.duration_ms,
            workspace_type="shared",
        )

    async def _exec_host(
        self,
        bot_id: str,
        command: str,
        workspace: WorkspaceConfig,
        working_dir: str,
        extra_env: dict[str, str] | None = None,
        redact_output: Callable[[str], str] | None = None,
    ) -> ExecResult:
        """Execute on the host via the host_exec service."""
        from app.services.host_exec import host_exec_service

        host_cfg = workspace.host
        root = host_cfg.root or self.get_workspace_root(bot_id)
        self.ensure_host_dir(bot_id) if not host_cfg.root else None

        if not working_dir:
            working_dir = root

        exec_config = HostExecConfig(
            enabled=True,
            dry_run=False,
            working_dirs=[root],
            commands=host_cfg.commands,
            blocked_patterns=host_cfg.blocked_patterns,
            env_passthrough=host_cfg.env_passthrough,
            timeout=workspace.timeout,
            max_output_bytes=workspace.max_output_bytes,
        )

        result = await host_exec_service.run(command, working_dir, exec_config, extra_env=extra_env)
        stdout = result.stdout
        stderr = result.stderr
        if redact_output is not None:
            stdout = redact_output(stdout)
            stderr = redact_output(stderr)
        return ExecResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=result.exit_code,
            truncated=result.truncated,
            duration_ms=result.duration_ms,
            workspace_type="host",
        )

    def translate_path(self, bot_id: str, bot_path: str, workspace: WorkspaceConfig, bot: BotConfig | None = None) -> str:
        """Map a bot-side path to a host-side path.

        Handles legacy /workspace/ paths from before the container collapse.
        """
        if bot and bot.shared_workspace_id:
            from app.services.shared_workspace import shared_workspace_service
            return shared_workspace_service.translate_path(bot.shared_workspace_id, bot_path)
        host_root = self.get_workspace_root(bot_id)
        if bot_path.startswith("/workspace/"):
            return os.path.join(host_root, bot_path[len("/workspace/"):])
        elif bot_path == "/workspace":
            return host_root
        return bot_path


workspace_service = WorkspaceService()
