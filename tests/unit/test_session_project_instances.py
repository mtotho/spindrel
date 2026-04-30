from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Channel, Project, ProjectInstance, Session
from app.routers.api_v1_sessions import _session_project_instance_out


class _FakeDb:
    def __init__(self, rows: dict[tuple[type, uuid.UUID], object]) -> None:
        self.rows = rows

    async def get(self, model: type, row_id: uuid.UUID):
        return self.rows.get((model, row_id))


def _project() -> Project:
    return Project(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Session Project",
        slug="session-project",
        root_path="common/projects/session-project",
        metadata_={},
    )


def _channel(project: Project | None) -> Channel:
    return Channel(
        id=uuid.uuid4(),
        name="Project Channel",
        bot_id="test-bot",
        client_id=f"project-channel-{uuid.uuid4().hex[:8]}",
        workspace_id=project.workspace_id if project is not None else None,
        project_id=project.id if project is not None else None,
    )


def _session(channel: Channel, *, project_instance_id: uuid.UUID | None = None) -> Session:
    return Session(
        id=uuid.uuid4(),
        client_id=f"project-session-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        channel_id=channel.id,
        session_type="channel",
        project_instance_id=project_instance_id,
    )


@pytest.mark.asyncio
async def test_session_project_instance_out_reports_shared_project_root():
    project = _project()
    channel = _channel(project)
    session = _session(channel)
    db = _FakeDb({(Project, project.id): project})

    out = await _session_project_instance_out(db, session, channel=channel)  # type: ignore[arg-type]

    assert out.project_id == project.id
    assert out.project_instance_id is None
    assert out.status == "shared"
    assert out.root_path == "common/projects/session-project"
    assert out.project_name == "Session Project"
    assert out.workspace_id == project.workspace_id


@pytest.mark.asyncio
async def test_session_project_instance_out_reports_bound_fresh_instance():
    project = _project()
    channel = _channel(project)
    instance_id = uuid.uuid4()
    session = _session(channel, project_instance_id=instance_id)
    instance = ProjectInstance(
        id=instance_id,
        workspace_id=project.workspace_id,
        project_id=project.id,
        root_path="common/project-instances/session-project/abc123",
        status="ready",
        source="blueprint_snapshot",
        source_snapshot={},
        created_at=datetime.now(timezone.utc),
    )
    db = _FakeDb({
        (Project, project.id): project,
        (ProjectInstance, instance.id): instance,
    })

    out = await _session_project_instance_out(db, session, channel=channel)  # type: ignore[arg-type]

    assert out.project_id == project.id
    assert out.project_instance_id == instance.id
    assert out.status == "ready"
    assert out.root_path == "common/project-instances/session-project/abc123"
    assert out.project_name == "Session Project"
    assert out.workspace_id == project.workspace_id


@pytest.mark.asyncio
async def test_session_project_instance_out_hides_non_project_sessions():
    channel = _channel(None)
    session = _session(channel)
    db = _FakeDb({})

    out = await _session_project_instance_out(db, session, channel=channel)  # type: ignore[arg-type]

    assert out.session_id == session.id
    assert out.project_id is None
    assert out.project_instance_id is None
    assert out.root_path is None
