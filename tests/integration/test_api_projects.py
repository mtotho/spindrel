"""Integration tests for /api/v1/projects endpoints."""
from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel, SharedWorkspace
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


async def _workspace(db_session) -> SharedWorkspace:
    workspace = SharedWorkspace(name=f"Project API Workspace {uuid.uuid4().hex[:8]}")
    db_session.add(workspace)
    await db_session.flush()
    return workspace


class TestProjectsApi:
    async def test_create_get_and_list_project(self, client, db_session):
        workspace = await _workspace(db_session)

        created = await client.post(
            "/api/v1/projects",
            json={
                "workspace_id": str(workspace.id),
                "name": "Project API Demo",
                "root_path": "/common//projects/api-demo/",
                "prompt": "Use the Project root.",
            },
            headers=AUTH_HEADERS,
        )

        assert created.status_code == 201
        body = created.json()
        assert body["workspace_id"] == str(workspace.id)
        assert body["root_path"] == "common/projects/api-demo"
        assert body["slug"] == "project-api-demo"
        assert body["resolved"]["path"] == "common/projects/api-demo"
        assert body["attached_channel_count"] == 0

        fetched = await client.get(f"/api/v1/projects/{body['id']}", headers=AUTH_HEADERS)
        assert fetched.status_code == 200
        assert fetched.json()["prompt"] == "Use the Project root."

        listed = await client.get("/api/v1/projects", headers=AUTH_HEADERS)
        assert listed.status_code == 200
        assert any(project["id"] == body["id"] for project in listed.json())

    async def test_project_channels_lists_attached_channels(self, client, db_session):
        workspace = await _workspace(db_session)
        created = await client.post(
            "/api/v1/projects",
            json={
                "workspace_id": str(workspace.id),
                "name": "Attached Project",
                "root_path": "common/projects/attached",
            },
            headers=AUTH_HEADERS,
        )
        assert created.status_code == 201
        project_id = uuid.UUID(created.json()["id"])

        channel_resp = await client.post(
            "/api/v1/channels",
            json={"bot_id": "test-bot", "client_id": f"project-api-{uuid.uuid4().hex[:8]}", "name": "Attached Channel"},
            headers=AUTH_HEADERS,
        )
        assert channel_resp.status_code == 201
        channel = await db_session.get(Channel, uuid.UUID(channel_resp.json()["id"]))
        channel.project_id = project_id
        await db_session.commit()

        channels = await client.get(f"/api/v1/projects/{project_id}/channels", headers=AUTH_HEADERS)

        assert channels.status_code == 200
        assert channels.json() == [
            {
                "id": str(channel.id),
                "name": "Attached Channel",
                "bot_id": "test-bot",
            }
        ]

    async def test_channel_settings_attach_and_detach_project_membership(self, client, db_session):
        workspace = await _workspace(db_session)
        created = await client.post(
            "/api/v1/projects",
            json={
                "workspace_id": str(workspace.id),
                "name": "Membership Project",
                "root_path": "common/projects/membership",
            },
            headers=AUTH_HEADERS,
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        channel_resp = await client.post(
            "/api/v1/channels",
            json={"bot_id": "test-bot", "client_id": f"project-member-{uuid.uuid4().hex[:8]}", "name": "Project Member"},
            headers=AUTH_HEADERS,
        )
        assert channel_resp.status_code == 201
        channel_id = channel_resp.json()["id"]

        attached = await client.put(
            f"/api/v1/admin/channels/{channel_id}/settings",
            json={"project_id": project_id},
            headers=AUTH_HEADERS,
        )
        assert attached.status_code == 200
        attached_body = attached.json()
        assert attached_body["project_id"] == project_id
        assert attached_body["project"]["root_path"] == "common/projects/membership"
        assert attached_body["project_path"] == "common/projects/membership"

        channels = await client.get(f"/api/v1/projects/{project_id}/channels", headers=AUTH_HEADERS)
        assert channels.status_code == 200
        assert [row["id"] for row in channels.json()] == [channel_id]

        detached = await client.put(
            f"/api/v1/admin/channels/{channel_id}/settings",
            json={"project_id": None},
            headers=AUTH_HEADERS,
        )
        assert detached.status_code == 200
        assert detached.json()["project_id"] is None

        channels_after_detach = await client.get(f"/api/v1/projects/{project_id}/channels", headers=AUTH_HEADERS)
        assert channels_after_detach.status_code == 200
        assert channels_after_detach.json() == []
