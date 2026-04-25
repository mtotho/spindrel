"""Docker sandbox service — ensure, exec, stop, remove, and lock enforcement."""
import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

from sqlalchemy import func, select

from app.config import settings
from app.db.engine import async_session
from app.db.models import SandboxBotAccess, SandboxInstance, SandboxProfile
from app.services.paths import local_to_host

if TYPE_CHECKING:
    from app.agent.bots import BotConfig, BotSandboxConfig

logger = logging.getLogger(__name__)

# Paths that are never allowed as bind mounts regardless of allowlist
_BLOCKED_MOUNT_PREFIXES = [
    "/var/run/docker.sock",
    "/etc",
    "/proc",
    "/sys",
    "/dev",
]


class SandboxError(Exception):
    pass


class SandboxLockedError(SandboxError):
    pass


class SandboxNotFoundError(SandboxError):
    pass


class SandboxAccessDeniedError(SandboxError):
    pass


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    duration_ms: int


def _validate_mount_specs(mount_specs: list) -> None:
    for spec in mount_specs:
        host_path = spec.get("host_path", "")
        for blocked in _BLOCKED_MOUNT_PREFIXES:
            if host_path == blocked or host_path.startswith(blocked + "/"):
                raise SandboxError(f"Mount path '{host_path}' is not allowed.")
        allowlist = settings.DOCKER_SANDBOX_MOUNT_ALLOWLIST
        if allowlist:
            if not any(
                host_path == allowed or host_path.startswith(allowed.rstrip("/") + "/")
                for allowed in allowlist
            ):
                raise SandboxError(
                    f"Mount path '{host_path}' is not in the mount allowlist. "
                    "Contact your administrator."
                )


# Docker container names: [a-zA-Z0-9][a-zA-Z0-9_.-]* (no ':' etc.). Slack client_ids look like slack:C09...
_DOCKER_NAME_INVALID_RUN = re.compile(r"[^a-zA-Z0-9_.-]+")

# New instances use scope_type=provisioned; scope_key/instance id (legacy rows keep older values).
_SCOPE_TYPE_PROVISIONED = "provisioned"


def _sanitize_docker_name_segment(raw: str, max_len: int) -> str:
    """Turn an arbitrary scope/profile string into a single Docker-legal name segment."""
    v = (raw or "").strip()
    if not v:
        return "x-" + hashlib.sha256(b"").hexdigest()[:12]
    s = _DOCKER_NAME_INVALID_RUN.sub("-", v)
    s = re.sub(r"-{2,}", "-", s).strip("-_.")
    if not s:
        return "x-" + hashlib.sha256(v.encode()).hexdigest()[:12]
    if not s[0].isalnum():
        s = "n-" + s
    if len(s) > max_len:
        digest = hashlib.sha256(v.encode()).hexdigest()[:8]
        head_len = max_len - len(digest) - 1
        s = f"{s[:head_len]}-{digest}" if head_len > 0 else digest[:max_len]
    return s[:max_len]


def _build_container_name(profile_name: str, instance_id: uuid.UUID) -> str:
    profile_seg = _sanitize_docker_name_segment(profile_name, 48)
    suf = instance_id.hex
    name = f"agent-sbx-{profile_seg}-{suf}"
    if len(name) > 253:
        name = name[:253].rstrip("-_.")
    return name


