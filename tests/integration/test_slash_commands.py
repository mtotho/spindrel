"""Integration tests for backend-owned slash commands."""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message, Session
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


async def _create_channel_with_session(db_session: AsyncSession) -> tuple[str, str]:
    channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    db_session.add(Channel(
        id=channel_id,
        name="slash-test",
        bot_id="test-bot",
        active_session_id=session_id,
    ))
    db_session.add(Session(
        id=session_id,
        bot_id="test-bot",
        client_id=f"slash-{channel_id.hex[:8]}",
        channel_id=channel_id,
    ))
    await db_session.commit()
    return str(channel_id), str(session_id)


async def _seed_messages(
    db_session: AsyncSession, session_id: str, *contents: tuple[str, str]
) -> list[str]:
    """Seed `(role, content)` tuples as messages. Returns message ids."""
    ids: list[str] = []
    for role, content in contents:
        msg = Message(
            id=uuid.uuid4(),
            session_id=uuid.UUID(session_id),
            role=role,
            content=content,
        )
        db_session.add(msg)
        ids.append(str(msg.id))
    await db_session.commit()
    return ids


class TestSlashCommandExecute:
    async def test_context_command_for_channel_returns_normalized_summary(self, client, db_session):
        channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "context", "channel_id": channel_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "context"
        assert body["result_type"] == "context_summary"
        assert body["payload"]["scope_kind"] == "channel"
        assert body["payload"]["scope_id"] == channel_id
        assert body["payload"]["session_id"] == session_id
        assert body["payload"]["pinned_widget_context"]["enabled"] is True
        assert isinstance(body["payload"]["top_categories"], list)
        assert isinstance(body["fallback_text"], str) and body["fallback_text"]

    async def test_context_command_for_session_returns_normalized_summary(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "context", "session_id": session_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "context"
        assert body["result_type"] == "context_summary"
        assert body["payload"]["scope_kind"] == "session"
        assert body["payload"]["scope_id"] == session_id
        assert body["payload"]["session_id"] == session_id
        assert body["payload"]["bot_id"] == "test-bot"
        assert body["payload"]["pinned_widget_context"]["enabled"] is True
        assert isinstance(body["fallback_text"], str) and body["fallback_text"]

    async def test_stop_command_for_session_returns_side_effect(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "stop", "session_id": session_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "stop"
        assert body["result_type"] == "side_effect"
        assert body["payload"]["effect"] == "stop"
        assert body["payload"]["scope_kind"] == "session"
        assert body["payload"]["scope_id"] == session_id
        assert isinstance(body["fallback_text"], str) and body["fallback_text"]

    async def test_plan_command_for_session_returns_side_effect(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "plan", "session_id": session_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "plan"
        assert body["result_type"] == "side_effect"
        assert body["payload"]["effect"] == "plan"
        assert body["payload"]["scope_kind"] == "session"
        assert body["payload"]["scope_id"] == session_id
        assert isinstance(body["fallback_text"], str) and body["fallback_text"]

    async def test_requires_exactly_one_scope(self, client):
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "context"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 422


class TestSlashCommandCatalog:
    async def test_list_endpoint_returns_full_arg_schema(self, client):
        resp = await client.get("/api/v1/slash-commands", headers=AUTH_HEADERS)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "commands" in body
        by_id = {c["id"]: c for c in body["commands"]}

        # Every command has the canonical keys.
        for cmd in body["commands"]:
            assert {"id", "label", "description", "surfaces", "local_only", "args"} <= set(cmd.keys())
            for arg in cmd["args"]:
                assert {"name", "source", "required", "enum"} <= set(arg.keys())

        # Spot-check a few specific commands.
        assert by_id["help"]["local_only"] is False
        assert by_id["help"]["args"] == []

        assert by_id["find"]["surfaces"] == ["channel"]
        assert by_id["find"]["args"][0]["source"] == "free_text"
        assert by_id["find"]["args"][0]["required"] is True

        assert by_id["model"]["local_only"] is True
        assert by_id["model"]["args"][0]["source"] == "model"

        assert by_id["theme"]["local_only"] is True
        assert by_id["theme"]["args"][0]["enum"] == ["light", "dark"]
        assert by_id["theme"]["args"][0]["required"] is False

        assert by_id["mode"]["args"][0]["enum"] == ["default", "terminal"]

    async def test_client_only_commands_rejected_over_backend(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "clear", "channel_id": channel_id},
            headers=AUTH_HEADERS,
        )
        # local_only=True commands must never execute server-side
        assert resp.status_code == 400, resp.text
        assert "client" in resp.json()["detail"].lower()


class TestSlashCommandHelp:
    async def test_help_in_channel_lists_channel_surface_commands(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "help", "channel_id": channel_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "help"
        assert body["result_type"] == "context_summary"
        cats = body["payload"]["top_categories"]
        labels = {c["label"] for c in cats}
        # Channel-surface commands include scratch + clear
        assert "/scratch" in labels
        assert "/clear" in labels
        assert "/find" in labels
        assert "/mode" in labels

    async def test_help_in_session_omits_channel_only_commands(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "help", "session_id": session_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        labels = {c["label"] for c in resp.json()["payload"]["top_categories"]}
        # Session surface — /find, /clear, /scratch, /mode, /effort are channel-only
        assert "/find" not in labels
        assert "/mode" not in labels
        assert "/effort" not in labels
        assert "/clear" not in labels
        assert "/scratch" not in labels
        # But /context, /help, /rename should be there
        assert {"/context", "/help", "/rename"} <= labels


class TestSlashCommandFind:
    async def test_find_returns_matching_messages(self, client, db_session):
        channel_id, session_id = await _create_channel_with_session(db_session)
        await _seed_messages(
            db_session,
            session_id,
            ("user", "can you help me with the mortgage paperwork"),
            ("assistant", "Sure, I can help with the mortgage."),
            ("user", "unrelated content about the weather"),
            ("assistant", "The weather is fine today."),
        )
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "find", "channel_id": channel_id, "args": ["mortgage"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["command_id"] == "find"
        assert body["result_type"] == "find_results"
        matches = body["payload"]["matches"]
        assert len(matches) == 2
        assert all("mortgage" in m["preview"].lower() for m in matches)
        assert body["payload"]["query"] == "mortgage"
        assert "2 matches for 'mortgage'" in body["fallback_text"]

    async def test_find_empty_result_is_zero_matches(self, client, db_session):
        channel_id, session_id = await _create_channel_with_session(db_session)
        await _seed_messages(db_session, session_id, ("user", "hello there"))
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "find", "channel_id": channel_id, "args": ["xxnevermatchesxx"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["payload"]["matches"] == []
        assert "0 matches" in body["fallback_text"]

    async def test_find_requires_query_arg(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "find", "channel_id": channel_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400, resp.text

    async def test_find_rejected_in_session_surface(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "find", "session_id": session_id, "args": ["x"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400, resp.text
        assert "not available in session" in resp.json()["detail"].lower()


class TestSlashCommandRename:
    async def test_rename_channel_updates_channel_name(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "rename", "channel_id": channel_id, "args": ["Quick", "demo"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result_type"] == "side_effect"
        assert body["payload"]["effect"] == "rename"
        assert body["payload"]["scope_kind"] == "channel"
        # Joined from args[0] + args[1]
        assert "Quick demo" in body["payload"]["detail"]

        ch = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(ch)
        assert ch.name == "Quick demo"

    async def test_rename_session_updates_session_title(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "rename", "session_id": session_id, "args": ["new", "title"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["payload"]["scope_kind"] == "session"
        sess = await db_session.get(Session, uuid.UUID(session_id))
        await db_session.refresh(sess)
        assert sess.title == "new title"

    async def test_rename_requires_title_arg(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "rename", "channel_id": channel_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400, resp.text


class TestSlashCommandMode:
    async def test_mode_with_arg_sets_channel_config(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "mode", "channel_id": channel_id, "args": ["terminal"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["payload"]["effect"] == "mode"
        assert "terminal" in body["payload"]["detail"]

        ch = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(ch)
        assert (ch.config or {}).get("chat_mode") == "terminal"

    async def test_mode_default_clears_config_key(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        # Seed with terminal first
        ch = await db_session.get(Channel, uuid.UUID(channel_id))
        ch.config = {"chat_mode": "terminal"}
        await db_session.commit()

        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "mode", "channel_id": channel_id, "args": ["default"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        ch = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(ch)
        # Default is stored as absence of the key — matches the PATCH config endpoint's behavior
        assert "chat_mode" not in (ch.config or {})

    async def test_mode_without_arg_toggles(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        # Start at default → toggle should go to terminal
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "mode", "channel_id": channel_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        ch = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(ch)
        assert ch.config.get("chat_mode") == "terminal"

        # Toggle back
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "mode", "channel_id": channel_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        ch = await db_session.get(Channel, uuid.UUID(channel_id))
        await db_session.refresh(ch)
        assert "chat_mode" not in (ch.config or {})

    async def test_mode_rejects_invalid_value(self, client, db_session):
        channel_id, _session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "mode", "channel_id": channel_id, "args": ["fancy"]},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400, resp.text

    async def test_mode_rejected_in_session_surface(self, client, db_session):
        _channel_id, session_id = await _create_channel_with_session(db_session)
        resp = await client.post(
            "/api/v1/slash-commands/execute",
            json={"command_id": "mode", "session_id": session_id},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400, resp.text


class TestSlashCommandRegistryDriftGate:
    """Guard that the registry remains the single source of truth.

    The frontend fetches `GET /api/v1/slash-commands` at load time. These
    assertions pin the shape so silent drift between backend dispatcher
    and the surfaced list is impossible.
    """

    async def test_every_registered_command_is_listed_or_explicitly_client_only(self):
        from app.services.slash_commands import COMMANDS

        for cmd_id, spec in COMMANDS.items():
            if spec.local_only:
                assert spec.handler is None, f"{cmd_id}: local_only commands must not have a handler"
            else:
                assert spec.handler is not None, f"{cmd_id}: non-local command must have a handler"

    async def test_every_command_has_at_least_one_surface(self):
        from app.services.slash_commands import COMMANDS

        for cmd_id, spec in COMMANDS.items():
            assert spec.surfaces, f"{cmd_id}: must declare at least one surface"
            for surf in spec.surfaces:
                assert surf in ("channel", "session"), f"{cmd_id}: invalid surface {surf}"
