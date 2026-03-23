"""Integration tests for the attachment system."""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.integration.conftest import AUTH_HEADERS, TEST_BOT


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file_metadata(**overrides):
    defaults = {
        "url": "https://files.slack.com/test.png",
        "filename": "test.png",
        "mime_type": "image/png",
        "size_bytes": 4096,
        "posted_by": "slack:U123",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# test_post_message_with_slack_file
# ---------------------------------------------------------------------------

class TestPostMessageWithSlackFile:
    @pytest.fixture(autouse=True)
    def _mock_run(self):
        with patch("app.routers.chat.run", new_callable=AsyncMock) as mock:
            from dataclasses import dataclass

            @dataclass
            class FakeResult:
                response: str = "Got it."
                transcript: str = ""
                client_actions: list = None

                def __post_init__(self):
                    if self.client_actions is None:
                        self.client_actions = []

            mock.return_value = FakeResult()
            yield mock

    @pytest.fixture(autouse=True)
    def _mock_persist(self):
        with patch("app.routers.chat.persist_turn", new_callable=AsyncMock) as mock:
            mock.return_value = uuid.uuid4()  # Return a user_msg_id
            yield mock

    @pytest.fixture(autouse=True)
    def _mock_compact(self):
        with patch("app.routers.chat.maybe_compact"):
            yield

    async def test_slack_file_triggers_attachment_creation(self, client):
        """Slack message with file → attachment creation awaited."""
        with patch("app.routers.chat._create_attachments_from_metadata", new_callable=AsyncMock) as mock_create:
            resp = await client.post(
                "/chat",
                json={
                    "message": "Check this file",
                    "bot_id": "test-bot",
                    "file_metadata": [_make_file_metadata()],
                    "msg_metadata": {"source": "slack"},
                },
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200

            # _create_attachments_from_metadata was awaited directly
            mock_create.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_message_history_redaction
# ---------------------------------------------------------------------------

class TestMessageHistoryRedaction:
    async def test_attachment_hint_format(self):
        """Turn 1+: attachment hint has correct format."""
        from app.services.sessions import _attachment_hint

        att = MagicMock()
        att.filename = "report.pdf"
        att.description = "A quarterly financial report."

        hint = _attachment_hint(att)
        assert "report.pdf" in hint
        assert "quarterly financial report" in hint

    async def test_attachment_hint_no_description(self):
        """Unsummarized attachment produces hint without description."""
        from app.services.sessions import _attachment_hint

        att = MagicMock()
        att.filename = "image.png"
        att.description = None

        hint = _attachment_hint(att)
        assert "image.png" in hint


# ---------------------------------------------------------------------------
# test_message_redaction — turn-by-turn attachment behavior
# ---------------------------------------------------------------------------

class TestMessageRedaction:
    """Verify turn 0 gets full attachment, turn 1+ gets redacted summary."""

    @pytest_asyncio.fixture
    async def session_with_image_attachment(self, db_session):
        """Create a session with a user message containing a redacted image + attachment row."""
        from app.db.models import Session, Message, Attachment

        session_id = uuid.uuid4()
        session = Session(
            id=session_id, client_id="test-client", bot_id="test-bot",
        )
        db_session.add(session)

        # System message
        sys_msg = Message(session_id=session_id, role="system", content="You are a test bot.")
        db_session.add(sys_msg)

        # User message — stored with placeholder (as _content_for_db would produce)
        import json
        stored_content = json.dumps([
            {"type": "text", "text": "Check this dashboard"},
            {"type": "text", "text": "[image — not available in this session]"},
        ])
        user_msg = Message(
            session_id=session_id, role="user", content=stored_content,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(user_msg)
        await db_session.flush()

        # Attachment with summary
        att = Attachment(
            message_id=user_msg.id,
            type="image",
            url="https://cdn.example.com/screenshot.png",
            filename="screenshot.png",
            mime_type="image/png",
            size_bytes=4096,
            source_integration="slack",
            description="A dashboard showing metrics",
            described_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(att)
        await db_session.commit()

        return session, user_msg, att

    @pytest_asyncio.fixture
    async def session_with_text_attachment(self, db_session):
        """Create a session with a large text file attachment."""
        from app.db.models import Session, Message, Attachment

        session_id = uuid.uuid4()
        session = Session(
            id=session_id, client_id="test-client", bot_id="test-bot",
        )
        db_session.add(session)

        sys_msg = Message(session_id=session_id, role="system", content="You are a test bot.")
        db_session.add(sys_msg)

        user_msg = Message(
            session_id=session_id, role="user",
            content="Please analyze the attached file",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(user_msg)
        await db_session.flush()

        att = Attachment(
            message_id=user_msg.id,
            type="text",
            url="https://cdn.example.com/data.csv",
            filename="data.csv",
            mime_type="text/csv",
            size_bytes=1_200_000,
            source_integration="web",
            description="A CSV file with 50k rows of sales data",
            described_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(att)
        await db_session.commit()

        return session, user_msg, att

    async def test_turn_0_agent_sees_full_image(self, db_session):
        """Turn 0: when user posts image, agent context includes full image for vision."""
        from app.services.sessions import _content_for_db, _redact_images_for_db

        # Simulate fresh multipart content with a real image URL (not data:)
        fresh_content = [
            {"type": "text", "text": "Check this dashboard"},
            {"type": "image_url", "image_url": {"url": "https://cdn.example.com/screenshot.png"}},
        ]

        # _redact_images_for_db only strips data: URLs — real URLs pass through
        redacted = _redact_images_for_db(fresh_content)
        assert any(
            p.get("type") == "image_url" for p in redacted
        ), "Real image URL must survive redaction — agent needs it for vision on turn 0"

        # _content_for_db serializes for storage but preserves the image_url part
        stored = _content_for_db({"content": fresh_content})
        import json
        parsed = json.loads(stored)
        assert any(
            p.get("type") == "image_url" for p in parsed
        ), "Stored content must retain full image_url for turn-0 agent vision"

    async def test_turn_0_data_url_redacted_for_storage(self, db_session):
        """Turn 0: data: URLs are stripped before storage (too large for DB rows)."""
        from app.services.sessions import _redact_images_for_db

        content_with_data_url = [
            {"type": "text", "text": "Here is a screenshot"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo..."}},
        ]
        redacted = _redact_images_for_db(content_with_data_url)

        assert not any(
            p.get("type") == "image_url" for p in redacted
        ), "data: URL must be replaced with placeholder"
        text_parts = " ".join(p.get("text", "") for p in redacted if p.get("type") == "text")
        assert "[image — not available in this session]" in text_parts

    async def test_turn_1_plus_shows_attachment_summary(
        self, db_session, session_with_image_attachment,
    ):
        """Turn 1+: same message in history shows [attached: filename — "summary"] not full image."""
        from app.services.sessions import _load_messages

        session, user_msg, att = session_with_image_attachment

        with patch("app.services.sessions.get_bot", return_value=TEST_BOT), \
             patch("app.services.sessions.get_persona", return_value=None):
            messages = await _load_messages(db_session, session)

        # Find the user message in loaded history
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1

        content = user_msgs[0]["content"]
        # For list content, combine text parts
        if isinstance(content, list):
            text_parts = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
            )
        else:
            text_parts = content

        # Verify: redacted to attachment hint
        assert "screenshot.png" in text_parts
        assert "A dashboard showing metrics" in text_parts
        # Verify: tool hint present
        assert "get_attachment" in text_parts
        # Verify: placeholder is gone
        assert "[image — not available in this session]" not in text_parts

    async def test_large_text_file_truncated_on_turn_1_plus(
        self, db_session, session_with_text_attachment,
    ):
        """Turn 1+: large text attachments show summary + hint, not full content."""
        from app.services.sessions import _load_messages

        session, user_msg, att = session_with_text_attachment

        with patch("app.services.sessions.get_bot", return_value=TEST_BOT), \
             patch("app.services.sessions.get_persona", return_value=None):
            messages = await _load_messages(db_session, session)

        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1

        content = user_msgs[0]["content"]
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
            )

        # Summary + hint injected
        assert "data.csv" in content
        assert "50k rows of sales data" in content
        assert "get_attachment" in content
        # Content is compact — no full 1MB file re-injected
        assert len(content) < 500

    async def test_no_attachment_unaffected(self, db_session):
        """Messages without attachments pass through unchanged across all turns."""
        from app.db.models import Session, Message
        from app.services.sessions import _load_messages

        session_id = uuid.uuid4()
        session = Session(
            id=session_id, client_id="test-client", bot_id="test-bot",
        )
        db_session.add(session)

        sys_msg = Message(session_id=session_id, role="system", content="You are a test bot.")
        db_session.add(sys_msg)

        user_msg = Message(
            session_id=session_id, role="user", content="Hello, no attachments here",
        )
        db_session.add(user_msg)
        await db_session.commit()

        with patch("app.services.sessions.get_bot", return_value=TEST_BOT), \
             patch("app.services.sessions.get_persona", return_value=None):
            messages = await _load_messages(db_session, session)

        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "Hello, no attachments here"


# ---------------------------------------------------------------------------
# test_attachment_sweep_worker
# ---------------------------------------------------------------------------

class TestAttachmentSweepWorker:
    async def test_sweep_finds_unsummarized(self):
        """Sweep worker finds unsummarized attachments and processes them."""
        fake_ids = [uuid.uuid4(), uuid.uuid4()]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = fake_ids

        with (
            patch("app.services.attachment_summarizer.async_session") as mock_session_factory,
            patch("app.services.attachment_summarizer.settings") as mock_settings,
            patch("app.services.attachment_summarizer.summarize_attachment", new_callable=AsyncMock) as mock_summarize,
        ):
            mock_settings.ATTACHMENT_SWEEP_INTERVAL_S = 0  # no delay for test
            mock_settings.ATTACHMENT_SUMMARY_ENABLED = True

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachment_summarizer import attachment_sweep_worker

            # Run one iteration then break
            call_count = 0
            original_sleep = asyncio.sleep

            async def _fake_sleep(seconds):
                nonlocal call_count
                call_count += 1
                if call_count > 1:
                    raise asyncio.CancelledError()  # Stop after one pass

            with patch("asyncio.sleep", side_effect=_fake_sleep):
                with pytest.raises(asyncio.CancelledError):
                    await attachment_sweep_worker()

            # summarize_attachment was called for each unsummarized ID
            assert mock_summarize.call_count == 2
            called_ids = {call.args[0] for call in mock_summarize.call_args_list}
            assert called_ids == set(fake_ids)


# ---------------------------------------------------------------------------
# test_vision_semaphore
# ---------------------------------------------------------------------------

class TestVisionSemaphore:
    async def test_semaphore_limits_concurrency(self):
        """Concurrent summarizations respect semaphore limit."""
        from app.services.attachment_summarizer import _get_semaphore, _get_bot_semaphore

        # Global semaphore respects config
        with patch("app.services.attachment_summarizer.settings") as mock_settings:
            mock_settings.ATTACHMENT_VISION_CONCURRENCY = 2

            # Reset global semaphore
            import app.services.attachment_summarizer as mod
            mod._semaphore = None
            sem = _get_semaphore()
            assert sem._value == 2

        # Bot-specific semaphore with different concurrency
        with patch("app.services.attachment_summarizer.settings") as mock_settings:
            mock_settings.ATTACHMENT_VISION_CONCURRENCY = 3
            bot_sem = _get_bot_semaphore(5)
            assert bot_sem._value == 5

    async def test_bot_semaphore_reuses_global(self):
        """When bot concurrency matches global, reuses global semaphore."""
        import app.services.attachment_summarizer as mod
        from app.services.attachment_summarizer import _get_bot_semaphore

        with patch("app.services.attachment_summarizer.settings") as mock_settings:
            mock_settings.ATTACHMENT_VISION_CONCURRENCY = 3
            mod._semaphore = None

            sem = _get_bot_semaphore(3)
            # Should be the same as _get_semaphore()
            global_sem = mod._get_semaphore()
            assert sem is global_sem


# ---------------------------------------------------------------------------
# test_bot_config_overrides_in_summarizer
# ---------------------------------------------------------------------------

class TestBotConfigOverridesInSummarizer:
    async def test_bot_model_override(self):
        """Bot-level model override is used for summarization."""
        att = MagicMock()
        att.id = uuid.uuid4()
        att.type = "image"
        att.url = "https://cdn.example.com/img.jpg"
        att.file_data = None
        att.described_at = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A cat photo."

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.attachment_summarizer.async_session") as mock_session_factory,
            patch("app.services.attachment_summarizer.settings") as mock_settings,
            patch("app.services.attachment_summarizer._get_semaphore", return_value=asyncio.Semaphore(3)),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
        ):
            mock_settings.ATTACHMENT_SUMMARY_MODEL = "gemini/gemini-2.5-flash"
            mock_settings.ATTACHMENT_VISION_CONCURRENCY = 3
            mock_settings.ATTACHMENT_TEXT_MAX_CHARS = 40000

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=att)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachment_summarizer import summarize_attachment
            await summarize_attachment(att.id, bot_overrides={"model": "openai/gpt-4o"})

            # Check model used
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["model"] == "openai/gpt-4o"

    async def test_bot_text_max_chars_override(self):
        """Bot-level text_max_chars override truncates at correct length."""
        att = MagicMock()
        att.id = uuid.uuid4()
        att.type = "text"
        att.url = "https://cdn.example.com/doc.txt"
        att.file_data = None
        att.described_at = None

        long_content = "x" * 20000

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary."

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_httpx_resp = MagicMock()
        mock_httpx_resp.text = long_content
        mock_httpx_resp.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get = AsyncMock(return_value=mock_httpx_resp)
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.attachment_summarizer.async_session") as mock_session_factory,
            patch("app.services.attachment_summarizer.settings") as mock_settings,
            patch("app.services.attachment_summarizer._get_semaphore", return_value=asyncio.Semaphore(3)),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("httpx.AsyncClient", return_value=mock_httpx_client),
        ):
            mock_settings.ATTACHMENT_SUMMARY_MODEL = "gemini/gemini-2.5-flash"
            mock_settings.ATTACHMENT_VISION_CONCURRENCY = 3
            mock_settings.ATTACHMENT_TEXT_MAX_CHARS = 40000

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=att)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachment_summarizer import summarize_attachment
            await summarize_attachment(att.id, bot_overrides={"text_max_chars": 5000})

            # Verify the text was truncated at bot-level limit
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            msg_content = call_kwargs["messages"][0]["content"]
            # The text content should have been truncated
            assert len(msg_content) < 20000
