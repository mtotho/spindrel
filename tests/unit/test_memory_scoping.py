"""Unit tests for user-scoped memory filtering in memory_scope_where."""
import uuid
from unittest.mock import patch

import pytest

from app.agent import bots
from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.agent.memory import memory_scope_where, _get_user_bot_ids
from app.db.models import Memory


def _bot(id: str, user_id: str | None = None) -> BotConfig:
    return BotConfig(
        id=id, name=id, model="gpt-4", system_prompt="test",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        user_id=user_id,
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    backup = bots._registry.copy()
    yield
    bots._registry.clear()
    bots._registry.update(backup)


# ---------------------------------------------------------------------------
# _get_user_bot_ids
# ---------------------------------------------------------------------------

class TestGetUserBotIds:
    def test_none_user_id_returns_none(self):
        assert _get_user_bot_ids(None) is None

    def test_empty_string_returns_none(self):
        assert _get_user_bot_ids("") is None

    def test_returns_bot_ids_for_user(self):
        bots._registry["bot-a"] = _bot("bot-a", user_id="user-1")
        bots._registry["bot-b"] = _bot("bot-b", user_id="user-1")
        bots._registry["bot-c"] = _bot("bot-c", user_id="user-2")
        result = _get_user_bot_ids("user-1")
        assert sorted(result) == ["bot-a", "bot-b"]

    def test_no_bots_for_user_returns_none(self):
        bots._registry["bot-a"] = _bot("bot-a", user_id="user-1")
        result = _get_user_bot_ids("user-999")
        assert result is None

    def test_bots_without_user_id_excluded(self):
        bots._registry["bot-a"] = _bot("bot-a", user_id="user-1")
        bots._registry["bot-b"] = _bot("bot-b", user_id=None)
        result = _get_user_bot_ids("user-1")
        assert result == ["bot-a"]


# ---------------------------------------------------------------------------
# memory_scope_where with user_id
# ---------------------------------------------------------------------------

class TestMemoryScopeWhereWithUserId:
    """Test that user_id scoping works in cross_bot=True scenarios."""

    def test_cross_channel_cross_bot_with_user_scopes_to_user_bots(self):
        """cross_channel=True, cross_client=False, cross_bot=True + user_id
        should scope to bots owned by that user within the client."""
        bots._registry["bot-a"] = _bot("bot-a", user_id="user-1")
        bots._registry["bot-b"] = _bot("bot-b", user_id="user-1")
        bots._registry["bot-c"] = _bot("bot-c", user_id="user-2")

        clause = memory_scope_where(
            session_id=uuid.uuid4(), client_id="client-1", bot_id="bot-a",
            cross_channel=True, cross_client=False, cross_bot=True,
            user_id="user-1",
        )
        # Should produce an AND clause with client_id + bot_id IN (user's bots)
        clause_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "client_id" in clause_str
        assert "bot_id" in clause_str
        # The IN clause should contain user-1's bots
        assert "bot-a" in clause_str
        assert "bot-b" in clause_str
        assert "bot-c" not in clause_str

    def test_full_cross_with_user_scopes_to_user_bots(self):
        """cross_channel=True, cross_client=True, cross_bot=True + user_id
        should scope to only bots owned by that user (global scope within user)."""
        bots._registry["bot-a"] = _bot("bot-a", user_id="user-1")
        bots._registry["bot-b"] = _bot("bot-b", user_id="user-2")

        clause = memory_scope_where(
            session_id=uuid.uuid4(), client_id="client-1", bot_id="bot-a",
            cross_channel=True, cross_client=True, cross_bot=True,
            user_id="user-1",
        )
        clause_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "bot-a" in clause_str
        assert "bot-b" not in clause_str

    def test_full_cross_without_user_returns_false(self):
        """cross_channel=True, cross_client=True, cross_bot=True WITHOUT user_id
        should return false() (fail-secure: block all rather than see everything)."""
        clause = memory_scope_where(
            session_id=uuid.uuid4(), client_id="client-1", bot_id="bot-a",
            cross_channel=True, cross_client=True, cross_bot=True,
            user_id=None,
        )
        assert clause is not None
        # Should compile to a false clause (blocks everything)
        clause_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "false" in clause_str.lower() or "1 != 1" in clause_str

    def test_cross_channel_cross_bot_without_user_scopes_to_client(self):
        """cross_channel=True, cross_client=False, cross_bot=True WITHOUT user_id
        should scope to client_id only (old behavior)."""
        clause = memory_scope_where(
            session_id=uuid.uuid4(), client_id="client-1", bot_id="bot-a",
            cross_channel=True, cross_client=False, cross_bot=True,
            user_id=None,
        )
        clause_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "client_id" in clause_str
        # Should NOT have bot_id IN clause
        assert "IN" not in clause_str


class TestMemoryScopeWhereBasic:
    """Test that basic scoping (non-cross_bot) is unaffected by user_id."""

    def test_no_cross_channel_uses_session_and_bot(self):
        sid = uuid.uuid4()
        clause = memory_scope_where(
            session_id=sid, client_id="client-1", bot_id="bot-a",
            cross_channel=False, cross_client=False, cross_bot=False,
            user_id="user-1",
        )
        clause_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "session_id" in clause_str
        assert "bot_id" in clause_str

    def test_cross_channel_not_cross_bot_uses_client_and_bot(self):
        clause = memory_scope_where(
            session_id=uuid.uuid4(), client_id="client-1", bot_id="bot-a",
            cross_channel=True, cross_client=False, cross_bot=False,
            user_id="user-1",
        )
        clause_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "client_id" in clause_str
        assert "bot_id" in clause_str

    def test_cross_channel_cross_client_not_cross_bot(self):
        clause = memory_scope_where(
            session_id=uuid.uuid4(), client_id="client-1", bot_id="bot-a",
            cross_channel=True, cross_client=True, cross_bot=False,
            user_id="user-1",
        )
        clause_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "bot_id" in clause_str
        # Should not have client_id filter (cross-client)
        assert "client_id" not in clause_str

    def test_channel_id_used_when_provided(self):
        ch_id = uuid.uuid4()
        clause = memory_scope_where(
            session_id=uuid.uuid4(), client_id="client-1", bot_id="bot-a",
            cross_channel=False, cross_client=False, cross_bot=False,
            channel_id=ch_id,
            user_id=None,
        )
        clause_str = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "channel_id" in clause_str
