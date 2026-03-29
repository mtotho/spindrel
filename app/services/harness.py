"""External harness execution service — run CLI tools (claude, cursor, etc.) as subprocesses."""
import logging
import shlex
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

from app.config import settings
from app.services.paths import local_to_host

if TYPE_CHECKING:
    from app.agent.bots import BotConfig, BotSandboxConfig

logger = logging.getLogger(__name__)


class HarnessError(Exception):
    pass


class HarnessNotFoundError(HarnessError):
    pass


class HarnessAccessDeniedError(HarnessError):
    pass


class HarnessWorkingDirError(HarnessError):
    pass


@dataclass
class HarnessConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    working_directory: str = ""  # template string; may contain {working_directory}
    timeout: int = 300


@dataclass
class HarnessResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    duration_ms: int


class HarnessService:
    def __init__(self) -> None:
        self._configs: dict[str, HarnessConfig] = {}

    def load(self, path: str) -> None:
        """Parse harnesses.yaml and populate _configs."""
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("Failed to load harnesses config from %s: %s", path, exc)
            return

        for name, cfg in (data.get("harnesses") or {}).items():
            self._configs[name] = HarnessConfig(
                name=name,
                command=cfg.get("command", name),
                args=cfg.get("args", []),
                working_directory=cfg.get("working_directory", ""),
                timeout=cfg.get("timeout", 300),
            )
        logger.info("Loaded %d harness config(s): %s", len(self._configs), list(self._configs.keys()))

    def list_harnesses(self) -> list[str]:
        return list(self._configs.keys())

    def _substitute_harness_args(
        self,
        cfg: HarnessConfig,
        prompt: str,
        template_wd: str | None,
    ) -> list[str]:
        out: list[str] = []
        for arg in cfg.args:
            a = arg.replace("{prompt}", prompt)
            if template_wd:
                a = a.replace("{working_directory}", template_wd)
            out.append(a)
        return out

    async def run(
        self,
        harness_name: str,
        prompt: str,
        working_directory: str | None,
        bot: "BotConfig",
        *,
        sandbox_instance_id: uuid.UUID | None = None,
        extra_args: list[str] | None = None,
    ) -> HarnessResult:
        """Execute a harness on the host (subprocess) or inside a Docker sandbox (docker exec).

        When *sandbox_instance_id* is set, the same argv as harnesses.yaml is run via
        ``docker exec … sh -c 'cd … && command …'``. *working_directory* is then a path **inside
        the container** (e.g. ``/workspace``); host HARNESS_WORKING_DIR_ALLOWLIST does not apply.
        """
        if harness_name not in self._configs:
            raise HarnessNotFoundError(f"Harness {harness_name!r} not found in harnesses.yaml.")

        if bot.harness_access and harness_name not in bot.harness_access:
            raise HarnessAccessDeniedError(
                f"Bot {bot.id!r} does not have access to harness {harness_name!r}."
            )

        cfg = self._configs[harness_name]
        timeout = cfg.timeout

        if sandbox_instance_id is not None:
            return await self._run_in_sandbox(
                harness_name=harness_name,
                cfg=cfg,
                prompt=prompt,
                working_directory=working_directory,
                bot=bot,
                sandbox_instance_id=sandbox_instance_id,
                timeout=timeout,
                extra_args=extra_args,
            )

        # New workspace path — build a BotSandboxConfig from workspace.docker
        if bot.workspace.enabled and bot.workspace.type == "docker":
            sandbox_config = self._workspace_to_sandbox_config(bot)
            return await self._run_in_bot_sandbox(
                harness_name=harness_name,
                cfg=cfg,
                prompt=prompt,
                working_directory=working_directory,
                bot=bot,
                sandbox_config=sandbox_config,
                timeout=timeout,
                extra_args=extra_args,
            )

        # Legacy bot_sandbox path
        if bot.bot_sandbox.enabled:
            return await self._run_in_bot_sandbox(
                harness_name=harness_name,
                cfg=cfg,
                prompt=prompt,
                working_directory=working_directory,
                bot=bot,
                sandbox_config=bot.bot_sandbox,
                timeout=timeout,
                extra_args=extra_args,
            )

        raise HarnessError("Harness must be run in a sandbox. Enable workspace (docker) or bot_sandbox.")

    @staticmethod
    def _workspace_to_sandbox_config(bot: "BotConfig") -> "BotSandboxConfig":
        """Build a BotSandboxConfig from workspace.docker config.

        For shared workspace bots, mount the entire shared workspace root at /workspace
        so paths match the shared container (repos, common/, etc. are all accessible).
        For standalone bots, mount just the bot's workspace directory.
        """
        from app.agent.bots import BotSandboxConfig
        from app.services.workspace import workspace_service

        docker = bot.workspace.docker

        if bot.shared_workspace_id:
            from app.services.shared_workspace import shared_workspace_service
            host_root = shared_workspace_service.ensure_host_dirs(bot.shared_workspace_id)
        else:
            host_root = workspace_service.ensure_host_dir(bot.id, bot=bot)

        workspace_mount = {
            "host_path": local_to_host(host_root),
            "container_path": "/workspace",
            "mode": "rw",
        }
        mounts = list(docker.mounts or [])
        if not any(m.get("container_path") == "/workspace" for m in mounts):
            mounts.insert(0, workspace_mount)

        return BotSandboxConfig(
            enabled=True,
            unrestricted=True,
            image=docker.image,
            network=docker.network,
            env=docker.env,
            ports=docker.ports,
            mounts=mounts,
            user=docker.user,
        )

    async def _run_in_bot_sandbox(
        self,
        *,
        harness_name: str,
        cfg: HarnessConfig,
        prompt: str,
        working_directory: str | None,
        bot: "BotConfig",
        sandbox_config: "BotSandboxConfig",
        timeout: int,
        extra_args: list[str] | None = None,
    ) -> HarnessResult:
        """Run harness inside a bot-local sandbox container."""
        from app.services.sandbox import sandbox_service

        if not sandbox_config.image:
            raise HarnessError("Cannot run harness in bot sandbox: no image configured.")

        wd_container: str | None = None
        if working_directory:
            w = working_directory.strip()
            if "\n" in w or "\x00" in w:
                raise HarnessWorkingDirError("Invalid working directory (container path).")
            wd_container = w
        elif cfg.working_directory and "{working_directory}" not in cfg.working_directory:
            wd_container = cfg.working_directory.strip() or None

        substituted_args = self._substitute_harness_args(cfg, prompt, wd_container)
        if extra_args:
            substituted_args.extend(extra_args)

        inner = shlex.join([cfg.command] + substituted_args)
        if wd_container:
            script = f"cd {shlex.quote(wd_container)} && {inner}"
        else:
            script = inner

        logger.info(
            "[harness] %s bot_sandbox bot=%s image=%r",
            harness_name,
            bot.id,
            sandbox_config.image,
        )

        exec_res = await sandbox_service.exec_bot_local(
            bot.id, script, sandbox_config, timeout=timeout,
        )
        return HarnessResult(
            stdout=exec_res.stdout,
            stderr=exec_res.stderr,
            exit_code=exec_res.exit_code,
            truncated=exec_res.truncated,
            duration_ms=exec_res.duration_ms,
        )

    async def _run_in_sandbox(
        self,
        *,
        harness_name: str,
        cfg: HarnessConfig,
        prompt: str,
        working_directory: str | None,
        bot: "BotConfig",
        sandbox_instance_id: uuid.UUID,
        timeout: int,
        extra_args: list[str] | None = None,
    ) -> HarnessResult:
        from app.services.sandbox import sandbox_service

        if not settings.DOCKER_SANDBOX_ENABLED:
            raise HarnessError(
                "Cannot run harness in sandbox: DOCKER_SANDBOX_ENABLED is false."
            )

        allowed = bot.docker_sandbox_profiles or None
        instance = await sandbox_service.get_instance_for_bot(
            sandbox_instance_id, bot.id, allowed_profiles=allowed
        )
        if instance is None:
            raise HarnessError(
                "Sandbox instance not found, not owned by this bot, or not allowed by "
                "docker_sandbox_profiles."
            )

        wd_container: str | None = None
        if working_directory:
            w = working_directory.strip()
            if "\n" in w or "\x00" in w:
                raise HarnessWorkingDirError("Invalid working directory (container path).")
            wd_container = w
        elif cfg.working_directory and "{working_directory}" not in cfg.working_directory:
            wd_container = cfg.working_directory.strip() or None

        substituted_args = self._substitute_harness_args(cfg, prompt, wd_container)
        if extra_args:
            substituted_args.extend(extra_args)

        inner = shlex.join([cfg.command] + substituted_args)
        if wd_container:
            script = f"cd {shlex.quote(wd_container)} && {inner}"
        else:
            script = inner

        logger.info(
            "[harness] %s sandbox=%s profile_container=%r",
            harness_name,
            sandbox_instance_id,
            instance.container_name,
        )

        exec_res = await sandbox_service.exec(instance, script, timeout=timeout)
        return HarnessResult(
            stdout=exec_res.stdout,
            stderr=exec_res.stderr,
            exit_code=exec_res.exit_code,
            truncated=exec_res.truncated,
            duration_ms=exec_res.duration_ms,
        )



harness_service = HarnessService()