def _build_docker_run_args(
    image: str,
    container_name: str,
    network_mode: str,
    read_only_root: bool,
    create_options: dict,
    env: dict,
    labels: dict,
    mount_specs: list,
    port_mappings: list,
) -> list[str]:
    args = ["docker", "run", "-d", "--name", container_name]

    args += ["--restart", "unless-stopped"]
    args += ["--network", network_mode or "none"]
    # Allow containers to reach the host (matches shared_workspace.py)
    args += ["--add-host", "host.docker.internal:host-gateway"]

    if read_only_root:
        args += ["--read-only"]

    if "cpus" in create_options:
        args += ["--cpus", str(create_options["cpus"])]
    if "memory" in create_options:
        args += ["--memory", str(create_options["memory"])]
    if "user" in create_options:
        args += ["--user", str(create_options["user"])]

    for pm in (port_mappings or []):
        host_port = pm.get("host_port", 0)
        container_port = pm["container_port"]
        proto = pm.get("protocol", "tcp")
        mapping = f"{host_port}:{container_port}" if host_port else str(container_port)
        if proto != "tcp":
            mapping = f"{mapping}/{proto}"
        args += ["-p", mapping]

    for env_var, env_val in (env or {}).items():
        args += ["-e", f"{env_var}={env_val}"]

    for key, val in (labels or {}).items():
        args += ["--label", f"{key}={val}"]

    for spec in (mount_specs or []):
        host_path = spec["host_path"]
        container_path = spec["container_path"]
        mode = spec.get("mode", "rw")
        args += ["-v", f"{host_path}:{container_path}:{mode}"]

    args.append(image)
    args += ["sleep", "infinity"]
    return args


# ===== Cluster 13 sandbox exec helpers =====
# Shared building blocks for `SandboxService.exec` and `SandboxService.exec_bot_local`.
# Both invoke `docker exec` with identical env injection (server URL + per-bot API
# key + scoped secrets) and identical subprocess + timeout + truncation handling;
# only the bot-id source and the optional `--user` flag differ.


async def _build_docker_exec_args(
    *,
    bot_id: str,
    user: str | None = None,
) -> list[str]:
    """Build the leading `docker exec` argv (env-injection only).

    Callers append `[container_id, "sh", "-c", command]` to the returned list.
    Best-effort secret/API-key lookups swallow exceptions to match prior behavior:
    a missing or broken secret store must not block command execution.
    """
    args: list[str] = ["docker", "exec", "-i"]
    if user:
        args += ["--user", user]
    args += ["-e", f"AGENT_SERVER_URL={settings.SERVER_PUBLIC_URL}"]
    try:
        from app.services.api_keys import get_bot_api_key_value
        async with async_session() as _db:
            _bot_key = await get_bot_api_key_value(_db, bot_id)
        if _bot_key:
            args += ["-e", f"AGENT_SERVER_API_KEY={_bot_key}"]
    except Exception:
        pass
    try:
        from app.services.secret_values import get_env_dict as _get_secret_env
        from app.agent.context import current_allowed_secrets
        _all_secrets = _get_secret_env()
        _allowed = current_allowed_secrets.get(None)
        _secrets_to_inject = (
            {k: v for k, v in _all_secrets.items() if k in _allowed}
            if _allowed is not None else _all_secrets
        )
        for _sk, _sv in _secrets_to_inject.items():
            if _ENV_NAME_RE.match(_sk) and "\x00" not in str(_sv):
                args += ["-e", f"{_sk}={_sv}"]
    except Exception:
        pass
    return args


