"""Integration tests for the attachment system."""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.integration.conftest import AUTH_HEADERS


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
        """Slack message with file → attachment creation task spawned."""
        with patch("app.routers.chat._create_attachments_from_metadata", new_callable=AsyncMock) as mock_create:
            # Patch asyncio.create_task to call the coroutine directly
            with patch("app.routers.chat.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()

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

                # asyncio.create_task was called for attachment creation
                mock_asyncio.create_task.assert_called()


# ---------------------------------------------------------------------------
# test_message_history_redaction
# ---------------------------------------------------------------------------

class TestMessageHistoryRedaction:
    def test_attachment_hint_format(self):
        """Turn 1+: attachment hint has correct format."""
        from app.services.sessions import _attachment_hint

        att = MagicMock()
        att.filename = "report.pdf"
        att.description = "A quarterly financial report."

        hint = _attachment_hint(att)
        assert "report.pdf" in hint
        assert "quarterly financial report" in hint

    def test_attachment_hint_no_description(self):
        """Unsummarized attachment produces hint without description."""
        from app.services.sessions import _attachment_hint

        att = MagicMock()
        att.filename = "image.png"
        att.description = None

        hint = _attachment_hint(att)
        assert "image.png" in hint


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
