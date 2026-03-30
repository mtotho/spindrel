"""Integration tests for workspace schema template support on channels."""
import uuid

import pytest

from app.db.models import Channel, PromptTemplate, Session
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_template(db_session, **overrides) -> PromptTemplate:
    defaults = {
        "id": uuid.uuid4(),
        "name": "Test Schema",
        "content": "## Workspace Organization\nUse tasks.md and notes.md.",
        "category": "workspace_schema",
        "tags": [],
        "source_type": "manual",
    }
    defaults.update(overrides)
    row = PromptTemplate(**defaults)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _create_channel(client, **overrides) -> dict:
    payload = {
        "bot_id": "test-bot",
        "client_id": f"ws-schema-{uuid.uuid4().hex[:8]}",
        **overrides,
    }
    resp = await client.post("/api/v1/channels", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Admin settings: GET/PUT workspace_schema_template_id
# ---------------------------------------------------------------------------

class TestAdminChannelSettingsWorkspaceSchema:
    async def test_settings_returns_null_by_default(self, client, db_session):
        ch = await _create_channel(client)
        resp = await client.get(
            f"/api/v1/admin/channels/{ch['id']}/settings",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_schema_template_id"] is None

    async def test_set_workspace_schema_template_id(self, client, db_session):
        tpl = await _seed_template(db_session)
        ch = await _create_channel(client)

        resp = await client.put(
            f"/api/v1/admin/channels/{ch['id']}/settings",
            json={"workspace_schema_template_id": str(tpl.id)},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_schema_template_id"] == str(tpl.id)

    async def test_clear_workspace_schema_template_id(self, client, db_session):
        tpl = await _seed_template(db_session)
        ch = await _create_channel(client)

        # Set it
        await client.put(
            f"/api/v1/admin/channels/{ch['id']}/settings",
            json={"workspace_schema_template_id": str(tpl.id)},
            headers=AUTH_HEADERS,
        )

        # Clear it
        resp = await client.put(
            f"/api/v1/admin/channels/{ch['id']}/settings",
            json={"workspace_schema_template_id": None},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_schema_template_id"] is None

    async def test_settings_persists_across_reads(self, client, db_session):
        tpl = await _seed_template(db_session)
        ch = await _create_channel(client)

        await client.put(
            f"/api/v1/admin/channels/{ch['id']}/settings",
            json={"workspace_schema_template_id": str(tpl.id)},
            headers=AUTH_HEADERS,
        )

        resp = await client.get(
            f"/api/v1/admin/channels/{ch['id']}/settings",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_schema_template_id"] == str(tpl.id)


# ---------------------------------------------------------------------------
# Public channel config: GET/PUT workspace_schema_template_id
# ---------------------------------------------------------------------------

class TestChannelConfigWorkspaceSchema:
    async def test_config_returns_null_by_default(self, client, db_session):
        ch = await _create_channel(client)
        resp = await client.get(
            f"/api/v1/channels/{ch['id']}/config",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_schema_template_id"] is None

    async def test_set_via_config_endpoint(self, client, db_session):
        tpl = await _seed_template(db_session)
        ch = await _create_channel(client)

        resp = await client.put(
            f"/api/v1/channels/{ch['id']}/config",
            json={"workspace_schema_template_id": str(tpl.id)},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_schema_template_id"] == str(tpl.id)

    async def test_config_get_reflects_set_value(self, client, db_session):
        tpl = await _seed_template(db_session)
        ch = await _create_channel(client)

        await client.put(
            f"/api/v1/channels/{ch['id']}/config",
            json={"workspace_schema_template_id": str(tpl.id)},
            headers=AUTH_HEADERS,
        )

        resp = await client.get(
            f"/api/v1/channels/{ch['id']}/config",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_schema_template_id"] == str(tpl.id)

    async def test_clear_via_config_endpoint(self, client, db_session):
        tpl = await _seed_template(db_session)
        ch = await _create_channel(client)

        await client.put(
            f"/api/v1/channels/{ch['id']}/config",
            json={"workspace_schema_template_id": str(tpl.id)},
            headers=AUTH_HEADERS,
        )

        resp = await client.put(
            f"/api/v1/channels/{ch['id']}/config",
            json={"workspace_schema_template_id": None},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["workspace_schema_template_id"] is None
