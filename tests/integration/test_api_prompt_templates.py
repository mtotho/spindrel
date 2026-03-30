"""Integration tests for /api/v1/prompt-templates endpoints."""
import uuid

import pytest

from app.db.models import PromptTemplate
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_template(db_session, **overrides) -> PromptTemplate:
    defaults = {
        "id": uuid.uuid4(),
        "name": f"tpl-{uuid.uuid4().hex[:6]}",
        "content": "test content",
        "category": None,
        "tags": [],
        "source_type": "manual",
    }
    defaults.update(overrides)
    row = PromptTemplate(**defaults)
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# GET /api/v1/prompt-templates  (category filter)
# ---------------------------------------------------------------------------

class TestListPromptTemplates:
    async def test_list_all(self, client, db_session):
        await _seed_template(db_session, category="workspace_schema")
        await _seed_template(db_session, category="coding")
        await _seed_template(db_session, category=None)

        resp = await client.get("/api/v1/prompt-templates", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()) >= 3

    async def test_filter_by_category(self, client, db_session):
        ws = await _seed_template(db_session, category="workspace_schema")
        await _seed_template(db_session, category="coding")

        resp = await client.get(
            "/api/v1/prompt-templates?category=workspace_schema",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert all(t["category"] == "workspace_schema" for t in body)
        ids = [t["id"] for t in body]
        assert str(ws.id) in ids

    async def test_filter_by_category_empty(self, client, db_session):
        await _seed_template(db_session, category="coding")

        resp = await client.get(
            "/api/v1/prompt-templates?category=nonexistent",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_filter_by_category_excludes_others(self, client, db_session):
        """Category filter must not return templates with different or null categories."""
        await _seed_template(db_session, category="workspace_schema", name="schema-1")
        await _seed_template(db_session, category="coding", name="coding-1")
        await _seed_template(db_session, category=None, name="uncategorized")

        resp = await client.get(
            "/api/v1/prompt-templates?category=coding",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 1
        assert all(t["category"] == "coding" for t in body)
        names = [t["name"] for t in body]
        assert "schema-1" not in names
        assert "uncategorized" not in names
