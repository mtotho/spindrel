"""Shared workspace service — container lifecycle + file ops for multi-bot workspaces."""
import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from app.config import settings
from app.services.paths import local_workspace_base, local_to_host
from app.db.engine import async_session
from app.db.models import SharedWorkspace, SharedWorkspaceBot

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    duration_ms: int


class SharedWorkspaceError(Exception):
    pass


def _slug(name: str) -> str:
    """Slugify a workspace name for container naming."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32]


class SharedWorkspaceService:
    """Manages shared workspace containers and file operations."""

    # ── Path management ──────────────────────────────────────────

    def get_host_root(self, workspace_id: str) -> str:
        """Local-side root for file I/O: ~/.agent-workspaces/shared/<workspace_id>/"""
        base = local_workspace_base()
        return os.path.join(base, "shared", workspace_id)

    def ensure_host_dirs(self, workspace_id: str) -> str:
        """Create the workspace directory structure on the host. Returns root."""
        root = self.get_host_root(workspace_id)
        for subdir in ("bots", "common", "users"):
            os.makedirs(os.path.join(root, subdir), exist_ok=True)
        return root

    def ensure_bot_dir(self, workspace_id: str, bot_id: str) -> str:
        """Ensure bots/<bot_id>/ exists inside the workspace."""
        root = self.get_host_root(workspace_id)
        bot_dir = os.path.join(root, "bots", bot_id)
        os.makedirs(bot_dir, exist_ok=True)
        return bot_dir

    def get_bot_cwd(
        self, bot_id: str, role: str, cwd_override: str | None,
    ) -> str:
        """Container-side cwd for a bot in a shared workspace."""
        if cwd_override:
            return cwd_override
        return f"/workspace/bots/{bot_id}"

    def translate_path(self, workspace_id: str, container_path: str) -> str:
        """Map a container-side path to a host-side path."""
        host_root = self.get_host_root(workspace_id)
        if container_path.startswith("/workspace/"):
            return os.path.join(host_root, container_path[len("/workspace/"):])
        if container_path == "/workspace":
            return host_root
        return container_path

    def _container_name(self, ws: SharedWorkspace) -> str:
        """Deterministic container name: agent-ws-<slug>-<id-hex[:8]>"""
        return f"agent-ws-{_slug(ws.name)}-{str(ws.id).replace('-', '')[:8]}"

    def _build_env(self, ws: SharedWorkspace) -> dict[str, str]:
        """Build environment dict with auto-injected server credentials."""
        env = dict(ws.env or {})
        # Auto-inject server API access so bots inside can call back
        env.setdefault("AGENT_SERVER_URL", settings.SERVER_PUBLIC_URL)
        env.setdefault("AGENT_SERVER_API_KEY", settings.API_KEY)
        return env

    # ── Container lifecycle ──────────────────────────────────────

    async def ensure_container(self, ws: SharedWorkspace) -> str:
        """Start the workspace container if not already running. Returns container_id."""
        if ws.container_id:
            # Check if still running
            status = await self.inspect_status(ws)
            if status == "running":
                return ws.container_id

        host_root = self.ensure_host_dirs(str(ws.id))
        container_name = self._container_name(ws)
        env = self._build_env(ws)

        # Build docker run command
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", ws.network or "none",
        ]
        # Env vars (skip empty keys)
        for k, v in env.items():
            if k:
                cmd += ["-e", f"{k}={v}"]
        # Workspace volume (translate to host path for docker -v)
        cmd += ["-v", f"{local_to_host(host_root)}:/workspace"]
        # Extra mounts
        for mount in (ws.mounts or []):
            host = mount.get("host_path", "")
            container = mount.get("container_path", "")
            mode = mount.get("mode", "rw")
            if host and container:
                cmd += ["-v", f"{host}:{container}:{mode}"]
        # Port mappings
        for port in (ws.ports or []):
            if isinstance(port, str):
                cmd += ["-p", port]
            elif isinstance(port, dict):
                host_port = port.get("host", "")
                container_port = port.get("container", "")
                if host_port and container_port:
                    cmd += ["-p", f"{host_port}:{container_port}"]
        # Editor port mapping (code-server)
        if ws.editor_enabled and ws.editor_port:
            cmd += ["-p", f"127.0.0.1:{ws.editor_port}:8443"]
        # Resource limits
        if ws.cpus:
            cmd += ["--cpus", str(ws.cpus)]
        if ws.memory_limit:
            cmd += ["--memory", ws.memory_limit]
        # User
        if ws.docker_user:
            cmd += ["--user", ws.docker_user]
        # Read-only root
        if ws.read_only_root:
            cmd += ["--read-only"]
        # Add host.docker.internal for API access
        cmd += ["--add-host", "host.docker.internal:host-gateway"]
        # Image + keep-alive command
        cmd += [ws.image, "sleep", "infinity"]

        # Remove existing container if any
        await self._remove_container(container_name)

        logger.info("Starting shared workspace container: %s (image=%s)", container_name, ws.image)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode().strip()
            logger.error("Failed to start workspace container %s: %s", container_name, err)
            await self._update_status(ws.id, "error")
            raise SharedWorkspaceError(f"Container start failed: {err}")

        container_id = stdout.decode().strip()[:12]
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            await db.execute(
                update(SharedWorkspace)
                .where(SharedWorkspace.id == ws.id)
                .values(
                    container_id=container_id,
                    container_name=container_name,
                    status="running",
                    last_started_at=now,
                    updated_at=now,
                )
            )
            await db.commit()

        # Ensure bot directories exist inside the container
        async with async_session() as db:
            sw_bots = (await db.execute(
                select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws.id)
            )).scalars().all()
        for swb in sw_bots:
            bot_dir = f"/workspace/bots/{swb.bot_id}"
            await self._docker_exec(container_name, f"mkdir -p {bot_dir}")

        # Run startup script if configured
        if ws.startup_script:
            await self._run_startup_script(container_name, ws.startup_script)

        logger.info("Workspace container %s started: %s", container_name, container_id)
        return container_id

    async def exec(
        self,
        ws: SharedWorkspace,
        bot_id: str,
        command: str,
        working_dir: str = "",
        timeout: int | None = None,
        max_bytes: int | None = None,
    ) -> ExecResult:
        """Execute a command in the workspace container as a specific bot."""
        if ws.status != "running" or not ws.container_name:
            await self.ensure_container(ws)
            # Reload status
            async with async_session() as db:
                ws = await db.get(SharedWorkspace, ws.id)

        # Determine working directory
        if not working_dir:
            # Look up bot's role/cwd from junction
            async with async_session() as db:
                swb = (await db.execute(
                    select(SharedWorkspaceBot).where(
                        SharedWorkspaceBot.workspace_id == ws.id,
                        SharedWorkspaceBot.bot_id == bot_id,
                    )
                )).scalar_one_or_none()
            if swb:
                working_dir = self.get_bot_cwd(bot_id, swb.role, swb.cwd_override)
            else:
                working_dir = f"/workspace/bots/{bot_id}"

        full_cmd = f"cd {working_dir} && {command}"
        _timeout = timeout or 30
        _max_bytes = max_bytes or 65536

        # Build docker exec command, optionally injecting per-bot API key
        exec_args = ["docker", "exec"]
        try:
            from app.services.api_keys import get_bot_api_key_value
            async with async_session() as _db:
                bot_key = await get_bot_api_key_value(_db, bot_id)
            if bot_key:
                exec_args += ["-e", f"AGENT_SERVER_API_KEY={bot_key}"]
        except Exception:
            pass  # Fall back to container-level env
        exec_args += [ws.container_name, "sh", "-c", full_cmd]

        import time
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *exec_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed = int((time.monotonic() - start) * 1000)
            return ExecResult(
                stdout="", stderr=f"Command timed out after {_timeout}s",
                exit_code=-1, truncated=False, duration_ms=elapsed,
            )

        elapsed = int((time.monotonic() - start) * 1000)
        stdout_str = stdout_bytes[:_max_bytes].decode(errors="replace")
        stderr_str = stderr_bytes[:_max_bytes].decode(errors="replace")
        truncated = len(stdout_bytes) > _max_bytes or len(stderr_bytes) > _max_bytes

        return ExecResult(
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=proc.returncode or 0,
            truncated=truncated,
            duration_ms=elapsed,
        )

    async def stop(self, ws: SharedWorkspace) -> None:
        """Stop the workspace container."""
        if ws.container_name:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", ws.container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        await self._update_status(ws.id, "stopped")
        logger.info("Stopped workspace container: %s", ws.container_name)

    async def recreate(self, ws: SharedWorkspace) -> str:
        """Stop, remove, and recreate the workspace container."""
        if ws.container_name:
            await self._remove_container(ws.container_name)
        await self._update_status(ws.id, "stopped", clear_container=True)
        # Reload
        async with async_session() as db:
            ws = await db.get(SharedWorkspace, ws.id)
        return await self.ensure_container(ws)

    async def pull_image(self, image: str) -> tuple[bool, str]:
        """Pull a Docker image. Returns (success, output)."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "pull", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = (stdout.decode() + stderr.decode()).strip()
        return proc.returncode == 0, output

    async def get_logs(self, ws: SharedWorkspace, tail: int = 300) -> str:
        """Get container logs."""
        if not ws.container_name:
            return ""
        proc = await asyncio.create_subprocess_exec(
            "docker", "logs", "--tail", str(tail), ws.container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()

    async def inspect_status(self, ws: SharedWorkspace) -> str:
        """Get live container status via docker inspect."""
        if not ws.container_name:
            return "stopped"
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{.State.Status}}", ws.container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return "stopped"
        return stdout.decode().strip() or "unknown"

    async def _run_startup_script(self, container_name: str, script_path: str) -> None:
        """Run a startup script inside the container. Logs output, warns on failure."""
        # Check if the script exists
        rc, _ = await self._docker_exec(container_name, f"test -f {script_path}")
        if rc != 0:
            logger.info("Startup script %s not found in %s, skipping", script_path, container_name)
            return

        logger.info("Running startup script %s in %s", script_path, container_name)
        rc, output = await self._docker_exec(
            container_name, f"chmod +x {script_path} && {script_path}"
        )
        if rc != 0:
            logger.warning(
                "Startup script %s failed (exit %d) in %s: %s",
                script_path, rc, container_name, output[:500],
            )
        else:
            logger.info("Startup script %s completed in %s: %s", script_path, container_name, output[:200])

    # ── File browser ─────────────────────────────────────────────

    def list_files(self, workspace_id: str, path: str = "/") -> list[dict]:
        """List files/dirs at a path inside the workspace (host-side)."""
        host_root = os.path.realpath(self.get_host_root(workspace_id))
        if path == "/" or not path:
            target = host_root
        else:
            # Normalize: strip leading /workspace/
            rel = path.lstrip("/")
            if rel.startswith("workspace/"):
                rel = rel[len("workspace/"):]
            target = os.path.join(host_root, rel)

        target = os.path.realpath(target)
        # Security: ensure within host_root
        if not target.startswith(host_root):
            return []

        entries = []
        try:
            for entry in sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name)):
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if entry.is_file() else None,
                    "path": os.path.relpath(os.path.realpath(entry.path), host_root),
                    "modified_at": stat.st_mtime,
                })
        except OSError:
            pass
        return entries

    def _resolve_path(self, workspace_id: str, path: str) -> str | None:
        """Resolve a workspace-relative path to a host-side path with security check.
        Returns None if the path escapes the workspace root."""
        host_root = self.get_host_root(workspace_id)
        rel = path.lstrip("/")
        if rel.startswith("workspace/"):
            rel = rel[len("workspace/"):]
        target = os.path.realpath(os.path.join(host_root, rel))
        if not target.startswith(os.path.realpath(host_root)):
            return None
        return target

    MAX_READ_SIZE = 1024 * 1024  # 1MB

    def read_file(self, workspace_id: str, path: str) -> dict:
        """Read file content from workspace. Returns {path, content, size, modified_at} or raises."""
        target = self._resolve_path(workspace_id, path)
        if target is None:
            raise SharedWorkspaceError("Path escapes workspace root")
        if not os.path.isfile(target):
            raise SharedWorkspaceError("Not a file or does not exist")
        stat = os.stat(target)
        size = stat.st_size
        if size > self.MAX_READ_SIZE:
            raise SharedWorkspaceError(f"File too large ({size} bytes, max {self.MAX_READ_SIZE})")
        try:
            with open(target, "r", encoding="utf-8", errors="strict") as f:
                content = f.read()
        except UnicodeDecodeError:
            raise SharedWorkspaceError("Binary file — cannot display")
        return {"path": path, "content": content, "size": size, "modified_at": stat.st_mtime}

    def write_file(self, workspace_id: str, path: str, content: str) -> dict:
        """Write content to a file in the workspace. Creates parent dirs if needed."""
        target = self._resolve_path(workspace_id, path)
        if target is None:
            raise SharedWorkspaceError("Path escapes workspace root")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        size = os.path.getsize(target)
        return {"path": path, "size": size}

    def write_binary_file(self, workspace_id: str, path: str, content: bytes) -> dict:
        """Write binary content to a file in the workspace. Creates parent dirs if needed."""
        target = self._resolve_path(workspace_id, path)
        if target is None:
            raise SharedWorkspaceError("Path escapes workspace root")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(content)
        size = os.path.getsize(target)
        return {"path": path, "size": size}

    def mkdir(self, workspace_id: str, path: str) -> dict:
        """Create a directory (and parents) in the workspace."""
        target = self._resolve_path(workspace_id, path)
        if target is None:
            raise SharedWorkspaceError("Path escapes workspace root")
        os.makedirs(target, exist_ok=True)
        return {"path": path}

    def delete_path(self, workspace_id: str, path: str) -> dict:
        """Delete a file or directory in the workspace."""
        target = self._resolve_path(workspace_id, path)
        if target is None:
            raise SharedWorkspaceError("Path escapes workspace root")
        host_root = os.path.realpath(self.get_host_root(workspace_id))
        if target == host_root:
            raise SharedWorkspaceError("Cannot delete workspace root")
        if not os.path.exists(target):
            raise SharedWorkspaceError("Path does not exist")
        if os.path.isdir(target):
            shutil.rmtree(target, onexc=self._force_remove)
        else:
            try:
                os.remove(target)
            except PermissionError:
                os.chmod(target, 0o700)
                os.remove(target)
        return {"path": path, "deleted": True}

    @staticmethod
    def _force_remove(func, path, exc):
        """onexc handler for shutil.rmtree — chmod and retry on PermissionError."""
        if isinstance(exc, PermissionError):
            # Ensure the parent dir is writable (needed to unlink children)
            parent = os.path.dirname(path)
            os.chmod(parent, os.stat(parent).st_mode | 0o700)
            # Ensure the path itself is writable (needed for dirs)
            if os.path.isdir(path):
                os.chmod(path, os.stat(path).st_mode | 0o700)
            else:
                os.chmod(path, os.stat(path).st_mode | 0o600)
            func(path)
        else:
            raise exc

    def move_path(self, workspace_id: str, src: str, dst: str) -> dict:
        """Move a file or directory within the workspace.

        If dst is an existing directory, the source is moved inside it.
        Returns {"src": <original>, "dst": <final workspace-relative path>}.
        """
        host_root = os.path.realpath(self.get_host_root(workspace_id))
        src_target = self._resolve_path(workspace_id, src)
        if src_target is None:
            raise SharedWorkspaceError("Source path escapes workspace root")
        if not os.path.exists(src_target):
            raise SharedWorkspaceError("Source path does not exist")
        if src_target == host_root:
            raise SharedWorkspaceError("Cannot move workspace root")

        dst_target = self._resolve_path(workspace_id, dst)
        if dst_target is None:
            raise SharedWorkspaceError("Destination path escapes workspace root")

        # If dst is an existing directory, move src inside it
        if os.path.isdir(dst_target):
            dst_target = os.path.join(dst_target, os.path.basename(src_target))

        # Guard: can't move a directory into itself or its own child
        if os.path.isdir(src_target):
            real_dst = os.path.realpath(dst_target)
            real_src = os.path.realpath(src_target)
            if real_dst.startswith(real_src + os.sep) or real_dst == real_src:
                raise SharedWorkspaceError("Cannot move a directory into itself")

        # Final security check
        if not os.path.realpath(dst_target).startswith(host_root):
            raise SharedWorkspaceError("Destination escapes workspace root")

        os.makedirs(os.path.dirname(dst_target), exist_ok=True)
        shutil.move(src_target, dst_target)

        final_rel = os.path.relpath(os.path.realpath(dst_target), host_root)
        return {"src": src, "dst": final_rel}

    # ── Internals ────────────────────────────────────────────────

    async def _remove_container(self, name: str) -> None:
        """Force-remove a container by name (ignore errors)."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def _docker_exec(self, container_name: str, command: str) -> tuple[int, str]:
        """Quick helper to exec a command in a running container."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_name, "sh", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, (stdout.decode() + stderr.decode()).strip()

    async def _update_status(
        self, workspace_id, status: str, clear_container: bool = False,
    ) -> None:
        """Update workspace status in DB."""
        values = {"status": status, "updated_at": datetime.now(timezone.utc)}
        if clear_container:
            values["container_id"] = None
            values["container_name"] = None
        async with async_session() as db:
            await db.execute(
                update(SharedWorkspace)
                .where(SharedWorkspace.id == workspace_id)
                .values(**values)
            )
            await db.commit()


shared_workspace_service = SharedWorkspaceService()
