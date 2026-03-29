"""Workspace code editor service — on-demand code-server inside workspace containers."""
import asyncio
import logging

from sqlalchemy import select, update

from app.config import settings
from app.db.engine import async_session
from app.db.models import SharedWorkspace
from app.services.shared_workspace import shared_workspace_service

logger = logging.getLogger(__name__)

CODE_SERVER_VERSION = "4.96.4"


async def _docker_exec(container_name: str, cmd: str) -> tuple[int, str]:
    """Run a command in the container. Returns (exit_code, combined_output)."""
    return await shared_workspace_service._docker_exec(container_name, cmd)


async def install_code_server(container_name: str) -> None:
    """Install code-server via npm inside the container."""
    logger.info("Installing code-server %s via npm in %s", CODE_SERVER_VERSION, container_name)
    rc, out = await _docker_exec(
        container_name,
        f"npm install -g code-server@{CODE_SERVER_VERSION} 2>&1",
    )
    if rc != 0:
        raise RuntimeError(f"npm install code-server failed (rc={rc}): {out[-1000:]}")
    logger.info("code-server installed successfully in %s", container_name)


async def is_code_server_installed(container_name: str) -> bool:
    """Check if code-server is installed in the container."""
    rc, out = await _docker_exec(container_name, "code-server --version 2>/dev/null")
    return rc == 0


async def start_code_server(container_name: str, workspace_id: str, port: int = 8443) -> None:
    """Start code-server inside the container (detached)."""
    cmd = (
        f"code-server "
        f"--bind-addr 0.0.0.0:{port} "
        f"--auth none "
        f"--disable-telemetry "
        f"--disable-update-check "
        f"--disable-getting-started-override "
        f"/workspace"
    )
    wrapped = f"nohup {cmd} > /tmp/code-server.log 2>&1 &"
    rc, out = await _docker_exec(container_name, wrapped)
    if rc != 0:
        logger.error("Failed to start code-server in %s: rc=%d output=%s", container_name, rc, out)
        return
    logger.info("Started code-server in %s on port %d", container_name, port)

    # Give it a moment then check if it's actually alive
    await asyncio.sleep(2)
    if not await is_code_server_running(container_name):
        rc, log = await _docker_exec(container_name, "cat /tmp/code-server.log")
        logger.error("code-server died immediately in %s. Log:\n%s", container_name, log[-2000:])


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

    host = "host.docker.internal" if settings.WORKSPACE_LOCAL_DIR else "127.0.0.1"
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
    """Orchestrate: allocate port -> ensure container with port -> install -> start.

    Returns {"editor_url": str, "editor_port": int}.
    """
    logger.info(
        "ensure_editor: ws=%s container=%s status=%s port=%s enabled=%s",
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
        async with async_session() as db:
            await db.execute(
                update(SharedWorkspace)
                .where(SharedWorkspace.id == ws.id)
                .values(editor_enabled=True)
            )
            await db.commit()
        ws.editor_enabled = True
        need_recreate = True

    # 2. Ensure container is running with editor port mapped
    container_alive = ws.container_name and await _container_actually_running(ws.container_name)

    if container_alive:
        # Check if port 8443 is actually mapped
        proc = await asyncio.create_subprocess_exec(
            "docker", "port", ws.container_name, "8443",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout.strip():
            logger.info("Port 8443 mapped: %s", stdout.decode().strip())
        else:
            logger.info("Recreating %s to add editor port mapping", ws.container_name)
            await shared_workspace_service.recreate(ws)
            async with async_session() as db:
                ws = await db.get(SharedWorkspace, ws.id)
    else:
        logger.info("Container not running, starting for workspace %s", ws.id)
        await shared_workspace_service.ensure_container(ws)
        async with async_session() as db:
            ws = await db.get(SharedWorkspace, ws.id)

    if not ws.container_name:
        raise RuntimeError("No container after ensure_container")

    # 3. Install code-server if needed
    if not await is_code_server_installed(ws.container_name):
        await install_code_server(ws.container_name)

    # 4. Start code-server if not running
    if not await is_code_server_running(ws.container_name):
        await start_code_server(ws.container_name, str(ws.id))

    # 5. Wait for healthy
    if ws.editor_port:
        await _wait_for_healthy(ws.editor_port, timeout=15)

    editor_url = f"/api/v1/workspaces/{ws.id}/editor/"
    logger.info("ensure_editor done: container=%s port=%s", ws.container_name, ws.editor_port)
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
