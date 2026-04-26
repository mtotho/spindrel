"""PTY-backed terminal session lifecycle.

Spawns a ``/bin/bash -l`` under a pseudo-terminal, exposes async helpers
for read/write/resize, and tracks sessions in a process-local registry
with per-user concurrent caps and an idle sweeper.

Stdlib only. Linux-only (relies on ``pty``/``termios``/``fcntl``); Spindrel
runs in a Linux container so this is fine. Document the constraint in the
guide rather than try to abstract it.
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import signal
import struct
import termios
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Tunables read once at import. Re-import-friendly via env.
_MAX_PER_USER = int(os.environ.get("ADMIN_TERMINAL_MAX_PER_USER", "3"))
_IDLE_TIMEOUT_SEC = int(os.environ.get("ADMIN_TERMINAL_IDLE_TIMEOUT_SEC", "300"))
_SWEEP_INTERVAL_SEC = 30
_DISABLED = os.environ.get("DISABLE_ADMIN_TERMINAL", "").lower() in {"1", "true", "yes"}

# Output queue cap per session. Bash that floods stdout (e.g. `cat /dev/urandom`)
# without a consumer fills the queue; we drop the oldest chunk to keep memory
# bounded. The visible result is xterm sees a brief gap, not OOM.
_OUTPUT_QUEUE_MAX = 256


def is_disabled() -> bool:
    """True if DISABLE_ADMIN_TERMINAL is set. Routers should 404 in that case."""
    return _DISABLED


class TerminalSessionLimitError(Exception):
    """Raised when a user has hit their concurrent-session cap."""


@dataclass
class TerminalSession:
    id: str
    user_key: str  # opaque per-caller identity (user id, api key id, "static")
    master_fd: int
    process: asyncio.subprocess.Process
    cwd: Optional[str]
    seed_command: Optional[str]
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    output_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_OUTPUT_QUEUE_MAX))
    closed: bool = False

    def write_input(self, data: bytes) -> None:
        if self.closed:
            return
        self.last_activity = time.monotonic()
        try:
            os.write(self.master_fd, data)
        except OSError as exc:
            logger.debug("terminal.write failed (id=%s): %s", self.id, exc)

    def resize(self, rows: int, cols: int) -> None:
        if self.closed:
            return
        try:
            fcntl.ioctl(
                self.master_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", max(rows, 1), max(cols, 1), 0, 0),
            )
        except OSError as exc:
            logger.debug("terminal.resize failed (id=%s): %s", self.id, exc)

    async def read_output(self) -> bytes:
        """Returns the next output chunk, or ``b""`` on EOF/close."""
        return await self.output_queue.get()


# Module-level registry. One process per Spindrel container — no IPC needed.
_SESSIONS: dict[str, TerminalSession] = {}
_SESSIONS_LOCK = asyncio.Lock()
_SWEEPER_TASK: Optional[asyncio.Task] = None


def _user_session_count(user_key: str) -> int:
    return sum(1 for s in _SESSIONS.values() if s.user_key == user_key and not s.closed)


def _on_master_readable(session: TerminalSession) -> None:
    """add_reader callback: drain master FD into the session's queue."""
    try:
        data = os.read(session.master_fd, 4096)
    except BlockingIOError:
        return
    except OSError:
        # FD closed or process gone. Signal EOF and stop reading.
        _signal_eof(session)
        return
    if not data:
        _signal_eof(session)
        return
    session.last_activity = time.monotonic()
    queue = session.output_queue
    if queue.full():
        try:
            queue.get_nowait()  # drop oldest
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(data)
    except asyncio.QueueFull:
        # Lost the race; drop silently.
        pass


def _signal_eof(session: TerminalSession) -> None:
    loop = asyncio.get_running_loop()
    try:
        loop.remove_reader(session.master_fd)
    except (ValueError, OSError):
        pass
    try:
        session.output_queue.put_nowait(b"")
    except asyncio.QueueFull:
        pass


