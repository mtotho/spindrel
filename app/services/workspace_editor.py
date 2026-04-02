"""Workspace code editor service — on-demand code-server inside workspace containers."""
import asyncio
import logging
import os
import platform
import shutil

from sqlalchemy import select, update

from app.config import settings
from app.db.engine import async_session
from app.db.models import SharedWorkspace
from app.services.shared_workspace import shared_workspace_service

logger = logging.getLogger(__name__)

CODE_SERVER_VERSION = "4.96.4"
CACHE_DIR = os.path.expanduser("~/.agent-workspaces/.cache/code-server")
CONTAINER_INSTALL_DIR = "/usr/local/lib/code-server"

CHAT_EXTENSION_SRC = os.path.join(
    os.path.dirname(__file__), "..", "..", "integrations", "vscode", "extension"
)
CHAT_EXTENSION_CACHE = os.path.expanduser("~/.agent-workspaces/.cache/spindrel-chat")
CONTAINER_EXTENSION_DIR = "/home/agent/.local/share/code-server/extensions/spindrel-chat"

_download_lock = asyncio.Lock()


async def _docker_exec(container_name: str, cmd: str) -> tuple[int, str]:
    return await shared_workspace_service._docker_exec(container_name, cmd)


def _download_url() -> str:
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
    """Download + extract code-server tarball to host cache. Returns unpacked dir."""
    async with _download_lock:
        unpacked = _cached_dir()
        marker = os.path.join(unpacked, ".patched")
        if os.path.isfile(marker):
            return unpacked

        # Clear broken extraction
        if os.path.isdir(unpacked):
            shutil.rmtree(unpacked)

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
                if os.path.exists(tarball):
                    os.remove(tarball)
                raise RuntimeError(f"Failed to download code-server: {stderr.decode()}")

        logger.info("Extracting code-server tarball to %s", unpacked)
        os.makedirs(unpacked, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "tar", "xzf", tarball, "--strip-components=1", "-C", unpacked,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"tar extract failed: {stderr.decode()}")

        # Patch the wrapper script to use system node instead of bundled lib/node.
        # The bundled node binary often fails in slim containers (dynamic linker mismatch).
        wrapper = os.path.join(unpacked, "bin", "code-server")
        if os.path.isfile(wrapper):
            with open(wrapper) as f:
                content = f.read()
            # Replace the exec line that runs the bundled node
            patched = content.replace(
                'exec "$ROOT/lib/node"',
                'exec node',
            )
            with open(wrapper, "w") as f:
                f.write(patched)
            os.chmod(wrapper, 0o755)
            logger.info("Patched code-server wrapper to use system node")

        # Write marker so we know extraction + patching is complete
        with open(marker, "w") as f:
            f.write("ok")

        logger.info("code-server %s ready at %s", CODE_SERVER_VERSION, unpacked)
    return unpacked


