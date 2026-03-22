"""Tests for model elevation classifier and JSONL logging."""

import asyncio
import json
import os
import tempfile
from unittest.mock import patch

import pytest

from app.agent.elevation import (
    ElevationDecision,
    classify_turn,
    _get_last_user_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOT_MODEL = "gemini/gemini-2.5-flash"
ELEVATED_MODEL = "claude-sonnet-4-5"
THRESHOLD = 0.4


def _msgs(user_text: str, extra: list[dict] | None = None) -> list[dict]:
    """Build a minimal message list with a single user message."""
    msgs = [{"role": "user", "content": user_text}]
    if extra:
        msgs = extra + msgs
    return msgs


def _classify(user_text: str, tool_history=None, extra_msgs=None, threshold=THRESHOLD):
    return classify_turn(
        _msgs(user_text, extra=extra_msgs),
        BOT_MODEL, ELEVATED_MODEL, threshold,
        tool_history=tool_history,
    )


# ---------------------------------------------------------------------------
# 1. Individual signal tests
# ---------------------------------------------------------------------------

class TestMessageLength:
    def test_short_simple_message_no_elevation(self):
        """'what time is it' is short — score should be below threshold."""
        d = _classify("what time is it")
        assert not d.was_elevated
        assert d.model == BOT_MODEL
        assert d.score < THRESHOLD

    def test_long_message_elevates(self):
        """500+ char message should fire message_length signal."""
        long_msg = "Please help me " + "x" * 1600
        d = _classify(long_msg)
        assert d.signal_breakdown["message_length"] > 0
        # With a 1600+ char message, message_length alone contributes 0.10
        # Combined with keyword or other signals it should push over threshold

    def test_very_long_message_max(self):
        """1500+ chars should produce weight * 1.0 contribution."""
        msg = "a" * 2000
        d = _classify(msg)
        assert abs(d.signal_breakdown["message_length"] - 0.10) < 0.001


class TestCodeContent:
    def test_code_block_elevates(self):
        """Message with ```code``` should fire code_content signal."""
        msg = "Can you fix this?\n```python\ndef foo():\n    pass\n```"
        d = _classify(msg)
        assert d.signal_breakdown["code_content"] > 0
        assert "code_content" in d.rules_fired

    def test_inline_backtick(self):
        msg = "What does `os.path.join` do?"
        d = _classify(msg)
        assert d.signal_breakdown["code_content"] > 0

    def test_no_code(self):
        msg = "Tell me a joke"
        d = _classify(msg)
        assert d.signal_breakdown["code_content"] == 0


class TestElevateKeywords:
    def test_elevate_keyword_fires(self):
        """'design' is an elevate keyword."""
        d = _classify("can you design a system for caching")
        assert d.signal_breakdown["keyword_elevate"] > 0
        assert "keyword_elevate" in d.rules_fired

    def test_multiple_elevate_keywords(self):
        d = _classify("explain why we should refactor this module")
        # "explain", "why", "refactor" → 2+ matches → 1.0
        assert d.signal_breakdown["keyword_elevate"] == pytest.approx(0.20, abs=0.001)

    def test_no_elevate_keyword(self):
        d = _classify("hello there")
        assert d.signal_breakdown["keyword_elevate"] == 0


class TestSimpleKeywords:
    def test_simple_keyword_suppresses(self):
        """'timer' is a simple keyword — should apply negative weight."""
        d = _classify("set a timer")
        assert d.signal_breakdown["keyword_simple"] < 0
        assert "keyword_simple" in d.rules_fired

    def test_simple_keyword_short_message(self):
        """Short message + simple keyword → max suppression."""
        d = _classify("turn off")
        # weight -0.20 * 1.0 = -0.20
        assert d.signal_breakdown["keyword_simple"] == pytest.approx(-0.20, abs=0.001)

    def test_no_simple_keyword(self):
        d = _classify("explain the architecture")
        assert d.signal_breakdown["keyword_simple"] == 0


class TestToolComplexity:
    def test_delegate_tool_elevates(self):
        d = _classify("do it", tool_history=["delegate_to_harness"])
        assert d.signal_breakdown["tool_complexity"] > 0
        assert "tool_complexity" in d.rules_fired

    def test_simple_tool_suppresses(self):
        """Simple tools like get_current_local_time should score 0."""
        d = _classify("what time", tool_history=["get_current_local_time"])
        assert d.signal_breakdown["tool_complexity"] == 0

    def test_research_tools(self):
        d = _classify("search for it", tool_history=["web_search"])
        assert d.signal_breakdown["tool_complexity"] > 0

    def test_no_tools(self):
        d = _classify("hello", tool_history=[])
        assert d.signal_breakdown["tool_complexity"] == 0


class TestConversationDepth:
    def test_deep_conversation_elevates(self):
        """10+ tool messages in context → conversation_depth fires."""
        extra = [{"role": "tool", "tool_call_id": f"tc{i}", "content": f"result {i}"} for i in range(12)]
        d = _classify("continue", extra_msgs=extra)
        assert d.signal_breakdown["conversation_depth"] > 0
        assert "conversation_depth" in d.rules_fired

    def test_shallow_conversation(self):
        extra = [{"role": "tool", "tool_call_id": "tc1", "content": "ok"}]
        d = _classify("hello", extra_msgs=extra)
        assert d.signal_breakdown["conversation_depth"] == 0


class TestIterationDepth:
    def test_high_iteration_depth(self):
        d = _classify("try again", tool_history=["t1", "t2", "t3", "t4", "t5"])
        assert d.signal_breakdown["iteration_depth"] > 0

    def test_zero_iterations(self):
        d = _classify("hello", tool_history=[])
        assert d.signal_breakdown["iteration_depth"] == 0


class TestPriorErrors:
    def test_prior_errors_elevate(self):
        """Tool results containing 'error' should fire prior_errors."""
        extra = [
            {"role": "tool", "tool_call_id": "tc1", "content": "Error: file not found"},
            {"role": "tool", "tool_call_id": "tc2", "content": "Traceback (most recent call last):\n  File..."},
        ]
        d = _classify("fix this", extra_msgs=extra)
        assert d.signal_breakdown["prior_errors"] > 0
        assert "prior_errors" in d.rules_fired

    def test_no_errors(self):
        extra = [{"role": "tool", "tool_call_id": "tc1", "content": "Success: all tests passed"}]
        d = _classify("good", extra_msgs=extra)
        assert d.signal_breakdown["prior_errors"] == 0


# ---------------------------------------------------------------------------
# 2. Combined / integration tests
# ---------------------------------------------------------------------------

class TestCombinedSignals:
    def test_multiple_signals_combine(self):
        """Long message + code + keyword → high score, should elevate."""
        msg = "Can you explain this code and refactor it?\n```python\n" + "x = 1\n" * 200 + "```"
        d = _classify(msg)
        assert d.was_elevated
        assert d.model == ELEVATED_MODEL
        assert d.score >= THRESHOLD

    def test_elevation_disabled_uses_bot_model(self):
        """When called with elevated_model == bot_model, never elevates."""
        msg = "explain the entire architecture and refactor everything"
        d = classify_turn(
            _msgs(msg), BOT_MODEL, BOT_MODEL, THRESHOLD,
        )
        assert not d.was_elevated
        assert d.model == BOT_MODEL

    def test_threshold_boundary_below(self):
        """Score just below threshold → no elevation."""
        # "hello" has no signals, score should be 0
        d = _classify("hello", threshold=0.01)
        # Even with threshold=0.01, "hello" scores 0
        assert d.score == 0.0
        assert not d.was_elevated

    def test_threshold_boundary_above(self):
        """Score at exactly 0 with threshold 0 → should elevate."""
        # With threshold=0, even score=0 should elevate (>=)
        d = _classify("hello", threshold=0.0)
        assert d.was_elevated
        assert d.model == ELEVATED_MODEL

    def test_returns_correct_model_strings(self):
        """Verify model strings are passed through correctly."""
        custom_elevated = "my-custom-model"
        d = classify_turn(
            _msgs("explain the design"), BOT_MODEL, custom_elevated, 0.0,
        )
        assert d.model == custom_elevated

    def test_rules_fired_list_populated(self):
        """rules_fired should contain signal names that contributed."""
        d = _classify("explain why we should debug this")
        assert isinstance(d.rules_fired, list)
        # "explain", "why", "debug" → keyword_elevate should fire
        assert "keyword_elevate" in d.rules_fired

    def test_signal_breakdown_populated(self):
        """signal_breakdown should have all 8 signal keys."""
        d = _classify("hello")
        assert len(d.signal_breakdown) == 8
        expected_keys = {
            "message_length", "code_content", "keyword_elevate",
            "keyword_simple", "tool_complexity", "conversation_depth",
            "iteration_depth", "prior_errors",
        }
        assert set(d.signal_breakdown.keys()) == expected_keys


# ---------------------------------------------------------------------------
# 3. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_messages(self):
        """Empty message list should not crash."""
        d = classify_turn([], BOT_MODEL, ELEVATED_MODEL, THRESHOLD)
        assert d.model == BOT_MODEL
        assert not d.was_elevated
        assert d.score == 0.0

    def test_last_message_not_user(self):
        """If last message is assistant, user content extraction returns empty."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        # _get_last_user_content walks backward, so it finds "hello"
        assert _get_last_user_content(msgs) == "hello"

    def test_only_assistant_messages(self):
        """No user messages at all."""
        msgs = [{"role": "assistant", "content": "I'm ready"}]
        text = _get_last_user_content(msgs)
        assert text == ""

    def test_very_long_conversation(self):
        """Many messages should not cause issues."""
        msgs = []
        for i in range(500):
            msgs.append({"role": "user", "content": f"message {i}"})
            msgs.append({"role": "assistant", "content": f"reply {i}"})
        d = classify_turn(msgs, BOT_MODEL, ELEVATED_MODEL, THRESHOLD)
        assert isinstance(d, ElevationDecision)

    def test_tool_history_with_dicts(self):
        """tool_history can contain dicts with 'name' key."""
        d = _classify("do it", tool_history=[{"name": "delegate_to_harness"}])
        assert d.signal_breakdown["tool_complexity"] > 0

    def test_multimodal_user_message(self):
        """User message with list-of-parts content."""
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "explain this image"},
            {"type": "image_url", "image_url": {"url": "data:..."}},
        ]}]
        d = classify_turn(msgs, BOT_MODEL, ELEVATED_MODEL, THRESHOLD)
        # Should extract "explain this image" and fire keyword_elevate
        assert "keyword_elevate" in d.rules_fired

    def test_score_clamped_to_zero(self):
        """Negative raw score (only simple keywords) should clamp to 0."""
        d = _classify("turn off")
        assert d.score >= 0.0

    def test_negative_weight_signal_in_rules_fired(self):
        """keyword_simple should appear in rules_fired even though weight is negative."""
        d = _classify("set a timer")
        assert "keyword_simple" in d.rules_fired


# ---------------------------------------------------------------------------
# 4. Logging tests
# ---------------------------------------------------------------------------

class TestElevationLogging:
    @pytest.fixture
    def tmp_log_dir(self, tmp_path):
        log_path = tmp_path / "elevation_log.jsonl"
        with patch("app.agent.elevation_log._LOG_DIR", str(tmp_path)), \
             patch("app.agent.elevation_log._LOG_PATH", str(log_path)):
            yield log_path

    def test_log_entry_written(self, tmp_log_dir):
        from app.agent.elevation_log import log_elevation
        decision = ElevationDecision(
            model=ELEVATED_MODEL, was_elevated=True, score=0.65,
            rules_fired=["code_content"], signal_breakdown={"code_content": 0.14},
        )
        entry_id = asyncio.get_event_loop().run_until_complete(
            log_elevation(decision, bot_id="test-bot")
        )
        assert tmp_log_dir.exists()
        lines = tmp_log_dir.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["id"] == entry_id
        assert data["was_elevated"] is True
        assert data["bot_id"] == "test-bot"

    def test_log_entry_schema(self, tmp_log_dir):
        from app.agent.elevation_log import log_elevation
        decision = ElevationDecision(
            model=BOT_MODEL, was_elevated=False, score=0.1,
            rules_fired=[], signal_breakdown={},
        )
        asyncio.get_event_loop().run_until_complete(
            log_elevation(decision, bot_id="b")
        )
        data = json.loads(tmp_log_dir.read_text().strip())
        required_fields = {
            "id", "turn_id", "timestamp", "bot_id", "channel_id",
            "model_chosen", "was_elevated", "score", "rules_fired",
            "signal_breakdown", "tokens_used", "latency_ms",
        }
        assert required_fields <= set(data.keys())

    def test_backfill_tokens_and_latency(self, tmp_log_dir):
        from app.agent.elevation_log import backfill_elevation_log, log_elevation
        decision = ElevationDecision(
            model=ELEVATED_MODEL, was_elevated=True, score=0.5,
            rules_fired=[], signal_breakdown={},
        )
        entry_id = asyncio.get_event_loop().run_until_complete(
            log_elevation(decision, bot_id="b")
        )
        asyncio.get_event_loop().run_until_complete(
            backfill_elevation_log(entry_id, tokens_used=1234, latency_ms=567)
        )
        lines = tmp_log_dir.read_text().strip().split("\n")
        assert len(lines) == 2
        backfill = json.loads(lines[1])
        assert backfill["id"] == entry_id
        assert backfill["backfill"] is True
        assert backfill["tokens_used"] == 1234
        assert backfill["latency_ms"] == 567
