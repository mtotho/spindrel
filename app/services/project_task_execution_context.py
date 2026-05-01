"""Project task execution context.

Single Module owning assembly, persistence, and read-side accessors for the
execution context of a Project task. Replaces the scattered helpers in
``project_coding_runs.py`` that today re-load runtime env, re-allocate dev
targets, and re-shape dependency-stack metadata across four duplicate sites.

The persisted shape under ``Task.execution_config["project_coding_run"]``
(or ``["project_coding_run_review"]`` for review sessions) is canonical and
owned here. ``to_persisted()`` and ``from_task()`` form an inverse pair.

Adapter Protocols (``DevTargetAllocator``, ``DependencyStackSpecResolver``,
``ContextSource``) are wired so future Project task classes — PR-review
automation, ephemeral preview environments, per-target dependency stacks —
slot in additively without redesign. Today there are two production adapters
for each Protocol (Sequential vs. NoOp allocator; Project vs. fresh-context
sources for review sessions), making each a real seam.
"""
from __future__ import annotations

import os
import re
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Project, Task
from app.services.project_dependency_stacks import project_dependency_stack_spec
from app.services.project_runtime import (
    ProjectRuntimeEnvironment,
    load_project_runtime_environment,
    project_snapshot,
)
from app.services.run_presets import (
    RunPreset,
    get_run_preset,
)


# Preset ids — duplicated here so callers can avoid re-importing both this
# Module and ``project_coding_runs``. Keep in sync with run_presets.py.
PROJECT_CODING_RUN_PRESET_ID = "project_coding_run"
PROJECT_CODING_RUN_REVIEW_PRESET_ID = "project_coding_run_review"

DEFAULT_DEV_TARGET_PORT_RANGE = (31_000, 32_999)


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class ExecutionContextError(ValueError):
    """Base for execution-context Module errors."""


class MalformedExecutionContextError(ExecutionContextError):
    """A persisted ``Task.execution_config`` payload is missing required keys.

    Replaces the silent ``cfg.get(...) or []`` fallbacks in continuation and
    receipt code; the caller can catch this specifically to render a typed
    error rather than treating any ValueError as a malformed-context bug.
    """

    def __init__(
        self,
        *,
        task_id: uuid.UUID | None,
        missing_keys: tuple[str, ...],
        kind: str = "project_coding_run",
    ) -> None:
        self.task_id = task_id
        self.missing_keys = missing_keys
        self.kind = kind
        suffix = ", ".join(missing_keys) or "<top-level>"
        super().__init__(
            f"execution context for task {task_id} ({kind}) missing keys: {suffix}"
        )


class PortAllocationError(ExecutionContextError):
    def __init__(self, *, target_key: str, attempted_range: tuple[int, int]) -> None:
        self.target_key = target_key
        self.attempted_range = attempted_range
        super().__init__(
            f"no available dev target port for {target_key} "
            f"in {attempted_range[0]}-{attempted_range[1]}"
        )


class MissingPresetError(ExecutionContextError):
    def __init__(self, preset_id: str) -> None:
        self.preset_id = preset_id
        super().__init__(f"run preset {preset_id} is not registered")


