"""Workspace code editor service — on-demand code-server inside workspace containers."""
import asyncio
import logging
import os
import platform
import tarfile
import tempfile
from pathlib import Path

from sqlalchemy import select, update

from app.config import settings
from app.db.engine import async_session
from app.db.models import SharedWorkspace
from app.services.shared_workspace import shared_workspace_service

logger = logging.getLogger(__name__)

CODE_SERVER_VERSION = "4.96.4"
CACHE_DIR = os.path.expanduser("~/.agent-workspaces/.cache/code-server")
CONTAINER_INSTALL_DIR = "/usr/local/lib/code-server"


def _download_url() -> str:
    """Build the code-server standalone release tarball URL."""
    arch = platform.machine()
    if arch in ("x86_64", "AMD64"):
        arch = "amd64"
    elif arch in ("aarch64", "arm64"):
        arch = "arm64"
    return (
        f"https://github.com/coder/code-server/releases/download/"
        f"v{CODE_SERVER_VERSION}/code-server-{CODE_SERVER_VERSION}-linux-{arch}.tar.gz"
    )


def _cached_tarball() -> str:
    return os.path.join(CACHE_DIR, f"code-server-{CODE_SERVER_VERSION}-linux.tar.gz")


def _cached_dir() -> str:
    return os.path.join(CACHE_DIR, f"code-server-{CODE_SERVER_VERSION}")


