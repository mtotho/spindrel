"""Tests for ``app.services.project_task_execution_context``.

Real-DB tests (per the testing-python skill) at the new Module's Interface.
The Interface is the test surface: every behavioral invariant in the public
shape is asserted at least once. The round-trip property
(``to_persisted ↔ from_task``) is the deletion test for the persisted shape.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Channel, Project, Task
from app.services.project_runtime import ProjectRuntimeEnvironment
from app.services.project_task_execution_context import (
    ContextAssembler,
    ContextRefreshPolicy,
    DependencyStackView,
    DevTarget,
    DevTargetSpec,
    ExecutionContextError,
    MalformedExecutionContextError,
    MachineGrantSummary,
    MissingPresetError,
    NoOpAllocator,
    PortAllocationError,
    PROJECT_CODING_RUN_PRESET_ID,
    PROJECT_CODING_RUN_REVIEW_PRESET_ID,
    ProjectContextSource,
    ProjectTaskExecutionContext,
    RuntimeTargetView,
    SequentialPortAllocator,
    SnapshotPolicy,
    WholeProjectResolver,
    default_port_prober,
)
from app.services.run_presets import get_run_preset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_project(
    *,
    workspace_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    name: str = "Spindrel",
    slug: str = "spindrel",
    root_path: str = "common/projects/spindrel",
) -> Project:
    return Project(
        id=project_id or uuid.uuid4(),
        workspace_id=workspace_id or uuid.uuid4(),
        name=name,
        slug=slug,
        root_path=root_path,
        metadata_=metadata if metadata is not None else {
            "blueprint_snapshot": {"repos": [{"path": "spindrel", "branch": "development"}]}
        },
    )


def _make_channel(
    *,
    project: Project,
    channel_id: uuid.UUID | None = None,
) -> Channel:
    return Channel(
        id=channel_id or uuid.uuid4(),
        name="Project Agent",
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        workspace_id=project.workspace_id,
    )


@dataclass
class _StubRuntimeEnvironment:
    """Minimal substitute for ProjectRuntimeEnvironment for ContextSource stubs."""

    env: dict[str, str]
    payload: dict[str, Any]

    def safe_payload(self) -> dict[str, Any]:
        return dict(self.payload)


# ---------------------------------------------------------------------------
# Construction — fresh()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_default_adapters_allocates_ports_loads_runtime_resolves_stack(
    db_session, monkeypatch
):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "repos": [{"path": "spindrel", "branch": "development"}],
            "dev_targets": [{
                "key": "api",
                "label": "API",
                "port_env": "SPINDREL_DEV_API_PORT",
                "url_env": "SPINDREL_DEV_API_URL",
                "port_range": [31100, 31102],
            }],
        }
    })
    db_session.add(project)
    await db_session.commit()
    task_id = uuid.uuid4()

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=task_id,
        request="Build the API",
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": False),
    )

    assert ctx.kind == "project_coding_run"
    assert ctx.preset_id == PROJECT_CODING_RUN_PRESET_ID
    assert ctx.request == "Build the API"
    assert len(ctx.dev_targets) == 1
    assert ctx.dev_targets[0].key == "api"
    assert ctx.dev_targets[0].port == 31100
    assert ctx.dev_targets[0].url == "http://127.0.0.1:31100"
    assert ctx.lineage.root_task_id == str(task_id)
    assert ctx.lineage.parent_task_id is None
    assert ctx.lineage.continuation_index == 0
    assert ctx.branch and ctx.branch.startswith(f"spindrel/project-{str(task_id)[:8]}-")


@pytest.mark.asyncio
async def test_fresh_with_no_dev_target_specs_produces_empty_dev_targets(db_session):
    project = _make_project(metadata={"blueprint_snapshot": {"repos": []}})
    db_session.add(project)
    await db_session.commit()

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session, project, task_id=uuid.uuid4()
    )

    assert ctx.dev_targets == ()
    assert ctx.to_persisted()["dev_targets"] == []


@pytest.mark.asyncio
async def test_fresh_with_no_op_allocator_skips_port_allocation_entirely(db_session):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "dev_targets": [{"key": "api", "port_range": [31100, 31102]}]
        }
    })
    db_session.add(project)
    await db_session.commit()

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session, project, task_id=uuid.uuid4(), allocator=NoOpAllocator()
    )

    assert ctx.dev_targets == ()


@pytest.mark.asyncio
async def test_fresh_raises_port_allocation_error_when_range_exhausted(db_session):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "dev_targets": [{"key": "api", "port_range": [31100, 31102]}]
        }
    })
    db_session.add(project)
    await db_session.commit()

    with pytest.raises(PortAllocationError) as exc:
        await ProjectTaskExecutionContext.fresh(
            db_session,
            project,
            task_id=uuid.uuid4(),
            allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": True),
        )

    assert exc.value.target_key == "api"
    assert exc.value.attempted_range == (31100, 31102)


@pytest.mark.asyncio
async def test_fresh_raises_missing_preset_error_when_preset_id_unknown(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()

    with pytest.raises(MissingPresetError) as exc:
        await ProjectTaskExecutionContext.fresh(
            db_session, project, task_id=uuid.uuid4(), preset_id="nonexistent"
        )

    assert exc.value.preset_id == "nonexistent"


@pytest.mark.asyncio
async def test_fresh_persists_machine_grant_summary_secret_safely(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()

    @dataclass
    class _Grant:
        provider_id: str = "ssh"
        target_id: str = "e2e-8000"
        capabilities: list[str] | None = None
        allow_agent_tools: bool = True
        expires_at: str | None = None

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=uuid.uuid4(),
        machine_grant=_Grant(capabilities=["inspect", "exec"]),
    )

    assert ctx.machine_grant is not None
    persisted = ctx.to_persisted()["machine_target_grant"]
    assert persisted == {
        "provider_id": "ssh",
        "target_id": "e2e-8000",
        "capabilities": ["inspect", "exec"],
        "allow_agent_tools": True,
        "expires_at": None,
    }


@pytest.mark.asyncio
async def test_fresh_persists_schedule_provenance_when_supplied(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    schedule_task_id = uuid.uuid4()
    source_artifact = {"path": "docs/tracks/x.md", "section": "Proposed Run Packs"}

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=uuid.uuid4(),
        schedule_task_id=schedule_task_id,
        schedule_run_number=3,
        source_artifact=source_artifact,
    )

    persisted = ctx.to_persisted()
    assert persisted["schedule_task_id"] == str(schedule_task_id)
    assert persisted["schedule_run_number"] == 3
    assert persisted["source_artifact"] == {
        "path": "docs/tracks/x.md",
        "section": "Proposed Run Packs",
        "commit_sha": None,
    }


@pytest.mark.asyncio
async def test_fresh_two_concurrent_runs_get_distinct_dev_target_ports(db_session):
    project_id = uuid.uuid4()
    project = _make_project(
        project_id=project_id,
        metadata={
            "blueprint_snapshot": {
                "dev_targets": [{"key": "api", "port_range": [31100, 31102]}]
            }
        },
    )
    channel = _make_channel(project=project)
    db_session.add_all([project, channel])
    await db_session.commit()

    first_task_id = uuid.uuid4()
    first = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=first_task_id,
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": False),
    )
    persisted_first = first.to_persisted()
    db_session.add(Task(
        id=first_task_id,
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel.id,
        status="running",
        title="Existing run",
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": persisted_first,
        },
    ))
    await db_session.commit()

    second = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=uuid.uuid4(),
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": False),
    )

    first_port = first.dev_targets[0].port
    second_port = second.dev_targets[0].port
    assert first_port == 31100
    assert second_port != first_port


# ---------------------------------------------------------------------------
# Construction — from_parent()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_from_parent_inherits_dev_targets_runtime_target_dependency_stack_verbatim(
    db_session,
):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "dev_targets": [{"key": "api", "port_range": [31100, 31102]}]
        }
    })
    db_session.add(project)
    await db_session.commit()
    parent_task_id = uuid.uuid4()
    parent_ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=parent_task_id,
        request="Original request",
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": False),
    )
    parent = Task(
        id=parent_task_id,
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        channel_id=uuid.uuid4(),
        status="completed",
        title="Parent",
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": parent_ctx.to_persisted(),
        },
    )
    db_session.add(parent)
    await db_session.commit()

    child = await ProjectTaskExecutionContext.from_parent(
        db_session,
        project,
        parent,
        new_task_id=uuid.uuid4(),
        feedback="Address review feedback",
    )

    assert child.dev_targets == parent_ctx.dev_targets
    assert child.runtime_target == parent_ctx.runtime_target
    assert child.dependency_stack == parent_ctx.dependency_stack
    assert child.request == parent_ctx.request
    assert child.lineage.parent_task_id == str(parent.id)
    assert child.lineage.root_task_id == parent_ctx.lineage.root_task_id
    assert child.lineage.continuation_index == 1
    assert child.lineage.continuation_feedback == "Address review feedback"


@pytest.mark.asyncio
async def test_from_parent_increments_continuation_index_from_parent_value(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    parent_task_id = uuid.uuid4()

    parent_persisted = {
        "project_id": str(project.id),
        "request": "Test",
        "branch": "spindrel/test",
        "base_branch": "development",
        "repo": {},
        "runtime_target": {"ready": True, "configured_keys": [], "missing_secrets": []},
        "dev_targets": [],
        "dev_target_env": {},
        "dependency_stack": {"configured": False, "source_path": None, "env_keys": [], "commands": []},
        "machine_target_grant": None,
        "source_artifact": None,
        "schedule_task_id": None,
        "schedule_run_number": None,
        "continuation_index": 5,
        "root_task_id": str(uuid.uuid4()),
    }
    parent = Task(
        id=parent_task_id,
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        channel_id=uuid.uuid4(),
        status="completed",
        title="Parent",
        execution_config={"run_preset_id": "project_coding_run", "project_coding_run": parent_persisted},
    )
    db_session.add(parent)
    await db_session.commit()

    child = await ProjectTaskExecutionContext.from_parent(
        db_session, project, parent, new_task_id=uuid.uuid4(), feedback="ok"
    )

    assert child.lineage.continuation_index == 6


@pytest.mark.asyncio
async def test_from_parent_raises_malformed_execution_context_when_top_level_key_missing(
    db_session,
):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    parent = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        channel_id=uuid.uuid4(),
        status="completed",
        title="Bad parent",
        execution_config={"run_preset_id": "other"},  # no project_coding_run
    )
    db_session.add(parent)
    await db_session.commit()

    with pytest.raises(MalformedExecutionContextError) as exc:
        await ProjectTaskExecutionContext.from_parent(
            db_session, project, parent, new_task_id=uuid.uuid4(), feedback=""
        )

    assert exc.value.task_id == parent.id


@pytest.mark.asyncio
async def test_from_parent_with_refresh_runtime_env_replaces_runtime_target_only(
    db_session,
):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    parent_persisted = {
        "project_id": str(project.id),
        "request": "Test",
        "branch": "spindrel/test",
        "base_branch": "development",
        "repo": {},
        "runtime_target": {
            "ready": False,
            "configured_keys": ["GITHUB_TOKEN"],
            "missing_secrets": ["E2E_API_KEY"],
        },
        "dev_targets": [{"key": "api", "label": "API", "port": 31100,
                         "port_env": "P", "url": "http://127.0.0.1:31100", "url_env": "U"}],
        "dev_target_env": {"P": "31100", "U": "http://127.0.0.1:31100"},
        "dependency_stack": {"configured": False, "source_path": None, "env_keys": [], "commands": []},
        "machine_target_grant": None,
        "source_artifact": None,
        "schedule_task_id": None,
        "schedule_run_number": None,
        "continuation_index": 0,
        "root_task_id": str(uuid.uuid4()),
    }
    parent = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        channel_id=uuid.uuid4(),
        status="completed",
        title="Parent",
        execution_config={"run_preset_id": "project_coding_run", "project_coding_run": parent_persisted},
    )
    db_session.add(parent)
    await db_session.commit()

    child = await ProjectTaskExecutionContext.from_parent(
        db_session,
        project,
        parent,
        new_task_id=uuid.uuid4(),
        feedback="",
        refresh=ContextRefreshPolicy.REFRESH_RUNTIME_ENV,
    )

    # dev_targets and dependency_stack inherited verbatim
    assert child.dev_targets == ProjectTaskExecutionContext.from_task(parent).dev_targets
    assert child.dependency_stack == ProjectTaskExecutionContext.from_task(parent).dependency_stack
    # runtime_target reloaded — empty Project means ready=True with no missing secrets
    assert child.runtime_target.missing_secrets == ()


# ---------------------------------------------------------------------------
# Construction — review()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_skips_dev_target_allocation_regardless_of_project_metadata(
    db_session,
):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "dev_targets": [{"key": "api", "port_range": [31100, 31102]}]
        }
    })
    db_session.add(project)
    await db_session.commit()
    selected = [uuid.uuid4(), uuid.uuid4()]

    ctx = await ProjectTaskExecutionContext.review(
        db_session,
        project,
        task_id=uuid.uuid4(),
        selected_task_ids=selected,
    )

    assert ctx.kind == "project_coding_run_review"
    assert ctx.preset_id == PROJECT_CODING_RUN_REVIEW_PRESET_ID
    assert ctx.dev_targets == ()
    assert ctx.selected_task_ids == tuple(str(rid) for rid in selected)


@pytest.mark.asyncio
async def test_review_persists_selected_task_ids(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    selected = [uuid.uuid4(), uuid.uuid4()]

    ctx = await ProjectTaskExecutionContext.review(
        db_session, project, task_id=uuid.uuid4(), selected_task_ids=selected
    )
    persisted = ctx.to_persisted()

    assert persisted["selected_task_ids"] == [str(rid) for rid in selected]


@pytest.mark.asyncio
async def test_review_raises_missing_preset_error_when_review_preset_unregistered(
    db_session, monkeypatch
):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    monkeypatch.setattr(
        "app.services.project_task_execution_context.get_run_preset",
        lambda preset_id: None,
    )

    with pytest.raises(MissingPresetError):
        await ProjectTaskExecutionContext.review(
            db_session, project, task_id=uuid.uuid4(), selected_task_ids=[]
        )


# ---------------------------------------------------------------------------
# Round-trip property — to_persisted ↔ from_task (the deletion test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_round_trip_byte_stable_for_fresh(db_session):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "repos": [{"path": "spindrel", "branch": "development"}],
            "dev_targets": [{"key": "api", "port_range": [31100, 31102]}],
        }
    })
    db_session.add(project)
    await db_session.commit()
    task_id = uuid.uuid4()
    ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=task_id,
        request="x",
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": False),
    )
    task = Task(
        id=task_id,
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        channel_id=uuid.uuid4(),
        status="pending",
        title="Round trip",
        execution_config=ctx.execution_config(),
    )

    rehydrated = ProjectTaskExecutionContext.from_task(task)

    assert rehydrated.to_persisted() == task.execution_config["project_coding_run"]


@pytest.mark.asyncio
async def test_round_trip_byte_stable_for_review(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    task_id = uuid.uuid4()
    ctx = await ProjectTaskExecutionContext.review(
        db_session,
        project,
        task_id=task_id,
        selected_task_ids=[uuid.uuid4(), uuid.uuid4()],
    )
    task = Task(
        id=task_id,
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        channel_id=uuid.uuid4(),
        status="pending",
        title="Review round trip",
        execution_config=ctx.execution_config(),
    )

    rehydrated = ProjectTaskExecutionContext.from_task(task)

    assert rehydrated.kind == "project_coding_run_review"
    assert rehydrated.to_persisted() == task.execution_config["project_coding_run_review"]


@pytest.mark.asyncio
async def test_round_trip_byte_stable_for_continuation(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    parent_task_id = uuid.uuid4()
    parent_ctx = await ProjectTaskExecutionContext.fresh(
        db_session, project, task_id=parent_task_id, request="parent"
    )
    parent = Task(
        id=parent_task_id,
        bot_id="agent",
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        channel_id=uuid.uuid4(),
        status="completed",
        title="Parent",
        execution_config=parent_ctx.execution_config(),
    )
    db_session.add(parent)
    await db_session.commit()
    child = await ProjectTaskExecutionContext.from_parent(
        db_session, project, parent, new_task_id=uuid.uuid4(), feedback="follow up"
    )
    child_task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=parent.client_id,
        channel_id=parent.channel_id,
        status="pending",
        title="Child",
        execution_config=child.execution_config(),
    )

    rehydrated = ProjectTaskExecutionContext.from_task(child_task)

    assert rehydrated.to_persisted() == child_task.execution_config["project_coding_run"]
    assert rehydrated.lineage.parent_task_id == str(parent.id)
    assert rehydrated.lineage.continuation_feedback == "follow up"


# ---------------------------------------------------------------------------
# from_task — read seam for receipts / row rendering
# ---------------------------------------------------------------------------


def test_from_task_does_not_hit_db_pure_read():
    """from_task is the read seam; no AsyncSession parameter."""
    persisted = {
        "project_id": str(uuid.uuid4()),
        "request": "anything",
        "branch": "main",
        "base_branch": None,
        "repo": {"name": "x"},
        "runtime_target": {"ready": True, "configured_keys": ["GITHUB_TOKEN"], "missing_secrets": []},
        "dev_targets": [{
            "key": "api", "label": "API", "port": 31100,
            "port_env": "P", "url": "http://127.0.0.1:31100", "url_env": "U",
        }],
        "dev_target_env": {"P": "31100"},
        "dependency_stack": {"configured": False, "source_path": None, "env_keys": [], "commands": []},
        "machine_target_grant": None,
        "source_artifact": None,
        "schedule_task_id": None,
        "schedule_run_number": None,
        "continuation_index": 0,
        "root_task_id": str(uuid.uuid4()),
    }
    task = Task(
        id=uuid.uuid4(),
        title="x",
        execution_config={"run_preset_id": "project_coding_run", "project_coding_run": persisted},
    )

    ctx = ProjectTaskExecutionContext.from_task(task)

    assert ctx.dev_targets[0].port == 31100
    assert ctx.repo == {"name": "x"}


def test_from_task_raises_for_missing_top_level_key():
    task = Task(id=uuid.uuid4(), title="x", execution_config={"run_preset_id": "other"})
    with pytest.raises(MalformedExecutionContextError):
        ProjectTaskExecutionContext.from_task(task)


def test_from_task_handles_review_kind():
    task_id = uuid.uuid4()
    persisted = {
        "project_id": str(uuid.uuid4()),
        "request": "",
        "branch": None,
        "base_branch": None,
        "repo": {},
        "runtime_target": {"ready": True, "configured_keys": [], "missing_secrets": []},
        "dev_targets": [],
        "dev_target_env": {},
        "dependency_stack": {"configured": False, "source_path": None, "env_keys": [], "commands": []},
        "machine_target_grant": None,
        "source_artifact": None,
        "schedule_task_id": None,
        "schedule_run_number": None,
        "continuation_index": 0,
        "root_task_id": str(task_id),
        "selected_task_ids": [str(uuid.uuid4())],
    }
    task = Task(
        id=task_id,
        title="x",
        execution_config={
            "run_preset_id": "project_coding_run_review",
            "project_coding_run_review": persisted,
        },
    )

    ctx = ProjectTaskExecutionContext.from_task(task)

    assert ctx.kind == "project_coding_run_review"
    assert len(ctx.selected_task_ids) == 1


# ---------------------------------------------------------------------------
# Read accessors / typed views
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_targets_property_returns_typed_dev_target_tuple(db_session):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "dev_targets": [{"key": "api", "port_range": [31100, 31102]}]
        }
    })
    db_session.add(project)
    await db_session.commit()

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=uuid.uuid4(),
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": False),
    )

    assert isinstance(ctx.dev_targets, tuple)
    assert all(isinstance(t, DevTarget) for t in ctx.dev_targets)


@pytest.mark.asyncio
async def test_runtime_safe_payload_carries_no_plaintext_secrets(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    ctx = await ProjectTaskExecutionContext.fresh(
        db_session, project, task_id=uuid.uuid4()
    )

    payload = ctx.runtime_safe_payload()

    # secret_keys list is intentionally empty in the persisted view (server
    # secrets must not leak to the persisted shape or UI).
    assert payload["secret_keys"] == []
    assert "missing_secrets" in payload


@pytest.mark.asyncio
async def test_env_for_subprocess_combines_runtime_env_and_dev_target_env(db_session):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "env": {"APP_ENV": "test"},
            "dev_targets": [{
                "key": "api",
                "port_env": "MY_PORT",
                "url_env": "MY_URL",
                "port_range": [31100, 31102],
            }],
        }
    })
    db_session.add(project)
    await db_session.commit()

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=uuid.uuid4(),
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": False),
    )

    env = ctx.env_for_subprocess()

    assert env["APP_ENV"] == "test"
    assert env["MY_PORT"] == "31100"
    assert env["MY_URL"] == "http://127.0.0.1:31100"


def test_readiness_summary_is_secret_safe_and_collects_run_contract():
    ctx = ProjectTaskExecutionContext(
        project_id=str(uuid.uuid4()),
        kind="project_coding_run",
        preset_id="project_coding_run",
        request="",
        repo={"path": "spindrel"},
        branch="spindrel/project-123-work",
        base_branch="development",
        dev_targets=(DevTarget(
            key="api",
            label="API",
            port=31100,
            port_env="SPINDREL_DEV_API_PORT",
            url="http://127.0.0.1:31100",
            url_env="SPINDREL_DEV_API_URL",
        ),),
        dependency_stack=DependencyStackView(
            True,
            "docker-compose.project.yml",
            ("DATABASE_URL",),
            ("migrate",),
        ),
        runtime_target=RuntimeTargetView(
            False,
            ("DATABASE_URL", "GITHUB_TOKEN"),
            ("GITHUB_TOKEN",),
        ),
        lineage=__import__("app.services.project_task_execution_context", fromlist=["RunLineage"]).RunLineage(
            parent_task_id=None,
            root_task_id=str(uuid.uuid4()),
            continuation_index=0,
        ),
        machine_grant=MachineGrantSummary(
            provider_id="ssh",
            target_id="e2e",
            capabilities=("inspect",),
            allow_agent_tools=True,
            expires_at=None,
        ),
        source_artifact=None,
        schedule_task_id=None,
        schedule_run_number=None,
        selected_task_ids=(),
        _runtime_env={"DATABASE_URL": "postgres://user:secret@host/db"},
    )

    summary = ctx.readiness_summary(
        dependency_stack_status={
            "status": "running",
            "services": [{"name": "postgres", "status": "healthy"}],
        }
    )

    assert summary["ready"] is False
    assert "Missing required runtime secret: GITHUB_TOKEN" in summary["blockers"]
    assert summary["dependency_stack"]["status"] == "running"
    assert summary["dependency_stack"]["services"] == [{"name": "postgres", "status": "healthy"}]
    assert summary["dev_targets"]["env"] == {
        "SPINDREL_DEV_API_PORT": "31100",
        "SPINDREL_DEV_API_URL": "http://127.0.0.1:31100",
    }
    assert {item["key"] for item in summary["receipt_evidence"]} >= {
        "changed_files",
        "tests",
        "screenshots",
        "handoff_url",
    }
    assert "postgres://user:secret@host/db" not in str(summary)


def test_runtime_env_redact_text_redacts_known_values():
    ctx = ProjectTaskExecutionContext(
        project_id=str(uuid.uuid4()),
        kind="project_coding_run",
        preset_id="project_coding_run",
        request="",
        repo={},
        branch=None,
        base_branch=None,
        dev_targets=(),
        dependency_stack=DependencyStackView(False, None, (), ()),
        runtime_target=RuntimeTargetView(True, (), ()),
        lineage=__import__("app.services.project_task_execution_context", fromlist=["RunLineage"]).RunLineage(
            parent_task_id=None,
            root_task_id=str(uuid.uuid4()),
            continuation_index=0,
        ),
        machine_grant=None,
        source_artifact=None,
        schedule_task_id=None,
        schedule_run_number=None,
        selected_task_ids=(),
        _runtime_env={"GITHUB_TOKEN": "ghp_secret_value", "OTHER": "not-secret"},
    )

    out = ctx.runtime_env_redact_text("token is ghp_secret_value here")

    assert out == "token is [REDACTED] here"


def test_runtime_env_redact_text_keeps_non_secret_numbers():
    ctx = ProjectTaskExecutionContext(
        project_id=str(uuid.uuid4()),
        kind="project_coding_run",
        preset_id="project_coding_run",
        request="",
        repo={},
        branch=None,
        base_branch=None,
        dev_targets=(),
        dependency_stack=DependencyStackView(False, None, (), ()),
        runtime_target=RuntimeTargetView(True, (), ()),
        lineage=__import__("app.services.project_task_execution_context", fromlist=["RunLineage"]).RunLineage(
            parent_task_id=None,
            root_task_id=str(uuid.uuid4()),
            continuation_index=0,
        ),
        machine_grant=None,
        source_artifact=None,
        schedule_task_id=None,
        schedule_run_number=None,
        selected_task_ids=(),
        _runtime_env={"SPINDREL_PROJECT_RUN_GUARD": "1", "SPINDREL_DEV_APP_PORT": "32001"},
    )

    out = ctx.runtime_env_redact_text("Iteration 1 failed on 32001 with exit 127")

    assert out == "Iteration 1 failed on 32001 with exit 127"


# ---------------------------------------------------------------------------
# apply_to_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_to_task_sets_execution_config_task_type_dispatch(db_session):
    project = _make_project()
    channel = _make_channel(project=project)
    db_session.add_all([project, channel])
    await db_session.commit()
    task_id = uuid.uuid4()
    ctx = await ProjectTaskExecutionContext.fresh(
        db_session, project, task_id=task_id, request="hello"
    )
    task = Task(id=task_id, status="pending", title="")

    ctx.apply_to_task(task, channel=channel)

    assert task.execution_config["run_preset_id"] == PROJECT_CODING_RUN_PRESET_ID
    assert task.execution_config["project_coding_run"]["request"] == "hello"
    assert task.execution_config["project_coding_run"]["readiness"]["ready"] is True
    assert task.execution_config["project_coding_run"]["readiness"]["receipt_evidence"][0]["key"] == "changed_files"
    preset = get_run_preset(PROJECT_CODING_RUN_PRESET_ID)
    assert preset is not None and preset.task_defaults is not None
    assert task.task_type == preset.task_defaults.task_type
    assert task.max_run_seconds == preset.task_defaults.max_run_seconds
    assert task.title == preset.task_defaults.title
    assert task.bot_id == channel.bot_id
    assert task.channel_id == channel.id


def test_apply_to_task_raises_when_called_on_from_task_only_context():
    """from_task does not carry the preset; apply_to_task must refuse."""
    persisted = {
        "project_id": str(uuid.uuid4()),
        "request": "",
        "branch": None,
        "base_branch": None,
        "repo": {},
        "runtime_target": {"ready": True, "configured_keys": [], "missing_secrets": []},
        "dev_targets": [],
        "dev_target_env": {},
        "dependency_stack": {"configured": False, "source_path": None, "env_keys": [], "commands": []},
        "machine_target_grant": None,
        "source_artifact": None,
        "schedule_task_id": None,
        "schedule_run_number": None,
        "continuation_index": 0,
        "root_task_id": str(uuid.uuid4()),
    }
    src = Task(id=uuid.uuid4(), title="src", execution_config={
        "run_preset_id": "project_coding_run", "project_coding_run": persisted,
    })
    ctx = ProjectTaskExecutionContext.from_task(src)
    sink = Task(id=uuid.uuid4(), status="pending", title="")
    channel = Channel(
        id=uuid.uuid4(), name="c", bot_id="agent",
        client_id="client-1", project_id=uuid.uuid4(), workspace_id=uuid.uuid4(),
    )

    with pytest.raises(ExecutionContextError):
        ctx.apply_to_task(sink, channel=channel)


# ---------------------------------------------------------------------------
# Internal seam — port_prober
# ---------------------------------------------------------------------------


def test_default_port_prober_is_callable():
    # Sanity: default prober has the right shape; we don't assert socket
    # behavior here (would require opening a real port).
    assert callable(default_port_prober)


@pytest.mark.asyncio
async def test_injected_port_prober_overrides_real_probe(db_session):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "dev_targets": [{"key": "api", "port_range": [31100, 31105]}]
        }
    })
    db_session.add(project)
    await db_session.commit()
    busy = {31100, 31101, 31102}

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=uuid.uuid4(),
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": port in busy),
    )

    assert ctx.dev_targets[0].port == 31103


# ---------------------------------------------------------------------------
# Adapter Protocols — custom implementations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_dev_target_allocator_is_respected(db_session):
    project = _make_project(metadata={
        "blueprint_snapshot": {
            "dev_targets": [{"key": "api", "port_range": [31100, 31102]}]
        }
    })
    db_session.add(project)
    await db_session.commit()

    class FakeAllocator:
        async def allocate(self, db, project, *, task_id, specs):
            return (DevTarget(
                key="api", label="API", port=42999,
                port_env="MY_PORT", url="http://127.0.0.1:42999", url_env="MY_URL",
            ),)

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session, project, task_id=uuid.uuid4(), allocator=FakeAllocator()
    )

    assert len(ctx.dev_targets) == 1
    assert ctx.dev_targets[0].port == 42999


@pytest.mark.asyncio
async def test_custom_dependency_stack_resolver_is_respected(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()

    class FakeResolver:
        def resolve(self, project):
            return DependencyStackView(
                configured=True,
                source_path="/custom/compose.yaml",
                env_keys=("DATABASE_URL",),
                commands=("migrate",),
            )

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session, project, task_id=uuid.uuid4(), resolver=FakeResolver()
    )

    assert ctx.dependency_stack.source_path == "/custom/compose.yaml"
    assert ctx.dependency_stack.env_keys == ("DATABASE_URL",)


@pytest.mark.asyncio
async def test_context_assembler_directly_supports_non_default_combinations(db_session):
    project = _make_project()
    db_session.add(project)
    await db_session.commit()
    preset = get_run_preset(PROJECT_CODING_RUN_PRESET_ID)
    assert preset is not None

    assembler = ContextAssembler(
        allocator=NoOpAllocator(),
        resolver=WholeProjectResolver(),
        source=ProjectContextSource(project),
        preset=preset,
    )

    ctx = await assembler.build(db_session, project, task_id=uuid.uuid4(), request="x")

    assert ctx.dev_targets == ()
    assert ctx.preset_id == PROJECT_CODING_RUN_PRESET_ID


# ---------------------------------------------------------------------------
# Typed errors carry useful structured fields
# ---------------------------------------------------------------------------


def test_malformed_execution_context_error_carries_task_id_and_missing_keys():
    err = MalformedExecutionContextError(
        task_id=None, missing_keys=("project_id",), kind="project_coding_run"
    )
    assert err.task_id is None
    assert err.missing_keys == ("project_id",)
    assert err.kind == "project_coding_run"
    assert "project_id" in str(err)


def test_port_allocation_error_carries_target_key_and_attempted_range():
    err = PortAllocationError(target_key="api", attempted_range=(31100, 31102))
    assert err.target_key == "api"
    assert err.attempted_range == (31100, 31102)
    assert "31100-31102" in str(err)


def test_missing_preset_error_carries_preset_id():
    err = MissingPresetError("nonexistent")
    assert err.preset_id == "nonexistent"
    assert "nonexistent" in str(err)


# ---------------------------------------------------------------------------
# Sibling-task port avoidance in real DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allocation_avoids_active_sibling_task_ports(db_session):
    project_id = uuid.uuid4()
    project = _make_project(
        project_id=project_id,
        metadata={
            "blueprint_snapshot": {
                "dev_targets": [{"key": "ui", "port_range": [31200, 31202]}]
            }
        },
    )
    channel = _make_channel(project=project)
    db_session.add_all([project, channel])
    await db_session.commit()
    db_session.add(Task(
        id=uuid.uuid4(),
        bot_id="agent",
        client_id=channel.client_id,
        channel_id=channel.id,
        status="running",
        title="Active",
        execution_config={
            "run_preset_id": "project_coding_run",
            "project_coding_run": {
                "project_id": str(project_id),
                "dev_targets": [{"key": "ui", "port": 31200}],
            },
        },
    ))
    await db_session.commit()

    ctx = await ProjectTaskExecutionContext.fresh(
        db_session,
        project,
        task_id=uuid.uuid4(),
        allocator=SequentialPortAllocator(prober=lambda port, host="127.0.0.1": False),
    )

    assert ctx.dev_targets[0].port == 31201
