"""Tests for the extended channel creation API (wizard fields)."""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


async def _create_channel(client, **overrides) -> dict:
    payload = {
        "bot_id": "default",
        "client_id": f"wizard-{uuid.uuid4().hex[:8]}",
        **overrides,
    }
    resp = await client.post("/api/v1/channels", json=payload, headers=AUTH_HEADERS)
    return resp.status_code, resp.json()


class TestChannelCreationWizard:

    async def test_backwards_compatible(self, client):
        """Existing minimal creation still works without wizard fields."""
        status, data = await _create_channel(client, name="basic-channel")
        assert status == 201
        assert data["name"] == "basic-channel"
        assert data["bot_id"] == "default"
        assert data.get("category") is None

    async def test_create_with_model_override(self, client):
        """model_override is set on the channel."""
        status, data = await _create_channel(
            client,
            name="model-channel",
            model_override="gemini/gemini-2.5-flash",
        )
        assert status == 201
        assert data["model_override"] == "gemini/gemini-2.5-flash"

    async def test_create_with_category(self, client):
        """category stored in metadata and returned."""
        status, data = await _create_channel(
            client,
            name="cat-channel",
            category="Work",
        )
        assert status == 201
        assert data["category"] == "Work"

    async def test_create_with_template(self, client, db_session):
        """workspace_schema_template_id validated and set."""
        from app.db.models import PromptTemplate

        tpl = PromptTemplate(
            id=uuid.uuid4(),
            name="Test Template",
            content="# Test",
            category="workspace_schema",
            tags=[],
            source_type="manual",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(tpl)
        await db_session.commit()

        status, data = await _create_channel(
            client,
            name="tpl-channel",
            workspace_schema_template_id=str(tpl.id),
        )
        assert status == 201

    async def test_create_with_invalid_template(self, client):
        """Nonexistent template returns 400."""
        status, data = await _create_channel(
            client,
            name="bad-tpl-channel",
            workspace_schema_template_id=str(uuid.uuid4()),
        )
        assert status == 400
        assert "Template not found" in data["detail"]

    async def test_create_with_activation(self, client, db_session):
        """Integration activation during creation creates ChannelIntegration rows."""
        from unittest.mock import patch

        fake_manifests = {
            "test_integration": {
                "description": "Test",
                "requires_workspace": False,
                "carapaces": [],
            }
        }

        with patch("integrations.get_activation_manifests", return_value=fake_manifests):
            status, data = await _create_channel(
                client,
                name="activation-channel",
                activate_integrations=["test_integration"],
            )

        assert status == 201
        # Verify the integration binding was created
        ch_id = data["id"]
        from app.db.models import ChannelIntegration
        from sqlalchemy import select
        rows = (await db_session.execute(
            select(ChannelIntegration).where(
                ChannelIntegration.channel_id == uuid.UUID(ch_id),
                ChannelIntegration.activated == True,  # noqa: E712
            )
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].integration_type == "test_integration"

    async def test_create_all_wizard_fields(self, client, db_session):
        """All wizard fields together in one call."""
        from app.db.models import PromptTemplate
        from unittest.mock import patch

        tpl = PromptTemplate(
            id=uuid.uuid4(),
            name="Full Test Template",
            content="# Full Test",
            category="workspace_schema",
            tags=[],
            source_type="manual",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(tpl)
        await db_session.commit()

        fake_manifests = {
            "full_integration": {
                "description": "Full Test",
                "requires_workspace": False,
                "carapaces": [],
            }
        }

        with patch("integrations.get_activation_manifests", return_value=fake_manifests):
            status, data = await _create_channel(
                client,
                name="full-wizard-channel",
                model_override="openai/gpt-4o",
                workspace_schema_template_id=str(tpl.id),
                category="Projects",
                activate_integrations=["full_integration"],
            )

        assert status == 201
        assert data["model_override"] == "openai/gpt-4o"
        assert data["category"] == "Projects"


class TestGlobalActivatableIntegrations:

    async def test_returns_activatable(self, client):
        """Global activatable endpoint returns integrations with activated=False."""
        from unittest.mock import patch

        fake_manifests = {
            "mock_int": {
                "description": "Mock integration",
                "requires_workspace": False,
                "carapaces": [],
            }
        }

        with patch("integrations.get_activation_manifests", return_value=fake_manifests):
            resp = await client.get(
                "/api/v1/admin/integrations/activatable",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["integration_type"] == "mock_int"
        assert data[0]["activated"] is False


class TestChannelCategories:

    async def test_list_categories(self, client, db_session):
        """Categories endpoint returns distinct categories."""
        # Create channels with different categories
        await _create_channel(client, name="ch1", category="Work")
        await _create_channel(client, name="ch2", category="Personal")
        await _create_channel(client, name="ch3", category="Work")  # duplicate
        await _create_channel(client, name="ch4")  # no category

        resp = await client.get("/api/v1/admin/channels/categories", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        cats = resp.json()
        assert "Work" in cats
        assert "Personal" in cats
        assert len(cats) == 2


class TestCategoryInSettings:

    async def test_category_in_settings_response(self, client):
        """category appears in channel settings GET."""
        _, data = await _create_channel(client, name="settings-cat", category="DevOps")

        resp = await client.get(
            f"/api/v1/admin/channels/{data['id']}/settings",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["category"] == "DevOps"

    async def test_update_category_via_settings(self, client):
        """category can be updated via settings PUT."""
        _, data = await _create_channel(client, name="update-cat", category="Old")

        resp = await client.put(
            f"/api/v1/admin/channels/{data['id']}/settings",
            json={"category": "New"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["category"] == "New"

    async def test_clear_category_via_settings(self, client):
        """Setting category to empty string clears it."""
        _, data = await _create_channel(client, name="clear-cat", category="Temp")

        resp = await client.put(
            f"/api/v1/admin/channels/{data['id']}/settings",
            json={"category": ""},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["category"] is None
