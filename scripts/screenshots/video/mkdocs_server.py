"""Subprocess-managed `mkdocs serve` for B2 doc-view scenes.

The B2 clip modules need a live mkdocs site to screenshot. Spinning up a
fresh server per scene would be wasteful — we run one server for the whole
build/preview, kill it on exit, and let scenes share the base URL through
a module-level global on ``_doc_capture``.

`mkdocs serve` defaults to a livereload websocket that injects
``<script>`` tags into every page, which would show up in screenshots.
``--no-livereload`` keeps the rendered HTML clean.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


logger = logging.getLogger("screenshots.video.mkdocs")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
READY_TIMEOUT_S = 30.0


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _wait_for_ready(url: str, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if 200 <= resp.status < 400:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_err = e
        time.sleep(0.25)
    raise RuntimeError(
        f"mkdocs server did not become ready at {url} within {timeout_s}s "
        f"(last error: {last_err!r})"
    )


@contextmanager
def mkdocs_serve(
    repo_root: Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> Iterator[str]:
    """Run `mkdocs serve` for the duration of the context, yielding base URL.

    Caller is responsible for not nesting these on the same port. If the
    port is already bound (e.g. user already has `mkdocs serve` running in
    another shell), we yield the existing URL without starting a second
    server.
    """
    base_url = f"http://{host}:{port}"

    if not _port_free(host, port):
        logger.info("mkdocs already running on %s — reusing", base_url)
        try:
            _wait_for_ready(base_url + "/", timeout_s=5.0)
        except RuntimeError as e:
            raise RuntimeError(
                f"port {port} is bound but {base_url} isn't serving mkdocs: {e}"
            ) from e
        yield base_url
        return

    cfg = repo_root / "mkdocs.yml"
    if not cfg.exists():
        raise FileNotFoundError(f"mkdocs.yml not found at {cfg}")

    cmd = [
        "mkdocs", "serve",
        "--dev-addr", f"{host}:{port}",
        "--no-livereload",
        "--config-file", str(cfg),
    ]
    logger.info("starting mkdocs: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Own process group so we can SIGTERM the whole tree on exit.
        start_new_session=True,
    )
    try:
        _wait_for_ready(base_url + "/", timeout_s=READY_TIMEOUT_S)
        logger.info("mkdocs ready at %s", base_url)
        yield base_url
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=2.0)
