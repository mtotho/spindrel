"""Tests for the event handler."""
from unittest.mock import MagicMock, patch

from agent_client.cli.display import StreamDisplay
from agent_client.cli.events import EventHandler


def _make_handler(display=None, client=None, verbose=False):
    """Create an EventHandler with mock dependencies."""
    if display is None:
        display = MagicMock(spec=StreamDisplay)
        display.is_active = False
    if client is None:
        client = MagicMock()
    return EventHandler(display, client, verbose=verbose)


class TestAssistantText:
    def test_starts_display_and_updates(self):
        display = MagicMock(spec=StreamDisplay)
        display.is_active = False
        handler = _make_handler(display=display)
        handler.handle({"type": "assistant_text", "text": "Hello"})
        display.start.assert_called_once()
        display.update_markdown.assert_called_once_with("Hello")

    def test_updates_existing_display(self):
        display = MagicMock(spec=StreamDisplay)
        display.is_active = True
        handler = _make_handler(display=display)
        handler.handle({"type": "assistant_text", "text": "Updated"})
        display.start.assert_not_called()
        display.update_markdown.assert_called_once_with("Updated")


class TestResponse:
    def test_stores_response(self):
        handler = _make_handler()
        handler.handle({"type": "response", "text": "Final answer", "client_actions": [{"action": "x"}]})
        assert handler.response_text == "Final answer"
        assert handler.client_actions == [{"action": "x"}]

    def test_ignores_compaction_response(self):
        handler = _make_handler()
        handler.handle({"type": "response", "text": "should be ignored", "compaction": True})
        assert handler.response_text == ""


class TestTranscript:
    def test_stores_transcript(self):
        handler = _make_handler()
        handler.handle({"type": "transcript", "text": "heard text"})
        assert handler.transcript_text == "heard text"


class TestToolRequest:
    @patch("agent_client.cli.events.execute_client_tool", return_value="result")
    def test_pauses_and_resumes(self, mock_tool):
        display = MagicMock(spec=StreamDisplay)
        client = MagicMock()
        handler = _make_handler(display=display, client=client)
        handler.handle({
            "type": "tool_request",
            "tool": "shell_exec",
            "arguments": {"command": "echo hi"},
            "request_id": "req-1",
        })
        display.pause.assert_called_once()
        mock_tool.assert_called_once_with("shell_exec", {"command": "echo hi"})
        client.submit_tool_result.assert_called_once_with("req-1", "result")
        display.resume.assert_called_once()


class TestQueued:
    def test_returns_signal(self):
        handler = _make_handler()
        signal = handler.handle({"type": "queued", "task_id": "abc-123", "reason": "session busy"})
        assert signal == "queued:abc-123"


class TestCancelled:
    def test_sets_flag(self):
        handler = _make_handler()
        handler.handle({"type": "cancelled"})
        assert handler.was_cancelled is True


class TestError:
    def test_handles_detail(self):
        handler = _make_handler()
        handler.handle({"type": "error", "detail": "Something went wrong"})

    def test_handles_message(self):
        handler = _make_handler()
        handler.handle({"type": "error", "message": "Error message"})


class TestApprovalFieldNames:
    """Server sends 'tool' not 'tool_name' in approval events."""

    @patch("agent_client.cli.events.console")
    def test_approval_request_uses_tool_field(self, mock_console):
        mock_console.input.return_value = "n"
        client = MagicMock()
        handler = _make_handler(client=client)
        handler.handle({
            "type": "approval_request",
            "approval_id": "apr-1",
            "tool": "dangerous_tool",
            "arguments": {"x": 1},
        })
        client.decide_approval.assert_called_once_with("apr-1", False)

    def test_approval_resolved_uses_tool_field(self):
        handler = _make_handler()
        # Should not crash — uses "tool" field correctly
        handler.handle({"type": "approval_resolved", "tool": "some_tool", "verdict": "approved"})


