"""Project runtime environment policy.

Project Blueprints declare env defaults and required secret slots. This module
turns the applied Project snapshot plus Project secret bindings into the
process environment that Project-bound runtimes can use, while keeping display
payloads secret-safe.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Project, ProjectDependencyStackInstance, ProjectSecretBinding, SecretValue, Task
from app.services.encryption import decrypt
from app.services.secret_registry import MIN_SECRET_LENGTH, redact

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENV_NAMES = {
    "AGENT_SERVER_API_KEY",
    "AGENT_SERVER_URL",
    "DATABASE_URL",
    "ENCRYPTION_KEY",
    "JWT_SECRET",
}
_RESERVED_ENV_PREFIXES = ("SPINDREL_INTERNAL_",)
_SENSITIVE_ENV_NAME_RE = re.compile(
    r"(SECRET|TOKEN|API_KEY|APIKEY|PASSWORD|PASSWD|PWD|PRIVATE|CREDENTIAL|DATABASE_URL|DSN)",
    re.IGNORECASE,
)


def _is_sensitive_env_key(name: str) -> bool:
    return bool(_SENSITIVE_ENV_NAME_RE.search(name or ""))


def _values_to_redact(env: Mapping[str, str], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = str(env.get(key) or "")
        if len(value) >= MIN_SECRET_LENGTH:
            values.append(value)
    return sorted(set(values), key=len, reverse=True)


@dataclass(frozen=True)
class ProjectRuntimeEnvironment:
    """Resolved Project env for process execution plus safe readiness metadata."""

    project_id: str
    env: Mapping[str, str] = field(repr=False)
    env_default_keys: tuple[str, ...] = ()
    secret_keys: tuple[str, ...] = ()
    missing_secrets: tuple[str, ...] = ()
    invalid_env_keys: tuple[str, ...] = ()
    reserved_env_keys: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.missing_secrets and not self.invalid_env_keys and not self.reserved_env_keys

    def redact_text(self, text: str) -> str:
        redacted = redact(text)
        sensitive_keys = tuple(
            key
            for key in set(self.secret_keys) | set(self.env.keys())
            if key in self.secret_keys or _is_sensitive_env_key(str(key))
        )
        values = _values_to_redact(self.env, sensitive_keys)
        for value in values:
            redacted = redacted.replace(value, "[REDACTED]")
        return redacted

    def safe_payload(self) -> dict[str, Any]:
        return {
            "source": "blueprint_snapshot",
            "ready": self.ready,
            "env_default_keys": list(self.env_default_keys),
            "secret_keys": list(self.secret_keys),
            "missing_secrets": list(self.missing_secrets),
            "invalid_env_keys": list(self.invalid_env_keys),
            "reserved_env_keys": list(self.reserved_env_keys),
        }


def project_snapshot(project: Project) -> dict[str, Any]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    snapshot = metadata.get("blueprint_snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def secret_name(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("key") or "").strip()
    return ""


def required_secret_names(snapshot: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for item in snapshot.get("required_secrets") or []:
        name = secret_name(item)
        if name and name not in names:
            names.append(name)
    return names


def is_valid_env_name(name: str) -> bool:
    return bool(_ENV_NAME_RE.match(name))


def is_reserved_env_name(name: str) -> bool:
    return name in _RESERVED_ENV_NAMES or any(name.startswith(prefix) for prefix in _RESERVED_ENV_PREFIXES)


def _normalize_env(raw: Any) -> tuple[dict[str, str], list[str], list[str]]:
    if not isinstance(raw, dict):
        return {}, [], []
    env: dict[str, str] = {}
    invalid: list[str] = []
    reserved: list[str] = []
    for key, value in raw.items():
        name = str(key).strip()
        if not is_valid_env_name(name) or "\x00" in str(value):
            invalid.append(name or str(key))
            continue
        if is_reserved_env_name(name):
            reserved.append(name)
            continue
        env[name] = str(value)
    return env, invalid, reserved


def build_project_runtime_environment(
    project: Project,
    *,
    bindings: list[ProjectSecretBinding],
) -> ProjectRuntimeEnvironment:
    snapshot = project_snapshot(project)
    env_defaults, invalid_env_keys, reserved_env_keys = _normalize_env(snapshot.get("env"))
    env = dict(env_defaults)
    binding_by_name = {binding.logical_name: binding for binding in bindings}
    secret_keys: list[str] = []
    missing_secrets: list[str] = []

    for name in required_secret_names(snapshot):
        binding = binding_by_name.get(name)
        if binding is None or binding.secret_value_id is None or binding.secret_value is None:
            missing_secrets.append(name)
            continue
        if not is_valid_env_name(name):
            invalid_env_keys.append(name)
            continue
        if is_reserved_env_name(name):
            reserved_env_keys.append(name)
            continue
        secret_keys.append(name)
        raw_value = getattr(binding.secret_value, "value", None)
        if raw_value is not None:
            env[name] = decrypt(raw_value)

    for binding in bindings:
        name = binding.logical_name
        if name in secret_keys or name in missing_secrets:
            continue
        if binding.secret_value_id is None or binding.secret_value is None:
            continue
        if not is_valid_env_name(name):
            invalid_env_keys.append(name)
            continue
        if is_reserved_env_name(name):
            reserved_env_keys.append(name)
            continue
        secret_keys.append(name)
        raw_value = getattr(binding.secret_value, "value", None)
        if raw_value is not None:
            env[name] = decrypt(raw_value)

    return ProjectRuntimeEnvironment(
        project_id=str(project.id),
        env=env,
        env_default_keys=tuple(sorted(env_defaults)),
        secret_keys=tuple(sorted(secret_keys)),
        missing_secrets=tuple(missing_secrets),
        invalid_env_keys=tuple(dict.fromkeys(invalid_env_keys)),
        reserved_env_keys=tuple(dict.fromkeys(reserved_env_keys)),
    )


def _with_extra_env(
    runtime: ProjectRuntimeEnvironment,
    extra_env: Mapping[str, str],
    *,
    extra_keys: tuple[str, ...] = (),
) -> ProjectRuntimeEnvironment:
    if not extra_env:
        return runtime
    env = dict(runtime.env)
    env.update({str(key): str(value) for key, value in extra_env.items()})
    return ProjectRuntimeEnvironment(
        project_id=runtime.project_id,
        env=env,
        env_default_keys=tuple(sorted(set(runtime.env_default_keys) | set(extra_keys or extra_env.keys()))),
        secret_keys=runtime.secret_keys,
        missing_secrets=runtime.missing_secrets,
        invalid_env_keys=runtime.invalid_env_keys,
        reserved_env_keys=runtime.reserved_env_keys,
    )


def _task_dev_target_env(task: Task | None) -> dict[str, str]:
    if task is None or not isinstance(task.execution_config, dict):
        return {}
    cfg = task.execution_config.get("project_coding_run")
    if not isinstance(cfg, dict):
        return {}
    env = cfg.get("dev_target_env")
    if isinstance(env, dict):
        return {str(key): str(value) for key, value in env.items()}
    values: dict[str, str] = {}
    for target in cfg.get("dev_targets") or []:
        if not isinstance(target, dict):
            continue
        if target.get("port_env") and target.get("port") is not None:
            values[str(target["port_env"])] = str(target["port"])
        if target.get("url_env") and target.get("url"):
            values[str(target["url_env"])] = str(target["url"])
    return values


async def _task_dependency_stack_env(db: AsyncSession, task: Task | None) -> dict[str, str]:
    if task is None:
        return {}
    stack = (await db.execute(
        select(ProjectDependencyStackInstance)
        .where(
            ProjectDependencyStackInstance.task_id == task.id,
            ProjectDependencyStackInstance.deleted_at.is_(None),
        )
        .order_by(ProjectDependencyStackInstance.updated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if stack is None or stack.status not in {"running", "stopped"} or not isinstance(stack.env, dict):
        return {}
    return {str(key): str(value) for key, value in stack.env.items()}


async def load_project_runtime_environment(
    db: AsyncSession,
    project: Project,
) -> ProjectRuntimeEnvironment:
    bindings = (await db.execute(
        select(ProjectSecretBinding)
        .options(selectinload(ProjectSecretBinding.secret_value))
        .where(ProjectSecretBinding.project_id == project.id)
        .order_by(ProjectSecretBinding.logical_name)
    )).scalars().all()
    return build_project_runtime_environment(project, bindings=list(bindings))


async def load_project_runtime_environment_for_id(
    db: AsyncSession,
    project_id: uuid.UUID | str | None,
    *,
    task_id: uuid.UUID | str | None = None,
) -> ProjectRuntimeEnvironment | None:
    if project_id is None:
        return None
    try:
        project_uuid = uuid.UUID(str(project_id))
    except ValueError:
        return None
    project = await db.get(Project, project_uuid)
    if project is None:
        return None
    runtime = await load_project_runtime_environment(db, project)
    if task_id is None:
        return runtime
    try:
        task_uuid = uuid.UUID(str(task_id))
    except ValueError:
        return runtime
    task = await db.get(Task, task_uuid)
    extra_env: dict[str, str] = {}
    extra_env["SPINDREL_PROJECT_RUN_GUARD"] = "1"
    extra_env["SPINDREL_PROJECT_TASK_ID"] = str(task_uuid)
    extra_env.update(await _task_dependency_stack_env(db, task))
    extra_env.update(_task_dev_target_env(task))
    return _with_extra_env(runtime, extra_env, extra_keys=tuple(sorted(extra_env)))


def redact_known_values(text: str, values: Mapping[str, str]) -> str:
    env = ProjectRuntimeEnvironment(project_id="", env=values)
    return env.redact_text(text)
