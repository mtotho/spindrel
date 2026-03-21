"""External harness execution service — run CLI tools (claude, cursor, etc.) as subprocesses."""
import asyncio
import logging
import os
import shlex
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

from app.config import settings

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

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
            )

        else:
           raise HarnessError("Harness must be run in a sandbox. Use sandbox_instance_id to run in a sandbox.")

        # Host subprocess
        wd: str | None = None
        if working_directory:
            wd = self._validate_working_dir(working_directory)
        elif cfg.working_directory and "{working_directory}" not in cfg.working_directory:
            wd = self._validate_working_dir(cfg.working_directory)

        substituted_args = self._substitute_harness_args(cfg, prompt, wd)

        logger.info("[harness] %s command=%r working_dir=%r", harness_name, cfg.command, wd)

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            cfg.command,
            *substituted_args,
            cwd=wd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        max_output = 65536  # 64 KB per stream
        try:
            raw_out, raw_err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            raise HarnessError(f"Harness {harness_name!r} timed out after {timeout}s.")

        duration_ms = int((time.monotonic() - start) * 1000)

        truncated = False
        if len(raw_out) > max_output:
            raw_out = raw_out[:max_output]
            truncated = True
        if len(raw_err) > max_output:
            raw_err = raw_err[:max_output]
            truncated = True

        return HarnessResult(
            stdout=raw_out.decode(errors="replace"),
            stderr=raw_err.decode(errors="replace"),
            exit_code=proc.returncode or 0,
            truncated=truncated,
            duration_ms=duration_ms,
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

    def _validate_working_dir(self, working_dir: str) -> str:
        """Resolve to realpath and validate against allowlist."""
        try:
            real = os.path.realpath(working_dir)
        except Exception as exc:
            raise HarnessWorkingDirError(f"Invalid working directory: {exc}") from exc

        if not os.path.isdir(real):
            raise HarnessWorkingDirError(f"Working directory does not exist: {real!r}")

        server_allowlist = settings.HARNESS_WORKING_DIR_ALLOWLIST
        if server_allowlist:
            if not any(
                real == p or real.startswith(p.rstrip("/") + "/")
                for p in server_allowlist
            ):
                raise HarnessWorkingDirError(
                    f"Working directory '{real}' is not in the server allowlist."
                )

        return real


harness_service = HarnessService()