async def _run_docker_exec(
    exec_args: list[str],
    *,
    timeout_secs: int,
    max_bytes: int,
    start_ts: float,
) -> ExecResult:
    """Run a prepared `docker exec` argv, applying timeout + output truncation.

    Returns a timeout-shaped `ExecResult` on `asyncio.TimeoutError`. All other
    exceptions propagate; callers wrap them as `SandboxError` to preserve
    per-call-site error messages.
    """
    proc = await asyncio.create_subprocess_exec(
        *exec_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_secs,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        duration_ms = int((datetime.now(timezone.utc).timestamp() - start_ts) * 1000)
        return ExecResult(
            stdout="",
            stderr=f"Command timed out after {timeout_secs}s",
            exit_code=-1,
            truncated=False,
            duration_ms=duration_ms,
        )

    duration_ms = int((datetime.now(timezone.utc).timestamp() - start_ts) * 1000)
    truncated = False
    if len(stdout_bytes) > max_bytes:
        stdout_bytes = stdout_bytes[:max_bytes]
        truncated = True
    if len(stderr_bytes) > max_bytes:
        stderr_bytes = stderr_bytes[:max_bytes]
        truncated = True

    return ExecResult(
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=proc.returncode if proc.returncode is not None else 0,
        truncated=truncated,
        duration_ms=duration_ms,
    )


async def _touch_instance_last_used(instance_id) -> None:
    """Bump `SandboxInstance.last_used_at` in its own commit."""
    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if inst:
            inst.last_used_at = datetime.now(timezone.utc)
            await db.commit()


class SandboxService:
    def _assert_not_locked(self, instance: SandboxInstance, operation: str) -> None:
        locked = instance.locked_operations or []
        if operation in locked:
            raise SandboxLockedError(
                f"Sandbox '{instance.container_name}' has '{operation}' locked by the operator. "
                "Contact your administrator."
            )

    async def list_profiles(self, bot_id: str, allowed_profiles: list[str] | None = None) -> list[dict]:
        async with async_session() as db:
            stmt = (
                select(SandboxProfile)
                .join(SandboxBotAccess, SandboxBotAccess.profile_id == SandboxProfile.id)
                .where(SandboxBotAccess.bot_id == bot_id)
                .where(SandboxProfile.enabled == True)  # noqa: E712
            )
            profiles = list((await db.execute(stmt)).scalars().all())

        if allowed_profiles:
            profiles = [p for p in profiles if p.name in allowed_profiles]

        return [
            {
                "name": p.name,
                "description": p.description,
                "image": p.image,
                "network_mode": (p.network_mode or "none"),
                "port_mappings": p.port_mappings or [],
            }
            for p in profiles
        ]

    async def ensure(
        self,
        profile_name: str,
        bot_id: str,
        allowed_profiles: list[str] | None = None,
        port_mappings: list | None = None,
    ) -> tuple[SandboxInstance, list, str]:
        if not settings.DOCKER_SANDBOX_ENABLED:
            raise SandboxError("Docker sandboxes are disabled. Set DOCKER_SANDBOX_ENABLED=true.")

        async with async_session() as db:
            stmt = select(SandboxProfile).where(SandboxProfile.name == profile_name)
            profile = (await db.execute(stmt)).scalar_one_or_none()
            if profile is None:
                raise SandboxNotFoundError(f"Sandbox profile '{profile_name}' not found.")
            if not profile.enabled:
                raise SandboxNotFoundError(f"Sandbox profile '{profile_name}' is disabled.")

            access_stmt = select(SandboxBotAccess).where(
                SandboxBotAccess.bot_id == bot_id,
                SandboxBotAccess.profile_id == profile.id,
            )
            access = (await db.execute(access_stmt)).scalar_one_or_none()
            if access is None:
                raise SandboxAccessDeniedError(
                    f"Bot '{bot_id}' does not have access to sandbox profile '{profile_name}'."
                )

            if allowed_profiles is not None and profile_name not in allowed_profiles:
                raise SandboxAccessDeniedError(
                    f"Profile '{profile_name}' is not listed in this bot's docker_sandbox_profiles."
                )

            running_count = (
                await db.execute(
                    select(func.count()).select_from(SandboxInstance).where(SandboxInstance.status == "running")
                )
            ).scalar_one()
            if running_count >= settings.DOCKER_SANDBOX_MAX_CONCURRENT:
                raise SandboxError(
                    f"Maximum concurrent sandboxes ({settings.DOCKER_SANDBOX_MAX_CONCURRENT}) reached."
                )

            instance_id = uuid.uuid4()
            container_name = _build_container_name(profile.name, instance_id)
            instance = SandboxInstance(
                id=instance_id,
                profile_id=profile.id,
                scope_type=_SCOPE_TYPE_PROVISIONED,
                scope_key=str(instance_id),
                container_name=container_name,
                status="creating",
                created_by_bot=bot_id,
            )
            db.add(instance)
            await db.commit()
            await db.refresh(instance)

            locked_ops = instance.locked_operations or []
            p_image = profile.image
            p_network = profile.network_mode
            p_read_only = profile.read_only_root
            p_create_options = dict(profile.create_options or {})
            p_env = dict(profile.env or {})
            p_labels = dict(profile.labels or {})
            p_mount_specs = list(profile.mount_specs or [])
            # Merge profile defaults with caller-supplied mappings (caller additions appended)
            p_port_mappings = list(profile.port_mappings or []) + list(port_mappings or [])

        if "ensure" in locked_ops:
            raise SandboxLockedError(
                f"Sandbox '{container_name}' has 'ensure' locked by the operator. "
                "Contact your administrator."
            )

        _validate_mount_specs(p_mount_specs)

        existing_id = await self._get_container_id_by_name(container_name)
        if existing_id:
            running = await self._is_container_running(existing_id)
            if not running:
                await self._docker_start(existing_id)
            container_id = existing_id
            new_status = "running"
        else:
            run_args = _build_docker_run_args(
                image=p_image,
                container_name=container_name,
                network_mode=p_network,
                read_only_root=p_read_only,
                create_options=p_create_options,
                env=p_env,
                labels=p_labels,
                mount_specs=p_mount_specs,
                port_mappings=p_port_mappings,
            )
            container_id, error = await self._docker_run(run_args)
            if error:
                async with async_session() as db:
                    inst = await db.get(SandboxInstance, instance_id)
                    if inst:
                        inst.status = "dead"
                        inst.error_message = error
                        await db.commit()
                raise SandboxError(f"Failed to create container '{container_name}': {error}")
            new_status = "running"

        async with async_session() as db:
            inst = await db.get(SandboxInstance, instance_id)
            if inst:
                inst.container_id = container_id
                inst.status = new_status
                inst.error_message = None
                inst.port_mappings = p_port_mappings
                inst.last_inspected_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(inst)
                return inst, inst.port_mappings, (p_network or "none")
        raise SandboxError("Failed to persist sandbox instance.")

    async def exec(
        self,
        instance: SandboxInstance,
        command: str,
        timeout: int | None = None,
    ) -> ExecResult:
        self._assert_not_locked(instance, "exec")

        if instance.container_id is None:
            raise SandboxError("Container has no ID. Call ensure_sandbox first.")
        if instance.status == "stopped" and instance.container_id:
            await self._docker_start(instance.container_id)
            async with async_session() as db:
                inst = await db.get(SandboxInstance, instance.id)
                if inst:
                    inst.status = "running"
                    inst.last_inspected_at = datetime.now(timezone.utc)
                    await db.commit()
            instance.status = "running"
        if instance.status != "running":
            raise SandboxError(
                f"Container is not running (status: {instance.status}). "
                "If it was removed or failed, call ensure_sandbox for a new instance."
            )

        timeout_secs = timeout or settings.DOCKER_SANDBOX_DEFAULT_TIMEOUT
        max_bytes = settings.DOCKER_SANDBOX_MAX_OUTPUT_BYTES
        start_ts = datetime.now(timezone.utc).timestamp()

        exec_args = await _build_docker_exec_args(bot_id=instance.created_by_bot)
        exec_args += [instance.container_id, "sh", "-c", command]

        try:
            result = await _run_docker_exec(
                exec_args,
                timeout_secs=timeout_secs,
                max_bytes=max_bytes,
                start_ts=start_ts,
            )
        except Exception as e:
            raise SandboxError(f"Failed to exec command: {e}") from e

        await _touch_instance_last_used(instance.id)
        return result

    async def stop(self, instance: SandboxInstance) -> None:
        self._assert_not_locked(instance, "stop")
        if instance.container_id and instance.status == "running":
            await self._docker_stop(instance.container_id)
        async with async_session() as db:
            inst = await db.get(SandboxInstance, instance.id)
            if inst:
                inst.status = "stopped"
                inst.last_inspected_at = datetime.now(timezone.utc)
                await db.commit()

    async def remove(self, instance: SandboxInstance) -> None:
        self._assert_not_locked(instance, "remove")
        if instance.container_id:
            await self._docker_stop(instance.container_id)
            await self._docker_rm(instance.container_id)
        async with async_session() as db:
            inst = await db.get(SandboxInstance, instance.id)
            if inst:
                await db.delete(inst)
                await db.commit()

    async def get_profile_meta(self, profile_id: uuid.UUID) -> dict:
        async with async_session() as db:
            profile = await db.get(SandboxProfile, profile_id)
            if profile is None:
                return {"description": None, "network_mode": "none"}
            return {
                "description": profile.description,
                "network_mode": profile.network_mode or "none",
            }

    async def get_instance_for_bot(
        self,
        instance_id: uuid.UUID,
        bot_id: str,
        allowed_profiles: list[str] | None = None,
    ) -> SandboxInstance | None:
        async with async_session() as db:
            inst = await db.get(SandboxInstance, instance_id)
            if inst is None:
                return None
            if inst.created_by_bot != bot_id:
                return None
            access_stmt = select(SandboxBotAccess).where(
                SandboxBotAccess.bot_id == bot_id,
                SandboxBotAccess.profile_id == inst.profile_id,
            )
            if (await db.execute(access_stmt)).scalar_one_or_none() is None:
                return None
            if allowed_profiles is not None:
                profile = await db.get(SandboxProfile, inst.profile_id)
                if profile is None or profile.name not in allowed_profiles:
                    return None
            return inst

    # --- Docker CLI helpers ---

    async def _get_container_id_by_name(self, container_name: str) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "inspect", "--format", "{{.Id}}", container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                return stdout.decode().strip() or None
            return None
        except Exception:
            return None

    async def _is_container_running(self, container_id: str) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "inspect", "--format", "{{.State.Running}}", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return stdout.decode().strip() == "true"
        except Exception:
            return False

    async def _docker_run(self, args: list[str]) -> tuple[str, str | None]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                return "", stderr.decode().strip()
            return stdout.decode().strip(), None
        except Exception as e:
            return "", str(e)

    async def _docker_start(self, container_id: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "start", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
        except Exception as e:
            logger.warning("docker start failed for %s: %s", container_id, e)

    async def _docker_stop(self, container_id: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
        except Exception as e:
            logger.warning("docker stop failed for %s: %s", container_id, e)

    async def _docker_rm(self, container_id: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
        except Exception as e:
            logger.warning("docker rm failed for %s: %s", container_id, e)

    async def _get_image_id(self, image_tag: str) -> str | None:
        """Return the sha256 image ID for a given tag, or None on failure."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "image", "inspect", "--format", "{{.Id}}", image_tag,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                return stdout.decode().strip() or None
            return None
        except Exception:
            return None


    # --- Bot-local sandbox (per-bot persistent container) ---

    def _bot_local_container_name(self, bot_id: str) -> str:
        seg = _sanitize_docker_name_segment(bot_id, 48)
        return f"agent-sbx-bot-{seg}"

    async def _ensure_bot_local_profile(self, bot_id: str, config: "BotSandboxConfig") -> tuple[uuid.UUID, bool]:
        """Get or create a synthetic SandboxProfile row for bot-local sandboxes.

        Returns (profile_uuid, config_changed) — config_changed is True when
        the profile was updated (meaning the running container is stale).
        """
        import hashlib as _hashlib
        profile_uuid = uuid.UUID(bytes=_hashlib.sha256(f"bot-sandbox:{bot_id}".encode()).digest()[:16])
        config_changed = False
        async with async_session() as db:
            profile = await db.get(SandboxProfile, profile_uuid)
            target_image = config.image or "python:3.12-slim"
            target_network = config.network or "none"
            target_env = config.env or {}
            target_mounts = config.mounts or []
            target_ports = config.ports or []
            if profile is None:
                profile = SandboxProfile(
                    id=profile_uuid,
                    name=f"bot-local:{bot_id}",
                    description=f"Auto-created bot-local sandbox for bot '{bot_id}'",
                    image=target_image,
                    scope_mode="bot",
                    network_mode=target_network,
                    env=target_env,
                    mount_specs=target_mounts,
                    port_mappings=target_ports,
                )
                db.add(profile)
                await db.commit()
            else:
                # Sync all fields from bot config
                if profile.image != target_image:
                    profile.image = target_image
                    config_changed = True
                if profile.network_mode != target_network:
                    profile.network_mode = target_network
                    config_changed = True
                if profile.env != target_env:
                    profile.env = target_env
                    config_changed = True
                if profile.mount_specs != target_mounts:
                    profile.mount_specs = target_mounts
                    config_changed = True
                if profile.port_mappings != target_ports:
                    profile.port_mappings = target_ports
                    config_changed = True
                if config_changed:
                    await db.commit()
        return profile_uuid, config_changed

    async def ensure_bot_local(
        self,
        bot_id: str,
        config: "BotSandboxConfig",
    ) -> SandboxInstance:
        """Ensure a long-lived per-bot container exists and is running.

        Uses scope_type='bot', scope_key=bot_id.
        """
        container_name = self._bot_local_container_name(bot_id)
        profile_uuid, config_changed = await self._ensure_bot_local_profile(bot_id, config)

        async with async_session() as db:
            stmt = select(SandboxInstance).where(
                SandboxInstance.scope_type == "bot",
                SandboxInstance.scope_key == bot_id,
            )
            instance = (await db.execute(stmt)).scalar_one_or_none()

            if instance is not None:
                # Check if the container actually exists in Docker
                container_alive = False
                if instance.container_id:
                    existing = await self._get_container_id_by_name(container_name)
                    container_alive = existing is not None

                if container_alive:
                    # Check if the image has changed (rebuild detection)
                    target_image = config.image or "python:3.12-slim"
                    current_image_id = await self._get_image_id(target_image)
                    needs_recreate = False
                    if (
                        instance.image_id is not None
                        and current_image_id is not None
                        and instance.image_id != current_image_id
                    ):
                        logger.info(
                            "Bot-local container '%s' image changed (%s → %s); recreating.",
                            container_name,
                            instance.image_id[:19],
                            current_image_id[:19],
                        )
                        needs_recreate = True
                    elif config_changed:
                        logger.info(
                            "Bot-local container '%s' config changed (ports/network/env/mounts); recreating.",
                            container_name,
                        )
                        needs_recreate = True

                    if needs_recreate:
                        await self._docker_stop(instance.container_id)
                        await self._docker_rm(instance.container_id)
                        await db.delete(instance)
                        await db.commit()
                        # Fall through to create a new container
                    else:
                        # Container exists with correct config — ensure it's running
                        if instance.status != "running":
                            await self._docker_start(instance.container_id)
                            instance.status = "running"
                            instance.last_used_at = datetime.now(timezone.utc)
                            await db.commit()
                            await db.refresh(instance)
                        return instance
                else:
                    # Container is gone (manually deleted, Docker pruned, etc.)
                    # Delete stale DB row and fall through to create a new one
                    logger.info(
                        "Bot-local container '%s' no longer exists in Docker (status=%s); recreating.",
                        container_name,
                        instance.status,
                    )
                    await db.delete(instance)
                    await db.commit()

            # Create new DB row
            instance = SandboxInstance(
                profile_id=profile_uuid,
                scope_type="bot",
                scope_key=bot_id,
                container_name=container_name,
                status="creating",
                created_by_bot=bot_id,
            )
            db.add(instance)
            await db.commit()
            await db.refresh(instance)

        # Build docker run args (reuse shared helper for mount validation + DRY)
        _validate_mount_specs(config.mounts or [])
        target_image = config.image or "python:3.12-slim"
        create_options: dict = {}
        if config.user:
            create_options["user"] = config.user
        run_args = _build_docker_run_args(
            image=target_image,
            container_name=container_name,
            network_mode=config.network or "none",
            read_only_root=False,
            create_options=create_options,
            env=config.env or {},
            labels={},
            mount_specs=config.mounts or [],
            port_mappings=config.ports or [],
        )

        container_id, error = await self._docker_run(run_args)
        async with async_session() as db:
            inst = await db.get(SandboxInstance, instance.id)
            if inst:
                if error:
                    inst.status = "dead"
                    inst.error_message = error
                else:
                    inst.container_id = container_id
                    inst.status = "running"
                    inst.image_id = await self._get_image_id(target_image)
                    inst.last_inspected_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(inst)
                if error:
                    raise SandboxError(f"Failed to create bot-local container '{container_name}': {error}")
                return inst
        raise SandboxError("Failed to persist bot-local sandbox instance.")

    async def exec_bot_local(
        self,
        bot_id: str,
        command: str,
        config: "BotSandboxConfig",
        timeout: int | None = None,
        max_bytes: int | None = None,
    ) -> ExecResult:
        """Execute a command in the bot-local sandbox container."""
        instance = await self.ensure_bot_local(bot_id, config)

        if instance.container_id is None:
            raise SandboxError("Bot-local container has no ID after ensure.")

        timeout_secs = timeout or settings.DOCKER_SANDBOX_DEFAULT_TIMEOUT
        max_out = max_bytes or settings.DOCKER_SANDBOX_MAX_OUTPUT_BYTES
        start_ts = datetime.now(timezone.utc).timestamp()

        exec_args = await _build_docker_exec_args(bot_id=bot_id, user=config.user)
        exec_args += [instance.container_id, "sh", "-c", command]

        try:
            result = await _run_docker_exec(
                exec_args,
                timeout_secs=timeout_secs,
                max_bytes=max_out,
                start_ts=start_ts,
            )
        except Exception as e:
            raise SandboxError(f"Failed to exec bot-local command: {e}") from e

        await _touch_instance_last_used(instance.id)
        return result

    async def recreate_bot_local(self, bot_id: str) -> None:
        """Stop, remove, and delete the DB row for a bot-local sandbox.

        Next exec_command call will auto-recreate via ensure_bot_local.
        """
        container_name = self._bot_local_container_name(bot_id)
        existing_id = await self._get_container_id_by_name(container_name)
        if existing_id:
            await self._docker_stop(existing_id)
            await self._docker_rm(existing_id)
        async with async_session() as db:
            stmt = select(SandboxInstance).where(
                SandboxInstance.scope_type == "bot",
                SandboxInstance.scope_key == bot_id,
            )
            inst = (await db.execute(stmt)).scalar_one_or_none()
            if inst:
                await db.delete(inst)
                await db.commit()
        logger.info("Recreated bot-local sandbox for bot '%s'", bot_id)


sandbox_service = SandboxService()


def workspace_to_sandbox_config(bot: "BotConfig") -> "BotSandboxConfig":
    """Build a BotSandboxConfig from workspace.docker config.

    For shared workspace bots, mount the entire shared workspace root at /workspace
    so paths match the shared container (repos, common/, etc. are all accessible).
    For standalone bots, mount just the bot's workspace directory.
    """
    from app.agent.bots import BotSandboxConfig
    from app.services.workspace import workspace_service

    docker = bot.workspace.docker

    if bot.shared_workspace_id:
        from app.services.shared_workspace import shared_workspace_service
        host_root = shared_workspace_service.ensure_host_dirs(bot.shared_workspace_id)
    else:
        host_root = workspace_service.ensure_host_dir(bot.id, bot=bot)

    workspace_mount = {
        "host_path": local_to_host(host_root),
        "container_path": "/workspace",
        "mode": "rw",
    }
    mounts = list(docker.mounts or [])
    if not any(m.get("container_path") == "/workspace" for m in mounts):
        mounts.insert(0, workspace_mount)

    return BotSandboxConfig(
        enabled=True,
        unrestricted=True,
        image=docker.image,
        network=docker.network,
        env=docker.env,
        ports=docker.ports,
        mounts=mounts,
        user=docker.user,
    )
