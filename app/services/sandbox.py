"""Docker sandbox service — ensure, exec, stop, remove, and lock enforcement."""
import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.config import settings
from app.db.engine import async_session
from app.db.models import SandboxBotAccess, SandboxInstance, SandboxProfile

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
) -> list[str]:
    args = ["docker", "run", "-d", "--name", container_name]

    args += ["--network", network_mode or "none"]

    if read_only_root:
        args += ["--read-only"]

    if "cpus" in create_options:
        args += ["--cpus", str(create_options["cpus"])]
    if "memory" in create_options:
        args += ["--memory", str(create_options["memory"])]
    if "user" in create_options:
        args += ["--user", str(create_options["user"])]

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
            )
            profiles = list((await db.execute(stmt)).scalars().all())

        if allowed_profiles:
            profiles = [p for p in profiles if p.name in allowed_profiles]

        return [
            {
                "name": p.name,
                "description": p.description,
                "image": p.image,
            }
            for p in profiles
        ]

    async def ensure(
        self,
        profile_name: str,
        bot_id: str,
        allowed_profiles: list[str] | None = None,
    ) -> SandboxInstance:
        if not settings.DOCKER_SANDBOX_ENABLED:
            raise SandboxError("Docker sandboxes are disabled. Set DOCKER_SANDBOX_ENABLED=true.")

        async with async_session() as db:
            stmt = select(SandboxProfile).where(SandboxProfile.name == profile_name)
            profile = (await db.execute(stmt)).scalar_one_or_none()
            if profile is None:
                raise SandboxNotFoundError(f"Sandbox profile '{profile_name}' not found.")

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
                inst.last_inspected_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(inst)
                return inst
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

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "-i", instance.container_id,
                "sh", "-c", command,
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
        except Exception as e:
            raise SandboxError(f"Failed to exec command: {e}") from e

        duration_ms = int((datetime.now(timezone.utc).timestamp() - start_ts) * 1000)

        truncated = False
        if len(stdout_bytes) > max_bytes:
            stdout_bytes = stdout_bytes[:max_bytes]
            truncated = True
        if len(stderr_bytes) > max_bytes:
            stderr_bytes = stderr_bytes[:max_bytes]
            truncated = True

        # Update last_used_at
        async with async_session() as db:
            inst = await db.get(SandboxInstance, instance.id)
            if inst:
                inst.last_used_at = datetime.now(timezone.utc)
                await db.commit()

        return ExecResult(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else 0,
            truncated=truncated,
            duration_ms=duration_ms,
        )

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


sandbox_service = SandboxService()
