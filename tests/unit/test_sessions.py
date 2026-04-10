"""Priority 3 tests for app.services.sessions — load_or_create, persist_turn, etc."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


# ---------------------------------------------------------------------------
# _content_for_db
# ---------------------------------------------------------------------------

class TestContentForDb:
    def test_plain_string(self):
        from app.services.sessions import _content_for_db
        assert _content_for_db({"content": "hello"}) == "hello"

    def test_none_content(self):
        from app.services.sessions import _content_for_db
        assert _content_for_db({"content": None}) is None

    def test_missing_content(self):
        from app.services.sessions import _content_for_db
        assert _content_for_db({}) is None

    def test_multimodal_list_serialized_to_json(self):
        from app.services.sessions import _content_for_db
        content = [
            {"type": "text", "text": "Look at this"},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
        ]
        result = _content_for_db({"content": content})
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["type"] == "text"
        assert parsed[1]["type"] == "image_url"

    def test_data_url_images_redacted(self):
        from app.services.sessions import _content_for_db
        content = [
            {"type": "text", "text": "see image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ]
        result = _content_for_db({"content": content})
        parsed = json.loads(result)
        assert parsed[1]["type"] == "text"
        assert "not available" in parsed[1]["text"]


# ---------------------------------------------------------------------------
# _redact_images_for_db
# ---------------------------------------------------------------------------

class TestRedactImagesForDb:
    def test_non_data_url_preserved(self):
        from app.services.sessions import _redact_images_for_db
        parts = [{"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}]
        result = _redact_images_for_db(parts)
        assert result[0]["type"] == "image_url"

    def test_data_url_replaced(self):
        from app.services.sessions import _redact_images_for_db
        parts = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
        result = _redact_images_for_db(parts)
        assert result[0]["type"] == "text"
        assert "not available" in result[0]["text"]

    def test_non_image_parts_unchanged(self):
        from app.services.sessions import _redact_images_for_db
        parts = [{"type": "text", "text": "hello"}, "raw_string"]
        result = _redact_images_for_db(parts)
        assert result[0] == {"type": "text", "text": "hello"}
        assert result[1] == "raw_string"


# ---------------------------------------------------------------------------
# _effective_system_prompt
# ---------------------------------------------------------------------------

class TestEffectiveSystemPrompt:
    @patch("app.config.settings.GLOBAL_BASE_PROMPT", "")
    def test_basic_prompt(self):
        from app.services.sessions import _effective_system_prompt
        bot = _make_bot(system_prompt="Hello bot")
        assert _effective_system_prompt(bot) == "Hello bot"

    @patch("app.config.settings.GLOBAL_BASE_PROMPT", "")
    def test_memory_prompt_ignored_deprecated(self):
        """DB memory prompt is deprecated and no longer injected."""
        from app.services.sessions import _effective_system_prompt
        mem = MemoryConfig(enabled=True, prompt="Remember things.")
        bot = _make_bot(system_prompt="Hello bot", memory=mem)
        result = _effective_system_prompt(bot)
        assert "Hello bot" in result
        # Memory prompt should NOT be injected (deprecated)
        assert "Remember things." not in result

    def test_global_base_prompt_prepended(self):
        from app.services.sessions import _effective_system_prompt
        with patch("app.config.settings.GLOBAL_BASE_PROMPT", "Global rules."):
            bot = _make_bot(system_prompt="Hello bot")
            result = _effective_system_prompt(bot)
        assert result.startswith("Global rules.")
        assert "Hello bot" in result


# ---------------------------------------------------------------------------
# _sanitize_tool_messages
# ---------------------------------------------------------------------------

class TestSanitizeToolMessages:
    def test_no_changes_when_valid(self):
        from app.services.sessions import _sanitize_tool_messages
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "tc1", "function": {"name": "t"}}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        result = _sanitize_tool_messages(messages)
        assert result == messages

    def test_orphan_tool_result_stripped(self):
        from app.services.sessions import _sanitize_tool_messages
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "orphan_tc", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        result = _sanitize_tool_messages(messages)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 0

    def test_orphan_tool_call_stripped(self):
        from app.services.sessions import _sanitize_tool_messages
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "see result", "tool_calls": [{"id": "tc1", "function": {"name": "t"}}]},
            {"role": "assistant", "content": "done"},
        ]
        result = _sanitize_tool_messages(messages)
        # The assistant message with unanswered tool call should have tool_calls stripped
        # but content preserved
        assistant_msgs = [m for m in result if m.get("role") == "assistant"]
        assert any(m.get("content") == "see result" for m in assistant_msgs)


# ---------------------------------------------------------------------------
# _strip_metadata_keys
# ---------------------------------------------------------------------------

class TestStripMetadataKeys:
    def test_removes_metadata(self):
        from app.services.sessions import _strip_metadata_keys
        messages = [
            {"role": "user", "content": "hi", "_metadata": {"passive": True}},
            {"role": "assistant", "content": "hello"},
        ]
        result = _strip_metadata_keys(messages)
        assert "_metadata" not in result[0]
        assert result[0]["content"] == "hi"
        assert result[1] == {"role": "assistant", "content": "hello"}


# ---------------------------------------------------------------------------
# _format_passive_context
# ---------------------------------------------------------------------------

class TestFormatPassiveContext:
    def test_formats_passive_messages(self):
        from app.services.sessions import _format_passive_context
        msgs = [
            {"content": "hello there", "_metadata": {"sender_id": "alice"}},
            {"content": "yo", "_metadata": {}},
        ]
        result = _format_passive_context(msgs)
        assert "alice: hello there" in result
        assert "user: yo" in result
        assert "Channel context" in result


# ---------------------------------------------------------------------------
# store_passive_message
# ---------------------------------------------------------------------------

class TestStorePassiveMessage:
    @pytest.mark.asyncio
    async def test_stores_message(self):
        from app.services.sessions import store_passive_message

        db = AsyncMock()
        db.add = MagicMock()
        # Make the session lookup return None so we don't try to publish
        # to a mocked channel id (publish_message would attempt to serialize
        # the record via MessageOut, which fails on the AsyncMock attributes).
        db.get.return_value = None
        session_id = uuid.uuid4()
        metadata = {"passive": True}

        await store_passive_message(db, session_id, "hello", metadata)

        db.add.assert_called_once()
        record = db.add.call_args[0][0]
        assert record.role == "user"
        assert record.content == "hello"
        assert record.metadata_ == metadata
        db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# persist_turn
# ---------------------------------------------------------------------------

class TestPersistTurn:
    @pytest.mark.asyncio
    async def test_skips_system_messages(self):
        from app.services.sessions import persist_turn

        db = AsyncMock()
        db.add = MagicMock()
        session_id = uuid.uuid4()
        bot = _make_bot()
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "injected context"},
            {"role": "assistant", "content": "hi back"},
        ]
        await persist_turn(db, session_id, bot, messages, from_index=0)

        # Only user + assistant should be persisted (system skipped)
        added = [call[0][0] for call in db.add.call_args_list]
        roles = [m.role for m in added]
        assert "system" not in roles
        assert "user" in roles
        assert "assistant" in roles

    @pytest.mark.asyncio
    async def test_attaches_metadata_to_first_user(self):
        from app.services.sessions import persist_turn

        db = AsyncMock()
        db.add = MagicMock()
        session_id = uuid.uuid4()
        bot = _make_bot()
        messages = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]
        meta = {"source": "slack"}
        await persist_turn(db, session_id, bot, messages, from_index=0, msg_metadata=meta)

        added = [call[0][0] for call in db.add.call_args_list]
        assert added[0].metadata_ == meta
        assert added[1].metadata_ == {}

    @pytest.mark.asyncio
    async def test_pre_user_msg_id_skips_first_user_message(self):
        """When pre_user_msg_id is set, the first user message should be skipped."""
        from app.services.sessions import persist_turn

        db = AsyncMock()
        db.add = MagicMock()
        session_id = uuid.uuid4()
        pre_id = uuid.uuid4()
        bot = _make_bot()
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi back"},
        ]
        result = await persist_turn(
            db, session_id, bot, messages, from_index=0,
            pre_user_msg_id=pre_id,
        )

        # Only assistant should be persisted (user was pre-persisted)
        added = [call[0][0] for call in db.add.call_args_list]
        roles = [m.role for m in added]
        assert "user" not in roles
        assert "assistant" in roles
        # Return value should be the pre-persisted user message ID
        assert result == pre_id

    @pytest.mark.asyncio
    async def test_pre_user_msg_id_skips_only_first_user(self):
        """pre_user_msg_id should only skip the first user message, not subsequent ones."""
        from app.services.sessions import persist_turn

        db = AsyncMock()
        db.add = MagicMock()
        session_id = uuid.uuid4()
        pre_id = uuid.uuid4()
        bot = _make_bot()
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "follow-up"},
            {"role": "assistant", "content": "reply2"},
        ]
        await persist_turn(
            db, session_id, bot, messages, from_index=0,
            pre_user_msg_id=pre_id,
        )

        added = [call[0][0] for call in db.add.call_args_list]
        roles = [m.role for m in added]
        # First user skipped, second user kept
        user_contents = [m.content for m in added if m.role == "user"]
        assert user_contents == ["follow-up"]
        assert roles.count("assistant") == 2

    @pytest.mark.asyncio
    async def test_no_pre_user_msg_id_persists_all(self):
        """Without pre_user_msg_id, all messages (except system) are persisted as before."""
        from app.services.sessions import persist_turn

        db = AsyncMock()
        db.add = MagicMock()
        session_id = uuid.uuid4()
        bot = _make_bot()
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        await persist_turn(db, session_id, bot, messages, from_index=0)

        added = [call[0][0] for call in db.add.call_args_list]
        roles = [m.role for m in added]
        assert "user" in roles
        assert "assistant" in roles
