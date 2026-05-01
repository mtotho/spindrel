from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.db.models import DockerStack, Project, ProjectInstance, Task
from app.services.docker_stacks import StackValidationError
from app.services.project_dependency_stacks import (
    ensure_project_dependency_stack_instance,
    prepare_project_dependency_stack,
    project_dependency_stack_spec,
)
from app.services.project_instances import project_directory_from_instance


def _project(workspace_id: uuid.UUID, project_id: uuid.UUID | None = None) -> Project:
    return Project(
        id=project_id or uuid.uuid4(),
        workspace_id=workspace_id,
        name="Dependency Project",
        slug="dependency-project",
        root_path=f"common/projects/dependency-{uuid.uuid4().hex[:8]}",
        metadata_={
            "blueprint_snapshot": {
                "dependency_stack": {
                    "source_path": "docker-compose.project.yml",
                    "env": {"DATABASE_URL": "postgresql://agent:agent@${postgres.host}:${postgres.5432}/agentdb"},
                    "commands": {"unit": "pytest -q"},
                }
            }
        },
    )


def test_project_dependency_stack_spec_reads_frozen_snapshot():
    project = _project(uuid.uuid4())

    spec = project_dependency_stack_spec(project)

    assert spec.configured is True
    assert spec.source_path == "docker-compose.project.yml"
    assert spec.env == {"DATABASE_URL": "postgresql://agent:agent@${postgres.host}:${postgres.5432}/agentdb"}
    assert spec.commands == {"unit": "pytest -q"}


@pytest.mark.asyncio
async def test_prepare_dependency_stack_uses_task_instance_root_and_distinct_stack(db_session, monkeypatch):
    workspace_id = uuid.uuid4()
    project = _project(workspace_id)
    instance = ProjectInstance(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        project_id=project.id,
        root_path="common/project-instances/dependency/demo",
        status="ready",
    )
    instance_dir = project_directory_from_instance(instance, project)
    compose_path = Path(instance_dir.host_path) / "docker-compose.project.yml"
    compose_path.parent.mkdir(parents=True, exist_ok=True)
    compose_path.write_text(
        """
services:
  web:
    image: python:3.12-slim
    volumes:
      - ${PROJECT_ROOT}:/app
  postgres:
    image: postgres:16
    ports:
      - "0:5432"
""",
        encoding="utf-8",
    )
    task = Task(
        id=uuid.uuid4(),
        bot_id="agent",
        channel_id=uuid.uuid4(),
        execution_config={"project_coding_run": {"project_id": str(project.id)}},
        status="pending",
        task_type="agent",
    )
    db_session.add_all([project, task, instance])
    await db_session.commit()

    created_defs: list[str] = []

    async def fake_create(**kwargs):
        created_defs.append(kwargs["compose_definition"])
        stack = DockerStack(
            id=uuid.uuid4(),
            name=kwargs["name"],
            created_by_bot=kwargs["bot_id"],
            compose_definition=kwargs["compose_definition"],
            project_name="spindrel-test-dependency",
            status="stopped",
            exposed_ports={},
        )
        db_session.add(stack)
        await db_session.commit()
        return stack

    async def fake_start(stack, force_recreate=False):
        stack.status = "running"
        stack.exposed_ports = {"postgres": [{"host_port": 39001, "container_port": 5432, "protocol": "tcp"}]}
        await db_session.commit()
        return stack

    monkeypatch.setattr("app.services.project_dependency_stacks.stack_service.create", fake_create)
    monkeypatch.setattr("app.services.project_dependency_stacks.stack_service.start", fake_start)

    runtime = await ensure_project_dependency_stack_instance(
        db_session,
        project,
        task=task,
        project_instance=instance,
    )
    payload = await prepare_project_dependency_stack(db_session, project, runtime=runtime)

    assert payload["status"] == "running"
    assert payload["scope"] == "task"
    assert payload["project_instance_id"] == str(instance.id)
    assert payload["env"]["DATABASE_URL"] == "postgresql://agent:agent@host.docker.internal:39001/agentdb"
    assert "${PROJECT_ROOT}" not in created_defs[0]
    assert "/common/project-instances/dependency/demo" in created_defs[0]


@pytest.mark.asyncio
async def test_dependency_stack_rejects_mounts_outside_project_root(db_session):
    workspace_id = uuid.uuid4()
    project = _project(workspace_id)
    project.metadata_ = {
        "blueprint_snapshot": {
            "dependency_stack": {
                "compose": """
services:
  web:
    image: alpine
    volumes:
      - /tmp/not-this-project:/app
""",
            }
        }
    }
    db_session.add(project)
    await db_session.commit()
    runtime = await ensure_project_dependency_stack_instance(db_session, project, scope="project")

    with pytest.raises(StackValidationError, match="must stay inside the Project root"):
        await prepare_project_dependency_stack(db_session, project, runtime=runtime)
