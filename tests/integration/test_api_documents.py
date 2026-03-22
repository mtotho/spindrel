"""Integration tests for /api/v1/documents endpoints.

Note: document search requires pgvector (cosine distance operator) and is
skipped here. Only CRUD operations are tested with the SQLite backend.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio

FAKE_EMBEDDING = [0.1] * 1536  # must match settings.EMBEDDING_DIMENSIONS


@pytest.fixture(autouse=True)
def mock_embed():
    """Patch the _embed helper to avoid real LLM calls."""
    with patch(
        "app.routers.api_v1_documents._embed",
        new_callable=AsyncMock,
        return_value=FAKE_EMBEDDING,
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# POST /api/v1/documents
# ---------------------------------------------------------------------------

class TestIngestDocument:
    async def test_ingest_document(self, client):
        resp = await client.post(
            "/api/v1/documents",
            json={"content": "Test document content", "title": "My Doc"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        uuid.UUID(body["id"])
        assert body["content"] == "Test document content"
        assert body["title"] == "My Doc"

    async def test_ingest_document_with_metadata(self, client):
        resp = await client.post(
            "/api/v1/documents",
            json={
                "content": "Content",
                "metadata": {"source": "email", "tags": ["test"]},
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        assert resp.json()["metadata"] == {"source": "email", "tags": ["test"]}

    async def test_ingest_document_with_integration_id(self, client):
        resp = await client.post(
            "/api/v1/documents",
            json={"content": "From Slack", "integration_id": "slack-123"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        assert resp.json()["integration_id"] == "slack-123"

    async def test_ingest_calls_embed(self, client, mock_embed):
        await client.post(
            "/api/v1/documents",
            json={"content": "Embed me", "title": "Title"},
            headers=AUTH_HEADERS,
        )
        mock_embed.assert_awaited_once()
        # Embed text should be "Title\nEmbed me"
        call_args = mock_embed.call_args[0][0]
        assert "Title" in call_args
        assert "Embed me" in call_args


# ---------------------------------------------------------------------------
# GET /api/v1/documents/{id}
# ---------------------------------------------------------------------------

class TestGetDocument:
    async def test_get_document(self, client):
        # Create first
        create_resp = await client.post(
            "/api/v1/documents",
            json={"content": "Findable doc", "title": "Find Me"},
            headers=AUTH_HEADERS,
        )
        doc_id = create_resp.json()["id"]

        # Fetch
        resp = await client.get(f"/api/v1/documents/{doc_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["content"] == "Findable doc"
        assert resp.json()["title"] == "Find Me"

    async def test_get_document_not_found(self, client):
        resp = await client.get(
            f"/api/v1/documents/{uuid.uuid4()}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404
        assert "Document not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# DELETE /api/v1/documents/{id}
# ---------------------------------------------------------------------------

class TestDeleteDocument:
    async def test_delete_document(self, client):
        # Create
        create_resp = await client.post(
            "/api/v1/documents",
            json={"content": "To be deleted"},
            headers=AUTH_HEADERS,
        )
        doc_id = create_resp.json()["id"]

        # Delete
        resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 204

        # Verify gone
        resp = await client.get(f"/api/v1/documents/{doc_id}", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    async def test_delete_document_not_found(self, client):
        resp = await client.delete(
            f"/api/v1/documents/{uuid.uuid4()}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/documents/search — requires pgvector, skip on SQLite
# ---------------------------------------------------------------------------

class TestSearchDocuments:
    @pytest.mark.skip(reason="Requires pgvector cosine distance operator (not available in SQLite)")
    async def test_search_documents(self, client):
        pass
