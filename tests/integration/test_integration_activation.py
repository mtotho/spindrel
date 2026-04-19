"""Integration tests for integration activation API endpoints."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _patch_manifests():
    manifests = {
        "mission_control": {
            "carapaces": ["mission-control"],
            "requires_workspace": True,
            "description": "MC activation",
        }
    }
    with patch("integrations.get_activation_manifests", return_value=manifests):
        yield manifests


class TestActivateEndpoint:
    async def test_activate_success(self, client, db_session, _patch_manifests):
        """Activating MC on a workspace-enabled channel succeeds."""
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="ws-channel",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        with patch("app.services.feature_validation.validate_activation", new_callable=AsyncMock, return_value=[]):
            resp = await client.post(
                f"/api/v1/channels/{ch.id}/integrations/mission_control/activate",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["activated"] is True
        assert body["integration_type"] == "mission_control"

    async def test_activate_idempotent(self, client, db_session, _patch_manifests):
        """Activating twice is idempotent."""
        from app.db.models import Channel, ChannelIntegration

        ch = Channel(
            id=uuid.uuid4(),
            name="idempotent",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        ci = ChannelIntegration(
            channel_id=ch.id,
            integration_type="mission_control",
            client_id=f"mc-activated:mission_control:{ch.id}",
            activated=True,
        )
        db_session.add(ci)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/channels/{ch.id}/integrations/mission_control/activate",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["activated"] is True

    async def test_activate_unknown_integration_404(self, client, db_session, _patch_manifests):
        """Activating an unknown integration type returns 404."""
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="unknown-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/channels/{ch.id}/integrations/nonexistent/activate",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


class TestDeactivateEndpoint:
    async def test_deactivate(self, client, db_session):
        """Deactivating sets activated=false."""
        from app.db.models import Channel, ChannelIntegration

        ch = Channel(
            id=uuid.uuid4(),
            name="deact-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        ci = ChannelIntegration(
            channel_id=ch.id,
            integration_type="mission_control",
            client_id=f"mc-activated:mission_control:{ch.id}",
            activated=True,
        )
        db_session.add(ci)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/channels/{ch.id}/integrations/mission_control/deactivate",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["activated"] is False

    async def test_deactivate_channel_not_found(self, client, db_session):
        """Deactivating on non-existent channel → 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/channels/{fake_id}/integrations/mission_control/deactivate",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


class TestAvailableIntegrationsEndpoint:
    async def test_available_integrations(self, client, db_session, _patch_manifests):
        """List available integrations shows activation status."""
        from app.db.models import Channel

        ch = Channel(
            id=uuid.uuid4(),
            name="avail-test",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/channels/{ch.id}/integrations/available",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 1
        mc = next((i for i in body if i["integration_type"] == "mission_control"), None)
        assert mc is not None
        assert mc["requires_workspace"] is True
        assert mc["activated"] is False

    async def test_available_shows_activated(self, client, db_session, _patch_manifests):
        """Activated integration shows activated=true in available list."""
        from app.db.models import Channel, ChannelIntegration

        ch = Channel(
            id=uuid.uuid4(),
            name="active-avail",
            bot_id="test-bot",
            channel_workspace_enabled=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(ch)
        ci = ChannelIntegration(
            channel_id=ch.id,
            integration_type="mission_control",
            client_id=f"mc-activated:mission_control:{ch.id}",
            activated=True,
        )
        db_session.add(ci)
        await db_session.commit()

        resp = await client.get(
            f"/api/v1/channels/{ch.id}/integrations/available",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        mc = next((i for i in body if i["integration_type"] == "mission_control"), None)
        assert mc is not None
        assert mc["activated"] is True