async def install_code_server(container_name: str) -> None:
    """Copy cached code-server into a running container via docker cp."""
    src = await _ensure_downloaded()

    proc = await asyncio.create_subprocess_exec(
        "docker", "cp", f"{src}/.", f"{container_name}:{CONTAINER_INSTALL_DIR}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"docker cp failed: {stderr.decode()}")

    # Ensure wrapper is executable
    await _docker_exec(container_name, f"chmod +x {CONTAINER_INSTALL_DIR}/bin/code-server")

    # Verify it works
    rc, out = await _docker_exec(container_name, f"{CONTAINER_INSTALL_DIR}/bin/code-server --version")
    if rc != 0:
        logger.error("code-server --version failed after install: %s", out)
        raise RuntimeError(f"code-server verify failed: {out}")
    logger.info("code-server installed and verified in %s: %s", container_name, out.split('\n')[0])


async def is_code_server_installed(container_name: str) -> bool:
    rc, _ = await _docker_exec(container_name, f"{CONTAINER_INSTALL_DIR}/bin/code-server --version")
    return rc == 0


async def start_code_server(container_name: str, workspace_id: str, port: int = 8443) -> None:
    cmd = (
        f"{CONTAINER_INSTALL_DIR}/bin/code-server "
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
        logger.error("Failed to start code-server: rc=%d output=%s", rc, out)
        return
    logger.info("Started code-server in %s on port %d", container_name, port)

    await asyncio.sleep(2)
    if not await is_code_server_running(container_name):
        _, log = await _docker_exec(container_name, "cat /tmp/code-server.log")
        logger.error("code-server died in %s. Log:\n%s", container_name, log[-2000:])


async def is_code_server_running(container_name: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "docker", "exec", container_name, "pgrep", "-f", "code-server",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return proc.returncode == 0


async def _wait_for_healthy(port: int, timeout: int = 30) -> None:
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
    logger.warning("code-server on port %d not healthy within %ds", port, timeout)


async def allocate_editor_port() -> int:
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
    proc = await asyncio.create_subprocess_exec(
        "docker", "inspect", "-f", "{{.State.Running}}", container_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode == 0 and stdout.decode().strip() == "true"


async def ensure_editor(ws: SharedWorkspace) -> dict:
    """Ensure editor is enabled, container has port mapping, code-server is installed and running."""
    logger.info(
        "ensure_editor: ws=%s container=%s status=%s port=%s enabled=%s",
        ws.id, ws.container_name, ws.status, ws.editor_port, ws.editor_enabled,
    )

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
    elif not ws.editor_enabled:
        async with async_session() as db:
            await db.execute(
                update(SharedWorkspace)
                .where(SharedWorkspace.id == ws.id)
                .values(editor_enabled=True)
            )
            await db.commit()
        ws.editor_enabled = True

    # 2. Ensure container is running with editor port mapped
    container_alive = ws.container_name and await _container_actually_running(ws.container_name)

    if container_alive:
        proc = await asyncio.create_subprocess_exec(
            "docker", "port", ws.container_name, "8443",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if not (proc.returncode == 0 and stdout.strip()):
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

    # 3. Install code-server if not present (docker cp, no network needed)
    if not await is_code_server_installed(ws.container_name):
        await install_code_server(ws.container_name)

    # 3b. Install chat extension alongside code-server
    await install_chat_extension(ws.container_name)

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


async def _build_chat_extension() -> str | None:
    """Build the VS Code chat extension if source exists. Returns path to built extension or None."""
    src = os.path.normpath(CHAT_EXTENSION_SRC)
    pkg_json = os.path.join(src, "package.json")
    if not os.path.isfile(pkg_json):
        logger.debug("Chat extension source not found at %s", src)
        return None

    marker = os.path.join(CHAT_EXTENSION_CACHE, ".built")
    src_ts = os.path.join(src, "src")

    # Check if rebuild needed — compare source mtime to marker
    if os.path.isfile(marker):
        marker_mtime = os.path.getmtime(marker)
        needs_rebuild = False
        for root, _, files in os.walk(src_ts):
            for f in files:
                if os.path.getmtime(os.path.join(root, f)) > marker_mtime:
                    needs_rebuild = True
                    break
            if needs_rebuild:
                break
        # Also check package.json
        if os.path.getmtime(pkg_json) > marker_mtime:
            needs_rebuild = True
        if not needs_rebuild:
            return CHAT_EXTENSION_CACHE

    logger.info("Building chat extension from %s", src)
    os.makedirs(CHAT_EXTENSION_CACHE, exist_ok=True)

    # npm install (if node_modules missing)
    node_modules = os.path.join(src, "node_modules")
    if not os.path.isdir(node_modules):
        proc = await asyncio.create_subprocess_exec(
            "npm", "ci", "--ignore-scripts",
            cwd=src,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("npm ci failed for chat extension: %s", stderr.decode())
            return None

    # Compile TypeScript
    proc = await asyncio.create_subprocess_exec(
        "npx", "tsc", "-p", "./",
        cwd=src,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error("tsc failed for chat extension: %s", stderr.decode())
        return None

    # Copy built artifacts to cache
    out_dir = os.path.join(src, "out")
    media_dir = os.path.join(src, "media")
    cache_out = os.path.join(CHAT_EXTENSION_CACHE, "out")
    cache_media = os.path.join(CHAT_EXTENSION_CACHE, "media")

    if os.path.isdir(cache_out):
        shutil.rmtree(cache_out)
    shutil.copytree(out_dir, cache_out)

    if os.path.isdir(media_dir):
        if os.path.isdir(cache_media):
            shutil.rmtree(cache_media)
        shutil.copytree(media_dir, cache_media)

    shutil.copy2(pkg_json, os.path.join(CHAT_EXTENSION_CACHE, "package.json"))

    with open(marker, "w") as f:
        f.write("ok")

    logger.info("Chat extension built successfully")
    return CHAT_EXTENSION_CACHE


async def install_chat_extension(container_name: str) -> None:
    """Build and install the Spindrel chat extension into a workspace container."""
    ext_path = await _build_chat_extension()
    if not ext_path:
        logger.debug("Skipping chat extension install — not built")
        return

    # Create extension directory in container
    await _docker_exec(container_name, f"mkdir -p {CONTAINER_EXTENSION_DIR}")

    # docker cp the built extension
    proc = await asyncio.create_subprocess_exec(
        "docker", "cp", f"{ext_path}/.", f"{container_name}:{CONTAINER_EXTENSION_DIR}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error("Failed to install chat extension: %s", stderr.decode())
        return

    logger.info("Chat extension installed in %s", container_name)


async def write_chat_config(
    container_name: str,
    server_url: str,
    token: str,
    user_id: str | None = None,
    user_email: str | None = None,
) -> None:
    """Write the chat extension config file into a workspace container."""
    import json

    config = {"serverUrl": server_url, "token": token}
    if user_id:
        config["userId"] = user_id
    if user_email:
        config["userEmail"] = user_email

    config_json = json.dumps(config)
    # Escape for shell
    escaped = config_json.replace("'", "'\\''")

    await _docker_exec(
        container_name,
        f"mkdir -p /home/agent/.spindrel-chat && echo '{escaped}' > /home/agent/.spindrel-chat/config.json",
    )


async def disable_editor(ws: SharedWorkspace) -> None:
    async with async_session() as db:
        await db.execute(
            update(SharedWorkspace)
            .where(SharedWorkspace.id == ws.id)
            .values(editor_enabled=False)
        )
        await db.commit()


async def editor_status(ws: SharedWorkspace) -> dict:
    running = False
    if ws.container_name and ws.editor_enabled:
        running = await is_code_server_running(ws.container_name)
    return {
        "editor_enabled": ws.editor_enabled,
        "editor_port": ws.editor_port,
        "editor_running": running,
        "editor_url": f"/api/v1/workspaces/{ws.id}/editor/" if ws.editor_enabled else None,
    }
