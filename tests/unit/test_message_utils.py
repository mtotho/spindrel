"""Unit tests for app.agent.message_utils — pure sync helpers."""
import json

from app.agent.message_utils import (
    _build_audio_user_message,
    _build_user_message_content,
    _event_with_compaction_tag,
    _extract_client_actions,
    _extract_transcript,
    _merge_tool_schemas,
)


# ---------------------------------------------------------------------------
# _build_user_message_content
# ---------------------------------------------------------------------------

class TestBuildUserMessageContent:
    def test_plain_text_no_attachments(self):
        assert _build_user_message_content("hello", None) == "hello"

    def test_plain_text_empty_attachments(self):
        assert _build_user_message_content("hello", []) == "hello"

    def test_multimodal_with_image(self):
        att = [{"type": "image", "content": "abc123", "mime_type": "image/png"}]
        result = _build_user_message_content("look at this", att)
        assert isinstance(result, list)
        assert result[0] == {"type": "text", "text": "look at this"}
        assert result[1]["type"] == "image_url"
        assert result[1]["image_url"]["url"] == "data:image/png;base64,abc123"

    def test_skips_non_image_attachments(self):
        att = [{"type": "file", "content": "abc"}]
        result = _build_user_message_content("hi", att)
        assert isinstance(result, list)
        # Only the text part, no image parts
        assert len(result) == 1
        assert result[0]["type"] == "text"

    def test_skips_empty_content_attachment(self):
        att = [{"type": "image", "content": "", "mime_type": "image/png"}]
        result = _build_user_message_content("hi", att)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_no_text_placeholder(self):
        att = [{"type": "image", "content": "abc123"}]
        result = _build_user_message_content("", att)
        assert isinstance(result, list)
        assert result[0]["text"] == "(no text)"

    def test_default_mime_type(self):
        att = [{"type": "image", "content": "abc123"}]
        result = _build_user_message_content("hi", att)
        assert "image/jpeg" in result[1]["image_url"]["url"]

    def test_surfaces_attachment_id_when_present(self):
        """Fresh uploads carry their DB attachment_id so the LLM can pass
        it to tools like ``generate_image(attachment_ids=...)`` directly.

        Without this, a model asked to edit an image it was just sent
        will hallucinate a plausible-looking UUID (observed on Gemini
        2.5 Flash) instead of calling ``list_attachments`` first, and
        the tool call fails with ``Attachment <fake-uuid> not found``.
        """
        att = [
            {
                "type": "image",
                "content": "abc123",
                "mime_type": "image/jpeg",
                "name": "IMG_2605.jpg",
                "attachment_id": "9316416e-5a79-4ab5-a490-e403cb615749",
            }
        ]
        result = _build_user_message_content("cartoonify this", att)
        assert isinstance(result, list)
        text_part = result[0]["text"]
        assert "cartoonify this" in text_part
        assert "9316416e-5a79-4ab5-a490-e403cb615749" in text_part
        assert "IMG_2605.jpg" in text_part
        # XML tag format — less copy-prone than arrow/instruction syntax.
        assert '<attachment id="9316416e-5a79-4ab5-a490-e403cb615749"' in text_part

    def test_no_attachment_id_leaves_text_untouched(self):
        """Images without an ID (web UI pre-creation path) don't inject hints."""
        att = [{"type": "image", "content": "abc123", "mime_type": "image/png"}]
        result = _build_user_message_content("look at this", att)
        assert result[0] == {"type": "text", "text": "look at this"}


# ---------------------------------------------------------------------------
# _build_audio_user_message
# ---------------------------------------------------------------------------

class TestBuildAudioUserMessage:
    def test_basic(self):
        msg = _build_audio_user_message("audiodata", "wav")
        assert msg["role"] == "user"
        assert msg["content"][0]["type"] == "input_audio"
        assert msg["content"][0]["input_audio"]["data"] == "audiodata"
        assert msg["content"][0]["input_audio"]["format"] == "wav"

    def test_default_format(self):
        msg = _build_audio_user_message("audiodata", None)
        assert msg["content"][0]["input_audio"]["format"] == "m4a"


# ---------------------------------------------------------------------------
# _extract_transcript
# ---------------------------------------------------------------------------

