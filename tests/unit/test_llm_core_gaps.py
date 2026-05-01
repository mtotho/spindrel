"""Phase B.3 targeted sweep of app/agent/llm.py core gaps.

Covers audit entries:
  #14  get_model_cooldown / fallback chain — module-dict cooldown state
  #20  _fold_system_messages — role alternation + tool_calls preservation
  #21  _describe_image_data — vision model fallback on error
  #19  _summarize_tool_result — truncation edges + fallback on exception
  #2   _strip_images_with_descriptions — DB lookup + vision fallback
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.llm import (
    _IMAGE_STRIPPED_NOTE,
    _describe_image_data,
    _fold_system_messages,
    _model_cooldowns,
    _strip_images_with_descriptions,
    _summarize_tool_result,
    clear_model_cooldown,
    get_active_cooldowns,
    get_model_cooldown,
    set_model_cooldown,
)


# ---------------------------------------------------------------------------
# Shared: ensure cooldown dict is clean between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cooldowns():
    _model_cooldowns.clear()
    yield
    _model_cooldowns.clear()


def _future(seconds: int = 300) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _past(seconds: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


# ===========================================================================
# #14 — get_model_cooldown / fallback chain
# ===========================================================================

class TestModelCooldown:
    def test_get_returns_none_when_empty(self):
        assert get_model_cooldown("gpt-4") is None

    def test_get_returns_fallback_when_active(self):
        _model_cooldowns["gpt-4"] = (_future(), "gpt-3.5", "openai")
        result = get_model_cooldown("gpt-4")
        assert result == ("gpt-3.5", "openai")

    def test_get_returns_none_when_expired_and_cleans_up(self):
        _model_cooldowns["gpt-4"] = (_past(), "gpt-3.5", "openai")
        result = get_model_cooldown("gpt-4")
        assert result is None
        assert "gpt-4" not in _model_cooldowns

    def test_get_provider_id_none_allowed(self):
        _model_cooldowns["claude-3"] = (_future(), "claude-2", None)
        result = get_model_cooldown("claude-3")
        assert result == ("claude-2", None)

    def test_set_skips_when_cooldown_seconds_zero(self):
        mock_settings = MagicMock()
        mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 0
        with patch("app.agent.llm.settings", mock_settings):
            set_model_cooldown("gpt-4", "gpt-3.5")
        assert "gpt-4" not in _model_cooldowns

    def test_set_records_entry(self):
        mock_settings = MagicMock()
        mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 300
        with patch("app.agent.llm.settings", mock_settings):
            set_model_cooldown("gpt-4", "gpt-3.5", "openai")
        assert "gpt-4" in _model_cooldowns
        _, fallback, provider = _model_cooldowns["gpt-4"]
        assert fallback == "gpt-3.5"
        assert provider == "openai"

    def test_set_expiry_is_in_the_future(self):
        mock_settings = MagicMock()
        mock_settings.LLM_FALLBACK_COOLDOWN_SECONDS = 300
        with patch("app.agent.llm.settings", mock_settings):
            set_model_cooldown("gpt-4", "gpt-3.5")
        expires, _, _ = _model_cooldowns["gpt-4"]
        assert expires > datetime.now(timezone.utc)

    def test_clear_returns_true_when_found(self):
        _model_cooldowns["gpt-4"] = (_future(), "gpt-3.5", None)
        result = clear_model_cooldown("gpt-4")
        assert result is True
        assert "gpt-4" not in _model_cooldowns

    def test_clear_returns_false_when_missing(self):
        result = clear_model_cooldown("nonexistent")
        assert result is False

    def test_get_active_cooldowns_returns_active(self):
        _model_cooldowns["active-model"] = (_future(600), "fallback-a", "provider-x")
        result = get_active_cooldowns()
        assert len(result) == 1
        entry = result[0]
        assert entry["model"] == "active-model"
        assert entry["fallback_model"] == "fallback-a"
        assert entry["fallback_provider"] == "provider-x"
        assert entry["remaining_seconds"] > 0

    def test_get_active_cooldowns_prunes_expired(self):
        _model_cooldowns["expired-model"] = (_past(), "old-fallback", None)
        _model_cooldowns["active-model"] = (_future(), "new-fallback", None)
        result = get_active_cooldowns()
        returned_models = [e["model"] for e in result]
        assert "active-model" in returned_models
        assert "expired-model" not in returned_models
        assert "expired-model" not in _model_cooldowns

    def test_get_active_cooldowns_empty(self):
        assert get_active_cooldowns() == []


# ===========================================================================
# #20 — _fold_system_messages role alternation
# ===========================================================================

class TestFoldSystemMessages:
    def test_empty_list_returns_empty(self):
        assert _fold_system_messages([]) == []

    def test_no_system_messages_pass_through_unchanged(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = _fold_system_messages(msgs)
        assert result == msgs

    def test_single_system_becomes_first_user_message(self):
        # System folds to user, which then merges with the following user msg.
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = _fold_system_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "You are helpful." in result[0]["content"]
        assert "Hello" in result[0]["content"]

    def test_multiple_system_messages_joined_with_separator(self):
        msgs = [
            {"role": "system", "content": "Part A"},
            {"role": "system", "content": "Part B"},
            {"role": "user", "content": "Hello"},
        ]
        result = _fold_system_messages(msgs)
        combined = result[0]["content"]
        assert "Part A" in combined
        assert "Part B" in combined
        assert "\n\n---\n\n" in combined

    def test_system_list_content_flattened_to_string(self):
        msgs = [
            {"role": "system", "content": [{"type": "text", "text": "System info"}]},
            {"role": "user", "content": "Hello"},
        ]
        result = _fold_system_messages(msgs)
        assert result[0]["role"] == "user"
        assert "System info" in result[0]["content"]

    def test_empty_system_content_skipped(self):
        msgs = [
            {"role": "system", "content": ""},
            {"role": "user", "content": "Hello"},
        ]
        result = _fold_system_messages(msgs)
        # No system folded in, so just the user message (no extra user msg prepended)
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello"}

    def test_none_system_content_skipped(self):
        msgs = [
            {"role": "system", "content": None},
            {"role": "user", "content": "Hello"},
        ]
        result = _fold_system_messages(msgs)
        assert len(result) == 1

    def test_adjacent_user_messages_merged(self):
        # System → user (injected) then another user message creates consecutive users
        msgs = [
            {"role": "system", "content": "Instructions"},
            {"role": "user", "content": "First"},
            {"role": "user", "content": "Second"},
        ]
        result = _fold_system_messages(msgs)
        # System becomes first user; then two user messages exist -> merged into one
        user_msgs = [m for m in result if m["role"] == "user"]
        # The system and first user message must have been merged
        assert len(user_msgs) <= 2
        # All content must be present
        all_content = " ".join(m["content"] for m in user_msgs)
        assert "Instructions" in all_content
        assert "First" in all_content
        assert "Second" in all_content

    def test_adjacent_assistant_messages_merged(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "First response"},
            {"role": "assistant", "content": "Second response"},
        ]
        result = _fold_system_messages(msgs)
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert "First response" in assistant_msgs[0]["content"]
        assert "Second response" in assistant_msgs[0]["content"]

    def test_adjacent_assistant_messages_preserve_tool_calls(self):
        tc1 = {"id": "tc1", "type": "function", "function": {"name": "tool_a", "arguments": "{}"}}
        tc2 = {"id": "tc2", "type": "function", "function": {"name": "tool_b", "arguments": "{}"}}
        msgs = [
            {"role": "user", "content": "Do stuff"},
            {"role": "assistant", "content": "Calling A", "tool_calls": [tc1]},
            {"role": "assistant", "content": "Calling B", "tool_calls": [tc2]},
        ]
        result = _fold_system_messages(msgs)
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        merged_tc = assistant_msgs[0].get("tool_calls", [])
        ids = [tc["id"] for tc in merged_tc]
        assert "tc1" in ids
        assert "tc2" in ids

    def test_tool_messages_never_merged(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "tool", "content": "result A", "tool_call_id": "tc1"},
            {"role": "tool", "content": "result B", "tool_call_id": "tc2"},
        ]
        result = _fold_system_messages(msgs)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 2

    def test_complex_list_content_not_merged_with_adjacent(self):
        msgs = [
            {"role": "user", "content": "Text only"},
            {"role": "user", "content": [{"type": "text", "text": "Multipart"}]},
        ]
        result = _fold_system_messages(msgs)
        user_msgs = [m for m in result if m["role"] == "user"]
        # Should not merge: prev is str, cur is list
        assert len(user_msgs) == 2


# ===========================================================================
# #21 — _describe_image_data vision model fallback
# ===========================================================================

class TestDescribeImageData:
    @pytest.mark.asyncio
    async def test_happy_path_returns_description(self):
        mock_summarize = AsyncMock(return_value="A cat sitting on a mat")
        mock_settings = MagicMock()
        mock_settings.ATTACHMENT_SUMMARY_MODEL = "llava"
        mock_settings.ATTACHMENT_SUMMARY_MODEL_PROVIDER_ID = ""
        with patch("app.services.attachment_summarizer._summarize_image", mock_summarize), \
             patch("app.agent.llm.settings", mock_settings):
            result = await _describe_image_data("data:image/png;base64,abc123")
        assert result == "A cat sitting on a mat"

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        mock_summarize = AsyncMock(side_effect=RuntimeError("Vision model unavailable"))
        mock_settings = MagicMock()
        mock_settings.ATTACHMENT_SUMMARY_MODEL = "llava"
        mock_settings.ATTACHMENT_SUMMARY_MODEL_PROVIDER_ID = ""
        with patch("app.services.attachment_summarizer._summarize_image", mock_summarize), \
             patch("app.agent.llm.settings", mock_settings):
            result = await _describe_image_data("data:image/png;base64,abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_model_returns_none_without_call(self):
        mock_summarize = AsyncMock(return_value="description")
        mock_settings = MagicMock()
        mock_settings.ATTACHMENT_SUMMARY_MODEL = ""
        mock_settings.ATTACHMENT_SUMMARY_MODEL_PROVIDER_ID = ""
        with patch("app.services.attachment_summarizer._summarize_image", mock_summarize), \
             patch("app.agent.llm.settings", mock_settings):
            result = await _describe_image_data("data:image/png;base64,xyz")
        assert result is None
        mock_summarize.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_model_and_provider_from_settings(self):
        mock_summarize = AsyncMock(return_value="description")
        mock_settings = MagicMock()
        mock_settings.ATTACHMENT_SUMMARY_MODEL = "llava-1.5"
        mock_settings.ATTACHMENT_SUMMARY_MODEL_PROVIDER_ID = "ollama"
        with patch("app.services.attachment_summarizer._summarize_image", mock_summarize), \
             patch("app.agent.llm.settings", mock_settings):
            await _describe_image_data("data:image/png;base64,xyz")
        mock_summarize.assert_awaited_once_with(
            url="data:image/png;base64,xyz",
            model="llava-1.5",
            provider_id="ollama",
        )

    @pytest.mark.asyncio
    async def test_empty_provider_id_passes_none(self):
        mock_summarize = AsyncMock(return_value="desc")
        mock_settings = MagicMock()
        mock_settings.ATTACHMENT_SUMMARY_MODEL = "llava"
        mock_settings.ATTACHMENT_SUMMARY_MODEL_PROVIDER_ID = ""
        with patch("app.services.attachment_summarizer._summarize_image", mock_summarize), \
             patch("app.agent.llm.settings", mock_settings):
            await _describe_image_data("data:image/png;base64,xyz")
        _, kwargs = mock_summarize.call_args
        assert kwargs["provider_id"] is None


# ===========================================================================
# #19 — _summarize_tool_result truncation + fallback
# ===========================================================================

def _mock_llm_client(response_content: str | None = "Short summary"):
    choice = MagicMock()
    choice.message.content = response_content
    resp = MagicMock()
    resp.choices = [choice]
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


class TestSummarizeToolResult:
    @pytest.mark.asyncio
    async def test_short_content_uses_full_text(self):
        short = "x" * 100
        client = _mock_llm_client("Summary")
        with patch("app.services.providers.get_llm_client", return_value=client):
            await _summarize_tool_result("my_tool", short, "gpt-4", 500)
        prompt_arg = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert short in prompt_arg
        assert "[... " not in prompt_arg

    @pytest.mark.asyncio
    async def test_long_content_truncated_with_omission_marker(self):
        head = "H" * 8000
        middle = "M" * 5000
        tail = "T" * 4000
        long_content = head + middle + tail
        client = _mock_llm_client("Big summary")
        with patch("app.services.providers.get_llm_client", return_value=client):
            await _summarize_tool_result("big_tool", long_content, "gpt-4", 500)
        prompt_arg = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "[... " in prompt_arg
        assert "chars omitted" in prompt_arg

    @pytest.mark.asyncio
    async def test_returns_summary_wrapped_with_char_count(self):
        content = "Tool output line 1\nTool output line 2"
        client = _mock_llm_client("Concise summary")
        with patch("app.services.providers.get_llm_client", return_value=client):
            result = await _summarize_tool_result("tool", content, "gpt-4", 500)
        assert result.startswith(f"[summarized from {len(content):,} chars]")
        assert "Concise summary" in result

    @pytest.mark.asyncio
    async def test_exception_returns_original_content(self):
        content = "Raw tool output"
        client = AsyncMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("LLM down"))
        with patch("app.services.providers.get_llm_client", return_value=client):
            result = await _summarize_tool_result("tool", content, "gpt-4", 500)
        assert result == content

    @pytest.mark.asyncio
    async def test_none_response_content_falls_back_to_original(self):
        content = "Original output"
        client = _mock_llm_client(response_content=None)
        with patch("app.services.providers.get_llm_client", return_value=client):
            result = await _summarize_tool_result("tool", content, "gpt-4", 500)
        # content=None means `resp.choices[0].message.content or content` → original
        assert result.endswith(content) or result == f"[summarized from {len(content):,} chars]\n" + content

    @pytest.mark.asyncio
    async def test_provider_id_forwarded_to_client(self):
        content = "output"
        client = _mock_llm_client()
        with patch("app.services.providers.get_llm_client", return_value=client) as mock_get:
            await _summarize_tool_result("tool", content, "gpt-4", 500, provider_id="ollama")
        mock_get.assert_called_once_with("ollama")


# ===========================================================================
# #2 — _strip_images_with_descriptions DB lookup + vision fallback
# ===========================================================================

def _image_msg(*image_urls: str, text: str = "See attached", attachment_id: str | None = None) -> dict:
    """Build a user message containing image_url parts and optional attachment hint."""
    hint = f'<attachment id="{attachment_id}"/>' if attachment_id else ""
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"{hint}{text}"},
            *[{"type": "image_url", "image_url": {"url": u}} for u in image_urls],
        ],
    }


def _make_attachment(description: str | None) -> MagicMock:
    att = MagicMock()
    att.description = description
    return att


class TestStripImagesWithDescriptions:
    @pytest.mark.asyncio
    async def test_non_list_content_unchanged(self):
        msgs = [{"role": "user", "content": "Plain text"}]
        result = await _strip_images_with_descriptions(msgs)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_list_content_without_images_unchanged(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "No images here"}]}]
        result = await _strip_images_with_descriptions(msgs)
        assert result == msgs

    @pytest.mark.asyncio
    async def test_image_with_db_description_uses_it(self):
        att_id = str(uuid.uuid4())
        msg = _image_msg("data:image/png;base64,abc", text="See", attachment_id=att_id)
        att = _make_attachment("A sunset photo")
        with patch("app.services.attachments.get_attachment_by_id", AsyncMock(return_value=att)):
            result = await _strip_images_with_descriptions([msg])
        content = result[0]["content"]
        text_parts = [p for p in content if p.get("type") == "text"]
        desc_part = next(p for p in text_parts if "Image description" in p["text"])
        assert "A sunset photo" in desc_part["text"]
        assert not any(p.get("type") == "image_url" for p in content)

    @pytest.mark.asyncio
    async def test_image_attachment_not_found_falls_back_to_vision(self):
        att_id = str(uuid.uuid4())
        msg = _image_msg("data:image/png;base64,abc", attachment_id=att_id)
        with patch("app.services.attachments.get_attachment_by_id", AsyncMock(return_value=None)), \
             patch("app.agent.llm._describe_image_data", AsyncMock(return_value="Vision desc")):
            result = await _strip_images_with_descriptions([msg])
        content = result[0]["content"]
        text_parts = [p["text"] for p in content if p.get("type") == "text"]
        assert any("Vision desc" in t for t in text_parts)

    @pytest.mark.asyncio
    async def test_image_attachment_lookup_raises_falls_back_to_vision(self):
        att_id = str(uuid.uuid4())
        msg = _image_msg("data:image/png;base64,abc", attachment_id=att_id)
        with patch("app.services.attachments.get_attachment_by_id", AsyncMock(side_effect=Exception("DB error"))), \
             patch("app.agent.llm._describe_image_data", AsyncMock(return_value="Vision desc")):
            result = await _strip_images_with_descriptions([msg])
        content = result[0]["content"]
        texts = [p["text"] for p in content if p.get("type") == "text"]
        assert any("Vision desc" in t for t in texts)

    @pytest.mark.asyncio
    async def test_image_without_attachment_id_goes_directly_to_vision(self):
        msg = _image_msg("data:image/png;base64,abc")  # no attachment_id
        with patch("app.agent.llm._describe_image_data", AsyncMock(return_value="Vision says: dog")):
            result = await _strip_images_with_descriptions([msg])
        content = result[0]["content"]
        texts = [p["text"] for p in content if p.get("type") == "text"]
        assert any("Vision says: dog" in t for t in texts)

    @pytest.mark.asyncio
    async def test_all_fallbacks_fail_uses_stripped_note(self):
        att_id = str(uuid.uuid4())
        msg = _image_msg("data:image/png;base64,abc", attachment_id=att_id)
        with patch("app.services.attachments.get_attachment_by_id", AsyncMock(return_value=None)), \
             patch("app.agent.llm._describe_image_data", AsyncMock(return_value=None)):
            result = await _strip_images_with_descriptions([msg])
        content = result[0]["content"]
        texts = [p["text"] for p in content if p.get("type") == "text"]
        assert any(_IMAGE_STRIPPED_NOTE in t for t in texts)

    @pytest.mark.asyncio
    async def test_description_format_differs_from_stripped_note(self):
        msg = _image_msg("data:image/png;base64,abc")
        with patch("app.agent.llm._describe_image_data", AsyncMock(return_value="A red barn")):
            result = await _strip_images_with_descriptions([msg])
        content = result[0]["content"]
        texts = [p["text"] for p in content if p.get("type") == "text"]
        assert any("[Image description: A red barn]" in t for t in texts)
        assert not any(t == _IMAGE_STRIPPED_NOTE for t in texts)

    @pytest.mark.asyncio
    async def test_multiple_images_in_one_message(self):
        att_id = str(uuid.uuid4())
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": f'<attachment id="{att_id}"/>See these'},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,first"}},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,second"}},
            ],
        }
        att = _make_attachment("First image: sunrise")
        with patch("app.services.attachments.get_attachment_by_id", AsyncMock(return_value=att)), \
             patch("app.agent.llm._describe_image_data", AsyncMock(return_value="Second image: sunset")):
            result = await _strip_images_with_descriptions([msg])
        content = result[0]["content"]
        assert not any(p.get("type") == "image_url" for p in content)
        texts = [p["text"] for p in content if p.get("type") == "text"]
        all_text = " ".join(texts)
        assert "First image: sunrise" in all_text
        assert "Second image: sunset" in all_text

    @pytest.mark.asyncio
    async def test_non_image_messages_passed_through(self):
        msgs = [
            {"role": "user", "content": "First"},
            _image_msg("data:image/png;base64,abc"),
            {"role": "assistant", "content": "Response"},
        ]
        with patch("app.agent.llm._describe_image_data", AsyncMock(return_value="desc")):
            result = await _strip_images_with_descriptions(msgs)
        assert result[0] == msgs[0]
        assert result[2] == msgs[2]
