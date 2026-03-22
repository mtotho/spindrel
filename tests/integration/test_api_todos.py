"""Integration tests for /api/v1/todos endpoints."""
import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Todo, Channel
from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


async def _create_channel(db_session, bot_id="test-bot"):
    """Helper to create a channel row and return its id."""
    ch = Channel(
        id=uuid.uuid4(),
        name="test-channel",
        bot_id=bot_id,
    )
    db_session.add(ch)
    await db_session.commit()
    return ch.id


class TestCreateTodo:
    async def test_create_todo_api(self, client, db_session):
        ch_id = await _create_channel(db_session)
        resp = await client.post(
            "/api/v1/todos",
            json={"bot_id": "test-bot", "channel_id": str(ch_id), "content": "Buy milk", "priority": 1},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["content"] == "Buy milk"
        assert body["status"] == "pending"
        assert body["priority"] == 1
        assert body["bot_id"] == "test-bot"
        assert body["channel_id"] == str(ch_id)

    async def test_create_todo_missing_content(self, client, db_session):
        ch_id = await _create_channel(db_session)
        resp = await client.post(
            "/api/v1/todos",
            json={"bot_id": "test-bot", "channel_id": str(ch_id)},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422

    async def test_create_todo_unknown_bot(self, client, db_session):
        ch_id = await _create_channel(db_session)
        resp = await client.post(
            "/api/v1/todos",
            json={"bot_id": "nonexistent", "channel_id": str(ch_id), "content": "test"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "Unknown bot" in resp.json()["detail"]


class TestListTodos:
    async def test_list_todos_api(self, client, db_session):
        ch_id = await _create_channel(db_session)
        todo = Todo(
            id=uuid.uuid4(), bot_id="test-bot", channel_id=ch_id,
            content="Item 1", status="pending", priority=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(todo)
        await db_session.commit()

        resp = await client.get(
            "/api/v1/todos",
            params={"bot_id": "test-bot", "channel_id": str(ch_id)},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["content"] == "Item 1"

    async def test_list_todos_status_filter(self, client, db_session):
        ch_id = await _create_channel(db_session)
        now = datetime.now(timezone.utc)
        db_session.add(Todo(
            id=uuid.uuid4(), bot_id="test-bot", channel_id=ch_id,
            content="Pending", status="pending", priority=0,
            created_at=now, updated_at=now,
        ))
        db_session.add(Todo(
            id=uuid.uuid4(), bot_id="test-bot", channel_id=ch_id,
            content="Done", status="done", priority=0,
            created_at=now, updated_at=now,
        ))
        await db_session.commit()

        resp = await client.get(
            "/api/v1/todos",
            params={"bot_id": "test-bot", "channel_id": str(ch_id), "status": "done"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["content"] == "Done"

    async def test_list_todos_by_channel(self, client, db_session):
        ch1 = await _create_channel(db_session)
        ch2 = await _create_channel(db_session)
        now = datetime.now(timezone.utc)
        db_session.add(Todo(
            id=uuid.uuid4(), bot_id="test-bot", channel_id=ch1,
            content="Ch1 item", status="pending", priority=0,
            created_at=now, updated_at=now,
        ))
        db_session.add(Todo(
            id=uuid.uuid4(), bot_id="test-bot", channel_id=ch2,
            content="Ch2 item", status="pending", priority=0,
            created_at=now, updated_at=now,
        ))
        await db_session.commit()

        resp = await client.get(
            "/api/v1/todos",
            params={"bot_id": "test-bot", "channel_id": str(ch1)},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["content"] == "Ch1 item"


class TestPatchTodo:
    async def test_patch_todo_api(self, client, db_session):
        ch_id = await _create_channel(db_session)
        todo = Todo(
            id=uuid.uuid4(), bot_id="test-bot", channel_id=ch_id,
            content="Original", status="pending", priority=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(todo)
        await db_session.commit()

        resp = await client.patch(
            f"/api/v1/todos/{todo.id}",
            json={"content": "Updated", "priority": 5, "status": "done"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["content"] == "Updated"
        assert body["priority"] == 5
        assert body["status"] == "done"

    async def test_patch_todo_not_found(self, client):
        resp = await client.patch(
            f"/api/v1/todos/{uuid.uuid4()}",
            json={"content": "x"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


class TestDeleteTodo:
    async def test_delete_todo_api(self, client, db_session):
        ch_id = await _create_channel(db_session)
        todo = Todo(
            id=uuid.uuid4(), bot_id="test-bot", channel_id=ch_id,
            content="To delete", status="pending", priority=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(todo)
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/todos/{todo.id}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 204

        # Verify it's gone
        resp2 = await client.get(
            "/api/v1/todos",
            params={"bot_id": "test-bot", "channel_id": str(ch_id), "status": "all"},
            headers=AUTH_HEADERS,
        )
        assert len(resp2.json()) == 0

    async def test_delete_todo_not_found(self, client):
        resp = await client.delete(
            f"/api/v1/todos/{uuid.uuid4()}",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


class TestAuthRequired:
    async def test_no_auth_returns_422(self, db_session):
        """Without auth header, FastAPI returns 422 for missing required header."""
        from fastapi import FastAPI
        from app.routers.api_v1 import router as api_v1_router
        from app.dependencies import get_db
        from httpx import ASGITransport, AsyncClient

        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db
        # Do NOT override verify_auth — so it actually checks the header

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/todos", params={"bot_id": "x", "channel_id": str(uuid.uuid4())})
        assert resp.status_code == 422
