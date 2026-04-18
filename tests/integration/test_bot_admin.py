"""Integration tests for bot admin endpoints: DELETE, scope enforcement, source_type."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import AUTH_HEADERS, _TEST_REGISTRY, _get_test_bot

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_bot(db: AsyncSession, bot_id: str, *, source_type: str = "manual") -> None:
    """Insert a bot row directly into the DB."""
    from app.db.models import Bot as BotRow
    row = BotRow(
        id=bot_id,
        name=f"Bot {bot_id}",
        model="test/model",
        system_prompt="test",
        source_type=source_type,
    )
    db.add(row)
    await db.commit()


async def _create_channel(db: AsyncSession, bot_id: str) -> uuid.UUID:
    """Insert a channel row linked to the given bot."""
    from app.db.models import Channel
    ch_id = uuid.uuid4()
    ch = Channel(id=ch_id, name="test-channel", bot_id=bot_id)
    db.add(ch)
    await db.commit()
    return ch_id


# ---------------------------------------------------------------------------
# DELETE /api/v1/admin/bots/{bot_id}
# ---------------------------------------------------------------------------

class TestBotDelete:
    async def test_delete_manual_bot(self, client, db_session):
        """Deleting a manual bot succeeds with 204."""
        await _create_bot(db_session, "deletable-bot")

        # Patch reload_bots and load_bots to avoid full registry refresh
        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/admin/bots/deletable-bot",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 204

        # Verify it's gone from DB
        from app.db.models import Bot as BotRow
        row = await db_session.get(BotRow, "deletable-bot")
        assert row is None

    async def test_delete_not_found(self, client, db_session):
        """Deleting a non-existent bot returns 404."""
        resp = await client.delete(
            "/api/v1/admin/bots/nonexistent-bot",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    async def test_delete_system_bot_rejected(self, client, db_session):
        """System bots cannot be deleted (403)."""
        await _create_bot(db_session, "system-bot", source_type="system")

        resp = await client.delete(
            "/api/v1/admin/bots/system-bot",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 403
        assert "system bot" in resp.json()["detail"].lower()

    async def test_delete_bot_with_channels_blocked(self, client, db_session):
        """Deleting a bot with channels is blocked without force (409)."""
        await _create_bot(db_session, "busy-bot")
        await _create_channel(db_session, "busy-bot")

        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/admin/bots/busy-bot",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 409
        assert "active channel" in resp.json()["detail"].lower()

    async def test_delete_bot_force_cascades(self, client, db_session):
        """Force delete removes bot and its channels."""
        await _create_bot(db_session, "force-bot")
        ch_id = await _create_channel(db_session, "force-bot")

        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/admin/bots/force-bot?force=true",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 204

        # Both bot and channel are gone
        from app.db.models import Bot as BotRow, Channel
        assert await db_session.get(BotRow, "force-bot") is None
        assert await db_session.get(Channel, ch_id) is None

    async def test_delete_file_bot_allowed(self, client, db_session):
        """File-sourced bots can be deleted (only system bots are protected)."""
        await _create_bot(db_session, "file-bot", source_type="file")

        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await client.delete(
                "/api/v1/admin/bots/file-bot",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

class TestBotScopeEnforcement:
    """Verify that bot endpoints use require_scopes instead of verify_auth_or_user."""

    @pytest_asyncio.fixture
    async def scoped_client(self, db_session):
        """Client that does NOT override auth — uses real scoped key validation."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from app.routers.api_v1 import router as api_v1_router
        from app.dependencies import get_db

        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db

        with (
            patch("app.agent.bots._registry", _TEST_REGISTRY),
            patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
            patch("app.agent.persona.get_persona", return_value=None),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac

        app.dependency_overrides.clear()

    async def test_read_scope_grants_list(self, scoped_client, db_session):
        """A key with bots:read can list bots."""
        from app.services.api_keys import create_api_key
        _, key = await create_api_key(db_session, "test-read", ["bots:read"])

        resp = await scoped_client.get(
            "/api/v1/admin/bots",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_read_scope_denies_create(self, scoped_client, db_session):
        """A key with bots:read cannot create bots (requires bots:write)."""
        from app.services.api_keys import create_api_key
        _, key = await create_api_key(db_session, "test-read-only", ["bots:read"])

        resp = await scoped_client.post(
            "/api/v1/admin/bots",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"id": "new-bot", "name": "New", "model": "test/m"},
        )
        assert resp.status_code == 403

    async def test_write_scope_denies_delete(self, scoped_client, db_session):
        """A key with bots:write cannot delete bots (requires bots:delete)."""
        from app.services.api_keys import create_api_key
        _, key = await create_api_key(db_session, "test-write", ["bots:write"])

        await _create_bot(db_session, "write-test-bot")

        resp = await scoped_client.delete(
            "/api/v1/admin/bots/write-test-bot",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

    async def test_delete_scope_grants_delete(self, scoped_client, db_session):
        """A key with bots:delete can delete bots."""
        from app.services.api_keys import create_api_key
        _, key = await create_api_key(db_session, "test-delete", ["bots:delete"])

        await _create_bot(db_session, "del-test-bot")

        with patch("app.agent.bots.load_bots", new_callable=AsyncMock):
            resp = await scoped_client.delete(
                "/api/v1/admin/bots/del-test-bot",
                headers={"Authorization": f"Bearer {key}"},
            )
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# source_type field
# ---------------------------------------------------------------------------

class TestBotSourceType:
    async def test_source_type_in_list(self, client, db_session):
        """Bot list includes source_type field."""
        await _create_bot(db_session, "typed-bot", source_type="file")

        # Patch registry to include the typed bot
        from app.agent.bots import BotConfig, MemoryConfig
        typed_bot = BotConfig(
            id="typed-bot", name="Typed Bot", model="test/model",
            system_prompt="test", source_type="file",
            memory=MemoryConfig(),
        )
        registry = {**_TEST_REGISTRY, "typed-bot": typed_bot}

        with (
            patch("app.agent.bots._registry", registry),
            patch("app.agent.bots.list_bots", return_value=list(registry.values())),
        ):
            resp = await client.get("/api/v1/admin/bots", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        bots = resp.json()["bots"]
        typed = next(b for b in bots if b["id"] == "typed-bot")
        assert typed["source_type"] == "file"


# ---------------------------------------------------------------------------
# POST /api/v1/admin/bots  (admin_bot_create)
# ---------------------------------------------------------------------------

def _register_new_bot_on_reload(bot_id: str, name: str = "New Bot", model: str = "test/model"):
    """Return an AsyncMock whose side-effect registers the given bot in _TEST_REGISTRY.

    The route under test calls reload_bots() after the insert; patching it with
    this lets the subsequent get_bot(data.id) succeed against our test registry.
    """
    from app.agent.bots import BotConfig, MemoryConfig

    async def _side_effect():
        _TEST_REGISTRY[bot_id] = BotConfig(
            id=bot_id, name=name, model=model, system_prompt="",
            memory=MemoryConfig(enabled=False),
        )

    return AsyncMock(side_effect=_side_effect)


class TestBotCreate:
    async def test_when_valid_payload_then_returns_201_and_row_persisted(self, client, db_session):
        payload = {"id": "alpha-bot", "name": "Alpha", "model": "test/alpha-model"}

        with patch("app.agent.bots.reload_bots", _register_new_bot_on_reload("alpha-bot", "Alpha", "test/alpha-model")):
            resp = await client.post("/api/v1/admin/bots", json=payload, headers=AUTH_HEADERS)

        from app.db.models import Bot as BotRow
        row = await db_session.get(BotRow, "alpha-bot")
        assert resp.status_code == 201
        assert resp.json()["id"] == "alpha-bot"
        assert row is not None and row.name == payload["name"]
        _TEST_REGISTRY.pop("alpha-bot", None)

    async def test_when_id_is_invalid_format_then_returns_400(self, client):
        payload = {"id": "Bad.ID", "name": "x", "model": "m"}  # uppercase + dot

        resp = await client.post("/api/v1/admin/bots", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 400
        assert "lowercase" in resp.json()["detail"].lower()

    async def test_when_name_missing_then_returns_400(self, client):
        payload = {"id": "ok-id", "name": "", "model": "test/m"}

        resp = await client.post("/api/v1/admin/bots", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 400
        assert "name" in resp.json()["detail"].lower()

    async def test_when_model_missing_then_returns_400(self, client):
        payload = {"id": "ok-id", "name": "Some Bot", "model": ""}

        resp = await client.post("/api/v1/admin/bots", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 400
        assert "model" in resp.json()["detail"].lower()

    async def test_when_id_already_exists_then_returns_409(self, client, db_session):
        await _create_bot(db_session, "dup-bot")
        payload = {"id": "dup-bot", "name": "Dup", "model": "test/m"}

        resp = await client.post("/api/v1/admin/bots", json=payload, headers=AUTH_HEADERS)

        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()

    async def test_when_created_then_memory_scheme_defaults_to_workspace_files(self, client, db_session):
        payload = {"id": "fresh-bot", "name": "Fresh", "model": "test/m"}

        with patch("app.agent.bots.reload_bots", _register_new_bot_on_reload("fresh-bot", "Fresh")):
            resp = await client.post("/api/v1/admin/bots", json=payload, headers=AUTH_HEADERS)

        from app.db.models import Bot as BotRow
        row = await db_session.get(BotRow, "fresh-bot")
        assert resp.status_code == 201
        assert row.memory_scheme == "workspace-files"
        _TEST_REGISTRY.pop("fresh-bot", None)


# ---------------------------------------------------------------------------
# POST /api/v1/admin/bots/{bot_id}/memory-hygiene/trigger
# ---------------------------------------------------------------------------

class TestMemoryHygieneTrigger:
    async def test_when_valid_then_creates_task_and_returns_id(self, client, db_session):
        from tests.factories import build_bot
        from app.db.models import Task as TaskRow
        bot = build_bot(id="hy-bot", memory_scheme="workspace-files")
        db_session.add(bot)
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/hy-bot/memory-hygiene/trigger",
            headers=AUTH_HEADERS,
        )

        body = resp.json()
        tasks = (await db_session.execute(select(TaskRow).where(TaskRow.bot_id == "hy-bot"))).scalars().all()
        assert resp.status_code == 200
        assert body == {"status": "ok", "task_id": str(tasks[0].id), "job_type": "memory_hygiene"}

    async def test_when_job_type_invalid_then_returns_400(self, client, db_session):
        from tests.factories import build_bot
        db_session.add(build_bot(id="hy-bot2", memory_scheme="workspace-files"))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/hy-bot2/memory-hygiene/trigger?job_type=bogus",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 400
        assert "bogus" in resp.json()["detail"]

    async def test_when_bot_missing_then_returns_404(self, client):
        resp = await client.post(
            "/api/v1/admin/bots/does-not-exist/memory-hygiene/trigger",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404

    async def test_when_memory_scheme_not_workspace_files_then_returns_400(self, client, db_session):
        from tests.factories import build_bot
        db_session.add(build_bot(id="legacy-hy-bot", memory_scheme=None))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/legacy-hy-bot/memory-hygiene/trigger",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 400
        assert "workspace-files" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/v1/admin/bots/{bot_id}/memory-scheme
# ---------------------------------------------------------------------------

class TestMemoryScheme:
    async def test_when_bot_exists_then_memory_scheme_set_to_workspace_files(self, client, db_session, tmp_path):
        from tests.factories import build_bot
        db_session.add(build_bot(id="ms-bot", memory_scheme=None))
        await db_session.commit()

        with (
            patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(tmp_path)),
            patch("app.agent.bots.reload_bots", new_callable=AsyncMock),
            patch("app.services.memory_indexing.index_memory_for_bot", new_callable=AsyncMock),
        ):
            resp = await client.post("/api/v1/admin/bots/ms-bot/memory-scheme", headers=AUTH_HEADERS)

        from app.db.models import Bot as BotRow
        await db_session.refresh(await db_session.get(BotRow, "ms-bot"))
        row = await db_session.get(BotRow, "ms-bot")
        body = resp.json()
        assert resp.status_code == 200
        assert body["memory_scheme"] == "workspace-files"
        assert row.memory_scheme == "workspace-files"

    async def test_when_bot_missing_then_returns_404(self, client):
        resp = await client.post("/api/v1/admin/bots/missing-bot/memory-scheme", headers=AUTH_HEADERS)

        assert resp.status_code == 404

    async def test_when_indexing_raises_then_request_still_succeeds(self, client, db_session, tmp_path):
        from tests.factories import build_bot
        db_session.add(build_bot(id="idx-fail-bot", memory_scheme=None))
        await db_session.commit()

        with (
            patch("app.services.workspace.workspace_service.get_workspace_root", return_value=str(tmp_path)),
            patch("app.agent.bots.reload_bots", new_callable=AsyncMock),
            patch(
                "app.services.memory_indexing.index_memory_for_bot",
                new_callable=AsyncMock,
                side_effect=RuntimeError("disk full"),
            ),
        ):
            resp = await client.post("/api/v1/admin/bots/idx-fail-bot/memory-scheme", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /api/v1/admin/bots/{bot_id}/sandbox/recreate
# ---------------------------------------------------------------------------

class TestSandboxRecreate:
    async def test_when_recreate_succeeds_then_returns_ok(self, client):
        with patch(
            "app.services.sandbox.sandbox_service.recreate_bot_local",
            new_callable=AsyncMock,
        ) as recreate:
            resp = await client.post(
                "/api/v1/admin/bots/test-bot/sandbox/recreate",
                headers=AUTH_HEADERS,
            )

        recreate.assert_awaited_once_with("test-bot")
        assert resp.status_code == 200
        assert "test-bot" in resp.json()["message"]

    async def test_when_recreate_raises_then_returns_500(self, client):
        with patch(
            "app.services.sandbox.sandbox_service.recreate_bot_local",
            new_callable=AsyncMock,
            side_effect=RuntimeError("docker unreachable"),
        ):
            resp = await client.post(
                "/api/v1/admin/bots/test-bot/sandbox/recreate",
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 500
        assert "docker unreachable" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST / DELETE /api/v1/admin/bots/{bot_id}/enrolled-skills
# ---------------------------------------------------------------------------

class TestEnrolledSkills:
    async def test_when_skill_and_bot_exist_then_enrollment_created(self, client, db_session):
        from tests.factories import build_bot, build_skill
        from app.db.models import BotSkillEnrollment
        db_session.add(build_bot(id="sk-bot"))
        db_session.add(build_skill(id="skills/alpha", name="alpha"))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/sk-bot/enrolled-skills",
            json={"skill_id": "skills/alpha", "source": "manual"},
            headers=AUTH_HEADERS,
        )

        row = await db_session.get(BotSkillEnrollment, ("sk-bot", "skills/alpha"))
        assert resp.status_code == 201
        assert resp.json() == {"status": "ok", "skill_id": "skills/alpha", "inserted": True}
        assert row is not None and row.source == "manual"

    async def test_when_bot_missing_then_returns_404(self, client, db_session):
        from tests.factories import build_skill
        db_session.add(build_skill(id="skills/beta", name="beta"))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/no-such-bot/enrolled-skills",
            json={"skill_id": "skills/beta"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404
        assert "bot" in resp.json()["detail"].lower()

    async def test_when_skill_missing_then_returns_404(self, client, db_session):
        from tests.factories import build_bot
        db_session.add(build_bot(id="sk-bot2"))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/sk-bot2/enrolled-skills",
            json={"skill_id": "skills/ghost"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404
        assert "skill" in resp.json()["detail"].lower()

    async def test_when_enrollment_duplicate_then_inserted_false(self, client, db_session):
        from tests.factories import build_bot, build_skill, build_bot_skill_enrollment
        db_session.add(build_bot(id="sk-bot3"))
        db_session.add(build_skill(id="skills/gamma", name="gamma"))
        db_session.add(build_bot_skill_enrollment(bot_id="sk-bot3", skill_id="skills/gamma"))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/sk-bot3/enrolled-skills",
            json={"skill_id": "skills/gamma"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 201
        assert resp.json() == {"status": "ok", "skill_id": "skills/gamma", "inserted": False}

    async def test_when_enrollment_exists_then_delete_removes_only_target(self, client, db_session):
        from tests.factories import build_bot, build_skill, build_bot_skill_enrollment
        from app.db.models import BotSkillEnrollment
        db_session.add(build_bot(id="sk-bot4"))
        db_session.add(build_skill(id="skills/target", name="target"))
        db_session.add(build_skill(id="skills/survivor", name="survivor"))
        db_session.add(build_bot_skill_enrollment(bot_id="sk-bot4", skill_id="skills/target"))
        db_session.add(build_bot_skill_enrollment(bot_id="sk-bot4", skill_id="skills/survivor"))
        await db_session.commit()

        resp = await client.delete(
            "/api/v1/admin/bots/sk-bot4/enrolled-skills/skills/target",
            headers=AUTH_HEADERS,
        )

        remaining = (await db_session.execute(
            select(BotSkillEnrollment.skill_id).where(BotSkillEnrollment.bot_id == "sk-bot4")
        )).scalars().all()
        assert resp.status_code == 204
        assert remaining == ["skills/survivor"]

    async def test_when_enrollment_missing_then_delete_returns_404(self, client, db_session):
        from tests.factories import build_bot
        db_session.add(build_bot(id="sk-bot5"))
        await db_session.commit()

        resp = await client.delete(
            "/api/v1/admin/bots/sk-bot5/enrolled-skills/skills/never-enrolled",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404
        assert "enrollment" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST / DELETE /api/v1/admin/bots/{bot_id}/enrolled-tools
# ---------------------------------------------------------------------------

class TestEnrolledTools:
    async def test_when_bot_exists_then_tool_enrollment_created(self, client, db_session):
        from tests.factories import build_bot
        from app.db.models import BotToolEnrollment
        db_session.add(build_bot(id="tl-bot"))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/tl-bot/enrolled-tools",
            json={"tool_name": "web_search", "source": "manual"},
            headers=AUTH_HEADERS,
        )

        row = await db_session.get(BotToolEnrollment, ("tl-bot", "web_search"))
        assert resp.status_code == 201
        assert resp.json() == {"status": "ok", "tool_name": "web_search", "inserted": True}
        assert row is not None and row.source == "manual"

    async def test_when_bot_missing_then_returns_404(self, client):
        resp = await client.post(
            "/api/v1/admin/bots/no-such-tl-bot/enrolled-tools",
            json={"tool_name": "web_search"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404

    async def test_when_enrollment_duplicate_then_inserted_false(self, client, db_session):
        from tests.factories import build_bot
        from app.db.models import BotToolEnrollment
        db_session.add(build_bot(id="tl-bot2"))
        db_session.add(BotToolEnrollment(bot_id="tl-bot2", tool_name="exec_command", source="manual"))
        await db_session.commit()

        resp = await client.post(
            "/api/v1/admin/bots/tl-bot2/enrolled-tools",
            json={"tool_name": "exec_command"},
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 201
        assert resp.json() == {"status": "ok", "tool_name": "exec_command", "inserted": False}

    async def test_when_enrollment_exists_then_delete_removes_only_target(self, client, db_session):
        from tests.factories import build_bot
        from app.db.models import BotToolEnrollment
        db_session.add(build_bot(id="tl-bot3"))
        db_session.add(BotToolEnrollment(bot_id="tl-bot3", tool_name="web_search", source="manual"))
        db_session.add(BotToolEnrollment(bot_id="tl-bot3", tool_name="exec_command", source="manual"))
        await db_session.commit()

        resp = await client.delete(
            "/api/v1/admin/bots/tl-bot3/enrolled-tools/web_search",
            headers=AUTH_HEADERS,
        )

        remaining = (await db_session.execute(
            select(BotToolEnrollment.tool_name).where(BotToolEnrollment.bot_id == "tl-bot3")
        )).scalars().all()
        assert resp.status_code == 204
        assert remaining == ["exec_command"]

    async def test_when_enrollment_missing_then_delete_returns_404(self, client, db_session):
        from tests.factories import build_bot
        db_session.add(build_bot(id="tl-bot4"))
        await db_session.commit()

        resp = await client.delete(
            "/api/v1/admin/bots/tl-bot4/enrolled-tools/never-enrolled",
            headers=AUTH_HEADERS,
        )

        assert resp.status_code == 404
