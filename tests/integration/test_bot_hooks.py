"""Integration tests for bot hooks API endpoints."""
import pytest

from tests.integration.conftest import AUTH_HEADERS

pytestmark = pytest.mark.asyncio


class TestBotHooksAPI:
    async def test_list_empty(self, client):
        r = await client.get("/api/v1/bot-hooks?bot_id=test-bot", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.json() == []

    async def test_create_before_access(self, client):
        r = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "vault-pull",
            "trigger": "before_access",
            "conditions": {"path": "/workspace/repos/vault/**"},
            "command": "cd /workspace/repos/vault && git pull",
            "cooldown_seconds": 60,
        })
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "vault-pull"
        assert body["trigger"] == "before_access"
        assert body["conditions"] == {"path": "/workspace/repos/vault/**"}
        assert body["command"] == "cd /workspace/repos/vault && git pull"
        assert body["cooldown_seconds"] == 60
        assert body["on_failure"] == "block"  # default for before_access
        assert body["enabled"] is True
        assert "id" in body

    async def test_create_after_write_default_on_failure(self, client):
        r = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "vault-push",
            "trigger": "after_write",
            "conditions": {"path": "/workspace/repos/vault/**"},
            "command": "cd /workspace/repos/vault && git add -A && git commit -m auto && git push",
        })
        assert r.status_code == 201
        assert r.json()["on_failure"] == "warn"  # default for after_write

    async def test_create_invalid_trigger(self, client):
        r = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "bad-hook",
            "trigger": "on_banana",
            "command": "echo nope",
        })
        assert r.status_code == 422

    async def test_get_by_id(self, client):
        create = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "test-hook",
            "trigger": "after_exec",
            "command": "echo done",
        })
        hook_id = create.json()["id"]

        r = await client.get(f"/api/v1/bot-hooks/{hook_id}", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert r.json()["id"] == hook_id
        assert r.json()["name"] == "test-hook"

    async def test_get_not_found(self, client):
        r = await client.get(
            "/api/v1/bot-hooks/00000000-0000-0000-0000-000000000000",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    async def test_update(self, client):
        create = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "old-name",
            "trigger": "before_access",
            "command": "echo old",
        })
        hook_id = create.json()["id"]

        r = await client.put(f"/api/v1/bot-hooks/{hook_id}", headers=AUTH_HEADERS, json={
            "name": "new-name",
            "command": "echo new",
            "cooldown_seconds": 120,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "new-name"
        assert body["command"] == "echo new"
        assert body["cooldown_seconds"] == 120

    async def test_update_invalid_trigger(self, client):
        create = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "hook",
            "trigger": "before_access",
            "command": "echo test",
        })
        hook_id = create.json()["id"]

        r = await client.put(f"/api/v1/bot-hooks/{hook_id}", headers=AUTH_HEADERS, json={
            "trigger": "invalid_trigger",
        })
        assert r.status_code == 422

    async def test_delete(self, client):
        create = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "to-delete",
            "trigger": "before_access",
            "command": "echo bye",
        })
        hook_id = create.json()["id"]

        r = await client.delete(f"/api/v1/bot-hooks/{hook_id}", headers=AUTH_HEADERS)
        assert r.status_code == 204

        r = await client.get(f"/api/v1/bot-hooks/{hook_id}", headers=AUTH_HEADERS)
        assert r.status_code == 404

    async def test_delete_not_found(self, client):
        r = await client.delete(
            "/api/v1/bot-hooks/00000000-0000-0000-0000-000000000000",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 404

    async def test_list_filtered_by_bot(self, client):
        await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "hook-a",
            "trigger": "before_access",
            "command": "echo a",
        })
        await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "other-bot",
            "name": "hook-b",
            "trigger": "after_write",
            "command": "echo b",
        })

        r = await client.get("/api/v1/bot-hooks?bot_id=test-bot", headers=AUTH_HEADERS)
        assert r.status_code == 200
        hooks = r.json()
        assert all(h["bot_id"] == "test-bot" for h in hooks)

    async def test_toggle_enabled(self, client):
        create = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "toggle-me",
            "trigger": "before_access",
            "command": "echo test",
        })
        hook_id = create.json()["id"]
        assert create.json()["enabled"] is True

        r = await client.put(f"/api/v1/bot-hooks/{hook_id}", headers=AUTH_HEADERS, json={
            "enabled": False,
        })
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    async def test_create_with_empty_conditions(self, client):
        r = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "no-conditions",
            "trigger": "after_exec",
            "command": "echo done",
            "conditions": {},
        })
        assert r.status_code == 201
        assert r.json()["conditions"] == {}

    async def test_explicit_on_failure(self, client):
        r = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "warn-before",
            "trigger": "before_access",
            "command": "echo test",
            "on_failure": "warn",
        })
        assert r.status_code == 201
        assert r.json()["on_failure"] == "warn"  # overrides block default

    async def test_invalid_on_failure(self, client):
        r = await client.post("/api/v1/bot-hooks", headers=AUTH_HEADERS, json={
            "bot_id": "test-bot",
            "name": "bad-failure",
            "trigger": "before_access",
            "command": "echo test",
            "on_failure": "explode",
        })
        assert r.status_code == 422
