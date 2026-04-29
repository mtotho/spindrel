"""Host shell execution service — run commands on the host system with security controls."""
import asyncio
import logging
import os
import re
import shlex
import time
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)

# Hardcoded blocked patterns — cannot be overridden by any config
_HARDCODED_BLOCKED: list[re.Pattern] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"\brm\b.*\s-[a-z]*f[a-z]*\s+/",     # rm -rf /path
        r"\bsudo\b",                             # privilege escalation
        r"\bsu\b\s",                             # switch user
        r">\s*/(?:etc|sys|proc|dev|boot)/",     # redirect to system dirs
        r"\bcurl\b.+\|\s*(?:ba)?sh",             # curl | bash
        r"\bwget\b.+\|\s*(?:ba)?sh",             # wget | bash
        r"\bmkfs\b",                             # filesystem formatting
        r"\bdd\b.*of=/dev/",                     # dd to device
        r":\(\)\s*\{.*\|.*:.*&.*\}",            # fork bomb
        r"\bcurl\b.*\blocalhost\b",              # curl to localhost
        r"\bcurl\b.*\b127\.0\.0\.\d",           # curl to 127.x
        r"\bwget\b.*\blocalhost\b",              # wget to localhost
        r"\bwget\b.*\b127\.0\.0\.\d",           # wget to 127.x
    ]
]


class HostExecError(Exception):
    pass


class HostExecAccessDeniedError(HostExecError):
    pass


class HostExecBlockedError(HostExecError):
    pass


@dataclass
class HostExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    duration_ms: int
    dry_run: bool = False


class HostExecService:
    async def run(
        self,
        command: str,
        working_dir: str,
        bot_config: "HostExecConfig",  # noqa: F821
        *,
        extra_env: dict[str, str] | None = None,
    ) -> HostExecResult:
        """Execute a shell command on the host with security validation."""
        from app.agent.bots import HostExecConfig  # local import to avoid circular

        if not settings.HOST_EXEC_ENABLED:
            raise HostExecAccessDeniedError("Host execution is disabled (HOST_EXEC_ENABLED=false).")

        if not bot_config.enabled:
            raise HostExecAccessDeniedError("Host execution is not enabled for this bot.")

        timeout = bot_config.timeout if bot_config.timeout is not None else settings.HOST_EXEC_DEFAULT_TIMEOUT
        max_output = bot_config.max_output_bytes if bot_config.max_output_bytes is not None else settings.HOST_EXEC_MAX_OUTPUT_BYTES

        if bot_config.dry_run:
            logger.info("[host_exec dry_run] command=%r working_dir=%r", command, working_dir)
            return HostExecResult(
                stdout="",
                stderr="",
                exit_code=0,
                truncated=False,
                duration_ms=0,
                dry_run=True,
            )

        real_wd = self._validate_working_dir(working_dir, bot_config)
        self._validate_command(command, bot_config)
        env = self._build_env(bot_config)
        env.update(extra_env or {})

        logger.info("[host_exec] command=%r working_dir=%r", command, real_wd)

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", command,
            cwd=real_wd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            raw_out, raw_err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            raise HostExecError(f"Command timed out after {timeout}s.")

        duration_ms = int((time.monotonic() - start) * 1000)

        truncated = False
        if len(raw_out) > max_output:
            raw_out = raw_out[:max_output]
            truncated = True
        if len(raw_err) > max_output:
            raw_err = raw_err[:max_output]
            truncated = True

        return HostExecResult(
            stdout=raw_out.decode(errors="replace"),
            stderr=raw_err.decode(errors="replace"),
            exit_code=proc.returncode or 0,
            truncated=truncated,
            duration_ms=duration_ms,
        )

    def _validate_command(self, command: str, cfg: "HostExecConfig") -> None:  # noqa: F821
        """Raise HostExecBlockedError if the command is not permitted."""
        # 1. Hardcoded blocked patterns — always checked, cannot override
        for pattern in _HARDCODED_BLOCKED:
            if pattern.search(command):
                raise HostExecBlockedError(
                    f"Command blocked by hardcoded security rule: {pattern.pattern!r}"
                )

        # 2. Server-level blocked patterns
        for raw in settings.HOST_EXEC_BLOCKED_PATTERNS:
            if re.search(raw, command, re.IGNORECASE):
                raise HostExecBlockedError(f"Command blocked by server policy: {raw!r}")

        # 3. Bot-level blocked patterns
        for raw in cfg.blocked_patterns:
            if re.search(raw, command, re.IGNORECASE):
                raise HostExecBlockedError(f"Command blocked by bot policy: {raw!r}")

        # 4. Command allowlist check
        if not cfg.commands:
            return  # no allowlist = no restriction beyond blocklist

        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()

        if not parts:
            return

        binary = os.path.basename(parts[0])

        # Wildcard entry bypasses name/subcommand checks
        cmd_entries = {e.name: e for e in cfg.commands}
        if "*" in cmd_entries:
            return

        if binary not in cmd_entries:
            raise HostExecBlockedError(
                f"Command '{binary}' is not in this bot's allowed command list."
            )

        entry = cmd_entries[binary]
        if entry.subcommands and len(parts) > 1:
            subcommand = parts[1]
            if subcommand not in entry.subcommands:
                raise HostExecBlockedError(
                    f"Subcommand '{binary} {subcommand}' is not allowed. "
                    f"Allowed subcommands: {', '.join(entry.subcommands)}"
                )

    def _validate_working_dir(self, working_dir: str, cfg: "HostExecConfig") -> str:  # noqa: F821
        """Resolve working_dir to realpath and check against allowlist. Returns realpath."""
        try:
            real = os.path.realpath(working_dir)
        except Exception as exc:
            raise HostExecBlockedError(f"Invalid working directory: {exc}") from exc

        if not os.path.isdir(real):
            raise HostExecBlockedError(f"Working directory does not exist: {real!r}")

        # Server-level allowlist (if set)
        server_allowlist = settings.HOST_EXEC_WORKING_DIR_ALLOWLIST
        if server_allowlist:
            if not any(
                real == p or real.startswith(p.rstrip("/") + "/")
                for p in server_allowlist
            ):
                raise HostExecBlockedError(
                    f"Working directory '{real}' is not in the server allowlist."
                )

        # Bot-level allowlist
        if cfg.working_dirs:
            if not any(
                real == p or real.startswith(os.path.realpath(p).rstrip("/") + "/")
                for p in cfg.working_dirs
            ):
                raise HostExecBlockedError(
                    f"Working directory '{real}' is not in this bot's allowed working directory list."
                )

        return real

    def _build_env(self, cfg: "HostExecConfig") -> dict:  # noqa: F821
        """Build a sanitized environment dict from passthrough lists."""
        passthrough_keys = set(settings.HOST_EXEC_ENV_PASSTHROUGH) | set(cfg.env_passthrough)
        env = {k: v for k, v in os.environ.items() if k in passthrough_keys}
        # Inject secret values (available in host exec even if not in os.environ)
        try:
            from app.services.secret_values import get_env_dict
            env.update(get_env_dict())
        except Exception:
            pass
        return env


host_exec_service = HostExecService()