class MissingSecretsError(ExecutionContextError):
    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(
            f"required Project runtime secrets not bound: {', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SnapshotPolicy(Enum):
    """How runtime/stack/dev_target state is frozen at construction."""

    PIN = "pin"
    """Default: freeze runtime_target + dependency_stack at construction time."""

    PIN_STACK_REFRESH_ENV = "pin_stack_refresh_env"
    """Future: pin stack but allow runtime env to refresh on long-lived runs."""


class ContextRefreshPolicy(Enum):
    """How ``from_parent`` reuses parent state."""

    NONE = "none"
    """Verbatim reuse; raise ``MalformedExecutionContextError`` on bad shape."""

    REFRESH_RUNTIME_ENV = "refresh_runtime_env"
    """Inherit dev_targets / dependency_stack; reload runtime_target fresh."""


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DevTarget:
    key: str
    label: str
    port: int
    port_env: str
    url: str
    url_env: str

    def env_pairs(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.port_env:
            out[self.port_env] = str(self.port)
        if self.url_env and self.url:
            out[self.url_env] = self.url
        return out

    def to_persisted(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "port": self.port,
            "port_env": self.port_env,
            "url": self.url,
            "url_env": self.url_env,
        }

    @classmethod
    def from_persisted(cls, raw: Mapping[str, Any]) -> "DevTarget":
        return cls(
            key=str(raw.get("key") or ""),
            label=str(raw.get("label") or ""),
            port=int(raw.get("port") or 0),
            port_env=str(raw.get("port_env") or ""),
            url=str(raw.get("url") or ""),
            url_env=str(raw.get("url_env") or ""),
        )


@dataclass(frozen=True)
class DevTargetSpec:
    key: str
    label: str
    port_env: str
    url_env: str
    url_template: str
    port_range: tuple[int, int]


@dataclass(frozen=True)
class RuntimeTargetView:
    """Secret-safe runtime view persisted on the Task and shown in UI."""

    ready: bool
    configured_keys: tuple[str, ...]
    missing_secrets: tuple[str, ...]

    _RECOGNIZED_KEYS = (
        "SPINDREL_E2E_URL",
        "E2E_BASE_URL",
        "E2E_HOST",
        "E2E_PORT",
        "E2E_API_KEY",
        "SPINDREL_UI_URL",
        "GITHUB_TOKEN",
    )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RuntimeTargetView":
        keys = set(payload.get("env_default_keys") or []) | set(
            payload.get("secret_keys") or []
        )
        configured = tuple(k for k in cls._RECOGNIZED_KEYS if k in keys)
        return cls(
            ready=bool(payload.get("ready")),
            configured_keys=configured,
            missing_secrets=tuple(payload.get("missing_secrets") or ()),
        )

    @classmethod
    def from_persisted(cls, raw: Mapping[str, Any]) -> "RuntimeTargetView":
        return cls(
            ready=bool(raw.get("ready")),
            configured_keys=tuple(raw.get("configured_keys") or ()),
            missing_secrets=tuple(raw.get("missing_secrets") or ()),
        )

    def to_persisted(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "configured_keys": list(self.configured_keys),
            "missing_secrets": list(self.missing_secrets),
        }


@dataclass(frozen=True)
class DependencyStackView:
    configured: bool
    source_path: str | None
    env_keys: tuple[str, ...]
    commands: tuple[str, ...]

    @classmethod
    def from_persisted(cls, raw: Mapping[str, Any]) -> "DependencyStackView":
        return cls(
            configured=bool(raw.get("configured")),
            source_path=raw.get("source_path"),
            env_keys=tuple(raw.get("env_keys") or ()),
            commands=tuple(raw.get("commands") or ()),
        )

    def to_persisted(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "source_path": self.source_path,
            "env_keys": list(self.env_keys),
            "commands": list(self.commands),
        }


@dataclass(frozen=True)
class RunLineage:
    parent_task_id: str | None
    root_task_id: str
    continuation_index: int
    continuation_feedback: str | None = None


@dataclass(frozen=True)
class MachineGrantSummary:
    """Secret-safe view of the task's machine target grant."""

    provider_id: str
    target_id: str
    capabilities: tuple[str, ...]
    allow_agent_tools: bool
    expires_at: str | None

    def to_persisted(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "target_id": self.target_id,
            "capabilities": list(self.capabilities),
            "allow_agent_tools": bool(self.allow_agent_tools),
            "expires_at": self.expires_at,
        }


# ---------------------------------------------------------------------------
# Adapter Protocols
# ---------------------------------------------------------------------------


class PortProber(Protocol):
    def __call__(self, port: int, host: str = "127.0.0.1") -> bool: ...


def default_port_prober(port: int, host: str = "127.0.0.1") -> bool:
    """Probe a TCP port via ``connect_ex``. Returns True if something listens."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.05)
        return sock.connect_ex((host, port)) == 0


class DevTargetAllocator(Protocol):
    async def allocate(
        self,
        db: AsyncSession,
        project: Project,
        *,
        task_id: uuid.UUID,
        specs: list[DevTargetSpec],
    ) -> tuple[DevTarget, ...]: ...


class DependencyStackSpecResolver(Protocol):
    def resolve(self, project: Project) -> DependencyStackView: ...


class ContextSource(Protocol):
    """Source of runtime env + repo/branch defaults for an ExecutionContext."""

    async def runtime(self, db: AsyncSession) -> ProjectRuntimeEnvironment: ...

    def repo_and_branch(
        self, *, request: str, task_id: uuid.UUID
    ) -> tuple[dict[str, Any], str | None, str | None]: ...


# ---------------------------------------------------------------------------
# Default adapter implementations
# ---------------------------------------------------------------------------


class SequentialPortAllocator:
    """Production allocator: scan each spec's port range for a free port.

    ``prober=None`` resolves ``default_port_prober`` at allocation time via
    module-level lookup, so tests monkeypatching
    ``app.services.project_task_execution_context.default_port_prober`` are
    honored without having to reach into this Adapter's constructor.
    """

    def __init__(self, *, prober: PortProber | None = None) -> None:
        self._prober = prober

    async def allocate(
        self,
        db: AsyncSession,
        project: Project,
        *,
        task_id: uuid.UUID,
        specs: list[DevTargetSpec],
    ) -> tuple[DevTarget, ...]:
        if not specs:
            return ()
        prober = self._prober if self._prober is not None else default_port_prober
        assigned_ports = await _collect_active_run_ports(db, project, exclude_task_id=task_id)
        allocated: list[DevTarget] = []
        for spec in specs:
            start, end = spec.port_range
            chosen: int | None = None
            for candidate in range(start, end + 1):
                if candidate in assigned_ports or prober(candidate):
                    continue
                chosen = candidate
                assigned_ports.add(candidate)
                break
            if chosen is None:
                raise PortAllocationError(
                    target_key=spec.key, attempted_range=(start, end)
                )
            url = spec.url_template.replace("{host}", "127.0.0.1").replace(
                "{port}", str(chosen)
            )
            allocated.append(
                DevTarget(
                    key=spec.key,
                    label=spec.label,
                    port=chosen,
                    port_env=spec.port_env,
                    url=url,
                    url_env=spec.url_env,
                )
            )
        return tuple(allocated)


class NoOpAllocator:
    """Allocator used by review sessions and PR-review automation: zero ports."""

    async def allocate(
        self,
        db: AsyncSession,
        project: Project,
        *,
        task_id: uuid.UUID,
        specs: list[DevTargetSpec],
    ) -> tuple[DevTarget, ...]:
        return ()


class WholeProjectResolver:
    """Default resolver: read the Project's compose.yaml-backed stack spec."""

    def resolve(self, project: Project) -> DependencyStackView:
        spec = project_dependency_stack_spec(project)
        return DependencyStackView(
            configured=spec.configured,
            source_path=spec.source_path,
            env_keys=tuple(sorted((spec.env or {}).keys())),
            commands=tuple(sorted((spec.commands or {}).keys())),
        )


class ProjectContextSource:
    """Default source: load runtime env + first-repo from a Project."""

    def __init__(self, project: Project) -> None:
        self._project = project

    async def runtime(self, db: AsyncSession) -> ProjectRuntimeEnvironment:
        return await load_project_runtime_environment(db, self._project)

    def repo_and_branch(
        self, *, request: str, task_id: uuid.UUID
    ) -> tuple[dict[str, Any], str | None, str | None]:
        snapshot = project_snapshot(self._project)
        repo = _first_repo(snapshot)
        base_branch = str(repo.get("branch") or "").strip() or None
        branch = (
            f"spindrel/project-{str(task_id)[:8]}-"
            f"{_slug(request or self._project.name)}"
        )[:96]
        return (
            {
                "name": str(repo.get("name") or "").strip() or None,
                "path": str(repo.get("path") or "").strip() or None,
                "url": str(repo.get("url") or "").strip() or None,
            },
            branch,
            base_branch,
        )


# ---------------------------------------------------------------------------
# The main value type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectTaskExecutionContext:
    """Materialised execution context for one Project task.

    Construction is via the four classmethods. Read accessors are
    ``@property``-style. ``apply_to_task`` writes the persisted shape onto a
    Task without touching the DB; ``from_task`` reads it back. The pair forms
    a byte-stable round-trip that is the deletion test for this Module.
    """

    project_id: str
    kind: str  # "project_coding_run" or "project_coding_run_review"
    preset_id: str
    request: str
    repo: dict[str, Any]
    branch: str | None
    base_branch: str | None
    dev_targets: tuple[DevTarget, ...]
    dependency_stack: DependencyStackView
    runtime_target: RuntimeTargetView
    lineage: RunLineage
    machine_grant: MachineGrantSummary | None
    source_work_pack_id: str | None
    schedule_task_id: str | None
    schedule_run_number: int | None
    selected_task_ids: tuple[str, ...] = ()  # populated for review only
    # Review-only fields. When kind == "project_coding_run_review", these drive
    # the narrower persisted shape under execution_config["project_coding_run_review"].
    operator_prompt: str | None = None
    merge_method: str | None = None
    repo_path: str | None = None
    # Continuation provenance — set on tasks built via ``from_parent``.
    prior_evidence: dict[str, Any] | None = None
    continued_from_handoff_url: str | None = None

    # In-memory only; never serialised, never reaches UI.
    _runtime_env: Mapping[str, str] = field(default_factory=dict, repr=False)
    _preset: RunPreset | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    async def fresh(
        cls,
        db: AsyncSession,
        project: Project,
        *,
        task_id: uuid.UUID,
        request: str = "",
        machine_grant: "MachineGrantInput | None" = None,
        source_work_pack_id: uuid.UUID | None = None,
        schedule_task_id: uuid.UUID | None = None,
        schedule_run_number: int | None = None,
        allocator: DevTargetAllocator | None = None,
        resolver: DependencyStackSpecResolver | None = None,
        source: ContextSource | None = None,
        preset_id: str = PROJECT_CODING_RUN_PRESET_ID,
        snapshot_policy: SnapshotPolicy = SnapshotPolicy.PIN,
    ) -> "ProjectTaskExecutionContext":
        """Assemble a fresh context: load runtime, allocate dev targets, resolve stack."""
        preset = _require_preset(preset_id)
        allocator = allocator or SequentialPortAllocator()
        resolver = resolver or WholeProjectResolver()
        source = source or ProjectContextSource(project)

        runtime = await source.runtime(db)
        runtime_target = RuntimeTargetView.from_payload(runtime.safe_payload())
        repo, branch, base_branch = source.repo_and_branch(
            request=request, task_id=task_id
        )
        specs = _dev_target_specs(project)
        dev_targets = await allocator.allocate(db, project, task_id=task_id, specs=specs)
        dependency_stack = resolver.resolve(project)
        machine_summary = _machine_grant_summary_from_input(machine_grant)

        return cls(
            project_id=str(project.id),
            kind="project_coding_run",
            preset_id=preset_id,
            request=request.strip(),
            repo=repo,
            branch=branch,
            base_branch=base_branch,
            dev_targets=dev_targets,
            dependency_stack=dependency_stack,
            runtime_target=runtime_target,
            lineage=RunLineage(
                parent_task_id=None,
                root_task_id=str(task_id),
                continuation_index=0,
                continuation_feedback=None,
            ),
            machine_grant=machine_summary,
            source_work_pack_id=str(source_work_pack_id) if source_work_pack_id else None,
            schedule_task_id=str(schedule_task_id) if schedule_task_id else None,
            schedule_run_number=int(schedule_run_number) if schedule_run_number is not None else None,
            selected_task_ids=(),
            _runtime_env=dict(runtime.env),
            _preset=preset,
        )

    @classmethod
    async def from_parent(
        cls,
        db: AsyncSession,
        project: Project,
        parent_task: Task,
        *,
        new_task_id: uuid.UUID,
        feedback: str = "",
        prior_evidence: dict[str, Any] | None = None,
        continued_from_handoff_url: str | None = None,
        continuation_index: int | None = None,
        refresh: ContextRefreshPolicy = ContextRefreshPolicy.NONE,
        preset_id: str = PROJECT_CODING_RUN_PRESET_ID,
    ) -> "ProjectTaskExecutionContext":
        """Continuation: reuse parent's persisted shape verbatim, with one allowed
        refresh axis (runtime env). Raises ``MalformedExecutionContextError`` if
        the parent's ``execution_config`` is missing required keys.
        """
        preset = _require_preset(preset_id)
        parent_ctx = cls.from_task(parent_task)
        # Strict validation: continuation requires the parent to have a fully
        # populated context, not the lenient defaults from_task tolerates.
        missing: list[str] = []
        parent_run = (
            parent_task.execution_config.get("project_coding_run")
            if isinstance(parent_task.execution_config, dict)
            else None
        )
        if not isinstance(parent_run, dict):
            missing.append("project_coding_run")
        else:
            for key in ("project_id", "runtime_target", "dev_targets", "dependency_stack"):
                if key not in parent_run:
                    missing.append(key)
        if missing:
            raise MalformedExecutionContextError(
                task_id=parent_task.id,
                missing_keys=tuple(missing),
                kind="project_coding_run",
            )

        if refresh is ContextRefreshPolicy.REFRESH_RUNTIME_ENV:
            runtime = await load_project_runtime_environment(db, project)
            runtime_target = RuntimeTargetView.from_payload(runtime.safe_payload())
            runtime_env: Mapping[str, str] = dict(runtime.env)
        else:
            runtime_target = parent_ctx.runtime_target
            runtime_env = dict(parent_ctx._runtime_env)

        if continuation_index is None:
            continuation_index = parent_ctx.lineage.continuation_index + 1

        feedback_text = feedback.strip() or None

        return cls(
            project_id=parent_ctx.project_id,
            kind="project_coding_run",
            preset_id=preset_id,
            request=parent_ctx.request,
            repo=dict(parent_ctx.repo),
            branch=parent_ctx.branch,
            base_branch=parent_ctx.base_branch,
            dev_targets=parent_ctx.dev_targets,
            dependency_stack=parent_ctx.dependency_stack,
            runtime_target=runtime_target,
            lineage=RunLineage(
                parent_task_id=str(parent_task.id),
                root_task_id=parent_ctx.lineage.root_task_id,
                continuation_index=continuation_index,
                continuation_feedback=feedback_text,
            ),
            machine_grant=parent_ctx.machine_grant,
            source_work_pack_id=parent_ctx.source_work_pack_id,
            schedule_task_id=parent_ctx.schedule_task_id,
            schedule_run_number=parent_ctx.schedule_run_number,
            selected_task_ids=(),
            prior_evidence=prior_evidence,
            continued_from_handoff_url=continued_from_handoff_url,
            _runtime_env=runtime_env,
            _preset=preset,
        )

    @classmethod
    async def review(
        cls,
        db: AsyncSession,
        project: Project,
        *,
        task_id: uuid.UUID,
        selected_task_ids: list[uuid.UUID] | tuple[uuid.UUID, ...] = (),
        operator_prompt: str = "",
        merge_method: str = "squash",
        repo_path: str | None = None,
        machine_grant: "MachineGrantInput | None" = None,
        granted_by_user_id: uuid.UUID | None = None,
        resolver: DependencyStackSpecResolver | None = None,
        source: ContextSource | None = None,
        preset_id: str = PROJECT_CODING_RUN_REVIEW_PRESET_ID,
    ) -> "ProjectTaskExecutionContext":
        """Review session context: fresh runtime env, NO dev_target allocation."""
        preset = _require_preset(preset_id)
        resolver = resolver or WholeProjectResolver()
        source = source or ProjectContextSource(project)
        runtime = await source.runtime(db)
        runtime_target = RuntimeTargetView.from_payload(runtime.safe_payload())
        repo, _branch, base_branch = source.repo_and_branch(
            request="", task_id=task_id
        )
        dependency_stack = resolver.resolve(project)
        machine_summary = _machine_grant_summary_from_input(machine_grant)

        return cls(
            project_id=str(project.id),
            kind="project_coding_run_review",
            preset_id=preset_id,
            request="",
            repo=repo,
            branch=None,
            base_branch=base_branch,
            dev_targets=(),
            dependency_stack=dependency_stack,
            runtime_target=runtime_target,
            lineage=RunLineage(
                parent_task_id=None,
                root_task_id=str(task_id),
                continuation_index=0,
                continuation_feedback=None,
            ),
            machine_grant=machine_summary,
            source_work_pack_id=None,
            schedule_task_id=None,
            schedule_run_number=None,
            selected_task_ids=tuple(str(rid) for rid in selected_task_ids),
            operator_prompt=operator_prompt or None,
            merge_method=merge_method,
            repo_path=repo_path,
            _runtime_env=dict(runtime.env),
            _preset=preset,
        )

    @classmethod
    def from_task(cls, task: Task) -> "ProjectTaskExecutionContext":
        """Read-only reconstitution from ``task.execution_config``. No DB hit.

        Raises ``MalformedExecutionContextError`` only when neither
        ``project_coding_run`` nor ``project_coding_run_review`` is present.
        Missing inner fields default to empty/None so receipt code and row
        renderers can read tolerantly. Strict callers (``from_parent``)
        validate required fields explicitly via ``require_fields``.
        """
        ecfg = task.execution_config if isinstance(task.execution_config, dict) else {}
        kind = "project_coding_run"
        run = ecfg.get("project_coding_run")
        if not isinstance(run, dict):
            run = ecfg.get("project_coding_run_review")
            if isinstance(run, dict):
                kind = "project_coding_run_review"
            else:
                raise MalformedExecutionContextError(
                    task_id=task.id, missing_keys=(), kind="project_coding_run"
                )

        if kind == "project_coding_run_review":
            machine_summary: MachineGrantSummary | None = None
            machine_raw = run.get("machine_target_grant")
            if isinstance(machine_raw, dict) and machine_raw.get("provider_id"):
                machine_summary = MachineGrantSummary(
                    provider_id=str(machine_raw["provider_id"]),
                    target_id=str(machine_raw.get("target_id") or ""),
                    capabilities=tuple(machine_raw.get("capabilities") or ()),
                    allow_agent_tools=bool(machine_raw.get("allow_agent_tools", True)),
                    expires_at=machine_raw.get("expires_at"),
                )
            return cls(
                project_id=str(run.get("project_id") or ""),
                kind=kind,
                preset_id=str(ecfg.get("run_preset_id") or kind),
                request="",
                repo={},
                branch=None,
                base_branch=None,
                dev_targets=(),
                dependency_stack=DependencyStackView(False, None, (), ()),
                runtime_target=RuntimeTargetView(False, (), ()),
                lineage=RunLineage(
                    parent_task_id=None,
                    root_task_id=str(task.id),
                    continuation_index=0,
                ),
                machine_grant=machine_summary,
                source_work_pack_id=None,
                schedule_task_id=None,
                schedule_run_number=None,
                selected_task_ids=tuple(
                    str(rid) for rid in (run.get("selected_task_ids") or ()) if rid is not None
                ),
                operator_prompt=run.get("operator_prompt") or None,
                merge_method=run.get("merge_method") or None,
                repo_path=run.get("repo_path") or None,
                prior_evidence=None,
                continued_from_handoff_url=None,
                _runtime_env={},
                _preset=None,
            )

        runtime_target_raw = run.get("runtime_target")
        if not isinstance(runtime_target_raw, dict):
            runtime_target_raw = {}
        dependency_stack_raw = run.get("dependency_stack")
        if not isinstance(dependency_stack_raw, dict):
            dependency_stack_raw = {}

        dev_targets_raw = run.get("dev_targets") or ()
        dev_targets = tuple(
            DevTarget.from_persisted(item)
            for item in dev_targets_raw
            if isinstance(item, dict)
        )

        machine_summary: MachineGrantSummary | None = None
        machine_raw = run.get("machine_target_grant")
        if isinstance(machine_raw, dict) and machine_raw.get("provider_id"):
            machine_summary = MachineGrantSummary(
                provider_id=str(machine_raw["provider_id"]),
                target_id=str(machine_raw.get("target_id") or ""),
                capabilities=tuple(machine_raw.get("capabilities") or ()),
                allow_agent_tools=bool(machine_raw.get("allow_agent_tools", True)),
                expires_at=machine_raw.get("expires_at"),
            )

        repo_raw = run.get("repo")
        repo = dict(repo_raw) if isinstance(repo_raw, dict) else {}

        try:
            continuation_index = int(run.get("continuation_index") or 0)
        except (TypeError, ValueError):
            continuation_index = 0
        lineage = RunLineage(
            parent_task_id=str(run["parent_task_id"]) if run.get("parent_task_id") else None,
            root_task_id=str(run.get("root_task_id") or task.id),
            continuation_index=max(0, continuation_index),
            continuation_feedback=(
                str(run.get("continuation_feedback") or "").strip() or None
            ),
        )

        try:
            schedule_run_number = (
                int(run["schedule_run_number"])
                if run.get("schedule_run_number") is not None
                else None
            )
        except (TypeError, ValueError):
            schedule_run_number = None

        selected_task_ids_raw = run.get("selected_task_ids") or ()
        selected_task_ids = tuple(
            str(rid) for rid in selected_task_ids_raw if rid is not None
        )

        prior_evidence_raw = run.get("prior_evidence")
        prior_evidence = (
            dict(prior_evidence_raw) if isinstance(prior_evidence_raw, dict) else None
        )
        continued_from_handoff_url_raw = run.get("continued_from_handoff_url")
        continued_from_handoff_url = (
            str(continued_from_handoff_url_raw)
            if isinstance(continued_from_handoff_url_raw, str) and continued_from_handoff_url_raw
            else None
        )

        return cls(
            project_id=str(run.get("project_id") or ""),
            kind=kind,
            preset_id=str(ecfg.get("run_preset_id") or kind),
            request=str(run.get("request") or ""),
            repo=repo,
            branch=run.get("branch"),
            base_branch=run.get("base_branch"),
            dev_targets=dev_targets,
            dependency_stack=DependencyStackView.from_persisted(dependency_stack_raw),
            runtime_target=RuntimeTargetView.from_persisted(runtime_target_raw),
            lineage=lineage,
            machine_grant=machine_summary,
            source_work_pack_id=(
                str(run["source_work_pack_id"]) if run.get("source_work_pack_id") else None
            ),
            schedule_task_id=(
                str(run["schedule_task_id"]) if run.get("schedule_task_id") else None
            ),
            schedule_run_number=schedule_run_number,
            selected_task_ids=selected_task_ids,
            prior_evidence=prior_evidence,
            continued_from_handoff_url=continued_from_handoff_url,
            _runtime_env={},  # not persisted
            _preset=None,  # not persisted
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_persisted(self) -> dict[str, Any]:
        """Return the dict stored at ``Task.execution_config[self.kind]``.

        Two shapes:
          - ``project_coding_run`` — full context (request, branch, dev_targets,
            runtime_target, dependency_stack, lineage, ...).
          - ``project_coding_run_review`` — narrower (project_id, selected_task_ids,
            operator_prompt, merge_method, repo_path, machine_target_grant).

        Round-trips byte-stable through ``from_task``: the inverse property is
        the deletion test for this Module.
        """
        if self.kind == "project_coding_run_review":
            return {
                "project_id": self.project_id,
                "selected_task_ids": list(self.selected_task_ids),
                "operator_prompt": self.operator_prompt or "",
                "merge_method": self.merge_method or "squash",
                "repo_path": self.repo_path,
                "machine_target_grant": (
                    self.machine_grant.to_persisted() if self.machine_grant else None
                ),
            }

        run: dict[str, Any] = {
            "project_id": self.project_id,
            "request": self.request,
            "branch": self.branch,
            "base_branch": self.base_branch,
            "repo": dict(self.repo),
            "runtime_target": self.runtime_target.to_persisted(),
            "dev_targets": [t.to_persisted() for t in self.dev_targets],
            "dev_target_env": self._dev_target_env(),
            "dependency_stack": self.dependency_stack.to_persisted(),
            "machine_target_grant": (
                self.machine_grant.to_persisted() if self.machine_grant else None
            ),
            "source_work_pack_id": self.source_work_pack_id,
            "schedule_task_id": self.schedule_task_id,
            "schedule_run_number": self.schedule_run_number,
            "continuation_index": self.lineage.continuation_index,
            "root_task_id": self.lineage.root_task_id,
        }
        if self.lineage.parent_task_id is not None:
            run["parent_task_id"] = self.lineage.parent_task_id
        if self.lineage.continuation_feedback is not None:
            run["continuation_feedback"] = self.lineage.continuation_feedback
        if self.prior_evidence is not None:
            run["prior_evidence"] = dict(self.prior_evidence)
        if self.continued_from_handoff_url is not None:
            run["continued_from_handoff_url"] = self.continued_from_handoff_url
        return run

    def execution_config(self) -> dict[str, Any]:
        """Full ``Task.execution_config`` dict for ``apply_to_task``."""
        if self._preset is None or self._preset.task_defaults is None:
            raise ExecutionContextError(
                "execution_config() requires a constructed context "
                "(use fresh/from_parent/review, not from_task)"
            )
        defaults = self._preset.task_defaults
        ecfg: dict[str, Any] = {
            "run_preset_id": self.preset_id,
            "skills": list(defaults.skills),
            "tools": list(defaults.tools),
            "post_final_to_channel": defaults.post_final_to_channel,
            "history_mode": defaults.history_mode,
            "history_recent_count": defaults.history_recent_count,
            "skip_tool_approval": defaults.skip_tool_approval,
            "session_target": dict(defaults.session_target or {}),
            "project_instance": dict(defaults.project_instance or {}),
            "allow_issue_reporting": defaults.allow_issue_reporting,
            "harness_effort": defaults.harness_effort,
            self.kind: self.to_persisted(),
        }
        return ecfg

    def apply_to_task(self, task: Task, *, channel: Channel) -> None:
        """Set Task fields from this context. Caller still owns db.add/commit."""
        if self._preset is None or self._preset.task_defaults is None:
            raise ExecutionContextError(
                "apply_to_task requires a constructed context "
                "(use fresh/from_parent/review, not from_task)"
            )
        defaults = self._preset.task_defaults
        task.execution_config = self.execution_config()
        task.task_type = defaults.task_type
        task.trigger_config = dict(defaults.trigger_config)
        task.max_run_seconds = defaults.max_run_seconds
        if not task.title:
            task.title = defaults.title
        task.dispatch_type = (
            channel.integration
            if channel.integration and channel.dispatch_config
            else "none"
        )
        task.dispatch_config = (
            dict(channel.dispatch_config)
            if channel.integration and channel.dispatch_config
            else None
        )
        task.bot_id = channel.bot_id
        task.client_id = channel.client_id
        task.session_id = channel.active_session_id
        task.channel_id = channel.id

    # ------------------------------------------------------------------
    # Read accessors / convenience views
    # ------------------------------------------------------------------

    def runtime_safe_payload(self) -> dict[str, Any]:
        """The shape returned by ``ProjectRuntimeEnvironment.safe_payload`` —
        derived from this context's persisted state, no DB hit."""
        return {
            "source": "blueprint_snapshot",
            "ready": self.runtime_target.ready,
            "env_default_keys": list(self.runtime_target.configured_keys),
            "secret_keys": [],
            "missing_secrets": list(self.runtime_target.missing_secrets),
            "invalid_env_keys": [],
            "reserved_env_keys": [],
        }

    def env_for_subprocess(self) -> dict[str, str]:
        """Process env for shell substitution: runtime env + dev_target env."""
        env: dict[str, str] = dict(self._runtime_env)
        env.update(self._dev_target_env())
        return env

    def _dev_target_env(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for target in self.dev_targets:
            out.update(target.env_pairs())
        return out

    def runtime_env_redact_text(self, text: str) -> str:
        """Redact known runtime-env values from a string, longest first."""
        if not self._runtime_env:
            return text
        out = text
        values = sorted(
            (str(v) for v in self._runtime_env.values() if v), key=len, reverse=True
        )
        for value in values:
            out = out.replace(value, "[REDACTED]")
        return out


# ---------------------------------------------------------------------------
# ContextAssembler — exotic shapes (PR-review automation, preview envs, etc.)
# ---------------------------------------------------------------------------


@dataclass
class ContextAssembler:
    """Direct constructor for non-default Adapter combinations.

    The four classmethods on ``ProjectTaskExecutionContext`` are sugar over
    this. Use this directly when wiring a future Project task class — e.g.
    PR-review automation with a remote PR ContextSource, or an ephemeral
    preview environment with ``IsolatedRangeAllocator``.
    """

    allocator: DevTargetAllocator
    resolver: DependencyStackSpecResolver
    source: ContextSource
    preset: RunPreset
    kind: str = "project_coding_run"

    async def build(
        self,
        db: AsyncSession,
        project: Project,
        *,
        task_id: uuid.UUID,
        request: str = "",
        machine_grant: "MachineGrantInput | None" = None,
        source_work_pack_id: uuid.UUID | None = None,
        schedule_task_id: uuid.UUID | None = None,
        schedule_run_number: int | None = None,
        selected_task_ids: list[uuid.UUID] | tuple[uuid.UUID, ...] = (),
    ) -> ProjectTaskExecutionContext:
        runtime = await self.source.runtime(db)
        runtime_target = RuntimeTargetView.from_payload(runtime.safe_payload())
        repo, branch, base_branch = self.source.repo_and_branch(
            request=request, task_id=task_id
        )
        if self.kind == "project_coding_run_review":
            specs: list[DevTargetSpec] = []
        else:
            specs = _dev_target_specs(project)
        dev_targets = await self.allocator.allocate(
            db, project, task_id=task_id, specs=specs
        )
        dependency_stack = self.resolver.resolve(project)

        return ProjectTaskExecutionContext(
            project_id=str(project.id),
            kind=self.kind,
            preset_id=self.preset.id,
            request=request.strip(),
            repo=repo,
            branch=branch if self.kind != "project_coding_run_review" else None,
            base_branch=base_branch,
            dev_targets=dev_targets,
            dependency_stack=dependency_stack,
            runtime_target=runtime_target,
            lineage=RunLineage(
                parent_task_id=None,
                root_task_id=str(task_id),
                continuation_index=0,
                continuation_feedback=None,
            ),
            machine_grant=_machine_grant_summary_from_input(machine_grant),
            source_work_pack_id=str(source_work_pack_id) if source_work_pack_id else None,
            schedule_task_id=str(schedule_task_id) if schedule_task_id else None,
            schedule_run_number=int(schedule_run_number) if schedule_run_number is not None else None,
            selected_task_ids=tuple(str(rid) for rid in selected_task_ids),
            prior_evidence=None,
            continued_from_handoff_url=None,
            _runtime_env=dict(runtime.env),
            _preset=self.preset,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# Structural shape for input grants. Both ``ProjectMachineTargetGrant`` (the
# dataclass in ``project_coding_runs``) and a plain dict satisfy this, so the
# Module avoids a circular import on the orchestration layer.
class MachineGrantInput(Protocol):
    provider_id: str
    target_id: str
    capabilities: list[str] | None
    allow_agent_tools: bool
    expires_at: str | datetime | None


def _machine_grant_summary_from_input(
    grant: MachineGrantInput | None,
) -> MachineGrantSummary | None:
    if grant is None:
        return None
    expires = getattr(grant, "expires_at", None)
    if isinstance(expires, datetime):
        expires_str: str | None = expires.isoformat()
    else:
        expires_str = expires if expires is None or isinstance(expires, str) else str(expires)
    return MachineGrantSummary(
        provider_id=str(grant.provider_id),
        target_id=str(grant.target_id),
        capabilities=tuple(grant.capabilities or ()),
        allow_agent_tools=bool(grant.allow_agent_tools),
        expires_at=expires_str,
    )


def _require_preset(preset_id: str) -> RunPreset:
    preset = get_run_preset(preset_id)
    if preset is None:
        raise MissingPresetError(preset_id)
    return preset


def _slug(text: str, *, fallback: str = "coding-run", max_len: int = 40) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return (value or fallback)[:max_len].strip("-") or fallback


def _first_repo(snapshot: dict[str, Any]) -> dict[str, Any]:
    repos = snapshot.get("repos")
    if isinstance(repos, list):
        for repo in repos:
            if isinstance(repo, dict):
                return repo
    return {}


def _dev_target_specs(project: Project) -> list[DevTargetSpec]:
    metadata = project.metadata_ if isinstance(project.metadata_, dict) else {}
    raw = metadata.get("dev_targets")
    snapshot = project_snapshot(project)
    if not isinstance(raw, list):
        raw = snapshot.get("dev_targets")
    if not isinstance(raw, list) and isinstance(snapshot.get("metadata"), dict):
        raw = snapshot["metadata"].get("dev_targets")
    if not isinstance(raw, list):
        return []
    specs: list[DevTargetSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        key = _slug(
            str(item.get("key") or item.get("name") or f"target-{index + 1}"),
            fallback=f"target-{index + 1}",
            max_len=32,
        )
        env_segment = (
            re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").upper()
            or f"TARGET_{index + 1}"
        )
        port_range = _parse_port_range(item.get("port_range"))
        specs.append(
            DevTargetSpec(
                key=key,
                label=str(item.get("label") or item.get("name") or key),
                port_env=str(item.get("port_env") or f"SPINDREL_DEV_{env_segment}_PORT"),
                url_env=str(item.get("url_env") or f"SPINDREL_DEV_{env_segment}_URL"),
                url_template=str(item.get("url_template") or "http://127.0.0.1:{port}"),
                port_range=port_range,
            )
        )
    return specs


def _parse_port_range(value: Any) -> tuple[int, int]:
    rng: tuple[int, int] = DEFAULT_DEV_TARGET_PORT_RANGE
    if isinstance(value, str) and "-" in value:
        start, end = value.split("-", 1)
        try:
            rng = (int(start), int(end))
        except ValueError:
            rng = DEFAULT_DEV_TARGET_PORT_RANGE
    elif isinstance(value, list) and len(value) == 2:
        try:
            rng = (int(value[0]), int(value[1]))
        except (TypeError, ValueError):
            rng = DEFAULT_DEV_TARGET_PORT_RANGE
    if rng[0] <= 0 or rng[1] > 65_535 or rng[0] > rng[1]:
        return DEFAULT_DEV_TARGET_PORT_RANGE
    return rng


async def _collect_active_run_ports(
    db: AsyncSession,
    project: Project,
    *,
    exclude_task_id: uuid.UUID | None = None,
) -> set[int]:
    """Read sibling Tasks' allocated ports so a new allocation skips them."""
    channel_ids = list(
        (
            await db.execute(
                select(Channel.id).where(Channel.project_id == project.id)
            )
        )
        .scalars()
        .all()
    )
    if not channel_ids:
        return set()
    rows = (
        await db.execute(
            select(Task).where(
                Task.channel_id.in_(channel_ids),
                Task.id != exclude_task_id if exclude_task_id is not None else True,
            )
        )
    ).scalars().all()
    assigned: set[int] = set()
    for task in rows:
        if task.status in {"complete", "completed", "failed", "cancelled"}:
            continue
        if not isinstance(task.execution_config, dict):
            continue
        cfg = task.execution_config.get("project_coding_run")
        if not isinstance(cfg, dict):
            continue
        for target in cfg.get("dev_targets") or []:
            if not isinstance(target, dict):
                continue
            try:
                assigned.add(int(target.get("port")))
            except (TypeError, ValueError):
                continue
    return assigned