async def create_session(
    user_key: str,
    *,
    seed_command: Optional[str] = None,
    cwd: Optional[str] = None,
) -> TerminalSession:
    """Spawn a new bash PTY session and register it.

    Raises:
        TerminalSessionLimitError: if user has hit the concurrent cap.
        OSError: if the PTY or subprocess can't be created.
    """
    if _DISABLED:
        raise RuntimeError("admin terminal disabled by env (DISABLE_ADMIN_TERMINAL)")

    async with _SESSIONS_LOCK:
        if _user_session_count(user_key) >= _MAX_PER_USER:
            raise TerminalSessionLimitError(
                f"max {_MAX_PER_USER} concurrent terminal sessions per user"
            )

    master_fd, slave_fd = pty.openpty()
    # Master must be non-blocking so add_reader's os.read doesn't stall the loop
    # if a partial read is interrupted. Slave stays blocking — bash expects a
    # POSIX-conforming tty.
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    # Stop bash printing motd / locale spam noise in the first prompt.
    env.setdefault("PS1", r"\u@\h:\w\$ ")

    work_dir = cwd if (cwd and os.path.isdir(cwd)) else os.path.expanduser("~")

    try:
        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-l",
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=work_dir,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        raise

    # Parent doesn't keep the slave; bash holds it.
    os.close(slave_fd)

    session_id = uuid.uuid4().hex
    session = TerminalSession(
        id=session_id,
        user_key=user_key,
        master_fd=master_fd,
        process=process,
        cwd=work_dir,
        seed_command=seed_command,
    )

    loop = asyncio.get_running_loop()
    loop.add_reader(master_fd, _on_master_readable, session)

    async with _SESSIONS_LOCK:
        _SESSIONS[session_id] = session

    if seed_command:
        # Give bash a beat to render its first prompt before injecting the
        # seed; otherwise the seed echo can collide with the prompt and look
        # weird. 100ms is below human perception but past bash startup.
        async def _seed():
            await asyncio.sleep(0.1)
            session.write_input((seed_command + "\n").encode())

        loop.create_task(_seed())

    start_idle_sweeper()
    logger.info(
        "admin.terminal.session_open",
        extra={
            "session_id": session_id,
            "user_key": user_key,
            "cwd": work_dir,
            "seed_command_present": bool(seed_command),
        },
    )
    return session


def get_session(session_id: str) -> Optional[TerminalSession]:
    return _SESSIONS.get(session_id)


async def close_session(session_id: str) -> None:
    """Tear down a session: SIGTERM process group, close FDs, drop from registry."""
    async with _SESSIONS_LOCK:
        session = _SESSIONS.pop(session_id, None)
    if session is None:
        return
    if session.closed:
        return
    session.closed = True

    loop = asyncio.get_running_loop()
    try:
        loop.remove_reader(session.master_fd)
    except (ValueError, OSError):
        pass

    if session.process and session.process.returncode is None:
        try:
            pgid = os.getpgid(session.process.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            await asyncio.wait_for(session.process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            try:
                pgid = os.getpgid(session.process.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                await asyncio.wait_for(session.process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    try:
        os.close(session.master_fd)
    except OSError:
        pass

    # Unblock anyone awaiting read_output
    try:
        session.output_queue.put_nowait(b"")
    except asyncio.QueueFull:
        pass

    logger.info(
        "admin.terminal.session_close", extra={"session_id": session_id}
    )


async def _idle_sweeper_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL_SEC)
            now = time.monotonic()
            stale = [
                sid
                for sid, s in list(_SESSIONS.items())
                if (now - s.last_activity) > _IDLE_TIMEOUT_SEC
            ]
            for sid in stale:
                logger.info("admin.terminal.session_idle_close", extra={"session_id": sid})
                await close_session(sid)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("admin.terminal.sweeper_error")


def start_idle_sweeper() -> None:
    """Idempotent — starts the background sweep task if not already running."""
    global _SWEEPER_TASK
    if _SWEEPER_TASK is not None and not _SWEEPER_TASK.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _SWEEPER_TASK = loop.create_task(_idle_sweeper_loop())
