"""Tool-result redaction at the persistence/LLM boundary.

Every tool result that gets stored on ``ToolCallResult.result`` or sent back
to the LLM via ``ToolCallResult.result_for_llm`` must pass through the
secret redaction filter. The previous code did this on the success path only;
the error and machine-access-denied paths leaked raw payloads.
"""
from __future__ import annotations

import pytest

from app.agent.tool_dispatch import _apply_error_payload, _set_tool_result
from app.services import secret_registry


@pytest.fixture(autouse=True)
def _seed_known_secret():
    """Register a known secret so redact() recognises it as ``[REDACTED]``."""
    prev_known = set(secret_registry._known_secrets)
    prev_pattern = secret_registry._pattern
    prev_built = secret_registry._built
    secret_registry._known_secrets = {"super-secret-token-1234567890"}
    secret_registry._pattern = secret_registry._build_pattern(
        secret_registry._known_secrets
    )
    secret_registry._built = True
    try:
        yield
    finally:
        secret_registry._known_secrets = prev_known
        secret_registry._pattern = prev_pattern
        secret_registry._built = prev_built


class _Sink:
    """Minimal stand-in for ToolCallResult so we don't have to import the dataclass."""

    def __init__(self) -> None:
        self.result = None
        self.result_for_llm = None
        self.tool_event = None


def test_set_tool_result_redacts_persisted_payload():
    sink = _Sink()
    _set_tool_result(sink, "leaked: super-secret-token-1234567890")
    assert "super-secret-token" not in sink.result
    assert "[REDACTED]" in sink.result


def test_set_tool_result_redacts_llm_payload():
    sink = _Sink()
    _set_tool_result(sink, "ok", llm="leaked: super-secret-token-1234567890")
    assert sink.result == "ok"
    assert "super-secret-token" not in sink.result_for_llm
    assert "[REDACTED]" in sink.result_for_llm


def test_apply_error_payload_redacts_error_path():
    """The error path used to write the raw payload — pin redaction."""
    sink = _Sink()
    _apply_error_payload(
        sink,
        tool_name="leaky_tool",
        tool_call_id="tc-1",
        error_message="Boom: super-secret-token-1234567890",
    )
    assert "super-secret-token" not in sink.result
    assert "[REDACTED]" in sink.result
    assert sink.result == sink.result_for_llm


def test_apply_error_payload_redacts_raw_result():
    sink = _Sink()
    raw = '{"error": "Boom: super-secret-token-1234567890"}'
    _apply_error_payload(
        sink,
        tool_name="leaky_tool",
        tool_call_id="tc-1",
        error_message="Boom",
        raw_result=raw,
    )
    assert "super-secret-token" not in sink.result
    assert "[REDACTED]" in sink.result


def test_pattern_secrets_redacted_even_without_registration():
    """Pattern-based detection still catches Anthropic/OpenAI/etc keys."""
    sink = _Sink()
    _set_tool_result(sink, "leaked sk-ant-api01-abcdefghij1234567890")
    assert "sk-ant-api01" not in sink.result
    assert "[REDACTED]" in sink.result
