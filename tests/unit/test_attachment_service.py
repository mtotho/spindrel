"""Unit tests for the attachment service and summarizer."""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_attachment(**overrides):
    """Create a minimal fake Attachment object."""
    defaults = dict(
        id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        type="image",
        url="https://example.com/img.png",
        filename="screenshot.png",
        mime_type="image/png",
        size_bytes=12345,
        file_data=b"fake-image-bytes",
        posted_by="slack:U123",
        source_integration="slack",
        description=None,
        description_model=None,
        described_at=None,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


# ---------------------------------------------------------------------------
# test_create_attachment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCreateAttachment:
    async def test_create_attachment(self):
        """Creates attachment, fires async summarization."""
        from app.services.attachments import _infer_type

        fake_att = _fake_attachment()
        msg_id = uuid.uuid4()
        channel_id = uuid.uuid4()

        with (
            patch("app.services.attachments.async_session") as mock_session_factory,
            patch("app.services.attachments.settings") as mock_settings,
            patch("app.services.attachment_summarizer.summarize_attachment", new_callable=AsyncMock) as mock_summarize,
        ):
            mock_settings.ATTACHMENT_SUMMARY_ENABLED = True
            mock_db = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachments import create_attachment

            with patch("asyncio.create_task") as mock_task:
                att = await create_attachment(
                    message_id=msg_id,
                    channel_id=channel_id,
                    url="https://example.com/img.png",
                    filename="test.png",
                    mime_type="image/png",
                    size_bytes=1024,
                    posted_by="user:1",
                    source_integration="web",
                )

                # Attachment was persisted
                mock_db.add.assert_called_once()
                mock_db.commit.assert_called_once()

                # Async summarization was kicked off
                mock_task.assert_called_once()

    async def test_create_attachment_disabled(self):
        """When summarization is disabled, no task is created."""
        with (
            patch("app.services.attachments.async_session") as mock_session_factory,
            patch("app.services.attachments.settings") as mock_settings,
            patch("app.services.attachments._get_bot_attachment_config", new_callable=AsyncMock, return_value={}),
        ):
            mock_settings.ATTACHMENT_SUMMARY_ENABLED = False
            mock_db = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachments import create_attachment

            with patch("asyncio.create_task") as mock_task:
                await create_attachment(
                    message_id=uuid.uuid4(),
                    channel_id=None,
                    url="https://example.com/doc.txt",
                    filename="doc.txt",
                    mime_type="text/plain",
                    size_bytes=500,
                    posted_by=None,
                    source_integration="web",
                )
                mock_task.assert_not_called()

    async def test_create_attachment_bot_override_disabled(self):
        """Bot-level config can disable summarization even when global is enabled."""
        with (
            patch("app.services.attachments.async_session") as mock_session_factory,
            patch("app.services.attachments.settings") as mock_settings,
            patch(
                "app.services.attachments._get_bot_attachment_config",
                new_callable=AsyncMock,
                return_value={"enabled": False},
            ),
        ):
            mock_settings.ATTACHMENT_SUMMARY_ENABLED = True
            mock_db = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachments import create_attachment

            with patch("asyncio.create_task") as mock_task:
                await create_attachment(
                    message_id=uuid.uuid4(),
                    channel_id=None,
                    url="https://example.com/img.png",
                    filename="test.png",
                    mime_type="image/png",
                    size_bytes=1024,
                    posted_by=None,
                    source_integration="web",
                    bot_id="my-bot",
                )
                mock_task.assert_not_called()


# ---------------------------------------------------------------------------
# test_summarize_image_attachment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSummarizeImageAttachment:
    async def test_summarize_image_attachment(self):
        """Vision model call stores description."""
        att = _fake_attachment(type="image", url="https://cdn.example.com/img.jpg")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A screenshot of a dashboard showing metrics."

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
            await summarize_attachment(att.id)

            # Vision model was called with image content
            mock_client.chat.completions.create.assert_called_once()
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
            content_parts = messages[0]["content"]
            assert any(p.get("type") == "image_url" for p in content_parts)

            # Description was persisted
            mock_db.execute.assert_called_once()
            mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# test_summarize_text_attachment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSummarizeTextAttachment:
    async def test_summarize_text_attachment(self):
        """LLM reads text, stores summary."""
        att = _fake_attachment(type="text", url="https://cdn.example.com/readme.md")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A README file describing installation steps."

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_httpx_resp = MagicMock()
        mock_httpx_resp.text = "# README\nInstall with pip install mypackage."
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
            await summarize_attachment(att.id)

            # LLM was called
            mock_client.chat.completions.create.assert_called_once()

            # Description was persisted
            mock_db.execute.assert_called_once()
            mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# test_summarization_failure_graceful
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSummarizationFailureGraceful:
    async def test_summarization_failure_graceful(self):
        """Summarization fails, doesn't crash, attachment left for retry."""
        att = _fake_attachment(type="image", url="https://cdn.example.com/img.jpg")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

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

            # Should not raise
            await summarize_attachment(att.id)

            # described_at was NOT set — attachment remains unsummarized for sweep retry
            # (no commit means no description stored)
            mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# test_get_attachment_tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetAttachmentTool:
    async def test_get_attachment_tool(self):
        """Agent tool fetches by ID, returns metadata."""
        att = _fake_attachment(
            description="A photo of a cat",
            description_model="gemini/gemini-2.5-flash",
            described_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )

        with patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock, return_value=att):
            from app.tools.local.attachments import get_attachment
            result = await get_attachment(str(att.id))
            data = json.loads(result)
            assert data["id"] == str(att.id)
            assert data["filename"] == att.filename
            assert data["type"] == att.type
            assert data["description"] == "A photo of a cat"
            assert data["description_model"] == "gemini/gemini-2.5-flash"

    async def test_get_attachment_tool_not_found(self):
        """Returns error when attachment doesn't exist."""
        with patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock, return_value=None):
            from app.tools.local.attachments import get_attachment
            result = await get_attachment(str(uuid.uuid4()))
            data = json.loads(result)
            assert "error" in data

    async def test_get_attachment_tool_invalid_uuid(self):
        """Returns error for invalid UUID."""
        from app.tools.local.attachments import get_attachment
        result = await get_attachment("not-a-uuid")
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# test_infer_type
# ---------------------------------------------------------------------------

