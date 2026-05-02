"""API v1 — Projects."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Project, ProjectBlueprint, ProjectInstance, ProjectRunReceipt, ProjectSecretBinding, ProjectSetupRun, SecretValue, SharedWorkspace, Task
from app.dependencies import get_db, require_scopes
from app.services.project_instances import cleanup_project_instance, create_project_instance, list_project_instances, project_directory_from_instance, project_instance_cleanup_summary, project_instance_task_status
from app.services.project_coding_runs import (
    ProjectCodingRunCreate,
    ProjectCodingRunContinue,
    ProjectCodingRunReviewCreate,
    ProjectCodingRunReviewFinalize,
    ProjectCodingRunScheduleCreate,
    ProjectCodingRunScheduleUpdate,
    ProjectMachineTargetGrant,
    cleanup_project_coding_run_instance,
    continue_project_coding_run,
    create_project_coding_run,
    create_project_coding_run_review_session,
    create_project_coding_run_schedule,
    disable_project_coding_run_schedule,
    finalize_project_coding_run_review,
    fire_project_coding_run_schedule,
    get_project_coding_run,
    get_project_coding_run_review_context,
    list_project_factory_review_inbox,
    list_project_coding_run_review_batches,
    list_project_coding_run_review_sessions,
    list_project_coding_run_schedules,
    list_project_coding_runs,
    mark_project_coding_run_reviewed,
    mark_project_coding_runs_reviewed,
    refresh_project_coding_run_status,
    update_project_coding_run_schedule,
)
from app.services.project_run_receipts import create_project_run_receipt, list_project_run_receipts, serialize_project_run_receipt
from app.services.project_coding_run_loops import disable_project_coding_run_loop
from app.services.project_dependency_stacks import (
    destroy_project_dependency_stack,
    ensure_project_dependency_stack_instance,
    exec_project_dependency_stack_command,
    get_project_dependency_stack,
    health_project_dependency_stack,
    prepare_project_dependency_stack,
    project_dependency_stack_logs,
    project_dependency_stack_status,
    restart_project_dependency_stack,
    stop_project_dependency_stack,
)
from app.services.project_setup import list_project_setup_runs, load_project_setup_plan, run_project_setup
from app.services.project_runtime import load_project_runtime_environment
from app.services.project_factory_state import get_project_factory_state
from app.services.projects import (
    materialize_project_blueprint,
    normalize_project_path,
    normalize_project_slug,
    project_blueprint_snapshot,
    project_directory_from_project,
    project_directory_payload,
    render_project_blueprint_root_path,
)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    applied_blueprint_id: uuid.UUID | None = None
    name: str
    slug: str
    description: Optional[str] = None
    root_path: str
    prompt: Optional[str] = None
    prompt_file_path: Optional[str] = None
    metadata_: dict = {}
    resolved: dict | None = None
    blueprint: "ProjectBlueprintSummaryOut | None" = None
    secret_bindings: list["ProjectSecretBindingOut"] = Field(default_factory=list)
    attached_channel_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectWrite(BaseModel):
    workspace_id: uuid.UUID | None = None
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    root_path: str | None = None
    prompt: str | None = None
    prompt_file_path: str | None = None
    metadata_: dict | None = None


class ProjectBlueprintSummaryOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    name: str
    slug: str
    description: str | None = None

    model_config = {"from_attributes": True}


class ProjectBlueprintOut(ProjectBlueprintSummaryOut):
    default_root_path_pattern: str | None = None
    prompt: str | None = None
    prompt_file_path: str | None = None
    folders: list = Field(default_factory=list)
    files: dict = Field(default_factory=dict)
    knowledge_files: dict = Field(default_factory=dict)
    repos: list = Field(default_factory=list)
    setup_commands: list = Field(default_factory=list)
    dependency_stack: dict = Field(default_factory=dict)
    env: dict = Field(default_factory=dict)
    required_secrets: list[str] = Field(default_factory=list)
    metadata_: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ProjectBlueprintWrite(BaseModel):
    workspace_id: uuid.UUID | None = None
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    default_root_path_pattern: str | None = None
    prompt: str | None = None
    prompt_file_path: str | None = None
    folders: list[str] | None = None
    files: dict[str, str] | None = None
    knowledge_files: dict[str, str] | None = None
    repos: list[dict] | None = None
    setup_commands: list[dict] | None = None
    dependency_stack: dict | None = None
    env: dict[str, str] | None = None
    required_secrets: list[str] | None = None
    metadata_: dict | None = None

    @field_validator("folders", "required_secrets")
    @classmethod
    def _strip_list_values(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item and item.strip()]


class ProjectBlueprintFromCurrentWrite(BaseModel):
    name: str | None = None
    apply_to_project: bool = True


class ProjectBlueprintFromCurrentOut(BaseModel):
    blueprint: ProjectBlueprintOut
    project: ProjectOut
    detected_repos: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    applied: bool = False


class ProjectSecretBindingOut(BaseModel):
    id: uuid.UUID
    logical_name: str
    secret_value_id: uuid.UUID | None = None
    secret_value_name: str | None = None
    bound: bool = False


class ProjectSecretBindingsWrite(BaseModel):
    bindings: dict[str, uuid.UUID | None] = Field(default_factory=dict)


class ProjectSetupRunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    source: str
    plan: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectSetupOut(BaseModel):
    plan: dict
    runs: list[ProjectSetupRunOut] = Field(default_factory=list)


class ProjectRuntimeEnvOut(BaseModel):
    source: str
    ready: bool
    env_default_keys: list[str] = Field(default_factory=list)
    secret_keys: list[str] = Field(default_factory=list)
    missing_secrets: list[str] = Field(default_factory=list)
    invalid_env_keys: list[str] = Field(default_factory=list)
    reserved_env_keys: list[str] = Field(default_factory=list)


class ProjectInstanceOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    root_path: str
    status: str
    source: str
    source_snapshot: dict = Field(default_factory=dict)
    setup_result: dict = Field(default_factory=dict)
    metadata_: dict = Field(default_factory=dict)
    owner_kind: str | None = None
    owner_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    resolved: dict | None = None
    cleanup: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class ProjectInstanceWrite(BaseModel):
    owner_kind: str = "manual"
    ttl_seconds: int | None = None
    metadata_: dict | None = None


class ProjectRunReceiptOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_instance_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    bot_id: str | None = None
    idempotency_key: str | None = None
    status: str
    summary: str
    handoff_type: str | None = None
    handoff_url: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    commit_sha: str | None = None
    changed_files: list = Field(default_factory=list)
    tests: list = Field(default_factory=list)
    screenshots: list = Field(default_factory=list)
    dev_targets: list = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class ProjectRunReceiptWrite(BaseModel):
    project_instance_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    bot_id: str | None = None
    idempotency_key: str | None = None
    status: str = "reported"
    summary: str
    handoff_type: str | None = None
    handoff_url: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    commit_sha: str | None = None
    changed_files: list = Field(default_factory=list)
    tests: list = Field(default_factory=list)
    screenshots: list = Field(default_factory=list)
    dev_targets: list = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ProjectMachineTargetGrantIn(BaseModel):
    provider_id: str
    target_id: str
    capabilities: list[str] | None = None
    allow_agent_tools: bool = True
    expires_at: str | None = None


class ProjectRunLoopPolicyIn(BaseModel):
    enabled: bool = False
    max_iterations: int = 3
    stop_condition: str = ""
    continuation_prompt: str = ""


class ProjectCodingRunWrite(BaseModel):
    channel_id: uuid.UUID
    request: str = ""
    repo_path: str | None = None
    machine_target_grant: ProjectMachineTargetGrantIn | None = None
    source_work_pack_id: uuid.UUID | None = None
    loop_policy: ProjectRunLoopPolicyIn | None = None


class ProjectCodingRunContinueWrite(BaseModel):
    feedback: str = ""


class ProjectCodingRunsReviewedWrite(BaseModel):
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    note: str = ""


class ProjectCodingRunReviewSessionWrite(BaseModel):
    channel_id: uuid.UUID
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    prompt: str = ""
    merge_method: str = "squash"
    machine_target_grant: ProjectMachineTargetGrantIn | None = None


class ProjectCodingRunReviewFinalizeWrite(BaseModel):
    review_task_id: uuid.UUID
    run_task_id: uuid.UUID
    outcome: str = "accepted"
    summary: str = ""
    details: dict = Field(default_factory=dict)
    merge: bool = False
    merge_method: str = "squash"


class ProjectCodingRunScheduleWrite(BaseModel):
    channel_id: uuid.UUID
    title: str = "Scheduled Project coding run"
    request: str = ""
    repo_path: str | None = None
    scheduled_at: datetime | None = None
    recurrence: str = "+1w"
    machine_target_grant: ProjectMachineTargetGrantIn | None = None
    loop_policy: ProjectRunLoopPolicyIn | None = None


class ProjectCodingRunSchedulePatch(BaseModel):
    channel_id: uuid.UUID | None = None
    title: str | None = None
    request: str | None = None
    repo_path: str | None = None
    scheduled_at: datetime | None = None
    recurrence: str | None = None
    enabled: bool | None = None
    machine_target_grant: ProjectMachineTargetGrantIn | None = None
    loop_policy: ProjectRunLoopPolicyIn | None = None


class ProjectCodingRunScheduleOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    channel_id: uuid.UUID | None = None
    title: str
    request: str = ""
    repo_path: str | None = None
    status: str
    enabled: bool
    scheduled_at: str | None = None
    recurrence: str | None = None
    run_count: int = 0
    last_run: dict | None = None
    recent_runs: list[dict] = Field(default_factory=list)
    created_at: str | None = None
    machine_target_grant: dict | None = None


class ProjectCodingRunTaskOut(BaseModel):
    id: uuid.UUID
    status: str
    title: str | None = None
    bot_id: str
    channel_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    project_instance_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None
    created_at: str | None = None
    scheduled_at: str | None = None
    run_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    machine_target_grant: dict | None = None


class ProjectCodingRunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    request: str = ""
    branch: str | None = None
    base_branch: str | None = None
    repo: dict = Field(default_factory=dict)
    runtime_target: dict = Field(default_factory=dict)
    dev_targets: list[dict] = Field(default_factory=list)
    dependency_stack: dict = Field(default_factory=dict)
    dependency_stack_preflight: dict = Field(default_factory=dict)
    readiness: dict = Field(default_factory=dict)
    work_surface: dict = Field(default_factory=dict)
    source_work_pack_id: uuid.UUID | None = None
    source_work_pack: dict | None = None
    launch_batch_id: str | None = None
    parent_task_id: uuid.UUID | None = None
    root_task_id: uuid.UUID | None = None
    continuation_index: int = 0
    continuation_feedback: str | None = None
    continuation_count: int = 0
    latest_continuation: dict | None = None
    continuations: list[dict] = Field(default_factory=list)
    loop: dict = Field(default_factory=dict)
    review_queue_state: str | None = None
    review_queue_priority: int | None = None
    review_next_action: str | None = None
    lifecycle: dict = Field(default_factory=dict)
    task: ProjectCodingRunTaskOut
    receipt: ProjectRunReceiptOut | None = None
    activity: list[dict] = Field(default_factory=list)
    review: dict = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class ProjectCodingRunReviewBatchOut(BaseModel):
    id: str
    project_id: uuid.UUID
    status: str
    run_count: int
    status_counts: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)
    run_ids: list[uuid.UUID] = Field(default_factory=list)
    task_ids: list[uuid.UUID] = Field(default_factory=list)
    ready_run_ids: list[uuid.UUID] = Field(default_factory=list)
    unreviewed_run_ids: list[uuid.UUID] = Field(default_factory=list)
    source_work_packs: list[dict] = Field(default_factory=list)
    review_sessions: list[dict] = Field(default_factory=list)
    active_review_task: dict | None = None
    latest_review_task: dict | None = None
    latest_activity_at: str | None = None
    summary: dict = Field(default_factory=dict)
    actions: dict = Field(default_factory=dict)


class ProjectFactoryReviewInboxOut(BaseModel):
    generated_at: str | None = None
    summary: dict = Field(default_factory=dict)
    items: list[dict] = Field(default_factory=list)
    projects: list[dict] = Field(default_factory=list)


class ProjectFactoryStateOut(BaseModel):
    project: dict
    current_stage: str
    blueprint: dict
    runtime_env: dict
    dependency_stack: dict
    intake: dict
    run_packs: dict
    runs: dict
    planning: dict
    recent_receipts: list[dict] = Field(default_factory=list)
    suggested_next_action: dict


class ProjectCodingRunReviewSessionLedgerOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    task_status: str
    title: str | None = None
    session_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    created_at: str | None = None
    completed_at: str | None = None
    latest_activity_at: str | None = None
    selected_task_ids: list[uuid.UUID] = Field(default_factory=list)
    selected_run_ids: list[uuid.UUID] = Field(default_factory=list)
    run_count: int
    launch_batch_ids: list[str] = Field(default_factory=list)
    outcome_counts: dict = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)
    source_work_packs: list[dict] = Field(default_factory=list)
    selected_runs: list[dict] = Field(default_factory=list)
    summaries: list[dict] = Field(default_factory=list)
    latest_summary: str | None = None
    merge: dict = Field(default_factory=dict)
    actions: dict = Field(default_factory=dict)


class ProjectFromBlueprintWrite(BaseModel):
    blueprint_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    name: str
    slug: str | None = None
    description: str | None = None
    root_path: str | None = None
    secret_bindings: dict[str, uuid.UUID | None] = Field(default_factory=dict)


class ProjectDependencyStackActionWrite(BaseModel):
    action: str = "status"
    service: str | None = None
    command: str | None = None
    command_name: str | None = None
    tail: int | None = None
    keep_volumes: bool = False


ProjectOut.model_rebuild()


class ProjectChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str

    model_config = {"from_attributes": True}


async def _default_workspace_id(db: AsyncSession) -> uuid.UUID:
    row = (await db.execute(select(SharedWorkspace.id).order_by(SharedWorkspace.created_at).limit(1))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=422, detail="No shared workspace exists")
    return row


async def _project_out(db: AsyncSession, project: Project) -> ProjectOut:
    out = ProjectOut(
        id=project.id,
        workspace_id=project.workspace_id,
        applied_blueprint_id=project.applied_blueprint_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        root_path=project.root_path,
        prompt=project.prompt,
        prompt_file_path=project.prompt_file_path,
        metadata_=project.metadata_ or {},
        created_at=project.created_at,
        updated_at=project.updated_at,
    )
    out.resolved = project_directory_payload(project_directory_from_project(project))
    if project.applied_blueprint_id:
        blueprint = await db.get(ProjectBlueprint, project.applied_blueprint_id)
        if blueprint is not None:
            out.blueprint = ProjectBlueprintSummaryOut.model_validate(blueprint)
    out.secret_bindings = await _project_secret_bindings_out(db, project.id)
    out.attached_channel_count = int((await db.execute(
        select(func.count()).select_from(Channel).where(Channel.project_id == project.id)
    )).scalar_one() or 0)
    return out


async def _project_secret_bindings_out(db: AsyncSession, project_id: uuid.UUID) -> list[ProjectSecretBindingOut]:
    rows = (await db.execute(
        select(ProjectSecretBinding, SecretValue.name)
        .outerjoin(SecretValue, SecretValue.id == ProjectSecretBinding.secret_value_id)
        .where(ProjectSecretBinding.project_id == project_id)
        .order_by(ProjectSecretBinding.logical_name)
    )).all()
    return [
        ProjectSecretBindingOut(
            id=binding.id,
            logical_name=binding.logical_name,
            secret_value_id=binding.secret_value_id,
            secret_value_name=secret_name,
            bound=binding.secret_value_id is not None and bool(secret_name),
        )
        for binding, secret_name in rows
    ]


def _blueprint_required_secret_names(blueprint: ProjectBlueprint) -> list[str]:
    names: list[str] = []
    for item in blueprint.required_secrets or []:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("key") or "").strip()
        else:
            name = ""
        if name and name not in names:
            names.append(name)
    return names


async def _ensure_secret_values_exist(db: AsyncSession, binding_ids: dict[str, uuid.UUID | None]) -> None:
    for logical_name, secret_id in binding_ids.items():
        if secret_id is None:
            continue
        if await db.get(SecretValue, secret_id) is None:
            raise HTTPException(status_code=422, detail=f"secret binding '{logical_name}' references an unknown secret")


def _blueprint_out(blueprint: ProjectBlueprint) -> ProjectBlueprintOut:
    return ProjectBlueprintOut.model_validate(blueprint)


async def _git_value(cwd: Path, *args: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    value = stdout.decode(errors="replace").strip()
    return value or None


async def _detect_project_repos(project: Project) -> tuple[list[dict], list[str]]:
    project_dir = project_directory_from_project(project)
    root = Path(project_dir.host_path).resolve()
    warnings: list[str] = []
    if not root.exists():
        return [], [f"Project root does not exist yet: /{project.root_path}"]

    candidates: list[Path] = []
    if (root / ".git").exists():
        warnings.append(
            "The Project root itself is a git repository. Blueprint setup clones repos into child paths, "
            "so add an explicit repo declaration if this Project should be recreated at the root."
        )
    for parent, dirs, _files in os.walk(root):
        parent_path = Path(parent)
        depth = len(parent_path.relative_to(root).parts)
        if depth > 2:
            dirs[:] = []
            continue
        if ".git" in dirs:
            candidates.append(parent_path)
            dirs[:] = []

    repos: list[dict] = []
    seen: set[str] = set()
    for repo_path in candidates:
        if repo_path == root:
            continue
        rel = repo_path.relative_to(root).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        remote = await _git_value(repo_path, "remote", "get-url", "origin")
        branch = await _git_value(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        repos.append(
            {
                "name": repo_path.name,
                "url": remote or "",
                "path": rel,
                "branch": branch if branch and branch != "HEAD" else "",
            }
        )
    if not repos:
        warnings.append("No child git repositories were detected under the Project root.")
    return repos, warnings


async def _apply_blueprint_snapshot_to_project(
    db: AsyncSession,
    *,
    project: Project,
    blueprint: ProjectBlueprint,
) -> None:
    snapshot = project_blueprint_snapshot(blueprint)
    metadata = dict(project.metadata_ or {})
    metadata["blueprint"] = {"id": str(blueprint.id), "name": blueprint.name, "slug": blueprint.slug}
    metadata["blueprint_snapshot"] = snapshot
    project.metadata_ = metadata
    project.applied_blueprint_id = blueprint.id
    if blueprint.description and not project.description:
        project.description = blueprint.description
    if blueprint.prompt and not project.prompt:
        project.prompt = blueprint.prompt
    if blueprint.prompt_file_path and not project.prompt_file_path:
        project.prompt_file_path = blueprint.prompt_file_path

    existing_slots = set((await db.execute(
        select(ProjectSecretBinding.logical_name).where(ProjectSecretBinding.project_id == project.id)
    )).scalars().all())
    for logical_name in _blueprint_required_secret_names(blueprint):
        if logical_name in existing_slots:
            continue
        db.add(ProjectSecretBinding(project_id=project.id, logical_name=logical_name))

    materialize_project_blueprint(project_directory_from_project(project), blueprint)


async def _unique_blueprint_slug(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    base: str,
) -> str:
    candidate = normalize_project_slug(base, fallback="project-blueprint")
    suffix = 2
    while True:
        existing = (await db.execute(
            select(ProjectBlueprint.id).where(
                ProjectBlueprint.workspace_id == workspace_id,
                ProjectBlueprint.slug == candidate,
            )
        )).scalar_one_or_none()
        if existing is None:
            return candidate
        candidate = f"{normalize_project_slug(base, fallback='project-blueprint')}-{suffix}"
        suffix += 1


def _setup_run_out(run: ProjectSetupRun) -> ProjectSetupRunOut:
    return ProjectSetupRunOut.model_validate(run)


def _instance_out(instance: ProjectInstance, *, cleanup: dict | None = None) -> ProjectInstanceOut:
    out = ProjectInstanceOut.model_validate(instance)
    out.resolved = project_directory_payload(project_directory_from_instance(instance))
    out.cleanup = cleanup or project_instance_cleanup_summary(instance)
    return out


def _run_receipt_out(receipt: ProjectRunReceipt) -> ProjectRunReceiptOut:
    return ProjectRunReceiptOut(**serialize_project_run_receipt(receipt))


def _auth_user_id(auth) -> uuid.UUID | None:
    user_id = getattr(auth, "id", None)
    return user_id if isinstance(user_id, uuid.UUID) else None


def _project_machine_target_grant_in(body: ProjectMachineTargetGrantIn | None) -> ProjectMachineTargetGrant | None:
    if body is None:
        return None
    return ProjectMachineTargetGrant(
        provider_id=body.provider_id,
        target_id=body.target_id,
        capabilities=body.capabilities,
        allow_agent_tools=body.allow_agent_tools,
        expires_at=body.expires_at,
    )


def _apply_blueprint_write(blueprint: ProjectBlueprint, body: ProjectBlueprintWrite) -> None:
    fields = body.model_fields_set
    if "workspace_id" in fields:
        blueprint.workspace_id = body.workspace_id
    if "name" in fields and body.name is not None:
        blueprint.name = body.name.strip()
    if "slug" in fields:
        blueprint.slug = normalize_project_slug(body.slug, fallback=blueprint.name)
    elif "name" in fields and not blueprint.slug:
        blueprint.slug = normalize_project_slug(None, fallback=blueprint.name)
    if "description" in fields:
        blueprint.description = body.description
    if "default_root_path_pattern" in fields:
        blueprint.default_root_path_pattern = normalize_project_path(body.default_root_path_pattern) if body.default_root_path_pattern else None
    if "prompt" in fields:
        blueprint.prompt = body.prompt
    if "prompt_file_path" in fields:
        blueprint.prompt_file_path = normalize_project_path(body.prompt_file_path)
    if "folders" in fields:
        blueprint.folders = body.folders or []
    if "files" in fields:
        blueprint.files = body.files or {}
    if "knowledge_files" in fields:
        blueprint.knowledge_files = body.knowledge_files or {}
    if "repos" in fields:
        blueprint.repos = body.repos or []
    if "setup_commands" in fields:
        blueprint.setup_commands = body.setup_commands or []
    if "dependency_stack" in fields:
        blueprint.dependency_stack = body.dependency_stack or {}
    if "env" in fields:
        blueprint.env = body.env or {}
    if "required_secrets" in fields:
        blueprint.required_secrets = body.required_secrets or []
    if "metadata_" in fields:
        blueprint.metadata_ = body.metadata_ or {}


@router.get("/blueprints", response_model=list[ProjectBlueprintOut])
async def list_project_blueprints(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    blueprints = (await db.execute(select(ProjectBlueprint).order_by(ProjectBlueprint.name))).scalars().all()
    return [_blueprint_out(blueprint) for blueprint in blueprints]


@router.post("/blueprints", response_model=ProjectBlueprintOut, status_code=201)
async def create_project_blueprint(
    body: ProjectBlueprintWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    if not body.name:
        raise HTTPException(status_code=422, detail="name is required")
    if body.workspace_id and await db.get(SharedWorkspace, body.workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    blueprint = ProjectBlueprint(
        workspace_id=body.workspace_id,
        name=body.name.strip(),
        slug=normalize_project_slug(body.slug, fallback=body.name),
        description=body.description,
        default_root_path_pattern=normalize_project_path(body.default_root_path_pattern) if body.default_root_path_pattern else None,
        prompt=body.prompt,
        prompt_file_path=normalize_project_path(body.prompt_file_path),
        folders=body.folders or [],
        files=body.files or {},
        knowledge_files=body.knowledge_files or {},
        repos=body.repos or [],
        setup_commands=body.setup_commands or [],
        dependency_stack=body.dependency_stack or {},
        env=body.env or {},
        required_secrets=body.required_secrets or [],
        metadata_=body.metadata_ or {},
    )
    db.add(blueprint)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project blueprint already exists or is invalid: {exc}") from exc
    await db.refresh(blueprint)
    return _blueprint_out(blueprint)


@router.get("/blueprints/{blueprint_id}", response_model=ProjectBlueprintOut)
async def get_project_blueprint(
    blueprint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    blueprint = await db.get(ProjectBlueprint, blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="project blueprint not found")
    return _blueprint_out(blueprint)


@router.patch("/blueprints/{blueprint_id}", response_model=ProjectBlueprintOut)
async def update_project_blueprint(
    blueprint_id: uuid.UUID,
    body: ProjectBlueprintWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    blueprint = await db.get(ProjectBlueprint, blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="project blueprint not found")
    if body.workspace_id and await db.get(SharedWorkspace, body.workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    _apply_blueprint_write(blueprint, body)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project blueprint update failed: {exc}") from exc
    await db.refresh(blueprint)
    return _blueprint_out(blueprint)


@router.delete("/blueprints/{blueprint_id}", status_code=204)
async def delete_project_blueprint(
    blueprint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    blueprint = await db.get(ProjectBlueprint, blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="project blueprint not found")
    projects = (await db.execute(
        select(Project).where(Project.applied_blueprint_id == blueprint_id)
    )).scalars().all()
    for project in projects:
        project.applied_blueprint_id = None
    await db.delete(blueprint)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project blueprint delete failed: {exc}") from exc


@router.post("/from-blueprint", response_model=ProjectOut, status_code=201)
async def create_project_from_blueprint(
    body: ProjectFromBlueprintWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    blueprint = await db.get(ProjectBlueprint, body.blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="project blueprint not found")
    workspace_id = body.workspace_id or blueprint.workspace_id or await _default_workspace_id(db)
    if await db.get(SharedWorkspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    project_name = body.name.strip()
    if not project_name:
        raise HTTPException(status_code=422, detail="name is required")
    project_slug = normalize_project_slug(body.slug, fallback=project_name)
    root_path = normalize_project_path(body.root_path)
    if not root_path:
        root_path = render_project_blueprint_root_path(
            blueprint.default_root_path_pattern,
            project_name=project_name,
            project_slug=project_slug,
        )
    secret_bindings = {name.strip(): secret_id for name, secret_id in body.secret_bindings.items() if name.strip()}
    await _ensure_secret_values_exist(db, secret_bindings)
    metadata = {
        "blueprint": {
            "id": str(blueprint.id),
            "name": blueprint.name,
            "slug": blueprint.slug,
        },
        "blueprint_snapshot": project_blueprint_snapshot(blueprint),
    }
    project = Project(
        workspace_id=workspace_id,
        applied_blueprint_id=blueprint.id,
        name=project_name,
        slug=project_slug,
        description=body.description if body.description is not None else blueprint.description,
        root_path=root_path,
        prompt=blueprint.prompt,
        prompt_file_path=normalize_project_path(blueprint.prompt_file_path),
        metadata_=metadata,
    )
    db.add(project)
    try:
        await db.flush()
        materialization = materialize_project_blueprint(project_directory_from_project(project), blueprint)
        project.metadata_ = {
            **metadata,
            "blueprint_materialization": materialization.payload(),
        }
        for logical_name in _blueprint_required_secret_names(blueprint):
            db.add(ProjectSecretBinding(
                project_id=project.id,
                logical_name=logical_name,
                secret_value_id=secret_bindings.get(logical_name),
            ))
        for logical_name, secret_id in secret_bindings.items():
            if logical_name in _blueprint_required_secret_names(blueprint):
                continue
            db.add(ProjectSecretBinding(
                project_id=project.id,
                logical_name=logical_name,
                secret_value_id=secret_id,
            ))
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project creation from blueprint failed: {exc}") from exc
    await db.refresh(project)
    return await _project_out(db, project)


@router.post("/{project_id}/blueprint-from-current", response_model=ProjectBlueprintFromCurrentOut, status_code=201)
async def create_project_blueprint_from_current(
    project_id: uuid.UUID,
    body: ProjectBlueprintFromCurrentWrite | None = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    payload = body or ProjectBlueprintFromCurrentWrite()
    detected_repos, warnings = await _detect_project_repos(project)
    metadata = dict(project.metadata_ or {})
    snapshot = metadata.get("blueprint_snapshot") if isinstance(metadata.get("blueprint_snapshot"), dict) else {}
    blueprint_metadata = dict(snapshot.get("metadata") or {})
    if isinstance(metadata.get("dev_targets"), list):
        blueprint_metadata["dev_targets"] = metadata["dev_targets"]
    elif isinstance(blueprint_metadata.get("dev_targets"), list):
        blueprint_metadata["dev_targets"] = blueprint_metadata["dev_targets"]

    repos = list(snapshot.get("repos") or []) or detected_repos
    if repos and any(not str(repo.get("url") or "").strip() for repo in repos if isinstance(repo, dict)):
        warnings.append("One or more detected repos has no origin remote URL; setup will need that repo declaration completed.")

    dependency_stack = metadata.get("dependency_stack")
    if not isinstance(dependency_stack, dict):
        dependency_stack = snapshot.get("dependency_stack") if isinstance(snapshot.get("dependency_stack"), dict) else {}
    env = snapshot.get("env") if isinstance(snapshot.get("env"), dict) else {}
    required_secrets: list[str] = []
    for item in snapshot.get("required_secrets") or []:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("key") or "").strip()
        else:
            name = ""
        if name and name not in required_secrets:
            required_secrets.append(name)
    setup_commands = list(snapshot.get("setup_commands") or [])

    name = (payload.name or f"{project.name} Blueprint").strip()
    slug = await _unique_blueprint_slug(db, workspace_id=project.workspace_id, base=name)
    blueprint = ProjectBlueprint(
        workspace_id=project.workspace_id,
        name=name,
        slug=slug,
        description=project.description,
        default_root_path_pattern=project.root_path,
        prompt=project.prompt,
        prompt_file_path=normalize_project_path(project.prompt_file_path),
        folders=list(snapshot.get("folders") or []),
        files=dict(snapshot.get("files") or {}),
        knowledge_files=dict(snapshot.get("knowledge_files") or {}),
        repos=[repo for repo in repos if isinstance(repo, dict)],
        setup_commands=setup_commands,
        dependency_stack=dependency_stack,
        env={str(key): str(value) for key, value in env.items()},
        required_secrets=required_secrets,
        metadata_=blueprint_metadata,
    )
    db.add(blueprint)
    await db.flush()
    applied = bool(payload.apply_to_project)
    if applied:
        await _apply_blueprint_snapshot_to_project(db, project=project, blueprint=blueprint)
    await db.commit()
    await db.refresh(blueprint)
    await db.refresh(project)
    return ProjectBlueprintFromCurrentOut(
        blueprint=_blueprint_out(blueprint),
        project=await _project_out(db, project),
        detected_repos=detected_repos,
        warnings=warnings,
        applied=applied,
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    projects = (await db.execute(select(Project).order_by(Project.name))).scalars().all()
    return [await _project_out(db, project) for project in projects]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    if not body.name:
        raise HTTPException(status_code=422, detail="name is required")
    workspace_id = body.workspace_id or await _default_workspace_id(db)
    if await db.get(SharedWorkspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    root_path = normalize_project_path(body.root_path)
    if not root_path:
        raise HTTPException(status_code=422, detail="root_path is required")
    project = Project(
        workspace_id=workspace_id,
        name=body.name.strip(),
        slug=normalize_project_slug(body.slug, fallback=body.name),
        description=body.description,
        root_path=root_path,
        prompt=body.prompt,
        prompt_file_path=normalize_project_path(body.prompt_file_path),
        metadata_=body.metadata_ or {},
    )
    db.add(project)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project already exists or is invalid: {exc}") from exc
    await db.refresh(project)
    return await _project_out(db, project)


@router.get("/review-inbox", response_model=ProjectFactoryReviewInboxOut)
async def get_project_factory_review_inbox(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    return await list_project_factory_review_inbox(db, limit=limit)


@router.get("/{project_id}/factory-state", response_model=ProjectFactoryStateOut)
async def get_project_factory_state_endpoint(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await get_project_factory_state(db, project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await _project_out(db, project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        project.name = body.name.strip()
    if "slug" in fields and body.slug is not None:
        project.slug = normalize_project_slug(body.slug, fallback=project.name)
    if "description" in fields:
        project.description = body.description
    if "root_path" in fields and body.root_path is not None:
        root_path = normalize_project_path(body.root_path)
        if not root_path:
            raise HTTPException(status_code=422, detail="root_path is required")
        project.root_path = root_path
    if "prompt" in fields:
        project.prompt = body.prompt
    if "prompt_file_path" in fields:
        project.prompt_file_path = normalize_project_path(body.prompt_file_path)
    if "metadata_" in fields:
        project.metadata_ = body.metadata_ or {}
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project update failed: {exc}") from exc
    await db.refresh(project)
    return await _project_out(db, project)


@router.patch("/{project_id}/secret-bindings", response_model=ProjectOut)
async def update_project_secret_bindings(
    project_id: uuid.UUID,
    body: ProjectSecretBindingsWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    binding_ids = {name.strip(): secret_id for name, secret_id in body.bindings.items() if name.strip()}
    await _ensure_secret_values_exist(db, binding_ids)
    existing = {
        binding.logical_name: binding
        for binding in (await db.execute(
            select(ProjectSecretBinding).where(ProjectSecretBinding.project_id == project_id)
        )).scalars().all()
    }
    for logical_name, secret_id in binding_ids.items():
        binding = existing.get(logical_name)
        if binding is None:
            db.add(ProjectSecretBinding(
                project_id=project_id,
                logical_name=logical_name,
                secret_value_id=secret_id,
            ))
        else:
            binding.secret_value_id = secret_id
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"project secret binding update failed: {exc}") from exc
    await db.refresh(project)
    return await _project_out(db, project)


@router.get("/{project_id}/setup", response_model=ProjectSetupOut)
async def get_project_setup(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    plan = await load_project_setup_plan(db, project)
    runs = await list_project_setup_runs(db, project_id)
    return ProjectSetupOut(plan=plan, runs=[_setup_run_out(run) for run in runs])


@router.get("/{project_id}/runtime-env", response_model=ProjectRuntimeEnvOut)
async def get_project_dependencies_env(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    runtime_env = await load_project_runtime_environment(db, project)
    return ProjectRuntimeEnvOut(**runtime_env.safe_payload())


@router.get("/{project_id}/dependency-stack")
async def get_project_dependency_stack_endpoint(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await get_project_dependency_stack(db, project, scope="project")


@router.post("/{project_id}/dependency-stack")
async def manage_project_dependency_stack_endpoint(
    project_id: uuid.UUID,
    body: ProjectDependencyStackActionWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    runtime = await ensure_project_dependency_stack_instance(db, project, scope="project")
    action = body.action
    try:
        if action in {"prepare", "reload", "rebuild"}:
            return {"ok": True, "dependency_stack": await prepare_project_dependency_stack(db, project, runtime=runtime, force_recreate=action == "rebuild")}
        if action == "restart":
            return {"ok": True, "dependency_stack": await restart_project_dependency_stack(db, runtime)}
        if action == "stop":
            return {"ok": True, "dependency_stack": await stop_project_dependency_stack(db, runtime)}
        if action == "status":
            return {"ok": True, "dependency_stack": await project_dependency_stack_status(db, runtime)}
        if action == "logs":
            return await project_dependency_stack_logs(db, runtime, service=body.service, tail=body.tail)
        if action == "health":
            return await health_project_dependency_stack(db, runtime)
        if action == "destroy":
            return {"ok": True, "dependency_stack": await destroy_project_dependency_stack(db, runtime, keep_volumes=body.keep_volumes)}
        if action == "exec":
            named_commands = runtime.commands if isinstance(runtime.commands, dict) else {}
            command = body.command or (named_commands.get(body.command_name or "") if body.command_name else None)
            if not command:
                raise HTTPException(status_code=422, detail="command or command_name is required for exec")
            service = body.service
            if not service:
                raise HTTPException(status_code=422, detail="service is required for dependency stack exec")
            return await exec_project_dependency_stack_command(db, runtime, service=service, command=command)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=f"unknown dependency stack action: {action}")


@router.get("/{project_id}/instances", response_model=list[ProjectInstanceOut])
async def get_project_instances(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    rows: list[ProjectInstanceOut] = []
    for instance in await list_project_instances(db, project_id):
        task_status = await project_instance_task_status(db, instance)
        rows.append(_instance_out(instance, cleanup=project_instance_cleanup_summary(instance, task_status=task_status)))
    return rows


@router.post("/{project_id}/instances", response_model=ProjectInstanceOut, status_code=201)
async def create_fresh_project_instance(
    project_id: uuid.UUID,
    body: ProjectInstanceWrite | None = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    payload = body or ProjectInstanceWrite()
    if payload.owner_kind not in {"manual", "task", "session"}:
        raise HTTPException(status_code=422, detail="owner_kind must be manual, task, or session")
    try:
        instance = await create_project_instance(
            db,
            project,
            owner_kind=payload.owner_kind,
            ttl_seconds=payload.ttl_seconds or 7 * 24 * 60 * 60,
            metadata=payload.metadata_ or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    task_status = await project_instance_task_status(db, instance)
    return _instance_out(instance, cleanup=project_instance_cleanup_summary(instance, task_status=task_status))


@router.post("/{project_id}/instances/{instance_id}/cleanup", response_model=ProjectInstanceOut)
async def cleanup_project_instance_endpoint(
    project_id: uuid.UUID,
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    instance = await db.get(ProjectInstance, instance_id)
    if instance is None or instance.project_id != project.id:
        raise HTTPException(status_code=404, detail="project instance not found")
    try:
        if instance.owner_kind == "task" and instance.owner_id is not None:
            await cleanup_project_coding_run_instance(db, project, instance.owner_id)
            instance = await db.get(ProjectInstance, instance_id)
        elif instance.owner_kind == "manual":
            instance = await cleanup_project_instance(db, instance)
        else:
            raise ValueError("Only manual and task-owned Project instances can be cleaned up from the Project Instances tab.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if instance is None:
        raise HTTPException(status_code=404, detail="project instance not found")
    task_status = await project_instance_task_status(db, instance)
    return _instance_out(instance, cleanup=project_instance_cleanup_summary(instance, task_status=task_status))


@router.get("/{project_id}/run-receipts", response_model=list[ProjectRunReceiptOut])
async def get_project_run_receipts(
    project_id: uuid.UUID,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        receipts = await list_project_run_receipts(db, project_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [_run_receipt_out(receipt) for receipt in receipts]


@router.post("/{project_id}/run-receipts", response_model=ProjectRunReceiptOut, status_code=201)
async def create_project_run_receipt_endpoint(
    project_id: uuid.UUID,
    body: ProjectRunReceiptWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    try:
        receipt = await create_project_run_receipt(
            db,
            project_id=project_id,
            project_instance_id=body.project_instance_id,
            task_id=body.task_id,
            session_id=body.session_id,
            bot_id=body.bot_id,
            status=body.status,
            summary=body.summary,
            handoff_type=body.handoff_type,
            handoff_url=body.handoff_url,
            branch=body.branch,
            base_branch=body.base_branch,
            commit_sha=body.commit_sha,
            changed_files=body.changed_files,
            tests=body.tests,
            screenshots=body.screenshots,
            dev_targets=body.dev_targets,
            metadata=body.metadata,
            idempotency_key=body.idempotency_key,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "project not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    return _run_receipt_out(receipt)


@router.get("/{project_id}/coding-runs", response_model=list[ProjectCodingRunOut])
async def get_project_coding_runs(
    project_id: uuid.UUID,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await list_project_coding_runs(db, project, limit=limit)


@router.get("/{project_id}/coding-runs/review-batches", response_model=list[ProjectCodingRunReviewBatchOut])
async def get_project_coding_run_review_batches(
    project_id: uuid.UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await list_project_coding_run_review_batches(db, project, limit=limit)


@router.get("/{project_id}/coding-runs/review-sessions", response_model=list[ProjectCodingRunReviewSessionLedgerOut])
async def get_project_coding_run_review_sessions(
    project_id: uuid.UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await list_project_coding_run_review_sessions(db, project, limit=limit)


@router.post("/{project_id}/coding-runs", response_model=ProjectCodingRunOut, status_code=201)
async def create_project_coding_run_endpoint(
    project_id: uuid.UUID,
    body: ProjectCodingRunWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        task = await create_project_coding_run(
            db,
            project,
            ProjectCodingRunCreate(
                channel_id=body.channel_id,
                request=body.request,
                repo_path=body.repo_path,
                machine_target_grant=_project_machine_target_grant_in(body.machine_target_grant),
                granted_by_user_id=_auth_user_id(_auth),
                source_work_pack_id=body.source_work_pack_id,
                loop_policy=body.loop_policy.model_dump() if body.loop_policy else None,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rows = await list_project_coding_runs(db, project, limit=1)
    for row in rows:
        if row["id"] == str(task.id):
            return row
    raise HTTPException(status_code=500, detail="Project coding run was created but could not be loaded")


@router.get("/{project_id}/coding-run-schedules", response_model=list[ProjectCodingRunScheduleOut])
async def get_project_coding_run_schedules(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await list_project_coding_run_schedules(db, project)


@router.post("/{project_id}/coding-run-schedules", response_model=ProjectCodingRunScheduleOut, status_code=201)
async def create_project_coding_run_schedule_endpoint(
    project_id: uuid.UUID,
    body: ProjectCodingRunScheduleWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        task = await create_project_coding_run_schedule(
            db,
            project,
            ProjectCodingRunScheduleCreate(
                channel_id=body.channel_id,
                title=body.title,
                request=body.request,
                repo_path=body.repo_path,
                scheduled_at=body.scheduled_at,
                recurrence=body.recurrence,
                machine_target_grant=_project_machine_target_grant_in(body.machine_target_grant),
                granted_by_user_id=_auth_user_id(_auth),
                loop_policy=body.loop_policy.model_dump() if body.loop_policy else None,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rows = await list_project_coding_run_schedules(db, project)
    for row in rows:
        if row["id"] == str(task.id):
            return row
    raise HTTPException(status_code=500, detail="Project coding-run schedule was created but could not be loaded")


@router.patch("/{project_id}/coding-run-schedules/{schedule_id}", response_model=ProjectCodingRunScheduleOut)
async def update_project_coding_run_schedule_endpoint(
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    body: ProjectCodingRunSchedulePatch,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        task = await update_project_coding_run_schedule(
            db,
            project,
            schedule_id,
            ProjectCodingRunScheduleUpdate(
                channel_id=body.channel_id,
                title=body.title,
                request=body.request,
                repo_path=body.repo_path,
                scheduled_at=body.scheduled_at,
                recurrence=body.recurrence,
                enabled=body.enabled,
                machine_target_grant=_project_machine_target_grant_in(body.machine_target_grant),
                granted_by_user_id=_auth_user_id(_auth),
                loop_policy=body.loop_policy.model_dump() if body.loop_policy else None,
            ),
        )
    except ValueError as exc:
        message = str(exc)
        if message == "coding-run schedule not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    rows = await list_project_coding_run_schedules(db, project)
    for row in rows:
        if row["id"] == str(task.id):
            return row
    raise HTTPException(status_code=500, detail="Project coding-run schedule was updated but could not be loaded")


@router.post("/{project_id}/coding-run-schedules/{schedule_id}/run-now", response_model=ProjectCodingRunOut, status_code=201)
async def run_project_coding_run_schedule_now_endpoint(
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    schedule = await db.get(Task, schedule_id)
    try:
        if schedule is None:
            raise ValueError("coding-run schedule not found")
        task = await fire_project_coding_run_schedule(db, schedule, advance=False)
    except ValueError as exc:
        message = str(exc)
        if message in {"coding-run schedule not found", "project not found"}:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    if task is None:
        raise HTTPException(status_code=422, detail="coding-run schedule is disabled")
    return await get_project_coding_run(db, project, task.id)


@router.delete("/{project_id}/coding-run-schedules/{schedule_id}", response_model=ProjectCodingRunScheduleOut)
async def disable_project_coding_run_schedule_endpoint(
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        task = await disable_project_coding_run_schedule(db, project, schedule_id)
    except ValueError as exc:
        message = str(exc)
        if message == "coding-run schedule not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    rows = await list_project_coding_run_schedules(db, project)
    for row in rows:
        if row["id"] == str(task.id):
            return row
    raise HTTPException(status_code=500, detail="Project coding-run schedule was disabled but could not be loaded")


@router.post("/{project_id}/coding-runs/reviewed", response_model=list[ProjectCodingRunOut])
async def mark_project_coding_runs_reviewed_endpoint(
    project_id: uuid.UUID,
    body: ProjectCodingRunsReviewedWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return await mark_project_coding_runs_reviewed(db, project, body.task_ids, note=body.note)
    except ValueError as exc:
        message = str(exc)
        if message == "coding run not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


@router.post("/{project_id}/coding-runs/review-sessions", response_model=ProjectCodingRunTaskOut, status_code=201)
async def create_project_coding_run_review_session_endpoint(
    project_id: uuid.UUID,
    body: ProjectCodingRunReviewSessionWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        task = await create_project_coding_run_review_session(
            db,
            project,
            ProjectCodingRunReviewCreate(
                channel_id=body.channel_id,
                task_ids=body.task_ids,
                prompt=body.prompt,
                merge_method=body.merge_method,
                machine_target_grant=_project_machine_target_grant_in(body.machine_target_grant),
                granted_by_user_id=_auth_user_id(_auth),
            ),
        )
    except ValueError as exc:
        message = str(exc)
        if message == "coding run not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    from app.services.machine_task_grants import task_machine_grant_payload

    return ProjectCodingRunTaskOut(**{
        "id": task.id,
        "status": task.status,
        "title": task.title,
        "bot_id": task.bot_id,
        "channel_id": task.channel_id,
        "session_id": task.session_id,
        "project_instance_id": task.project_instance_id,
        "correlation_id": task.correlation_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "run_at": task.run_at.isoformat() if task.run_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error,
        "machine_target_grant": await task_machine_grant_payload(db, task),
    })


@router.get("/{project_id}/coding-runs/review-sessions/{review_task_id}/context")
async def get_project_coding_run_review_context_endpoint(
    project_id: uuid.UUID,
    review_task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return await get_project_coding_run_review_context(db, project, review_task_id)
    except ValueError as exc:
        message = str(exc)
        if message == "Project coding-run review task not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


@router.post("/{project_id}/coding-runs/review-finalize")
async def finalize_project_coding_run_review_endpoint(
    project_id: uuid.UUID,
    body: ProjectCodingRunReviewFinalizeWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return await finalize_project_coding_run_review(
        db,
        project,
        ProjectCodingRunReviewFinalize(
            review_task_id=body.review_task_id,
            run_task_id=body.run_task_id,
            outcome=body.outcome,
            summary=body.summary,
            details=body.details,
            merge=body.merge,
            merge_method=body.merge_method,
        ),
    )


@router.get("/{project_id}/coding-runs/{task_id}", response_model=ProjectCodingRunOut)
async def get_project_coding_run_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return await get_project_coding_run(db, project, task_id)
    except ValueError as exc:
        message = str(exc)
        if message == "coding run not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


@router.post("/{project_id}/coding-runs/{task_id}/refresh", response_model=ProjectCodingRunOut)
async def refresh_project_coding_run_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return await refresh_project_coding_run_status(db, project, task_id)
    except ValueError as exc:
        message = str(exc)
        if message == "coding run not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


@router.post("/{project_id}/coding-runs/{task_id}/continue", response_model=ProjectCodingRunOut, status_code=201)
async def continue_project_coding_run_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    body: ProjectCodingRunContinueWrite,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        task = await continue_project_coding_run(
            db,
            project,
            task_id,
            ProjectCodingRunContinue(feedback=body.feedback),
        )
        return await get_project_coding_run(db, project, task.id)
    except ValueError as exc:
        message = str(exc)
        if message == "coding run not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


@router.post("/{project_id}/coding-runs/{task_id}/loop-disable", response_model=ProjectCodingRunOut)
async def disable_project_coding_run_loop_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        task = await disable_project_coding_run_loop(db, project, task_id)
        return await get_project_coding_run(db, project, task.id)
    except ValueError as exc:
        message = str(exc)
        if message == "coding run not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


@router.post("/{project_id}/coding-runs/{task_id}/reviewed", response_model=ProjectCodingRunOut)
async def mark_project_coding_run_reviewed_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return await mark_project_coding_run_reviewed(db, project, task_id)
    except ValueError as exc:
        message = str(exc)
        if message == "coding run not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


@router.post("/{project_id}/coding-runs/{task_id}/cleanup", response_model=ProjectCodingRunOut)
async def cleanup_project_coding_run_endpoint(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return await cleanup_project_coding_run_instance(db, project, task_id)
    except ValueError as exc:
        message = str(exc)
        if message == "coding run not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


@router.post("/{project_id}/setup/runs", response_model=ProjectSetupRunOut, status_code=201)
async def create_project_setup_run(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    plan = await load_project_setup_plan(db, project)
    if not plan.get("ready"):
        raise HTTPException(status_code=409, detail={"message": "project setup is not ready", "plan": plan})
    run = await run_project_setup(db, project)
    return _setup_run_out(run)


@router.get("/{project_id}/setup/runs/{run_id}", response_model=ProjectSetupRunOut)
async def get_project_setup_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    run = await db.get(ProjectSetupRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="project setup run not found")
    return _setup_run_out(run)


@router.get("/{project_id}/channels", response_model=list[ProjectChannelOut])
async def get_project_channels(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("admin")),
):
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return (await db.execute(
        select(Channel).where(Channel.project_id == project_id).order_by(Channel.name)
    )).scalars().all()
