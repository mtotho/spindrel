"""UDS bridge for the run_script netns sandbox (R2 Phase 2).

The sandboxed script subprocess lives inside an empty network namespace —
``127.0.0.1:8000`` is unreachable. To preserve the spindrel.py helper's
ability to call ``/api/v1/internal/tools/exec``, the agent server starts a
unix-domain-socket listener at ``settings.SCRIPT_SANDBOX_UDS_PATH`` and
forwards bytes to its own TCP listener (``http://127.0.0.1:<port>``).

UDS sockets bound by filesystem path are not netns-isolated — ``connect()``
from inside the script's empty netns to the path works because path
resolution lives in the (shared) mount namespace. The bridge process itself
runs in the parent netns where TCP loopback is reachable.

The bridge is intentionally a transparent byte-stream proxy rather than a
second uvicorn instance: it's far simpler, has identical observable behavior
on the helper's narrow request shape, and inherits the existing TCP
listener's auth + routing without duplication.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Forward bytes from ``reader`` to ``writer`` until EOF.

    Uses half-close (``write_eof``) on the destination so the *other*
    direction of the bidirectional bridge can still finish — HTTP semantics
    are request-then-response on the same socket, so a full close here would
    truncate the response before the client could read it.
    """
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
        except (ConnectionError, OSError):
            pass


async def _handle_uds_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tcp_host: str,
    tcp_port: int,
) -> None:
    try:
        tcp_reader, tcp_writer = await asyncio.open_connection(tcp_host, tcp_port)
    except OSError as exc:
        logger.warning("script_sandbox_bridge: backend connect failed: %s", exc)
        try:
            writer.close()
        except Exception:
            pass
        return
    try:
        await asyncio.gather(
            _pipe(reader, tcp_writer),
            _pipe(tcp_reader, writer),
        )
    finally:
        for w in (writer, tcp_writer):
            try:
                w.close()
            except Exception:
                pass


async def serve_uds_bridge(
    uds_path: str,
    tcp_host: str,
    tcp_port: int,
    *,
    socket_mode: int = 0o660,
) -> asyncio.AbstractServer:
    """Start a UDS server that forwards every connection to ``tcp_host:tcp_port``.

    Returns the asyncio server. Caller is responsible for keeping a reference
    so it isn't garbage-collected and for closing it on shutdown.

    The parent dir is created (mode 0o755) if missing. Any existing socket
    file at ``uds_path`` is replaced — a stale socket from a prior process
    would otherwise block bind().
    """
    path = Path(uds_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        try:
            path.unlink()
        except OSError as exc:
            logger.warning(
                "script_sandbox_bridge: could not remove stale socket %s: %s",
                uds_path, exc,
            )
    server = await asyncio.start_unix_server(
        lambda r, w: _handle_uds_client(r, w, tcp_host, tcp_port),
        path=uds_path,
    )
    try:
        os.chmod(uds_path, socket_mode)
    except OSError as exc:
        logger.warning(
            "script_sandbox_bridge: chmod %s -> %o failed: %s",
            uds_path, socket_mode, exc,
        )
    logger.info(
        "script_sandbox_bridge: listening at %s -> tcp %s:%d",
        uds_path, tcp_host, tcp_port,
    )
    return server


async def run_uds_bridge_forever(
    uds_path: str,
    tcp_host: str,
    tcp_port: int,
) -> None:
    """Long-running task wrapper. Started via ``asyncio.create_task`` from the
    FastAPI lifespan; cancellation closes the listener cleanly.
    """
    server = await serve_uds_bridge(uds_path, tcp_host, tcp_port)
    try:
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        logger.info("script_sandbox_bridge: shutting down")
        raise
    finally:
        try:
            Path(uds_path).unlink(missing_ok=True)
        except OSError:
            pass
