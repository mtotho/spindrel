"""Tests for the display module."""
import uuid

from agent_client.cli.display import (
    StreamDisplay,
    _clean_for_markdown,
    format_last_active,
    make_prompt,
    short_id,
    strip_silent,
    tool_status,
)


class TestStripSilent:
    def test_no_markers(self):
        display, speak, has = strip_silent("Hello world")
        assert display == "Hello world"
        assert speak == "Hello world"
        assert has is False

    def test_with_markers(self):
        text = "Hello [nospeech]debug info[/nospeech] world"
        display, speak, has = strip_silent(text)
        assert "debug info" in display
        assert "debug info" not in speak
        assert "Hello" in speak
        assert "world" in speak
        assert has is True

    def test_multiple_markers(self):
        text = "[nospeech]a[/nospeech] visible [nospeech]b[/nospeech]"
        display, speak, has = strip_silent(text)
        assert speak == "visible"
        assert has is True

    def test_empty_nospeech(self):
        text = "before [nospeech][/nospeech] after"
        display, speak, has = strip_silent(text)
        assert "before" in speak
        assert "after" in speak
        assert has is True


class TestCleanForMarkdown:
    def test_strips_nospeech_tags(self):
        text = "Hello [nospeech]hidden[/nospeech] world"
        cleaned = _clean_for_markdown(text)
        assert "[nospeech]" not in cleaned
        assert "[/nospeech]" not in cleaned
        assert "hidden" not in cleaned
        assert "Hello" in cleaned
        assert "world" in cleaned

    def test_no_tags(self):
        text = "Hello world"
        assert _clean_for_markdown(text) == text


class TestToolStatus:
    def test_known_tool(self):
        assert tool_status("web_search") == "Searching the web"

    def test_suppressed_tool(self):
        assert tool_status("client_action") is None
        assert tool_status("shell_exec") is None

    def test_unknown_tool(self):
        assert tool_status("my_custom_tool") == "Using my_custom_tool"


class TestShortId:
    def test_uuid(self):
        sid = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        assert short_id(sid) == "123456"

    def test_string(self):
        assert short_id("abcdef-1234") == "abcdef"


class TestFormatLastActive:
    def test_empty(self):
        assert format_last_active("") == ""

    def test_invalid(self):
        result = format_last_active("not-a-date")
        assert isinstance(result, str)

    def test_recent(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = format_last_active(now.isoformat())
        assert result == "just now"


class TestMakePrompt:
    def test_basic(self):
        prompt = make_prompt("mybot", None, None)
        assert "mybot" in prompt
        assert prompt.endswith("> ")

    def test_with_channel(self):
        prompt = make_prompt("mybot", "abc123-def456", None)
        assert "mybot" in prompt
        assert "ch:abc123" in prompt

    def test_with_model(self):
        prompt = make_prompt("mybot", None, "gpt-4")
        assert "mybot" in prompt
        assert "gpt-4" in prompt

    def test_with_all(self):
        prompt = make_prompt("mybot", "abc123", "gpt-4")
        assert "mybot" in prompt
        assert "ch:abc123" in prompt
        assert "gpt-4" in prompt

    def test_no_markup_injection(self):
        """Bot IDs that look like Rich markup should not break the prompt."""
        prompt = make_prompt("bold", None, None)
        # Should contain the literal text "bold", not be interpreted as markup
        assert "bold" in prompt
        # The prompt is plain text (used with input(), not console.input())
        assert "[" in prompt  # brackets are literal


class TestStreamDisplay:
    def test_lifecycle(self):
        sd = StreamDisplay()
        assert not sd.is_active

        sd.start()
        assert sd.is_active

        sd.update_markdown("Hello **world**")
        assert sd._buffer == "Hello **world**"

        sd.pause()
        assert not sd.is_active
        assert sd._buffer == "Hello **world**"

        sd.resume()
        assert sd.is_active

        sd.finish()
        assert not sd.is_active

    def test_finish_without_start(self):
        sd = StreamDisplay()
        sd.finish()

    def test_pause_without_start(self):
        sd = StreamDisplay()
        sd.pause()

    def test_resume_without_start_is_noop(self):
        """Resume should not start Live if it was never started."""
        sd = StreamDisplay()
        sd.resume()
        assert not sd.is_active

    def test_double_finish(self):
        sd = StreamDisplay()
        sd.start()
        sd.update_markdown("test")
        sd.finish()
        sd.finish()

    def test_nospeech_tags_cleaned_in_markdown(self):
        """Nospeech tags should be stripped before markdown rendering."""
        sd = StreamDisplay()
        sd.start()
        sd.update_markdown("Hello [nospeech]hidden[/nospeech] world")
        # Buffer stores raw text
        assert sd._buffer == "Hello [nospeech]hidden[/nospeech] world"
        sd.pause()
