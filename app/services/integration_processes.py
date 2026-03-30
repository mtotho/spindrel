"""Integration background process manager.

Manages lifecycle of integration processes (those with process.py).
Replaces the bash-driven approach in dev-server.sh with a Python-native
manager that works in both dev and Docker production.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

logger = logging.getLogger(__name__)


class _ProcessState:
    """Tracks state for a single managed process."""
    __slots__ = (
        "integration_id", "cmd", "description", "required_env",
        "process", "monitor_task", "started_at", "exit_code",
        "restart_count",
    )

    def __init__(self, integration_id: str, cmd: list[str], description: str, required_env: list[str]):
        self.integration_id = integration_id
        self.cmd = cmd
        self.description = description
        self.required_env = required_env
        self.process: asyncio.subprocess.Process | None = None
        self.monitor_task: asyncio.Task | None = None
        self.started_at: float | None = None
        self.exit_code: int | None = None
        self.restart_count: int = 0


class IntegrationProcessManager:
    """Manages integration background processes."""

    def __init__(self):
        self._states: dict[str, _ProcessState] = {}

    def _discover(self) -> dict[str, dict]:
        """Discover all integrations with process.py (regardless of env readiness)."""
        from integrations import _iter_integration_candidates, _import_module

        results: dict[str, dict] = {}
        for candidate, integration_id, is_external, source in _iter_integration_candidates():
            process_file = candidate / "process.py"
            if not process_file.exists():
                continue
            try:
                module = _import_module(integration_id, "process", process_file, is_external, source)
                cmd = getattr(module, "CMD", None)
                if not cmd:
                    continue
                results[integration_id] = {
                    "cmd": cmd,
                    "required_env": getattr(module, "REQUIRED_ENV", []),
                    "description": getattr(module, "DESCRIPTION", integration_id),
                }
            except Exception:
                logger.exception("Failed to load process config for integration %r", integration_id)
        return results

    def _env_ready(self, required_env: list[str]) -> bool:
        """Check if all required env vars are set in os.environ.

        Uses os.environ directly (same as discover_processes()), not the
        integration_settings DB cache — process.py env vars are system-level
        credentials that must be in the real environment for the subprocess.
        """
        return all(os.environ.get(k) for k in required_env)

    async def get_auto_start(self, integration_id: str) -> bool:
        """Check if auto-start is enabled for an integration.

        Default: auto-start if all required env vars are set (matching
        legacy dev-server.sh behavior), unless explicitly disabled via
        the _process_auto_start setting.
        """
        try:
            from app.services.integration_settings import get_value
            val = get_value(integration_id, "_process_auto_start")
            if val:
                return val.lower() in ("true", "1", "yes")
        except ImportError:
            pass
        # Default: auto-start if env is ready
        return True

    async def set_auto_start(self, integration_id: str, enabled: bool) -> None:
        """Persist auto-start setting to DB. Raises on failure."""
        from app.db.engine import async_session
        from app.services.integration_settings import _cache
        from app.db.models import IntegrationSetting
        from datetime import datetime, timezone
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        value = "true" if enabled else "false"
        now = datetime.now(timezone.utc)

        async with async_session() as db:
            stmt = pg_insert(IntegrationSetting).values(
                integration_id=integration_id,
                key="_process_auto_start",
                value=value,
                is_secret=False,
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["integration_id", "key"],
                set_={"value": value, "updated_at": now},
            )
            await db.execute(stmt)
            await db.commit()

        # Update cache only after successful DB write
        _cache[(integration_id, "_process_auto_start")] = value

    async def start(self, integration_id: str) -> bool:
        """Start a process for the given integration. Returns True if started."""
        # Already running?
        state = self._states.get(integration_id)
        if state and state.process and state.process.returncode is None:
            logger.warning("Process for %s is already running (pid=%s)", integration_id, state.process.pid)
            return False

        # Discover or re-use cached state
        if not state:
            discovered = self._discover()
            info = discovered.get(integration_id)
            if not info:
                logger.error("No process.py found for integration %r", integration_id)
                return False
            state = _ProcessState(
                integration_id=integration_id,
                cmd=info["cmd"],
                description=info["description"],
                required_env=info["required_env"],
            )
            self._states[integration_id] = state

        # Check env readiness
        if not self._env_ready(state.required_env):
            missing = [k for k in state.required_env if not os.environ.get(k)]
            logger.warning(
                "Cannot start %s: missing env vars %s", integration_id, missing,
            )
            return False

        # Spawn the process
        try:
            logger.info("Starting integration process: %s (%s)", state.description, " ".join(state.cmd))
            state.process = await asyncio.create_subprocess_exec(
                *state.cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            state.started_at = time.monotonic()
            state.exit_code = None

            # Start monitor task
            state.monitor_task = asyncio.create_task(
                self._monitor(state),
                name=f"process-monitor-{integration_id}",
            )
            logger.info(
                "Started %s (pid=%s)", state.description, state.process.pid,
            )
            return True
        except Exception:
            logger.exception("Failed to start process for %s", integration_id)
            return False

    async def _monitor(self, state: _ProcessState) -> None:
        """Monitor a process, log output, detect crashes."""
        proc = state.process
        if not proc or not proc.stdout:
            return

        # Stream stdout/stderr (merged) line by line
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.debug("[%s] %s", state.integration_id, text)

        # Process exited
        await proc.wait()
        state.exit_code = proc.returncode
        uptime = time.monotonic() - (state.started_at or 0)

        if state.exit_code == 0:
            logger.info(
                "Process %s exited cleanly (uptime %.0fs)", state.integration_id, uptime,
            )
        elif state.exit_code == -signal.SIGTERM:
            logger.info(
                "Process %s terminated by SIGTERM (uptime %.0fs)", state.integration_id, uptime,
            )
        else:
            logger.warning(
                "Process %s crashed (exit_code=%s, uptime=%.0fs)",
                state.integration_id, state.exit_code, uptime,
            )

    async def stop(self, integration_id: str) -> bool:
        """Stop a running process. Returns True if stopped."""
        state = self._states.get(integration_id)
        if not state or not state.process:
            return False

        proc = state.process
        if proc.returncode is not None:
            # Already exited
            return False

        logger.info("Stopping process %s (pid=%s)...", integration_id, proc.pid)
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("Process %s did not exit in 10s, sending SIGKILL", integration_id)
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass  # already gone

        # Cancel monitor task
        if state.monitor_task and not state.monitor_task.done():
            state.monitor_task.cancel()
            try:
                await state.monitor_task
            except asyncio.CancelledError:
                pass

        state.exit_code = proc.returncode
        logger.info("Stopped %s (exit_code=%s)", integration_id, state.exit_code)
        return True

    async def restart(self, integration_id: str) -> bool:
        """Restart a process."""
        await self.stop(integration_id)
        state = self._states.get(integration_id)
        if state:
            state.restart_count += 1
        return await self.start(integration_id)

    def status(self, integration_id: str) -> dict:
        """Get status for a single process."""
        state = self._states.get(integration_id)
        if not state:
            return {
                "integration_id": integration_id,
                "status": "stopped",
                "pid": None,
                "uptime_seconds": None,
                "exit_code": None,
                "restart_count": 0,
            }

        proc = state.process
        is_running = proc is not None and proc.returncode is None
        uptime = None
        if is_running and state.started_at:
            uptime = round(time.monotonic() - state.started_at)

        return {
            "integration_id": integration_id,
            "status": "running" if is_running else "stopped",
            "pid": proc.pid if proc and is_running else None,
            "uptime_seconds": uptime,
            "exit_code": state.exit_code,
            "restart_count": state.restart_count,
        }

    def status_all(self) -> list[dict]:
        """Get status for all known processes."""
        # Include discovered but not-yet-started processes
        discovered = self._discover()
        results = []
        seen = set()

        for iid in discovered:
            results.append(self.status(iid))
            seen.add(iid)

        # Include any that were started but no longer discovered (rare)
        for iid in self._states:
            if iid not in seen:
                results.append(self.status(iid))

        return results

    async def start_auto_start_processes(self) -> None:
        """Start all processes that should auto-start. Called from lifespan."""
        discovered = self._discover()
        if not discovered:
            logger.debug("No integration processes discovered")
            return

        logger.info("Discovered %d integration process(es): %s", len(discovered), list(discovered.keys()))

        for integration_id, info in discovered.items():
            # Check env readiness first
            if not self._env_ready(info["required_env"]):
                missing = [k for k in info["required_env"] if not os.environ.get(k)]
                logger.debug("Skipping %s: missing env vars %s", integration_id, missing)
                continue

            # Check auto-start setting
            auto = await self.get_auto_start(integration_id)
            if not auto:
                logger.info("Skipping %s: auto-start disabled", integration_id)
                continue

            await self.start(integration_id)

    async def shutdown_all(self) -> None:
        """Stop all running processes. Called from lifespan finally block."""
        running = [
            iid for iid, state in self._states.items()
            if state.process and state.process.returncode is None
        ]
        if not running:
            return

        logger.info("Shutting down %d integration process(es)...", len(running))
        await asyncio.gather(
            *(self.stop(iid) for iid in running),
            return_exceptions=True,
        )

    def get_discoverable(self) -> list[dict]:
        """Return all discoverable processes with their env readiness status."""
        discovered = self._discover()
        results = []
        for iid, info in discovered.items():
            results.append({
                "integration_id": iid,
                "description": info["description"],
                "required_env": info["required_env"],
                "env_ready": self._env_ready(info["required_env"]),
            })
        return results


# Singleton
process_manager = IntegrationProcessManager()
