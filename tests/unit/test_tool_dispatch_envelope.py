"""Tests for the ToolResultEnvelope opt-in path through dispatch_tool_call.

Covers:
- Tools that don't opt in get a default text/plain envelope built from raw result
- Tools that emit `{"_envelope": {...}}` lift the envelope cleanly
- Body truncation at INLINE_BODY_CAP_BYTES
- record_id is set when the envelope is truncated
- Envelope body goes through secret redaction
- The compact_dict() wire format round-trips through JSON

Avoids touching the live tool dispatcher's policy / approval / summarization
machinery — these tests directly exercise the helpers
(`_build_default_envelope`, `_build_envelope_from_optin`,
`ToolResultEnvelope.compact_dict`).
"""
import json
import uuid

import pytest

from app.agent.tool_dispatch import (
    INLINE_BODY_CAP_BYTES,
    PLAIN_BODY_CAP_CHARS,
    ToolResultEnvelope,
    _build_default_envelope,
    _build_envelope_from_optin,
    _extract_embedded_payloads,
    _select_result_envelope,
)


class TestDefaultEnvelope:
    def test_short_text_inline(self):
        env = _build_default_envelope("Hello world")
        assert env.content_type == "text/plain"
        assert env.body == "Hello world"
        assert env.plain_body == "Hello world"
        assert env.display == "badge"
        assert env.truncated is False
        assert env.byte_size == len(b"Hello world")

    def test_empty_text(self):
        env = _build_default_envelope("")
        assert env.body == ""
        assert env.plain_body == ""
        assert env.byte_size == 0
        assert env.truncated is False

    def test_none_text_safe(self):
        env = _build_default_envelope(None)  # type: ignore[arg-type]
        assert env.body == ""
        assert env.truncated is False

    def test_truncation_at_cap(self):
        big = "x" * (INLINE_BODY_CAP_BYTES + 100)
        env = _build_default_envelope(big)
        assert env.truncated is True
        assert env.body is None
        # plain_body still gets a short summary
        assert env.plain_body == "x" * PLAIN_BODY_CAP_CHARS
        # byte_size reflects the FULL underlying text, not the (None) inline body
        assert env.byte_size == INLINE_BODY_CAP_BYTES + 100

    def test_truncated_json_still_detected_as_json(self):
        # `_run_tool_step` appends "... [truncated]" past its result cap,
        # which makes the tail of the string invalid JSON. Without the
        # suffix-aware detector, the envelope fell through to markdown
        # rendering — and the bot system prompts embedded inside the
        # response body contain `---` separators and `**bold**` that
        # the markdown renderer then mis-rendered.
        body = '{"status": 200, "body": {"id": "qa-bot", "system_prompt": "Hello ---\\n**bold**"}... [truncated]'
        env = _build_default_envelope(body)
        assert env.content_type == "application/json"

    def test_plain_text_with_truncated_suffix_stays_plain(self):
        # The suffix check only upgrades text that *starts* with { or [.
        body = "plain text that happens to end ... [truncated]"
        env = _build_default_envelope(body)
        assert env.content_type == "text/plain"


class TestOptInEnvelope:
    def test_basic_optin(self):
        env = _build_envelope_from_optin(
            {
                "content_type": "text/markdown",
                "body": "# Heading\nA paragraph.",
                "plain_body": "Heading + paragraph",
                "display": "inline",
            },
            raw_text="# Heading\nA paragraph.",
        )
        assert env.content_type == "text/markdown"
        assert env.body == "# Heading\nA paragraph."
        assert env.plain_body == "Heading + paragraph"
        assert env.display == "inline"
        assert env.truncated is False

    def test_optin_with_dict_body_serializes_to_json(self):
        env = _build_envelope_from_optin(
            {
                "content_type": "application/json",
                "body": {"a": 1, "b": [2, 3]},
                "plain_body": "json",
            },
            raw_text="",
        )
        # Non-string body is JSON-encoded so the wire format stays consistent
        assert isinstance(env.body, str)
        parsed = json.loads(env.body)
        assert parsed == {"a": 1, "b": [2, 3]}

    def test_optin_truncation_drops_body(self):
        big = "x" * (INLINE_BODY_CAP_BYTES + 50)
        env = _build_envelope_from_optin(
            {
                "content_type": "text/plain",
                "body": big,
                "plain_body": "very large output",
            },
            raw_text=big,
        )
        assert env.truncated is True
        assert env.body is None
        assert env.plain_body == "very large output"

    def test_interactive_html_body_exempt_from_cap(self):
        # HTML widgets carry ship-time markup, not user-generated payload,
        # and the renderer has no lazy-fetch fallback — truncation would
        # render as an empty iframe. Confirm they survive past the cap.
        big_html = "<div>" + ("x" * (INLINE_BODY_CAP_BYTES + 1024)) + "</div>"
        env = _build_envelope_from_optin(
            {
                "content_type": "application/vnd.spindrel.html+interactive",
                "body": big_html,
                "plain_body": "",
            },
            raw_text=big_html,
        )
        assert env.truncated is False
        assert env.body == big_html

    def test_optin_invalid_display_falls_back_to_badge(self):
        env = _build_envelope_from_optin(
            {"content_type": "text/plain", "body": "x", "display": "totally-invalid"},
            raw_text="x",
        )
        assert env.display == "badge"

    def test_optin_missing_content_type_defaults_plain(self):
        env = _build_envelope_from_optin({"body": "x"}, raw_text="x")
        assert env.content_type == "text/plain"