async def _ensure_downloaded() -> str:
    """Download code-server tarball to host cache if not present. Returns path to unpacked dir."""
    unpacked = _cached_dir()
    if os.path.isdir(unpacked) and os.path.isfile(os.path.join(unpacked, "bin", "code-server")):
        return unpacked

    os.makedirs(CACHE_DIR, exist_ok=True)
    tarball = _cached_tarball()

    if not os.path.isfile(tarball):
        url = _download_url()
        logger.info("Downloading code-server %s from %s", CODE_SERVER_VERSION, url)
        proc = await asyncio.create_subprocess_exec(
            "curl", "-fSL", "-o", tarball, url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            os.remove(tarball) if os.path.exists(tarball) else None
            raise RuntimeError(f"Failed to download code-server: {stderr.decode()}")

    # Unpack
    logger.info("Unpacking code-server tarball to %s", unpacked)
    os.makedirs(unpacked, exist_ok=True)

    def _extract():
        with tarfile.open(tarball, "r:gz") as tf:
            # Tarball has a top-level dir like code-server-4.96.4-linux-amd64/
            members = tf.getmembers()
            prefix = members[0].name.split("/")[0] if members else ""
            for member in members:
                # Strip the top-level directory
                if member.name.startswith(prefix + "/"):
                    member.name = member.name[len(prefix) + 1:]
                if not member.name:
                    continue
                tf.extract(member, unpacked, filter="data")

    await asyncio.to_thread(_extract)

    bin_path = os.path.join(unpacked, "bin", "code-server")
    if not os.path.isfile(bin_path):
        # Some releases have the binary at lib/code-server — create a bin/ wrapper
        lib_bin = os.path.join(unpacked, "lib", "node")
        if os.path.isfile(lib_bin):
            os.makedirs(os.path.join(unpacked, "bin"), exist_ok=True)

    logger.info("code-server %s cached at %s", CODE_SERVER_VERSION, unpacked)
    return unpacked


async def install_code_server(container_name: str) -> None:
    """Copy cached code-server into a running container via docker cp."""
    src = await _ensure_downloaded()

    # docker cp the entire directory into the container
    proc = await asyncio.create_subprocess_exec(
        "docker", "cp", src, f"{container_name}:{CONTAINER_INSTALL_DIR}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"docker cp failed: {stderr.decode()}")

    # Make binary executable
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container_name, "chmod", "+x",
        f"{CONTAINER_INSTALL_DIR}/bin/code-server",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


async def start_code_server(container_name: str, workspace_id: str, port: int = 8443) -> None:
    """Start code-server inside the container (detached)."""
    base_path = f"/api/v1/workspaces/{workspace_id}/editor"
    cmd = (
        f"{CONTAINER_INSTALL_DIR}/bin/code-server "
        f"--bind-addr 0.0.0.0:{port} "
        f"--auth none "
        f"--disable-telemetry "
        f"--disable-update-check "
        f"--disable-getting-started-override "
        f'--proxy-domain "" '
        f"/workspace"
    )
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", "-d", container_name, "sh", "-c", cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    logger.info("Started code-server in %s on port %d", container_name, port)


async def is_code_server_running(container_name: str) -> bool:
    """Check if code-server process is alive inside the container."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container_name, "pgrep", "-f", "code-server",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return proc.returncode == 0


async def _wait_for_healthy(port: int, timeout: int = 15) -> None:
    """Poll code-server's HTTP port until it responds or timeout."""
    import httpx

    host = "127.0.0.1"
    if settings.WORKSPACE_LOCAL_DIR:
        host = "host.docker.internal"

    url = f"http://{host}:{port}/healthz"
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(url)
                if resp.status_code < 500:
                    logger.info("code-server healthy on port %d", port)
                    return
        except (httpx.ConnectError, httpx.RemoteProtocolError, OSError):
            pass
        await asyncio.sleep(1)
    logger.warning("code-server on port %d did not become healthy within %ds", port, timeout)


async def allocate_editor_port() -> int:
    """Find the first unused port in the configured range."""
    start = settings.EDITOR_PORT_RANGE_START
    end = settings.EDITOR_PORT_RANGE_END

    async with async_session() as db:
        used = set(
            (await db.execute(
                select(SharedWorkspace.editor_port)
                .where(SharedWorkspace.editor_port.isnot(None))
            )).scalars().all()
        )

    for port in range(start, end + 1):
        if port not in used:
            return port
    raise RuntimeError(f"No free editor ports in range {start}-{end}")


async def _container_actually_running(container_name: str) -> bool:
    """Check if a Docker container actually exists and is running."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "inspect", "-f", "{{.State.Running}}", container_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode == 0 and stdout.decode().strip() == "true"


async def ensure_editor(ws: SharedWorkspace) -> dict:
    """Orchestrate: allocate port -> recreate container if needed -> install -> start.

    Returns {"editor_url": str, "editor_port": int}.
    """
    print(
        f"[EDITOR] ensure_editor called: ws.id={ws.id} container_name={ws.container_name} "
        f"status={ws.status} editor_port={ws.editor_port} editor_enabled={ws.editor_enabled}"
    )
    logger.info(
        "ensure_editor called: ws.id=%s container_name=%s status=%s "
        "editor_port=%s editor_enabled=%s",
        ws.id, ws.container_name, ws.status, ws.editor_port, ws.editor_enabled,
    )
    need_recreate = False

    # 1. Allocate port if not set
    if not ws.editor_port:
        port = await allocate_editor_port()
        logger.info("Allocated editor port %d for workspace %s", port, ws.id)
        async with async_session() as db:
            await db.execute(
                update(SharedWorkspace)
                .where(SharedWorkspace.id == ws.id)
                .values(editor_port=port, editor_enabled=True)
            )
            await db.commit()
        ws.editor_port = port
        ws.editor_enabled = True
        need_recreate = True
    elif not ws.editor_enabled:
        logger.info("Enabling editor for workspace %s (port already %s)", ws.id, ws.editor_port)
        async with async_session() as db:
            await db.execute(
                update(SharedWorkspace)
                .where(SharedWorkspace.id == ws.id)
                .values(editor_enabled=True)
            )
            await db.commit()
        ws.editor_enabled = True
        need_recreate = True

    # 2. Ensure the container is actually running with the editor port mapped
    container_alive = False
    if ws.container_name:
        container_alive = await _container_actually_running(ws.container_name)
    logger.info(
        "Container check: name=%s alive=%s need_recreate=%s",
        ws.container_name, container_alive, need_recreate,
    )

    if container_alive:
        # Container is running — check if editor port 8443 is actually mapped
        proc = await asyncio.create_subprocess_exec(
            "docker", "port", ws.container_name, "8443",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        port_mapped = proc.returncode == 0 and bool(stdout.strip())
        if port_mapped:
            logger.info("Port 8443 already mapped: %s", stdout.decode().strip())
        else:
            # Port not mapped — must recreate container to add -p mapping
            logger.info("Recreating container %s to add editor port mapping", ws.container_name)
            await shared_workspace_service.recreate(ws)
            async with async_session() as db:
                ws = await db.get(SharedWorkspace, ws.id)
    else:
        # Container doesn't exist or isn't running — start it
        logger.info("Container not running — calling ensure_container for workspace %s", ws.id)
        try:
            container_id = await shared_workspace_service.ensure_container(ws)
            logger.info("ensure_container returned container_id=%s", container_id)
        except Exception:
            logger.exception("ensure_container FAILED for workspace %s", ws.id)
            raise
        async with async_session() as db:
            ws = await db.get(SharedWorkspace, ws.id)
        logger.info(
            "After ensure_container: container_name=%s status=%s editor_port=%s",
            ws.container_name, ws.status, ws.editor_port,
        )

    # 3. Install code-server (idempotent — checks if binary exists)
    if ws.container_name:
        rc, _ = await shared_workspace_service._docker_exec(
            ws.container_name, f"test -f {CONTAINER_INSTALL_DIR}/bin/code-server"
        )
        if rc != 0:
            logger.info("Installing code-server in %s", ws.container_name)
            await install_code_server(ws.container_name)
        else:
            logger.info("code-server already installed in %s", ws.container_name)
    else:
        logger.warning("No container_name after ensure — cannot install code-server!")

    # 4. Start code-server if not running
    if ws.container_name and not await is_code_server_running(ws.container_name):
        logger.info("Starting code-server in %s", ws.container_name)
        await start_code_server(ws.container_name, str(ws.id))
    elif ws.container_name:
        logger.info("code-server already running in %s", ws.container_name)

    # 5. Wait for code-server to become healthy (up to 15s)
    if ws.container_name and ws.editor_port:
        logger.info("Waiting for code-server healthy on port %d...", ws.editor_port)
        await _wait_for_healthy(ws.editor_port, timeout=15)

    editor_url = f"/api/v1/workspaces/{ws.id}/editor/"
    logger.info(
        "ensure_editor done: container=%s port=%s url=%s",
        ws.container_name, ws.editor_port, editor_url,
    )
    return {
        "editor_url": editor_url,
        "editor_port": ws.editor_port,
        "editor_enabled": True,
    }


async def disable_editor(ws: SharedWorkspace) -> None:
    """Disable the editor (doesn't stop code-server, just marks as disabled)."""
    async with async_session() as db:
        await db.execute(
            update(SharedWorkspace)
            .where(SharedWorkspace.id == ws.id)
            .values(editor_enabled=False)
        )
        await db.commit()


async def editor_status(ws: SharedWorkspace) -> dict:
    """Get current editor status."""
    running = False
    if ws.container_name and ws.editor_enabled:
        running = await is_code_server_running(ws.container_name)
    return {
        "editor_enabled": ws.editor_enabled,
        "editor_port": ws.editor_port,
        "editor_running": running,
        "editor_url": f"/api/v1/workspaces/{ws.id}/editor/" if ws.editor_enabled else None,
    }
