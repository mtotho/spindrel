"""Docker Compose stack management for agent-managed multi-container services.

Agents create, start, stop, and destroy Docker Compose stacks through the
StackService, which mediates all operations with ownership checks, YAML
sanitization, and resource limit enforcement.
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import async_session
from app.db.models import DockerStack
from app.services.paths import local_to_host, local_workspace_base

logger = logging.getLogger(__name__)

PROJECT_PREFIX = "spindrel-"

# Blocked Compose keys (security-sensitive)
_BLOCKED_SERVICE_KEYS = {
    "privileged", "cap_add", "devices", "pid", "ipc",
    "security_opt", "sysctls", "cgroup_parent", "userns_mode",
}
_BLOCKED_NETWORK_MODES = {"host"}
_BLOCKED_VOLUME_PATHS = (
    "/var/run/docker.sock",
    "/etc",
    "/proc",
    "/sys",
    "/dev",
)


class StackError(Exception):
    pass


class StackNotFoundError(StackError):
    pass


class StackValidationError(StackError):
    pass


class StackLimitError(StackError):
    pass


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool
    duration_ms: int


@dataclass
class ServiceStatus:
    name: str
    state: str
    health: str | None
    ports: list[dict]


def _stacks_base_dir() -> str:
    """Base directory for materialized compose files."""
    return os.path.join(local_workspace_base(), "stacks")


def _stack_dir(stack_id: str) -> str:
    return os.path.join(_stacks_base_dir(), stack_id)


def _compose_path(stack_id: str) -> str:
    return os.path.join(_stack_dir(stack_id), "docker-compose.yml")


def _generate_project_name() -> str:
    hex_id = uuid.uuid4().hex[:12]
    return f"{PROJECT_PREFIX}{hex_id}"


def validate_compose(
    definition: str,
    allowed_images: list[str] | None = None,
) -> dict:
    """Parse and sanitize a docker-compose YAML definition.

    Returns the sanitized dict. Raises StackValidationError on problems.
    """
    try:
        doc = yaml.safe_load(definition)
    except yaml.YAMLError as e:
        raise StackValidationError(f"Invalid YAML: {e}")

    if not isinstance(doc, dict):
        raise StackValidationError("Compose definition must be a YAML mapping")

    services = doc.get("services")
    if not services or not isinstance(services, dict):
        raise StackValidationError("Compose definition must have a 'services' section")

    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            raise StackValidationError(f"Service '{svc_name}' must be a mapping")

        # Block dangerous keys
        for key in _BLOCKED_SERVICE_KEYS:
            if key in svc:
                raise StackValidationError(
                    f"Service '{svc_name}': '{key}' is not allowed"
                )

        # Block host network mode
        net_mode = svc.get("network_mode", "")
        if net_mode in _BLOCKED_NETWORK_MODES:
            raise StackValidationError(
                f"Service '{svc_name}': network_mode '{net_mode}' is not allowed"
            )

        # Check image allowlist
        image = svc.get("image", "")
        if allowed_images and image:
            if not any(_image_matches(image, allowed) for allowed in allowed_images):
                raise StackValidationError(
                    f"Service '{svc_name}': image '{image}' not in allowed list"
                )

        # Validate volumes
        for vol in svc.get("volumes", []):
            vol_str = vol if isinstance(vol, str) else str(vol.get("source", ""))
            # Extract host path (before the colon in bind-mount syntax)
            host_path = vol_str.split(":")[0]
            for blocked in _BLOCKED_VOLUME_PATHS:
                if host_path == blocked or host_path.startswith(blocked + "/"):
                    raise StackValidationError(
                        f"Service '{svc_name}': volume mount '{vol_str}' is not allowed"
                    )

        # Inject resource limits
        deploy = svc.setdefault("deploy", {})
        resources = deploy.setdefault("resources", {})
        limits = resources.setdefault("limits", {})
        limits.setdefault("cpus", str(settings.DOCKER_STACK_DEFAULT_CPUS))
        limits.setdefault("memory", settings.DOCKER_STACK_DEFAULT_MEMORY)

        # Force restart policy
        if svc.get("restart") == "always":
            svc["restart"] = "unless-stopped"

        # Inject labels
        labels = svc.setdefault("labels", {})
        if isinstance(labels, list):
            # Convert list format to dict
            label_dict = {}
            for item in labels:
                if "=" in item:
                    k, v = item.split("=", 1)
                    label_dict[k] = v
            labels = label_dict
            svc["labels"] = labels
        labels["spindrel.managed"] = "true"

    return doc


def _image_matches(image: str, pattern: str) -> bool:
    """Check if image matches an allowed pattern (supports prefix matching)."""
    # Exact match
    if image == pattern:
        return True
    # Match without tag (e.g. "postgres" matches "postgres:16")
    image_name = image.split(":")[0]
    pattern_name = pattern.split(":")[0]
    if image_name == pattern_name:
        # If pattern has a tag, require exact match; otherwise any tag is fine
        if ":" not in pattern:
            return True
    return False


class StackService:
    """Mediates all Docker Compose stack operations."""

    async def create(
        self,
        bot_id: str,
        name: str,
        compose_definition: str,
        channel_id: uuid.UUID | None = None,
        description: str | None = None,
        allowed_images: list[str] | None = None,
        max_stacks: int | None = None,
    ) -> DockerStack:
        """Create a new stack. Validates YAML and enforces limits."""
        # Validate compose definition
        sanitized = validate_compose(compose_definition, allowed_images)

        limit = max_stacks or settings.DOCKER_STACK_MAX_PER_BOT
        async with async_session() as db:
            count = (await db.execute(
                select(func.count(DockerStack.id)).where(
                    DockerStack.created_by_bot == bot_id
                )
            )).scalar_one()
            if count >= limit:
                raise StackLimitError(
                    f"Bot '{bot_id}' has {count}/{limit} stacks (limit reached)"
                )

            project_name = _generate_project_name()
            sanitized_yaml = yaml.dump(sanitized, default_flow_style=False)

            stack = DockerStack(
                name=name,
                description=description,
                created_by_bot=bot_id,
                channel_id=channel_id,
                compose_definition=sanitized_yaml,
                project_name=project_name,
                status="stopped",
            )
            db.add(stack)
            await db.commit()
            await db.refresh(stack)

            # Materialize compose file to disk
            self._materialize(str(stack.id), sanitized_yaml)
            return stack

    async def start(self, stack: DockerStack) -> DockerStack:
        """Start all services in a stack."""
        stack_id = str(stack.id)
        self._materialize(stack_id, stack.compose_definition)

        async with async_session() as db:
            await db.execute(
                update(DockerStack)
                .where(DockerStack.id == stack.id)
                .values(status="starting", error_message=None, updated_at=datetime.now(timezone.utc))
            )
            await db.commit()

        try:
            result = await self._compose_cmd(stack, ["up", "-d", "--remove-orphans"])
            if result.exit_code != 0:
                raise StackError(f"docker compose up failed: {result.stderr}")

            # Fetch container info
            container_ids, exposed_ports, network_name = await self._inspect_stack(stack)

            async with async_session() as db:
                await db.execute(
                    update(DockerStack)
                    .where(DockerStack.id == stack.id)
                    .values(
                        status="running",
                        container_ids=container_ids,
                        exposed_ports=exposed_ports,
                        network_name=network_name,
                        last_started_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()

            # Connect workspace container to stack network if available
            if network_name:
                await self._connect_workspace(stack.created_by_bot, network_name)

            # Bridge stack containers into additional networks (integration stacks)
            if stack.connect_networks and container_ids:
                for net in stack.connect_networks:
                    for cid in container_ids.values():
                        await self._connect_network(net, cid)

            return await self._get(stack.id)

        except Exception as e:
            async with async_session() as db:
                await db.execute(
                    update(DockerStack)
                    .where(DockerStack.id == stack.id)
                    .values(
                        status="error",
                        error_message=str(e)[:2000],
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
            raise

    async def stop(self, stack: DockerStack) -> DockerStack:
        """Stop all services in a stack."""
        # Disconnect workspace first
        if stack.network_name:
            await self._disconnect_workspace(stack.created_by_bot, stack.network_name)

        result = await self._compose_cmd(stack, ["stop"])
        if result.exit_code != 0:
            logger.warning("docker compose stop failed for %s: %s", stack.project_name, result.stderr)

        async with async_session() as db:
            await db.execute(
                update(DockerStack)
                .where(DockerStack.id == stack.id)
                .values(
                    status="stopped",
                    last_stopped_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
        return await self._get(stack.id)

    async def restart(self, stack: DockerStack) -> DockerStack:
        """Restart all services in a stack."""
        result = await self._compose_cmd(stack, ["restart"])
        if result.exit_code != 0:
            raise StackError(f"docker compose restart failed: {result.stderr}")

        container_ids, exposed_ports, network_name = await self._inspect_stack(stack)
        async with async_session() as db:
            await db.execute(
                update(DockerStack)
                .where(DockerStack.id == stack.id)
                .values(
                    status="running",
                    container_ids=container_ids,
                    exposed_ports=exposed_ports,
                    network_name=network_name,
                    last_started_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
        return await self._get(stack.id)

    async def destroy(self, stack: DockerStack, remove_volumes: bool = True) -> None:
        """Tear down a stack completely and delete the DB row."""
        if stack.source == "integration":
            raise StackError("Integration stacks cannot be destroyed — they are managed by code")
        # Disconnect workspace first
        if stack.network_name:
            await self._disconnect_workspace(stack.created_by_bot, stack.network_name)

        async with async_session() as db:
            await db.execute(
                update(DockerStack)
                .where(DockerStack.id == stack.id)
                .values(status="removing", updated_at=datetime.now(timezone.utc))
            )
            await db.commit()

        args = ["down"]
        if remove_volumes:
            args.append("--volumes")
        args.append("--remove-orphans")

        result = await self._compose_cmd(stack, args)
        if result.exit_code != 0:
            logger.warning("docker compose down failed for %s: %s", stack.project_name, result.stderr)

        # Clean up disk
        stack_dir = _stack_dir(str(stack.id))
        if os.path.exists(stack_dir):
            import shutil
            shutil.rmtree(stack_dir, ignore_errors=True)

        # Delete DB row
        async with async_session() as db:
            row = await db.get(DockerStack, stack.id)
            if row:
                await db.delete(row)
                await db.commit()

    async def update_definition(
        self,
        stack: DockerStack,
        compose_definition: str,
        allowed_images: list[str] | None = None,
    ) -> DockerStack:
        """Update a stack's compose definition. Stack must be stopped."""
        if stack.status not in ("stopped", "error"):
            raise StackError("Stack must be stopped before updating definition")

        sanitized = validate_compose(compose_definition, allowed_images)
        sanitized_yaml = yaml.dump(sanitized, default_flow_style=False)

        async with async_session() as db:
            await db.execute(
                update(DockerStack)
                .where(DockerStack.id == stack.id)
                .values(
                    compose_definition=sanitized_yaml,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        self._materialize(str(stack.id), sanitized_yaml)
        return await self._get(stack.id)

    async def get_status(self, stack: DockerStack) -> list[ServiceStatus]:
        """Get live container status for a stack."""
        result = await self._compose_cmd(stack, ["ps", "--format", "json"])
        if result.exit_code != 0:
            return []

        services = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                ports = []
                for p in data.get("Publishers", []):
                    if isinstance(p, dict) and p.get("PublishedPort"):
                        ports.append({
                            "host_port": p["PublishedPort"],
                            "container_port": p.get("TargetPort"),
                            "protocol": p.get("Protocol", "tcp"),
                        })
                services.append(ServiceStatus(
                    name=data.get("Service", data.get("Name", "")),
                    state=data.get("State", "unknown"),
                    health=data.get("Health", None),
                    ports=ports,
                ))
            except (json.JSONDecodeError, KeyError):
                continue
        return services

    async def get_logs(
        self,
        stack: DockerStack,
        service: str | None = None,
        tail: int | None = None,
    ) -> str:
        """Get logs from a stack's services."""
        args = ["logs", "--no-log-prefix"]
        tail_n = min(tail or 100, settings.DOCKER_STACK_LOG_TAIL_MAX)
        args.extend(["--tail", str(tail_n)])
        if service:
            args.append(service)

        result = await self._compose_cmd(stack, args)
        output = result.stdout or result.stderr
        max_bytes = settings.DOCKER_STACK_MAX_OUTPUT_BYTES
        if len(output) > max_bytes:
            output = output[:max_bytes] + "\n... (truncated)"
        return output

    async def exec_in_service(
        self,
        stack: DockerStack,
        service: str,
        command: str,
        timeout: int | None = None,
    ) -> ExecResult:
        """Execute a command in a running service container."""
        if stack.status != "running":
            raise StackError("Stack must be running to exec commands")

        exec_timeout = timeout or settings.DOCKER_STACK_EXEC_TIMEOUT
        args = ["exec", "-T", service, "sh", "-c", command]

        start = datetime.now(timezone.utc)
        result = await self._compose_cmd(stack, args, timeout=exec_timeout)
        duration_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

        max_bytes = settings.DOCKER_STACK_MAX_OUTPUT_BYTES
        truncated = len(result.stdout) > max_bytes
        stdout = result.stdout[:max_bytes] if truncated else result.stdout

        return ExecResult(
            stdout=stdout,
            stderr=result.stderr[:max_bytes] if result.stderr else "",
            exit_code=result.exit_code,
            truncated=truncated,
            duration_ms=duration_ms,
        )

    # --- Access helpers ---

    async def get_by_id(self, stack_id: uuid.UUID) -> DockerStack | None:
        async with async_session() as db:
            return await db.get(DockerStack, stack_id)

    async def list_for_bot(
        self,
        bot_id: str,
        channel_id: uuid.UUID | None = None,
    ) -> list[DockerStack]:
        """List stacks accessible to a bot (own stacks + same-channel stacks)."""
        from sqlalchemy import or_

        async with async_session() as db:
            conditions = [DockerStack.created_by_bot == bot_id]
            # Only include channel filter when a real channel_id is present —
            # otherwise IS NULL would match all channel-less stacks from any bot
            if channel_id is not None:
                conditions.append(DockerStack.channel_id == channel_id)
            stmt = (
                select(DockerStack)
                .where(or_(*conditions))
                .order_by(DockerStack.created_at.desc())
            )
            return list((await db.execute(stmt)).scalars().all())

    async def list_all(
        self,
        bot_id: str | None = None,
        channel_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[DockerStack]:
        """List all stacks (admin). Supports optional filtering."""
        async with async_session() as db:
            stmt = select(DockerStack).order_by(DockerStack.created_at.desc())
            if bot_id:
                stmt = stmt.where(DockerStack.created_by_bot == bot_id)
            if channel_id:
                stmt = stmt.where(DockerStack.channel_id == channel_id)
            if status:
                stmt = stmt.where(DockerStack.status == status)
            return list((await db.execute(stmt)).scalars().all())

    async def reconcile_running(self) -> int:
        """Check stacks marked as running and update status if containers are gone.

        Called at server startup to sync DB state with reality.
        Returns the number of stacks updated.
        """
        fixed = 0
        async with async_session() as db:
            stacks = (await db.execute(
                select(DockerStack).where(DockerStack.status == "running")
            )).scalars().all()

        for stack in stacks:
            try:
                statuses = await self.get_status(stack)
                if not statuses:
                    async with async_session() as db:
                        await db.execute(
                            update(DockerStack)
                            .where(DockerStack.id == stack.id)
                            .values(status="stopped", updated_at=datetime.now(timezone.utc))
                        )
                        await db.commit()
                    fixed += 1
                    logger.info("Reconciled stack %s (%s) → stopped", stack.name, stack.project_name)
            except Exception:
                logger.warning("Failed to reconcile stack %s", stack.name, exc_info=True)

        return fixed

    async def sync_integration_stack(
        self,
        integration_id: str,
        name: str,
        compose_definition: str,
        project_name: str,
        description: str | None = None,
        connect_networks: list[str] | None = None,
        config_files: dict[str, str] | None = None,
    ) -> DockerStack:
        """Upsert an integration-owned stack.

        Creates or updates the DB row and materializes compose + config files
        to the stacks directory.  Skips validate_compose() since integration
        compose files are trusted checked-in code.

        Args:
            integration_id: e.g. "web_search"
            name: human-readable name
            compose_definition: raw YAML string
            project_name: Docker Compose project name (must start with PROJECT_PREFIX)
            description: optional description
            connect_networks: Docker networks to bridge containers into after start
            config_files: {relative_path: file_content} for volume-mounted config files
        """
        async with async_session() as db:
            # Look up by integration_id
            row = (await db.execute(
                select(DockerStack).where(DockerStack.integration_id == integration_id)
            )).scalar_one_or_none()

            if row:
                # Update if compose changed
                if row.compose_definition != compose_definition:
                    row.compose_definition = compose_definition
                    row.updated_at = datetime.now(timezone.utc)
                row.connect_networks = connect_networks or []
                row.name = name
                row.description = description
                row.project_name = project_name
                await db.commit()
                await db.refresh(row)
            else:
                row = DockerStack(
                    name=name,
                    description=description,
                    created_by_bot="_integration",
                    compose_definition=compose_definition,
                    project_name=project_name,
                    status="stopped",
                    source="integration",
                    integration_id=integration_id,
                    connect_networks=connect_networks or [],
                )
                db.add(row)
                await db.commit()
                await db.refresh(row)

        # Materialize compose file + config files to stacks directory
        stack_id = str(row.id)
        self._materialize(stack_id, compose_definition)
        if config_files:
            for rel_path, content in config_files.items():
                self._materialize_file(stack_id, rel_path, content)

        return row

    # --- Internal helpers ---

    async def _get(self, stack_id: uuid.UUID) -> DockerStack:
        async with async_session() as db:
            row = await db.get(DockerStack, stack_id)
            if not row:
                raise StackNotFoundError(f"Stack {stack_id} not found")
            return row

    def _materialize(self, stack_id: str, yaml_content: str) -> None:
        """Write compose YAML to disk for CLI consumption."""
        stack_dir = _stack_dir(stack_id)
        os.makedirs(stack_dir, exist_ok=True)
        path = _compose_path(stack_id)
        with open(path, "w") as f:
            f.write(yaml_content)

    def _materialize_file(self, stack_id: str, rel_path: str, content: str) -> None:
        """Write an auxiliary file (e.g. config) to the stack directory.

        If ``target`` already exists as a directory (which can happen when
        ``docker compose up`` ran before this method and Docker auto-created
        the bind-mount source as an empty dir), wipe it before writing —
        otherwise the next compose run mounts a directory into a file path
        and the container fails to start permanently.
        """
        import shutil
        target = os.path.join(_stack_dir(stack_id), rel_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isdir(target) and not os.path.islink(target):
            logger.warning(
                "Materialize target %s exists as a directory; removing before write", target,
            )
            shutil.rmtree(target)
        with open(target, "w") as f:
            f.write(content)

    async def _compose_cmd(
        self,
        stack: DockerStack,
        args: list[str],
        timeout: int | None = None,
    ) -> ExecResult:
        """Run: docker compose -p {project_name} -f {host_path} {args}"""
        if not stack.project_name.startswith(PROJECT_PREFIX):
            raise StackError("Invalid project name prefix — refusing to operate")

        compose_file = _compose_path(str(stack.id))
        host_file = local_to_host(compose_file)

        cmd = [
            "docker", "compose",
            "-p", stack.project_name,
            "-f", host_file,
            *args,
        ]
        effective_timeout = timeout or settings.DOCKER_STACK_COMPOSE_TIMEOUT

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=effective_timeout + 5,  # slight buffer for subprocess creation
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            raise StackError(f"Docker compose command timed out after {effective_timeout}s")

        return ExecResult(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=proc.returncode or 0,
            truncated=False,
            duration_ms=0,
        )

    async def _inspect_stack(self, stack: DockerStack) -> tuple[dict, dict, str | None]:
        """Inspect running stack to get container IDs, ports, and network name."""
        container_ids = {}
        exposed_ports = {}
        network_name = None

        statuses = await self.get_status(stack)
        for svc in statuses:
            if svc.ports:
                exposed_ports[svc.name] = svc.ports

        # Get container IDs
        result = await self._compose_cmd(stack, ["ps", "-q"])
        if result.exit_code == 0:
            for line in result.stdout.strip().splitlines():
                cid = line.strip()
                if cid:
                    # Try to map container ID to service
                    try:
                        inspect_proc = await asyncio.create_subprocess_exec(
                            "docker", "inspect", "--format",
                            '{{index .Config.Labels "com.docker.compose.service"}}',
                            cid,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        out, _ = await inspect_proc.communicate()
                        svc_name = out.decode().strip()
                        if svc_name:
                            container_ids[svc_name] = cid[:12]
                    except Exception:
                        pass

        # Determine network name
        expected_network = f"{stack.project_name}_default"
        try:
            net_proc = await asyncio.create_subprocess_exec(
                "docker", "network", "ls", "--filter", f"name={expected_network}",
                "--format", "{{.Name}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await net_proc.communicate()
            for line in out.decode().strip().splitlines():
                if line.strip() == expected_network:
                    network_name = expected_network
                    break
        except Exception:
            pass

        return container_ids, exposed_ports, network_name

    async def _connect_workspace(self, bot_id: str, network_name: str) -> None:
        """Connect the bot's workspace container to the stack network."""
        container_name = await self._find_workspace_container(bot_id)
        if not container_name:
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "network", "connect", network_name, container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("Connected workspace %s to stack network %s", container_name, network_name)
            elif b"already exists" in stderr:
                pass  # Already connected
            else:
                logger.warning("Failed to connect workspace to stack network: %s", stderr.decode())
        except Exception:
            logger.warning("Error connecting workspace to stack network", exc_info=True)

    async def _disconnect_workspace(self, bot_id: str, network_name: str) -> None:
        """Disconnect the bot's workspace container from the stack network."""
        container_name = await self._find_workspace_container(bot_id)
        if not container_name:
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "network", "disconnect", network_name, container_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception:
            pass  # Best-effort

    async def _connect_network(self, network: str, container_id: str) -> None:
        """Connect a container to an external Docker network."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "network", "connect", network, container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("Connected container %s to network %s", container_id, network)
            elif b"already exists" in stderr:
                pass  # Already connected
            else:
                logger.warning("Failed to connect container %s to network %s: %s",
                               container_id, network, stderr.decode())
        except Exception:
            logger.warning("Error connecting container to network", exc_info=True)

    async def _find_workspace_container(self, bot_id: str) -> str | None:
        """Find the workspace container name for a bot."""
        try:
            from app.db.models import SharedWorkspaceBot, SharedWorkspace
            async with async_session() as db:
                result = await db.execute(
                    select(SharedWorkspace.container_name)
                    .join(SharedWorkspaceBot, SharedWorkspace.id == SharedWorkspaceBot.workspace_id)
                    .where(SharedWorkspaceBot.bot_id == bot_id)
                )
                row = result.first()
                return row[0] if row and row[0] else None
        except Exception:
            return None


stack_service = StackService()