class TestCapBodyBypass:
    """Widget-actions dispatch passes ``cap_body=False`` so ``callTool``
    returns a fully parseable envelope to widget JS. Without this, large
    JSON tool results arrive as ``{body: null, truncated: true, plain_body: <200-char preview>}``
    and any widget that runs ``JSON.parse(env.body)`` crashes."""

    def test_default_envelope_bypass_cap(self):
        big = "x" * (INLINE_BODY_CAP_BYTES + 500)
        env = _build_default_envelope(big, cap_body=False)
        assert env.truncated is False
        assert env.body == big
        # byte_size still reflects actual size so widgets can decide what to do
        assert env.byte_size == INLINE_BODY_CAP_BYTES + 500

    def test_optin_bypass_cap(self):
        big_json = json.dumps({"items": [{"k": "v"} for _ in range(500)]})
        assert len(big_json) > INLINE_BODY_CAP_BYTES
        env = _build_envelope_from_optin(
            {"content_type": "application/json", "body": big_json, "plain_body": "big"},
            raw_text=big_json,
            cap_body=False,
        )
        assert env.truncated is False
        assert env.body == big_json
        # Widget JS can parse it without a lazy-fetch roundtrip
        parsed = json.loads(env.body)
        assert len(parsed["items"]) == 500

    def test_cap_body_default_still_caps(self):
        # Sanity: the default path (LLM turn loop) must still truncate.
        big = "x" * (INLINE_BODY_CAP_BYTES + 100)
        env = _build_default_envelope(big)
        assert env.truncated is True
        assert env.body is None


class TestCompactDict:
    def test_round_trip_through_json(self):
        record = uuid.uuid4()
        env = ToolResultEnvelope(
            content_type="application/vnd.spindrel.diff+text",
            body=None,
            plain_body="Edited foo.py: +12 −3 lines",
            display="inline",
            truncated=True,
            record_id=record,
            byte_size=8192,
        )
        compact = env.compact_dict()
        # All fields present
        assert set(compact.keys()) == {
            "content_type",
            "body",
            "plain_body",
            "display",
            "truncated",
            "record_id",
            "byte_size",
        }
        # record_id is a string for JSONB round-trip safety
        assert compact["record_id"] == str(record)
        # JSON-safe
        encoded = json.dumps(compact)
        assert json.loads(encoded) == compact

    def test_compact_dict_with_no_record_id(self):
        env = ToolResultEnvelope(
            content_type="text/plain",
            body="hi",
            plain_body="hi",
        )
        compact = env.compact_dict()
        assert compact["record_id"] is None
        assert compact["truncated"] is False


class TestEnvelopeFieldOnToolCallResult:
    """ToolCallResult must default-construct an envelope so legacy tools
    that take early-return paths (policy denied, pending approval, error)
    still emit a well-formed envelope on the bus."""

    def test_default_envelope_on_fresh_result(self):
        from app.agent.tool_dispatch import ToolCallResult

        result = ToolCallResult()
        assert isinstance(result.envelope, ToolResultEnvelope)
        assert result.envelope.content_type == "text/plain"
        assert result.envelope.display == "badge"


class TestMemoryToolEnvelopeThroughDispatcher:
    def test_memory_tool_lifts_envelope_and_keeps_short_llm_text(self):
        raw = json.dumps({
            "path": "memory/MEMORY.md",
            "message": "replace_section complete",
            "llm": "Memory operation completed for memory/MEMORY.md.",
            "_envelope": {
                "content_type": "application/json",
                "body": {
                    "path": "memory/MEMORY.md",
                    "message": "replace_section complete",
                },
                "plain_body": "Replace Section memory/MEMORY.md",
                "display": "badge",
            },
        })

        result_for_llm, envelope_optin, client_action, injected_images = _extract_embedded_payloads(raw)
        assert result_for_llm == "Memory operation completed for memory/MEMORY.md."
        assert client_action is None
        assert injected_images is None
        assert envelope_optin is not None

        env = _select_result_envelope(
            name="memory",
            tool_call_id="call-memory-1",
            redacted_result=raw,
            envelope_optin=envelope_optin,
            redact=lambda value: value,
        )

        assert env.tool_name == "memory"
        assert env.tool_call_id == "call-memory-1"
        assert env.content_type == "application/json"
        assert env.plain_body == "Replace Section memory/MEMORY.md"
        assert json.loads(env.body) == {
            "path": "memory/MEMORY.md",
            "message": "replace_section complete",
        }
