"""Shared workspace service — subprocess exec + file ops for multi-bot workspaces.

Workspaces are directories on the host (or mounted volume). Commands run via
subprocess in the server process — no separate Docker container.
"""
import asyncio
import fnmatch
import logging
import os
import re
import shlex
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.services.paths import local_workspace_base
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


class SharedWorkspaceService:
    """Manages shared workspace directories and command execution."""

    # ── Path management ──────────────────────────────────────────

    def get_host_root(self, workspace_id: str) -> str:
        """Root directory for workspace file I/O."""
        base = local_workspace_base()
        return os.path.join(base, "shared", workspace_id)

    def ensure_host_dirs(self, workspace_id: str) -> str:
        """Create the workspace directory structure. Returns root."""
        root = self.get_host_root(workspace_id)
        for subdir in ("bots", "common", "users", "integrations"):
            os.makedirs(os.path.join(root, subdir), exist_ok=True)
        return root

    def ensure_bot_dir(self, workspace_id: str, bot_id: str) -> str:
        """Ensure bots/<bot_id>/ exists inside the workspace.

        Also creates bots/<bot_id>/knowledge-base/ — the convention-based folder
        every bot gets for auto-indexed, auto-retrievable knowledge.
        """
        root = self.get_host_root(workspace_id)
        bot_dir = os.path.join(root, "bots", bot_id)
        os.makedirs(bot_dir, exist_ok=True)
        os.makedirs(os.path.join(bot_dir, "knowledge-base"), exist_ok=True)
        return bot_dir

    def get_bot_cwd(
        self, bot_id: str, role: str, cwd_override: str | None,
    ) -> str:
        """Working directory for a bot in a shared workspace."""
        if cwd_override:
            return cwd_override
        ws_root = local_workspace_base()
        # Return absolute host path — no container path translation needed
        return os.path.join(ws_root, "shared", "{workspace_id}", "bots", bot_id)

    def get_bot_cwd_for_workspace(
        self, workspace_id: str, bot_id: str, role: str, cwd_override: str | None,
    ) -> str:
        """Working directory for a bot, resolved to actual host path."""
        if cwd_override:
            # If cwd_override is a container-style path, translate it
            if cwd_override.startswith("/workspace/"):
                return self.translate_path(workspace_id, cwd_override)
            return cwd_override
        return self.ensure_bot_dir(workspace_id, bot_id)

    def translate_path(self, workspace_id: str, container_path: str) -> str:
        """Map a legacy container-side path (/workspace/...) to a host-side path.

        After the workspace collapse, all paths are host-side. This handles
        backward compat for any stored /workspace/ paths in the DB or bot config.
        """
        host_root = self.get_host_root(workspace_id)
        if container_path.startswith("/workspace/"):
            return os.path.join(host_root, container_path[len("/workspace/"):])
        if container_path == "/workspace":
            return host_root
        return container_path

    _ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    # Safe env vars to pass through to subprocess (same pattern as host_exec).
    # Server secrets (DATABASE_URL, JWT_SECRET, API_KEY, ENCRYPTION_KEY, etc.)
    # are intentionally excluded — bots get only what they need.
    _ENV_PASSTHROUGH = {"PATH", "HOME", "USER", "LANG", "TERM", "SHELL", "TMPDIR", "TZ"}

    def _build_env(self, ws: SharedWorkspace) -> dict[str, str]:
        """Build a sanitized environment dict for subprocess execution.

        Starts with an empty dict and only passes through safe system vars.
        Server secrets are never leaked — bots get per-bot API keys and
        user-managed secret values instead.
        """
        # Start clean — only pass through safe system vars
        env = {k: v for k, v in os.environ.items() if k in self._ENV_PASSTHROUGH}
        # Add workspace-configured env vars
        for k, v in (ws.env or {}).items():
            if k and self._ENV_NAME_RE.match(k) and "\x00" not in str(v):
                env[k] = str(v)
        # Auto-inject server API access (setdefault so workspace env can override).
        # Same-container subprocesses use SERVER_INTERNAL_URL (localhost) — they
        # can't resolve host.docker.internal, which is only wired into sidecar
        # containers launched by sandbox.py.
        env.setdefault("AGENT_SERVER_URL", settings.SERVER_INTERNAL_URL)
        return env

    # ── Write protection ───────────────────────────────────────────

    def _check_write_protection(
        self,
        bot_id: str,
        ws: SharedWorkspace,
        swb: "SharedWorkspaceBot | None",
        command: str,
        working_dir: str,
    ) -> None:
        """Raise SharedWorkspaceError if command would write to a protected path."""
        protected: list[str] = ws.write_protected_paths or []
        if not protected:
            return

        bot_write_access: list[str] = (swb.write_access if swb else None) or []

        for pattern in protected:
            if any(fnmatch.fnmatch(pattern, exempt) for exempt in bot_write_access):
                continue

            if fnmatch.fnmatch(working_dir, pattern) or (
                working_dir.startswith(pattern.rstrip("*").rstrip("/") + "/")
            ):
                if self._command_has_write_intent(command):
                    raise SharedWorkspaceError(
                        f"Write blocked: {working_dir} is within protected path {pattern}"
                    )

            base = pattern.rstrip("*").rstrip("/")
            if base and re.search(re.escape(base), command):
                if self._command_has_write_intent(command):
                    raise SharedWorkspaceError(
                        f"Write blocked: {base} is protected"
                    )

    @staticmethod
    def _command_has_write_intent(command: str) -> bool:
        """Heuristic: does this command look like it intends to write/modify files?"""
        if re.search(r'>{1,2}\s*\S', command):
            return True
        if re.search(
            r'\b(?:rm|mv|touch|mkdir|chmod|chown|tee|dd|cp|rsync|install)\b',
            command,
        ):
            return True
        if re.search(r'\bsed\b.*\s-i', command):
            return True
        if re.search(r'\b(?:pip|npm|yarn|pnpm)\s+install\b', command):
            return True
        return False

    # ── Command execution ──────────────────────────────────────────

    async def exec(
        self,
        ws: SharedWorkspace,
        bot_id: str,
        command: str,
        working_dir: str = "",
        timeout: int | None = None,
        max_bytes: int | None = None,
    ) -> ExecResult:
        """Execute a command via subprocess in the workspace directory."""
        # Ensure workspace dirs exist
        self.ensure_host_dirs(str(ws.id))

        # Look up bot's workspace membership
        async with async_session() as db:
            swb = (await db.execute(
                select(SharedWorkspaceBot).where(
                    SharedWorkspaceBot.workspace_id == ws.id,
                    SharedWorkspaceBot.bot_id == bot_id,
                )
            )).scalar_one_or_none()

        # Determine working directory
        if not working_dir:
            working_dir = self.get_bot_cwd_for_workspace(
                str(ws.id), bot_id,
                swb.role if swb else "member",
                swb.cwd_override if swb else None,
            )
        elif working_dir.startswith("/workspace/"):
            # Translate legacy container paths
            working_dir = self.translate_path(str(ws.id), working_dir)

        # Ensure working directory exists
        os.makedirs(working_dir, exist_ok=True)

        # Enforce write protection
        self._check_write_protection(bot_id, ws, swb, command, working_dir)

        full_cmd = f"umask 0000 && {command}"
        _timeout = timeout or 30
        _max_bytes = max_bytes or 65536

        # Build environment
        env = self._build_env(ws)

        # Inject per-bot API key
        try:
            from app.services.api_keys import get_bot_api_key_value
            async with async_session() as _db:
                bot_key = await get_bot_api_key_value(_db, bot_id)
            if bot_key:
                env["AGENT_SERVER_API_KEY"] = bot_key
        except Exception:
            pass

        # Inject secret values
        try:
            from app.services.secret_values import get_env_dict as _get_secret_env
            for _sk, _sv in _get_secret_env().items():
                if self._ENV_NAME_RE.match(_sk) and "\x00" not in str(_sv):
                    env[_sk] = str(_sv)
        except Exception:
            pass

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", full_cmd,
            cwd=working_dir,
            env=env,
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

    # ── File browser ─────────────────────────────────────────────

    def list_files(self, workspace_id: str, path: str = "/") -> list[dict]:
        """List files/dirs at a path inside the workspace."""
        host_root = os.path.realpath(self.get_host_root(workspace_id))
        if path == "/" or not path:
            target = host_root
        else:
            rel = path.lstrip("/")
            if rel.startswith("workspace/"):
                rel = rel[len("workspace/"):]
            target = os.path.join(host_root, rel)

        target = os.path.realpath(target)
        if not target.startswith(host_root):
            return []

        entries = []
        try:
            for entry in sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name)):
                if entry.is_symlink():
                    continue
                real_entry = os.path.realpath(entry.path)
                if not (real_entry == host_root or real_entry.startswith(host_root + os.sep)):
                    continue
                stat = entry.stat()
                item: dict = {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if entry.is_file() else None,
                    "path": os.path.relpath(real_entry, host_root),
                    "modified_at": stat.st_mtime,
                }
                if entry.is_dir():
                    info_path = os.path.join(real_entry, ".channel_info")
                    if os.path.isfile(info_path) and not os.path.islink(info_path):
                        try:
                            for line in open(info_path).readlines():
                                if line.startswith("display_name:"):
                                    item["display_name"] = line.split(":", 1)[1].strip()
                                    break
                        except Exception:
                            pass
                entries.append(item)
        except OSError:
            pass
        return entries

    def _resolve_path(self, workspace_id: str, path: str) -> str | None:
        """Resolve a workspace-relative path to a host-side path with security check."""
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
        """Read file content from workspace."""
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

    def read_file_bytes(self, workspace_id: str, path: str) -> bytes:
        """Read raw file bytes from workspace."""
        target = self._resolve_path(workspace_id, path)
        if target is None:
            raise SharedWorkspaceError("Path escapes workspace root")
        if not os.path.isfile(target):
            raise SharedWorkspaceError("Not a file or does not exist")
        with open(target, "rb") as f:
            return f.read()

    def write_file(self, workspace_id: str, path: str, content: str) -> dict:
        """Write content to a file in the workspace."""
        target = self._resolve_path(workspace_id, path)
        if target is None:
            raise SharedWorkspaceError("Path escapes workspace root")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        size = os.path.getsize(target)
        return {"path": path, "size": size}

    def write_binary_file(self, workspace_id: str, path: str, content: bytes) -> dict:
        """Write binary content to a file in the workspace."""
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
            parent = os.path.dirname(path)
            os.chmod(parent, os.stat(parent).st_mode | 0o700)
            if os.path.isdir(path):
                os.chmod(path, os.stat(path).st_mode | 0o700)
            else:
                os.chmod(path, os.stat(path).st_mode | 0o600)
            func(path)
        else:
            raise exc

    def move_path(self, workspace_id: str, src: str, dst: str) -> dict:
        """Move a file or directory within the workspace."""
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

        if os.path.isdir(dst_target):
            dst_target = os.path.join(dst_target, os.path.basename(src_target))

        if os.path.isdir(src_target):
            real_dst = os.path.realpath(dst_target)
            real_src = os.path.realpath(src_target)
            if real_dst.startswith(real_src + os.sep) or real_dst == real_src:
                raise SharedWorkspaceError("Cannot move a directory into itself")

        if not os.path.realpath(dst_target).startswith(host_root):
            raise SharedWorkspaceError("Destination escapes workspace root")

        os.makedirs(os.path.dirname(dst_target), exist_ok=True)
        shutil.move(src_target, dst_target)

        final_rel = os.path.relpath(os.path.realpath(dst_target), host_root)
        return {"src": src, "dst": final_rel}


shared_workspace_service = SharedWorkspaceService()
