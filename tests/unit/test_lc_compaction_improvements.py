"""Tests for LC-inspired compaction engine improvements (Phases 1-5)."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.services.compaction import (
    _select_section_prompt,
    _parse_section_response,
    _generate_section,
    _format_section_period,
    format_section_index,
    _SECTION_PROMPT_TIER0,
    _SECTION_PROMPT_TIER1,
    _SECTION_PROMPT_TIER2,
    _SECTION_PROMPT_AGGRESSIVE,
)


# ---------------------------------------------------------------------------
# Phase 1: _select_section_prompt — depth-aware tier selection
# ---------------------------------------------------------------------------

class TestSelectSectionPrompt:
    def test_tier0_for_zero_sections(self):
        assert _select_section_prompt(0) == _SECTION_PROMPT_TIER0

    def test_tier0_for_few_sections(self):
        assert _select_section_prompt(4) == _SECTION_PROMPT_TIER0

    def test_tier1_for_medium_sections(self):
        assert _select_section_prompt(5) == _SECTION_PROMPT_TIER1
        assert _select_section_prompt(10) == _SECTION_PROMPT_TIER1
        assert _select_section_prompt(14) == _SECTION_PROMPT_TIER1

    def test_tier2_for_many_sections(self):
        assert _select_section_prompt(15) == _SECTION_PROMPT_TIER2
        assert _select_section_prompt(50) == _SECTION_PROMPT_TIER2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_llm_response(content):
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


def _mock_section(title="Previous Title", summary="Previous summary text.", sequence=5):
    sec = MagicMock()
    sec.title = title
    sec.summary = summary
    sec.sequence = sequence
    return sec


# ---------------------------------------------------------------------------
# Phase 1+2: _generate_section with depth-aware prompts + previous context
# ---------------------------------------------------------------------------

class TestGenerateSectionDepthAndContext:
    """Test that _generate_section queries section count and injects previous context."""

    @pytest.mark.asyncio
    async def test_no_channel_uses_tier0(self):
        """Without channel_id, uses tier0 prompt and no previous context."""
        llm_response = json.dumps({
            "title": "Test Title",
            "summary": "Test summary.",
            "tags": ["test"],
        })
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(llm_response)
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags, _usage = await _generate_section(
                [{"role": "user", "content": "hello"}],
                "test-model",
            )

        assert title == "Test Title"
        assert summary == "Test summary."
        assert tags == ["test"]
        # Verify no "Previous section" in the prompt (no channel_id)
        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        assert "Previous section" not in user_msg

    @pytest.mark.asyncio
    async def test_previous_context_injected(self):
        """With channel_id and existing sections, injects previous context."""
        llm_response = json.dumps({
            "title": "New Title",
            "summary": "New summary.",
            "tags": ["new"],
        })
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(llm_response)
        )

        channel_id = uuid.uuid4()
        prev_section = _mock_section(title="Old Topic", summary="Old summary.", sequence=3)

        # Mock DB queries: count returns 3, previous section exists
        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 3
        prev_result = MagicMock()
        prev_result.scalar_one_or_none.return_value = prev_section
        mock_db.execute = AsyncMock(side_effect=[count_result, prev_result])

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction.async_session", return_value=mock_session_ctx),
        ):
            title, summary, transcript, tags, _usage = await _generate_section(
                [{"role": "user", "content": "hello"}],
                "test-model",
                channel_id=channel_id,
            )

        assert title == "New Title"
        # Verify previous context was in the prompt
        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        assert "Previous section covered: 'Old Topic'" in user_msg
        assert "Do NOT repeat this" in user_msg


# ---------------------------------------------------------------------------
# Phase 3: Fallback escalation
# ---------------------------------------------------------------------------

class TestGenerateSectionFallback:
    @pytest.mark.asyncio
    async def test_normal_success(self):
        """Normal tier succeeds — no escalation."""
        llm_response = json.dumps({
            "title": "Normal Title",
            "summary": "Normal summary.",
            "tags": ["normal"],
        })
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(llm_response)
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags, _usage = await _generate_section(
                [{"role": "user", "content": "hello"}],
                "test-model",
            )

        assert title == "Normal Title"
        assert tags == ["normal"]
        # LLM called only once
        assert mock_client.chat.completions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_normal_fails_aggressive_succeeds(self):
        """Normal tier fails → aggressive tier succeeds."""
        aggressive_response = json.dumps({
            "title": "Aggressive Title",
            "summary": "Short summary.",
            "tags": ["fallback"],
        })
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[
                Exception("Rate limit"),
                _mock_llm_response(aggressive_response),
            ]
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags, _usage = await _generate_section(
                [{"role": "user", "content": "hello"}],
                "test-model",
            )

        assert title == "Aggressive Title"
        assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_all_llm_fails_deterministic(self):
        """Both LLM tiers fail → deterministic fallback."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Service down")
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags, _usage = await _generate_section(
                [{"role": "user", "content": "Fix the database connection error"}],
                "test-model",
            )

        assert title == "Fix the database connection error"
        assert summary == "Auto-archived conversation segment."
        assert tags == ["auto-truncated"]

    @pytest.mark.asyncio
    async def test_deterministic_truncates_long_title(self):
        """Deterministic fallback truncates long first user messages."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("Service down")
        )
        long_msg = "x" * 200

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags, _usage = await _generate_section(
                [{"role": "user", "content": long_msg}],
                "test-model",
            )

        assert len(title) <= 82  # 80 chars + "…"
        assert title.endswith("…")
        assert tags == ["auto-truncated"]

    @pytest.mark.asyncio
    async def test_non_json_normal_falls_to_aggressive(self):
        """Normal returns non-JSON → falls through to aggressive."""
        aggressive_response = json.dumps({
            "title": "Recovered",
            "summary": "Recovered summary.",
            "tags": ["recovered"],
        })
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=[
                _mock_llm_response("This is not JSON"),  # Normal: non-JSON
                _mock_llm_response(aggressive_response),  # Aggressive: success
            ]
        )

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags, _usage = await _generate_section(
                [{"role": "user", "content": "hello"}],
                "test-model",
            )

        assert title == "Recovered"
        assert mock_client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------------
# _parse_section_response
# ---------------------------------------------------------------------------

class TestParseSectionResponse:
    def test_valid_json(self):
        data = _parse_section_response('{"title": "Test"}')
        assert data == {"title": "Test"}

    def test_json_in_markdown_fences(self):
        raw = '```json\n{"title": "Test"}\n```'
        data = _parse_section_response(raw)
        assert data == {"title": "Test"}

    def test_invalid_json(self):
        assert _parse_section_response("not json at all") is None

    def test_empty_string(self):
        assert _parse_section_response("") is None


# ---------------------------------------------------------------------------
# Phase 5b: Tool dispatch retrieval hint
# ---------------------------------------------------------------------------

class TestToolDispatchRetrievalHint:
    @pytest.mark.asyncio
    async def test_hint_appended_when_summarized(self):
        """When a tool result is summarized, retrieval hint is appended."""
        from app.agent.tool_dispatch import dispatch_tool_call

        # Large result that exceeds threshold
        large_result = "x" * 10000

        with (
            patch("app.agent.tool_dispatch.is_client_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_local_tool", return_value=True),
            patch("app.agent.tool_dispatch.call_local_tool", return_value=large_result),
            patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False),
            patch("app.agent.tool_dispatch._summarize_tool_result", return_value="Summarized output"),
            patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock),
            patch("app.agent.tool_dispatch._record_trace_event", new_callable=AsyncMock),
            patch("app.agent.tool_dispatch._check_tool_policy", return_value=None),
        ):
            result = await dispatch_tool_call(
                name="test_tool",
                args="{}",
                tool_call_id="call_123",
                bot_id="test",
                bot_memory=None,
                session_id=uuid.uuid4(),
                client_id="test-client",
                correlation_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                iteration=1,
                provider_id=None,
                summarize_enabled=True,
                summarize_threshold=1000,
                summarize_model="test-model",
                summarize_max_tokens=500,
                summarize_exclude=set(),
                compaction=False,
            )

        assert result.was_summarized is True
        assert "read_conversation_history" in result.result_for_llm
        assert "tool:" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_no_hint_when_not_summarized(self):
        """When result is small (no summarization), no hint is appended."""
        from app.agent.tool_dispatch import dispatch_tool_call

        small_result = '{"status": "ok"}'

        with (
            patch("app.agent.tool_dispatch.is_client_tool", return_value=False),
            patch("app.agent.tool_dispatch.is_local_tool", return_value=True),
            patch("app.agent.tool_dispatch.call_local_tool", return_value=small_result),
            patch("app.agent.tool_dispatch.is_mcp_tool", return_value=False),
            patch("app.agent.tool_dispatch._record_tool_call", new_callable=AsyncMock),
            patch("app.agent.tool_dispatch._check_tool_policy", return_value=None),
        ):
            result = await dispatch_tool_call(
                name="test_tool",
                args="{}",
                tool_call_id="call_123",
                bot_id="test",
                bot_memory=None,
                session_id=uuid.uuid4(),
                client_id="test-client",
                correlation_id=None,
                channel_id=None,
                iteration=1,
                provider_id=None,
                summarize_enabled=True,
                summarize_threshold=100000,
                summarize_model="test-model",
                summarize_max_tokens=500,
                summarize_exclude=set(),
                compaction=False,
            )

        assert result.was_summarized is False
        assert "read_conversation_history" not in result.result_for_llm


# ---------------------------------------------------------------------------
# _format_section_period — deterministic timestamp rendering
# ---------------------------------------------------------------------------

class TestFormatSectionPeriod:
    def test_none_returns_question_mark(self):
        assert _format_section_period(None, None) == "?"

    def test_start_only(self):
        dt = datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc)
        result = _format_section_period(dt, None)
        assert "mar" in result.lower() or "Mar" in result

    def test_same_day_shows_time_range(self):
        start = datetime(2026, 3, 25, 14, 10, tzinfo=timezone.utc)
        end = datetime(2026, 3, 25, 15, 45, tzinfo=timezone.utc)
        result = _format_section_period(start, end)
        # Should include both times on same day
        assert "—" in result or "-" in result

    def test_different_days_shows_date_range(self):
        start = datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 27, 10, 0, tzinfo=timezone.utc)
        result = _format_section_period(start, end)
        assert "25" in result
        assert "27" in result

    def test_detailed_mode(self):
        start = datetime(2026, 3, 25, 14, 10, tzinfo=timezone.utc)
        end = datetime(2026, 3, 25, 15, 45, tzinfo=timezone.utc)
        result = _format_section_period(start, end, detailed=True)
        assert "—" in result or "-" in result


# ---------------------------------------------------------------------------
# format_section_index — section index rendering with periods
# ---------------------------------------------------------------------------

class TestFormatSectionIndex:
    def _make_section(self, seq, title, summary="Summary.", tags=None,
                      period_start=None, period_end=None, message_count=5):
        s = MagicMock()
        s.sequence = seq
        s.title = title
        s.summary = summary
        s.tags = tags or []
        s.period_start = period_start
        s.period_end = period_end
        s.message_count = message_count
        return s

    def test_compact_with_period(self):
        start = datetime(2026, 3, 25, 14, 10, tzinfo=timezone.utc)
        end = datetime(2026, 3, 25, 15, 45, tzinfo=timezone.utc)
        sections = [self._make_section(1, "Slack Setup", period_start=start, period_end=end)]
        result = format_section_index(sections, "compact")
        assert "#1: Slack Setup" in result
        assert "(?" not in result  # Should have real date, not "?"

    def test_compact_without_period_shows_question_mark(self):
        sections = [self._make_section(1, "Slack Setup")]
        result = format_section_index(sections, "compact")
        assert "(?)" in result

    def test_standard_includes_summary(self):
        start = datetime(2026, 3, 25, 14, 10, tzinfo=timezone.utc)
        end = datetime(2026, 3, 25, 15, 45, tzinfo=timezone.utc)
        sections = [self._make_section(1, "Slack Setup", "Set up Slack.",
                                        period_start=start, period_end=end, tags=["slack"])]
        result = format_section_index(sections, "standard")
        assert "Slack Setup" in result
        assert "Set up Slack." in result
        assert "slack" in result

    def test_header_includes_all_modes(self):
        result = format_section_index([], "compact")
        assert "tool:" in result
        assert "search:" in result

    def test_multiple_sections_all_have_dates(self):
        base = datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc)
        sections = [
            self._make_section(i, f"Section {i}",
                               period_start=base + timedelta(hours=i),
                               period_end=base + timedelta(hours=i, minutes=30))
            for i in range(1, 4)
        ]
        result = format_section_index(sections, "compact")
        # None of the sections should show "?"
        assert result.count("(?)") == 0


# ---------------------------------------------------------------------------
# Prompt content validation
# ---------------------------------------------------------------------------

class TestPromptContent:
    def test_all_tiers_tell_llm_not_to_include_dates(self):
        """Verify all prompts tell the LLM to NOT include dates (we add them deterministically)."""
        for prompt in [_SECTION_PROMPT_TIER0, _SECTION_PROMPT_TIER1, _SECTION_PROMPT_TIER2]:
            assert "Do NOT include dates" in prompt, f"Prompt missing date exclusion: {prompt[:80]}..."

    def test_tier0_requests_detailed_summary(self):
        assert "3-sentence" in _SECTION_PROMPT_TIER0

    def test_tier1_requests_moderate_summary(self):
        assert "2-sentence" in _SECTION_PROMPT_TIER1

    def test_tier2_requests_brief_summary(self):
        assert "1-2 sentence" in _SECTION_PROMPT_TIER2