class TestInferType:
    def test_image_types(self):
        from app.services.attachments import _infer_type
        assert _infer_type("image/png") == "image"
        assert _infer_type("image/jpeg") == "image"

    def test_text_types(self):
        from app.services.attachments import _infer_type
        assert _infer_type("text/plain") == "text"
        assert _infer_type("application/json") == "text"
        assert _infer_type("text/x-python") == "text"

    def test_audio_video(self):
        from app.services.attachments import _infer_type
        assert _infer_type("audio/mpeg") == "audio"
        assert _infer_type("video/mp4") == "video"

    def test_fallback(self):
        from app.services.attachments import _infer_type
        assert _infer_type("application/pdf") == "file"


# ---------------------------------------------------------------------------
# test_bot_attachment_config_lookup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBotAttachmentConfig:
    async def test_returns_overrides(self):
        """Returns non-None bot overrides."""
        mock_row = MagicMock()
        mock_row.attachment_summarization_enabled = False
        mock_row.attachment_summary_model = "openai/gpt-4o"
        mock_row.attachment_text_max_chars = 5000
        mock_row.attachment_vision_concurrency = 1

        with patch("app.services.attachments.async_session") as mock_session_factory:
            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=mock_row)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachments import _get_bot_attachment_config
            config = await _get_bot_attachment_config("my-bot")
            assert config["enabled"] is False
            assert config["model"] == "openai/gpt-4o"
            assert config["text_max_chars"] == 5000
            assert config["vision_concurrency"] == 1

    async def test_returns_empty_for_no_bot(self):
        """Returns empty dict when no bot_id provided."""
        from app.services.attachments import _get_bot_attachment_config
        config = await _get_bot_attachment_config(None)
        assert config == {}

    async def test_returns_empty_when_bot_not_found(self):
        """Returns empty dict when bot doesn't exist."""
        with patch("app.services.attachments.async_session") as mock_session_factory:
            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=None)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachments import _get_bot_attachment_config
            config = await _get_bot_attachment_config("nonexistent")
            assert config == {}

    async def test_empty_model_falls_back_to_default(self):
        """When ATTACHMENT_SUMMARY_MODEL is empty, falls back to DEFAULT_MODEL."""
        att = _fake_attachment(type="image", url="https://cdn.example.com/img.jpg")

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
            mock_settings.ATTACHMENT_SUMMARY_MODEL = ""
            mock_settings.DEFAULT_MODEL = "gemma3:4b"
            mock_settings.ATTACHMENT_VISION_CONCURRENCY = 3
            mock_settings.ATTACHMENT_TEXT_MAX_CHARS = 40000

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=att)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachment_summarizer import summarize_attachment
            await summarize_attachment(att.id)

            # LLM was called with the fallback model
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["model"] == "gemma3:4b"

    async def test_no_model_at_all_skips_silently(self):
        """When both ATTACHMENT_SUMMARY_MODEL and DEFAULT_MODEL are empty, skip."""
        att = _fake_attachment(type="image", url="https://cdn.example.com/img.jpg")

        mock_client = AsyncMock()

        with (
            patch("app.services.attachment_summarizer.async_session") as mock_session_factory,
            patch("app.services.attachment_summarizer.settings") as mock_settings,
            patch("app.services.attachment_summarizer._get_semaphore", return_value=asyncio.Semaphore(3)),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
        ):
            mock_settings.ATTACHMENT_SUMMARY_MODEL = ""
            mock_settings.DEFAULT_MODEL = ""
            mock_settings.ATTACHMENT_VISION_CONCURRENCY = 3
            mock_settings.ATTACHMENT_TEXT_MAX_CHARS = 40000

            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=att)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachment_summarizer import summarize_attachment
            await summarize_attachment(att.id)

            # LLM was NOT called — no model available
            mock_client.chat.completions.create.assert_not_called()

    async def test_partial_overrides(self):
        """Only non-None fields are returned."""
        mock_row = MagicMock()
        mock_row.attachment_summarization_enabled = True
        mock_row.attachment_summary_model = None
        mock_row.attachment_summary_model_provider_id = None
        mock_row.attachment_text_max_chars = None
        mock_row.attachment_vision_concurrency = 5

        with patch("app.services.attachments.async_session") as mock_session_factory:
            mock_db = AsyncMock()
            mock_db.get = AsyncMock(return_value=mock_row)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.services.attachments import _get_bot_attachment_config
            config = await _get_bot_attachment_config("partial-bot")
            assert config == {"enabled": True, "vision_concurrency": 5}
