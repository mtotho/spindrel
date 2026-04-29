"""Tests for the package-less widget preview endpoints used by the developer panel.

- POST /api/v1/admin/widget-packages/preview-inline  (arbitrary YAML + payload)
- POST /api/v1/admin/widget-packages/preview-for-tool (active template for a tool_name)
"""
from __future__ import annotations

import json

import pytest

from app.db.models import WidgetTemplatePackage


AUTH_HEADERS = {"Authorization": "Bearer test-key"}


RICH_YAML = (
    "display: inline\n"
    "display_label: 'Hello {{name}}'\n"
    "template:\n"
    "  v: 1\n"
    "  components:\n"
    "    - type: heading\n"
    "      text: 'Hi {{name}}'\n"
    "      level: 3\n"
    "    - type: status\n"
    "      text: '{{status}}'\n"
    "      when: '{{status | not_empty}}'\n"
)


class TestPreviewInline:
    @pytest.mark.asyncio
    async def test_renders_against_sample_payload(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/preview-inline",
            json={
                "yaml_template": RICH_YAML,
                "sample_payload": {"name": "World", "status": "running"},
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        env = data["envelope"]
        assert env["display"] == "inline"
        assert env["display_label"] == "Hello World"
        body = json.loads(env["body"])
        types = [c.get("type") for c in body["components"]]
        assert "heading" in types
        assert "status" in types

    @pytest.mark.asyncio
    async def test_gates_prune_components_when_data_missing(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/preview-inline",
            json={
                "yaml_template": RICH_YAML,
                "sample_payload": {"name": "World"},  # no status
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        body = json.loads(r.json()["envelope"]["body"])
        types = [c.get("type") for c in body["components"]]
        assert "status" not in types  # filtered by when-gate
        assert "heading" in types

    @pytest.mark.asyncio
    async def test_returns_validation_errors_for_bad_yaml(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/preview-inline",
            json={"yaml_template": "template:\n  v: 1\n  components:\n    - : bad\n"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["errors"]

    @pytest.mark.asyncio
    async def test_requires_yaml_template(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/preview-inline",
            json={"sample_payload": {}},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422  # Pydantic: yaml_template is required


class TestAuthoringCheck:
    @pytest.mark.asyncio
    async def test_runs_shared_static_authoring_check(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/authoring-check",
            json={
                "yaml_template": RICH_YAML,
                "sample_payload": {"name": "World", "status": "running"},
                "tool_name": "demo_tool",
                "include_runtime": False,
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["readiness"] == "ready"
        assert data["envelope"]["display_label"] == "Hello World"
        assert [phase["name"] for phase in data["phases"]][-1] == "browser_smoke"

    @pytest.mark.asyncio
    async def test_reports_authoring_validation_errors(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/authoring-check",
            json={
                "yaml_template": "template:\n  v: 1\n  components:\n    - : bad\n",
                "include_runtime": False,
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["readiness"] == "blocked"
        assert data["envelope"] is None
        assert data["issues"]


class TestPreviewForTool:
    @pytest.mark.asyncio
    async def test_resolves_active_db_package(self, client, db_session):
        row = WidgetTemplatePackage(
            tool_name="my_tool",
            name="my_tool default",
            yaml_template=RICH_YAML,
            source="user",
            is_readonly=False,
            is_active=True,
            content_hash="hashX",
            version=1,
        )
        db_session.add(row)
        await db_session.commit()

        r = await client.post(
            "/api/v1/admin/widget-packages/preview-for-tool",
            json={
                "tool_name": "my_tool",
                "sample_payload": {"name": "DB", "status": "ok"},
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["envelope"]["display_label"] == "Hello DB"

    @pytest.mark.asyncio
    async def test_returns_error_when_no_active_template(self, client):
        r = await client.post(
            "/api/v1/admin/widget-packages/preview-for-tool",
            json={"tool_name": "ghost_tool_does_not_exist", "sample_payload": {}},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert any(e["phase"] == "lookup" for e in data["errors"])

    @pytest.mark.asyncio
    async def test_falls_back_to_in_memory_registry(self, client, monkeypatch):
        from app.services import widget_templates as wt

        entry = {
            "content_type": "application/vnd.spindrel.components+json",
            "display": "inline",
            "display_label": "Integration {{name}}",
            "template": {
                "v": 1,
                "components": [
                    {"type": "heading", "text": "From registry: {{name}}", "level": 3},
                ],
            },
            "default_config": {},
            "transform": None,
            "state_poll": None,
            "source": "test",
        }
        monkeypatch.setitem(wt._widget_templates, "registry_only_tool", entry)

        r = await client.post(
            "/api/v1/admin/widget-packages/preview-for-tool",
            json={
                "tool_name": "registry_only_tool",
                "sample_payload": {"name": "Mem"},
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["envelope"]["display_label"] == "Integration Mem"
        body = json.loads(data["envelope"]["body"])
        assert body["components"][0]["text"] == "From registry: Mem"


class TestPublicPreviewForTool:
    @pytest.mark.asyncio
    async def test_executes_tool_and_renders_active_template(self, client, db_session, monkeypatch):
        row = WidgetTemplatePackage(
            tool_name="fake_preview_tool",
            name="fake preview tool",
            yaml_template=RICH_YAML,
            source="user",
            is_readonly=False,
            is_active=True,
            content_hash="hash-public-preview",
            version=1,
        )
        db_session.add(row)
        await db_session.commit()

        async def _call_local_tool(name: str, args_json: str) -> str:
            assert name == "fake_preview_tool"
            args = json.loads(args_json)
            return json.dumps({"name": args.get("name", "n/a"), "status": "running"})

        monkeypatch.setattr("app.tools.registry.is_local_tool", lambda name: name == "fake_preview_tool")
        monkeypatch.setattr("app.tools.registry.is_mcp_tool", lambda name: False, raising=False)
        monkeypatch.setattr("app.tools.registry.call_local_tool", _call_local_tool)
        monkeypatch.setattr(
            "app.tools.registry.get_tool_context_requirements",
            lambda name: (False, False),
        )

        r = await client.post(
            "/api/v1/widgets/preview-for-tool",
            json={
                "tool_name": "fake_preview_tool",
                "tool_args": {"name": "Public"},
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["envelope"]["display_label"] == "Hello Public"

    @pytest.mark.asyncio
    async def test_enforces_required_bot_context(self, client, monkeypatch):
        monkeypatch.setattr("app.tools.registry.get_tool_context_requirements", lambda name: (True, False))

        r = await client.post(
            "/api/v1/widgets/preview-for-tool",
            json={"tool_name": "needs_bot"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400
        assert "requires bot context" in r.text
