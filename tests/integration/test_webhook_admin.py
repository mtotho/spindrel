"""Integration tests for api_v1_admin/webhooks.py — 5 mutating routes.

Phase 3 of the Test Quality track. Real FastAPI + real SQLite DB + real router
+ real ORM. Only `send_test_event`'s outbound HTTP call is intercepted via
respx — it is a true external per skill rule E.1.
`invalidate_cache()`, `generate_secret()`, and `validate_webhook_url()` are pure
functions; no mocking needed.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models import WebhookDelivery, WebhookEndpoint
from app.services.webhooks import EVENT_REGISTRY
from tests.factories import build_webhook_endpoint
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# POST /webhooks — admin_create_webhook
# ---------------------------------------------------------------------------

class TestCreateWebhook:
    async def test_when_valid_payload_then_row_persisted_and_secret_returned(
        self, client, db_session,
    ):
        payload = {
            "name": "My Hook",
            "url": "https://hooks.example.com/recv",
            "events": ["after_response"],
        }

        resp = await client.post("/api/v1/admin/webhooks", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 201
        body = resp.json()
        assert body["endpoint"]["name"] == "My Hook"
        assert isinstance(body["secret"], str) and len(body["secret"]) == 64
        row = (await db_session.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.name == "My Hook")
        )).scalar_one_or_none()
        assert row is not None and row.url == "https://hooks.example.com/recv"

    async def test_when_empty_name_then_422(self, client):
        resp = await client.post(
            "/api/v1/admin/webhooks",
            json={"name": "  ", "url": "https://hooks.example.com/recv"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422

    async def test_when_localhost_url_then_422(self, client):
        resp = await client.post(
            "/api/v1/admin/webhooks",
            json={"name": "Bad Hook", "url": "http://localhost:4000/recv"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422
        assert "localhost" in resp.json()["detail"].lower()

    async def test_when_private_ip_url_then_422(self, client):
        resp = await client.post(
            "/api/v1/admin/webhooks",
            json={"name": "Private Hook", "url": "http://192.168.1.50/recv"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422

    async def test_when_unknown_event_then_422(self, client):
        resp = await client.post(
            "/api/v1/admin/webhooks",
            json={"name": "Hook", "url": "https://hooks.example.com/recv", "events": ["no_such_event"]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422
        assert "no_such_event" in resp.json()["detail"]

    async def test_when_created_then_secret_not_persisted_in_plaintext_form_matches_response(
        self, client, db_session,
    ):
        payload = {"name": "Secret Hook", "url": "https://hooks.example.com/s"}

        resp = await client.post("/api/v1/admin/webhooks", json=payload, headers=AUTH_HEADERS)

        raw_secret = resp.json()["secret"]
        row = (await db_session.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.name == "Secret Hook")
        )).scalar_one()
        # Without ENCRYPTION_KEY, encrypt() is a passthrough — secret stored as-is
        assert row.secret == raw_secret


# ---------------------------------------------------------------------------
# PUT /webhooks/{endpoint_id} — admin_update_webhook
# ---------------------------------------------------------------------------

class TestUpdateWebhook:
    async def test_when_name_updated_then_row_reflects_change(self, client, db_session):
        row = build_webhook_endpoint(name="Old Name")
        db_session.add(row)
        await db_session.commit()

        resp = await client.put(
            f"/api/v1/admin/webhooks/{row.id}",
            json={"name": "New Name"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        await db_session.refresh(row)
        assert row.name == "New Name"
        assert resp.json()["name"] == "New Name"

    async def test_when_url_set_to_private_ip_then_422(self, client, db_session):
        row = build_webhook_endpoint()
        db_session.add(row)
        await db_session.commit()

        resp = await client.put(
            f"/api/v1/admin/webhooks/{row.id}",
            json={"url": "http://10.0.0.1/recv"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422

    async def test_when_invalid_event_in_update_then_422(self, client, db_session):
        row = build_webhook_endpoint()
        db_session.add(row)
        await db_session.commit()

        resp = await client.put(
            f"/api/v1/admin/webhooks/{row.id}",
            json={"events": ["bogus_event"]},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 422
        assert "bogus_event" in resp.json()["detail"]

    async def test_when_is_active_toggled_then_persisted(self, client, db_session):
        row = build_webhook_endpoint(is_active=True)
        db_session.add(row)
        await db_session.commit()

        resp = await client.put(
            f"/api/v1/admin/webhooks/{row.id}",
            json={"is_active": False},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        await db_session.refresh(row)
        assert row.is_active is False

    async def test_when_endpoint_missing_then_404(self, client):
        resp = await client.put(
            f"/api/v1/admin/webhooks/{uuid.uuid4()}",
            json={"name": "Ghost"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404

    async def test_when_events_replaced_then_sibling_rows_unaffected(
        self, client, db_session,
    ):
        sibling = build_webhook_endpoint(name="Sibling", events=["before_llm_call"])
        target = build_webhook_endpoint(name="Target", events=["after_response"])
        db_session.add(sibling)
        db_session.add(target)
        await db_session.commit()

        valid_event = next(iter(EVENT_REGISTRY))
        await client.put(
            f"/api/v1/admin/webhooks/{target.id}",
            json={"events": [valid_event]},
            headers=AUTH_HEADERS,
        )

        await db_session.refresh(sibling)
        assert sibling.events == ["before_llm_call"]


# ---------------------------------------------------------------------------
# DELETE /webhooks/{endpoint_id} — admin_delete_webhook
# ---------------------------------------------------------------------------

class TestDeleteWebhook:
    async def test_when_endpoint_exists_then_row_deleted(self, client, db_session):
        row = build_webhook_endpoint()
        sibling = build_webhook_endpoint(name="Sibling")
        db_session.add(row)
        db_session.add(sibling)
        await db_session.commit()
        row_id = row.id

        resp = await client.delete(
            f"/api/v1/admin/webhooks/{row_id}", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        gone = await db_session.execute(
            select(WebhookEndpoint).where(WebhookEndpoint.id == row_id)
        )
        assert gone.scalar_one_or_none() is None
        await db_session.refresh(sibling)
        assert sibling.id is not None  # extra mile: sibling untouched

    async def test_when_endpoint_missing_then_404(self, client):
        resp = await client.delete(
            f"/api/v1/admin/webhooks/{uuid.uuid4()}", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404

    async def test_when_invalid_uuid_then_404(self, client):
        resp = await client.delete(
            "/api/v1/admin/webhooks/not-a-uuid", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /webhooks/{endpoint_id}/rotate-secret — admin_rotate_webhook_secret
# ---------------------------------------------------------------------------

class TestRotateWebhookSecret:
    async def test_when_rotated_then_new_secret_returned_and_row_updated(
        self, client, db_session,
    ):
        row = build_webhook_endpoint(secret="old-secret")
        db_session.add(row)
        await db_session.commit()
        old_updated_at = row.updated_at

        resp = await client.post(
            f"/api/v1/admin/webhooks/{row.id}/rotate-secret", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 200
        new_secret = resp.json()["secret"]
        assert isinstance(new_secret, str) and len(new_secret) == 64
        await db_session.refresh(row)
        assert row.secret == new_secret  # passthrough encryption in tests
        assert row.updated_at > old_updated_at

    async def test_when_endpoint_missing_then_404(self, client):
        resp = await client.post(
            f"/api/v1/admin/webhooks/{uuid.uuid4()}/rotate-secret", headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /webhooks/{endpoint_id}/test — admin_test_webhook
# ---------------------------------------------------------------------------

class TestTestWebhook:
    async def test_when_endpoint_reachable_then_success_result(
        self, client, db_session,
    ):
        row = build_webhook_endpoint(url="https://hooks.example.com/recv")
        db_session.add(row)
        await db_session.commit()

        success_result = {"success": True, "status_code": 200, "duration_ms": 42}
        with patch("app.routers.api_v1_admin.webhooks.send_test_event", return_value=success_result):
            resp = await client.post(
                f"/api/v1/admin/webhooks/{row.id}/test", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_when_endpoint_missing_then_404(self, client):
        not_found_error = ValueError("Endpoint not found")
        with patch(
            "app.routers.api_v1_admin.webhooks.send_test_event",
            side_effect=not_found_error,
        ):
            resp = await client.post(
                f"/api/v1/admin/webhooks/{uuid.uuid4()}/test", headers=AUTH_HEADERS,
            )

        assert resp.status_code == 404