class TestContextSummary:
    """Context events should be collapsed into a summary in non-verbose mode."""

    def test_context_events_accumulated(self):
        handler = _make_handler(verbose=False)
        handler.handle({"type": "skill_context", "count": 3, "chars": 1500})
        handler.handle({"type": "carapace_context", "count": 2, "chars": 800})
        assert len(handler._context_items) == 2
        assert "3 skills" in handler._context_items[0]
        assert "2 carapaces" in handler._context_items[1]

    def test_context_flushed_on_tool_start(self):
        handler = _make_handler(verbose=False)
        handler.handle({"type": "skill_context", "count": 3, "chars": 1500})
        handler.handle({"type": "tool_start", "tool": "web_search"})
        assert len(handler._context_items) == 0  # flushed

    def test_context_flushed_on_assistant_text(self):
        display = MagicMock(spec=StreamDisplay)
        display.is_active = False
        handler = _make_handler(display=display, verbose=False)
        handler.handle({"type": "carapace_context", "count": 1, "chars": 500})
        handler.handle({"type": "assistant_text", "text": "Hello"})
        assert len(handler._context_items) == 0  # flushed

    def test_verbose_mode_prints_individually(self):
        handler = _make_handler(verbose=True)
        handler.handle({"type": "skill_context", "count": 3, "chars": 1500})
        assert len(handler._context_items) == 0  # verbose mode doesn't accumulate


class TestContextEvents:
    """Context assembly events should be handled without errors."""

    def test_memory_scheme_bootstrap(self):
        handler = _make_handler()
        handler.handle({"type": "memory_scheme_bootstrap", "chars": 500})

    def test_memory_scheme_today(self):
        handler = _make_handler()
        handler.handle({"type": "memory_scheme_today_log", "chars": 300})

    def test_channel_workspace(self):
        handler = _make_handler()
        handler.handle({"type": "channel_workspace_context", "count": 4, "chars": 2000})

    def test_section_context(self):
        handler = _make_handler()
        handler.handle({"type": "section_context", "count": 5, "chars": 3000})

    def test_fs_context(self):
        handler = _make_handler()
        handler.handle({"type": "fs_context", "count": 10})

    def test_rag_rerank(self):
        handler = _make_handler()
        handler.handle({"type": "rag_rerank", "kept": 5, "total": 20})

    def test_delegation_post(self):
        handler = _make_handler()
        handler.handle({"type": "delegation_post", "bot_id": "helper"})


class TestStatusEvents:
    def test_rate_limit_wait(self):
        handler = _make_handler()
        handler.handle({"type": "rate_limit_wait", "wait_seconds": 30, "provider_id": "openai"})

    def test_fallback(self):
        handler = _make_handler()
        handler.handle({"type": "fallback", "from_model": "gpt-4", "to_model": "gpt-3.5"})

    def test_secret_warning(self):
        handler = _make_handler()
        handler.handle({"type": "secret_warning", "patterns": [{"type": "api_key"}]})

    def test_context_budget(self):
        handler = _make_handler()
        handler.handle({"type": "context_budget", "used_tokens": 50000, "budget_tokens": 128000})

    def test_compaction_start(self):
        handler = _make_handler()
        handler.handle({"type": "compaction_start"})

    def test_compaction_done(self):
        handler = _make_handler()
        handler.handle({"type": "compaction_done", "title": "Session summary"})


class TestDeprecatedEventsNotHandled:
    """Deprecated events (memory_context, knowledge_context) should be silently ignored."""

    def test_memory_context_ignored(self):
        handler = _make_handler()
        result = handler.handle({"type": "memory_context", "count": 5})
        assert result is None

    def test_knowledge_context_ignored(self):
        handler = _make_handler()
        result = handler.handle({"type": "knowledge_context", "count": 3})
        assert result is None


class TestUnknownEvent:
    def test_unknown_event_ignored(self):
        handler = _make_handler()
        result = handler.handle({"type": "totally_new_event", "data": 42})
        assert result is None