class TestExtractTranscript:
    def test_no_tags(self):
        transcript, clean = _extract_transcript("Hello world")
        assert transcript == ""
        assert clean == "Hello world"

    def test_with_tags(self):
        text = "[transcript]Hello there[/transcript]\nGood to see you!"
        transcript, clean = _extract_transcript(text)
        assert transcript == "Hello there"
        assert "Good to see you!" in clean
        assert "[transcript]" not in clean

    def test_multiline_transcript(self):
        text = "[transcript]Line 1\nLine 2[/transcript] rest"
        transcript, clean = _extract_transcript(text)
        assert "Line 1\nLine 2" == transcript
        assert "[transcript]" not in clean

    def test_strips_whitespace(self):
        text = "[transcript]  spaced  [/transcript]reply"
        transcript, clean = _extract_transcript(text)
        assert transcript == "spaced"


# ---------------------------------------------------------------------------
# _extract_client_actions
# ---------------------------------------------------------------------------

class TestExtractClientActions:
    def test_finds_client_actions(self):
        messages = [
            {"role": "user", "content": "do something"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": {
                            "name": "client_action",
                            "arguments": json.dumps({"action": "tts_on"}),
                        }
                    }
                ],
            },
        ]
        actions = _extract_client_actions(messages, 0)
        assert actions == [{"action": "tts_on"}]

    def test_from_index(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "client_action", "arguments": '{"a":1}'}}
                ],
            },
            {"role": "user", "content": "next"},
        ]
        # from_index=1 should skip first message
        assert _extract_client_actions(messages, 1) == []

    def test_skips_non_assistant(self):
        messages = [
            {
                "role": "user",
                "tool_calls": [
                    {"function": {"name": "client_action", "arguments": '{"a":1}'}}
                ],
            },
        ]
        assert _extract_client_actions(messages, 0) == []

    def test_malformed_json(self):
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "client_action", "arguments": "not json"}}
                ],
            },
        ]
        assert _extract_client_actions(messages, 0) == []

    def test_missing_function_key(self):
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "123"}]},
        ]
        assert _extract_client_actions(messages, 0) == []

    def test_empty_messages(self):
        assert _extract_client_actions([], 0) == []


# ---------------------------------------------------------------------------
# _event_with_compaction_tag
# ---------------------------------------------------------------------------

class TestEventWithCompactionTag:
    def test_adds_tag_when_true(self):
        event = {"type": "response", "text": "hi"}
        result = _event_with_compaction_tag(event, True)
        assert result["compaction"] is True
        assert result["type"] == "response"

    def test_returns_unchanged_when_false(self):
        event = {"type": "response", "text": "hi"}
        result = _event_with_compaction_tag(event, False)
        assert result == event
        assert "compaction" not in result

    def test_does_not_mutate_original(self):
        event = {"type": "response"}
        result = _event_with_compaction_tag(event, True)
        assert "compaction" not in event
        assert "compaction" in result


# ---------------------------------------------------------------------------
# _merge_tool_schemas
# ---------------------------------------------------------------------------

class TestMergeToolSchemas:
    def test_deduplicates_by_name(self):
        g1 = [{"function": {"name": "foo"}}, {"function": {"name": "bar"}}]
        g2 = [{"function": {"name": "foo"}}, {"function": {"name": "baz"}}]
        result = _merge_tool_schemas(g1, g2)
        names = [t["function"]["name"] for t in result]
        assert names == ["foo", "bar", "baz"]

    def test_preserves_first_occurrence(self):
        g1 = [{"function": {"name": "foo", "v": 1}}]
        g2 = [{"function": {"name": "foo", "v": 2}}]
        result = _merge_tool_schemas(g1, g2)
        assert result[0]["function"]["v"] == 1

    def test_empty_groups(self):
        assert _merge_tool_schemas([], []) == []
        assert _merge_tool_schemas() == []

    def test_handles_missing_function_key(self):
        g = [{"no_function": True}, {"function": {"name": "ok"}}]
        result = _merge_tool_schemas(g)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "ok"

    def test_handles_missing_name(self):
        g = [{"function": {}}, {"function": {"name": "ok"}}]
        result = _merge_tool_schemas(g)
        assert len(result) == 1
