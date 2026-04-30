"""Integration tests for /api/v1/projects endpoints."""
from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel, ProjectInstance, SecretValue, SharedWorkspace, Task
from app.services.encryption import encrypt
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

    async def test_project_run_receipts_create_and_list(self, client, db_session):
        workspace = await _workspace(db_session)
        created = await client.post(
            "/api/v1/projects",
            json={
                "workspace_id": str(workspace.id),
                "name": "Receipt Project",
                "root_path": "common/projects/receipt",
            },
            headers=AUTH_HEADERS,
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        receipt = await client.post(
            f"/api/v1/projects/{project_id}/run-receipts",
            json={
                "status": "completed",
                "summary": "Implemented the Project run surface.",
                "bot_id": "test-bot",
                "changed_files": ["app/services/project_run_receipts.py"],
                "tests": [{"command": "pytest tests/unit/test_run_presets.py", "status": "passed"}],
                "screenshots": [{"path": "docs/images/project-workspace-runs.png"}],
                "handoff_type": "branch",
                "handoff_url": "https://example.invalid/review",
            },
            headers=AUTH_HEADERS,
        )
        assert receipt.status_code == 201
        receipt_body = receipt.json()
        assert receipt_body["project_id"] == project_id
        assert receipt_body["status"] == "completed"
        assert receipt_body["idempotency_key"] == "handoff:https://example.invalid/review"
        assert receipt_body["changed_files"] == ["app/services/project_run_receipts.py"]
        assert receipt_body["tests"][0]["status"] == "passed"

        listed = await client.get(f"/api/v1/projects/{project_id}/run-receipts", headers=AUTH_HEADERS)
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [receipt_body["id"]]

    async def test_project_run_receipts_are_idempotent(self, client, db_session):
        workspace = await _workspace(db_session)
        created = await client.post(
            "/api/v1/projects",
            json={
                "workspace_id": str(workspace.id),
                "name": "Idempotent Receipt Project",
                "root_path": "common/projects/idempotent-receipt",
            },
            headers=AUTH_HEADERS,
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        first = await client.post(
            f"/api/v1/projects/{project_id}/run-receipts",
            json={
                "idempotency_key": "coding-run:abc123",
                "status": "needs_review",
                "summary": "Initial draft handoff.",
                "changed_files": ["a.py"],
            },
            headers=AUTH_HEADERS,
        )
        assert first.status_code == 201
        first_body = first.json()

        second = await client.post(
            f"/api/v1/projects/{project_id}/run-receipts",
            json={
                "idempotency_key": "coding-run:abc123",
                "status": "completed",
                "summary": "Final handoff.",
                "changed_files": ["a.py", "b.py"],
                "screenshots": [{"path": "docs/images/project-workspace-runs.png"}],
            },
            headers=AUTH_HEADERS,
        )
        assert second.status_code == 201
        second_body = second.json()
        assert second_body["id"] == first_body["id"]
        assert second_body["status"] == "completed"
        assert second_body["summary"] == "Final handoff."
        assert second_body["changed_files"] == ["a.py", "b.py"]

        listed = await client.get(f"/api/v1/projects/{project_id}/run-receipts", headers=AUTH_HEADERS)
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [first_body["id"]]

    async def test_project_coding_runs_create_guided_task_and_list_receipt(self, client, db_session):
        workspace = await _workspace(db_session)
        blueprint_resp = await client.post(
            "/api/v1/projects/blueprints",
            json={
                "workspace_id": str(workspace.id),
                "name": "Coding Run Blueprint",
                "repos": [
                    {
                        "name": "spindrel",
                        "url": "https://github.com/mtotho/spindrel.git",
                        "path": "spindrel",
                        "branch": "development",
                    }
                ],
                "env": {"SPINDREL_E2E_URL": "http://127.0.0.1:8000"},
                "required_secrets": ["GITHUB_TOKEN"],
            },
            headers=AUTH_HEADERS,
        )
        assert blueprint_resp.status_code == 201

        created = await client.post(
            "/api/v1/projects/from-blueprint",
            json={
                "blueprint_id": blueprint_resp.json()["id"],
                "workspace_id": str(workspace.id),
                "name": "Coding Run Project",
                "root_path": "common/projects/coding-run",
            },
            headers=AUTH_HEADERS,
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        channel_resp = await client.post(
            "/api/v1/channels",
            json={
                "bot_id": "test-bot",
                "client_id": f"project-coding-run-{uuid.uuid4().hex[:8]}",
                "name": "Coding Run Channel",
            },
            headers=AUTH_HEADERS,
        )
        assert channel_resp.status_code == 201
        channel = await db_session.get(Channel, uuid.UUID(channel_resp.json()["id"]))
        channel.project_id = uuid.UUID(project_id)
        await db_session.commit()

        wrong_channel = await client.post(
            "/api/v1/channels",
            json={
                "bot_id": "test-bot",
                "client_id": f"project-coding-wrong-{uuid.uuid4().hex[:8]}",
                "name": "Wrong Project Channel",
            },
            headers=AUTH_HEADERS,
        )
        assert wrong_channel.status_code == 201
        rejected = await client.post(
            f"/api/v1/projects/{project_id}/coding-runs",
            json={"channel_id": wrong_channel.json()["id"], "request": "Should not run"},
            headers=AUTH_HEADERS,
        )
        assert rejected.status_code == 422

        launched = await client.post(
            f"/api/v1/projects/{project_id}/coding-runs",
            json={"channel_id": str(channel.id), "request": "Fix the screenshot diff in Project runs"},
            headers=AUTH_HEADERS,
        )
        assert launched.status_code == 201
        launched_body = launched.json()
        assert launched_body["status"] == "pending"
        assert launched_body["request"] == "Fix the screenshot diff in Project runs"
        assert launched_body["base_branch"] == "development"
        assert launched_body["branch"].startswith("spindrel/project-")
        assert launched_body["repo"]["path"] == "spindrel"
        assert launched_body["runtime_target"]["configured_keys"] == ["SPINDREL_E2E_URL"]
        assert launched_body["runtime_target"]["missing_secrets"] == ["GITHUB_TOKEN"]
        assert launched_body["review"]["status"] == "pending"
        assert launched_body["review"]["actions"]["can_refresh"] is True

        task = await db_session.get(Task, uuid.UUID(launched_body["task"]["id"]))
        assert task is not None
        assert task.channel_id == channel.id
        assert task.execution_config["run_preset_id"] == "project_coding_run"
        assert task.execution_config["session_target"] == {"mode": "new_each_run"}
        assert task.execution_config["project_instance"] == {"mode": "fresh"}
        assert task.execution_config["project_coding_run"]["branch"] == launched_body["branch"]
        assert "Create or switch to the work branch" in task.prompt
        assert "publish_project_run_receipt" in task.prompt

        receipt = await client.post(
            f"/api/v1/projects/{project_id}/run-receipts",
            json={
                "task_id": launched_body["task"]["id"],
                "status": "needs_review",
                "summary": "Screenshot diff is fixed and ready for review.",
                "branch": launched_body["branch"],
                "base_branch": "development",
                "changed_files": ["ui/app/(app)/admin/projects/[projectId]/ProjectRunsSection.tsx"],
                "tests": [{"command": "pytest tests/integration/test_api_projects.py", "status": "passed"}],
                "screenshots": [{"path": "docs/images/project-workspace-runs.png"}],
                "handoff_type": "pull_request",
                "handoff_url": "https://github.com/mtotho/spindrel/pull/123",
            },
            headers=AUTH_HEADERS,
        )
        assert receipt.status_code == 201

        listed = await client.get(f"/api/v1/projects/{project_id}/coding-runs", headers=AUTH_HEADERS)
        assert listed.status_code == 200
        rows = listed.json()
        assert [row["id"] for row in rows] == [launched_body["id"]]
        assert rows[0]["status"] == "needs_review"
        assert rows[0]["receipt"]["handoff_url"] == "https://github.com/mtotho/spindrel/pull/123"
        assert rows[0]["receipt"]["screenshots"][0]["path"] == "docs/images/project-workspace-runs.png"
        assert rows[0]["review"]["status"] == "ready_for_review"
        assert rows[0]["review"]["handoff_url"] == "https://github.com/mtotho/spindrel/pull/123"
        assert rows[0]["review"]["evidence"]["tests_count"] == 1

        reviewed = await client.post(
            f"/api/v1/projects/{project_id}/coding-runs/{launched_body['task']['id']}/reviewed",
            headers=AUTH_HEADERS,
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["review"]["status"] == "reviewed"

        instance = ProjectInstance(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            project_id=uuid.UUID(project_id),
            root_path=f"common/project-instances/coding-run/{uuid.uuid4().hex[:12]}",
            status="ready",
            source="blueprint_snapshot",
            source_snapshot={},
            setup_result={},
            owner_kind="task",
            owner_id=task.id,
        )
        db_session.add(instance)
        task.project_instance_id = instance.id
        await db_session.commit()

        cleaned = await client.post(
            f"/api/v1/projects/{project_id}/coding-runs/{launched_body['task']['id']}/cleanup",
            headers=AUTH_HEADERS,
        )
        assert cleaned.status_code == 200
        cleaned_review = cleaned.json()["review"]
        assert cleaned_review["instance"]["status"] == "deleted"
        assert cleaned_review["steps"]["cleanup"]["status"] == "succeeded"
        assert cleaned_review["actions"]["can_cleanup_instance"] is False

    async def test_create_project_from_blueprint_materializes_files_and_secret_slots(self, client, db_session, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.shared_workspace.local_workspace_base",
            lambda: str(tmp_path),
        )
        workspace = await _workspace(db_session)
        secret = SecretValue(name=f"GITHUB_TOKEN_{uuid.uuid4().hex[:8]}", value="secret")
        db_session.add(secret)
        await db_session.flush()

        blueprint_resp = await client.post(
            "/api/v1/projects/blueprints",
            json={
                "workspace_id": str(workspace.id),
                "name": "Blueprint API",
                "default_root_path_pattern": "common/projects/{slug}",
                "folders": ["docs"],
                "files": {"README.md": "# Starter\n"},
                "knowledge_files": {"overview.md": "Shared project knowledge.\n"},
                "repos": [{"name": "app", "url": "https://example.invalid/app.git"}],
                "env": {"NODE_ENV": "development"},
                "required_secrets": [secret.name, "NPM_TOKEN"],
            },
            headers=AUTH_HEADERS,
        )
        assert blueprint_resp.status_code == 201
        blueprint = blueprint_resp.json()

        created = await client.post(
            "/api/v1/projects/from-blueprint",
            json={
                "blueprint_id": blueprint["id"],
                "workspace_id": str(workspace.id),
                "name": "Blueprint Project",
                "secret_bindings": {secret.name: str(secret.id)},
            },
            headers=AUTH_HEADERS,
        )

        assert created.status_code == 201
        body = created.json()
        assert body["applied_blueprint_id"] == blueprint["id"]
        assert body["root_path"] == "common/projects/blueprint-project"
        assert body["blueprint"]["name"] == "Blueprint API"
        bindings = {binding["logical_name"]: binding for binding in body["secret_bindings"]}
        assert bindings[secret.name]["secret_value_id"] == str(secret.id)
        assert bindings[secret.name]["bound"] is True
        assert bindings["NPM_TOKEN"]["bound"] is False
        assert body["metadata_"]["blueprint_snapshot"]["repos"][0]["name"] == "app"
        assert body["metadata_"]["blueprint_materialization"]["files_written"] == ["README.md"]

        project_root = tmp_path / "shared" / str(workspace.id) / "common" / "projects" / "blueprint-project"
        assert (project_root / "docs").is_dir()
        assert (project_root / "README.md").read_text() == "# Starter\n"
        assert (project_root / ".spindrel" / "knowledge-base" / "overview.md").read_text() == "Shared project knowledge.\n"

        secret_two = SecretValue(name=f"NPM_TOKEN_{uuid.uuid4().hex[:8]}", value="secret")
        db_session.add(secret_two)
        await db_session.flush()
        patched = await client.patch(
            f"/api/v1/projects/{body['id']}/secret-bindings",
            json={"bindings": {"NPM_TOKEN": str(secret_two.id)}},
            headers=AUTH_HEADERS,
        )
        assert patched.status_code == 200
        patched_bindings = {binding["logical_name"]: binding for binding in patched.json()["secret_bindings"]}
        assert patched_bindings["NPM_TOKEN"]["secret_value_id"] == str(secret_two.id)
        assert patched_bindings["NPM_TOKEN"]["bound"] is True

        deleted = await client.delete(f"/api/v1/projects/blueprints/{blueprint['id']}", headers=AUTH_HEADERS)
        assert deleted.status_code == 204

        fetched_after_delete = await client.get(f"/api/v1/projects/{body['id']}", headers=AUTH_HEADERS)
        assert fetched_after_delete.status_code == 200
        deleted_body = fetched_after_delete.json()
        assert deleted_body["applied_blueprint_id"] is None
        assert deleted_body["blueprint"] is None
        assert deleted_body["metadata_"]["blueprint_snapshot"]["name"] == "Blueprint API"

    async def test_project_setup_readiness_uses_snapshot_and_redacts_secret_values(self, client, db_session, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.shared_workspace.local_workspace_base",
            lambda: str(tmp_path),
        )
        workspace = await _workspace(db_session)
        secret = SecretValue(name=f"GITHUB_TOKEN_{uuid.uuid4().hex[:8]}", value=encrypt("ghp_super_secret_setup_token"))
        db_session.add(secret)
        await db_session.flush()

        blueprint_resp = await client.post(
            "/api/v1/projects/blueprints",
            json={
                "workspace_id": str(workspace.id),
                "name": "Setup Blueprint API",
                "repos": [{"name": "spindrel", "url": "https://github.com/mtotho/spindrel.git", "path": "spindrel"}],
                "setup_commands": [{"name": "Install", "command": "npm install", "cwd": "spindrel", "timeout_seconds": 60}],
                "env": {"NODE_ENV": "development"},
                "required_secrets": [secret.name, "NPM_TOKEN"],
            },
            headers=AUTH_HEADERS,
        )
        assert blueprint_resp.status_code == 201
        blueprint = blueprint_resp.json()

        created = await client.post(
            "/api/v1/projects/from-blueprint",
            json={
                "blueprint_id": blueprint["id"],
                "workspace_id": str(workspace.id),
                "name": "Setup Project",
                "secret_bindings": {secret.name: str(secret.id)},
            },
            headers=AUTH_HEADERS,
        )
        assert created.status_code == 201
        project_id = created.json()["id"]

        setup = await client.get(f"/api/v1/projects/{project_id}/setup", headers=AUTH_HEADERS)
        assert setup.status_code == 200
        body = setup.json()
        assert body["plan"]["ready"] is False
        assert body["plan"]["missing_secrets"] == ["NPM_TOKEN"]
        assert body["plan"]["repos"][0]["url"] == "https://github.com/mtotho/spindrel.git"
        assert body["plan"]["commands"][0]["name"] == "Install"
        assert body["plan"]["commands"][0]["command"] == "npm install"
        assert "ghp_super_secret_setup_token" not in str(body)

        runtime = await client.get(f"/api/v1/projects/{project_id}/runtime-env", headers=AUTH_HEADERS)
        assert runtime.status_code == 200
        runtime_body = runtime.json()
        assert runtime_body["env_default_keys"] == ["NODE_ENV"]
        assert runtime_body["secret_keys"] == [secret.name]
        assert runtime_body["missing_secrets"] == ["NPM_TOKEN"]
        assert "ghp_super_secret_setup_token" not in str(runtime_body)

        not_ready = await client.post(f"/api/v1/projects/{project_id}/setup/runs", headers=AUTH_HEADERS)
        assert not_ready.status_code == 409

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
