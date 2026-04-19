"""Guard the _trim_stored_result helper against regressions that would eat
tool-authored envelope JSON. The dev panel's Recent tab and the Import-into-
Templates flow both depend on the stored result being re-parseable JSON —
mid-string slicing of an `{"_envelope": ...}` payload collapses the preview to
"—" and disables Import. See the 2026-04-19 widget-dashboard paper-cuts fix.
"""
import json

from app.agent.recording import _trim_stored_result


def test_none_stays_none():
    assert _trim_stored_result(None, False) is None
    assert _trim_stored_result(None, True) is None


def test_store_full_preserves_large_payload():
    big = "x" * 10_000
    assert _trim_stored_result(big, True) == big


def test_default_cap_truncates_large_payload():
    big = "x" * 10_000
    result = _trim_stored_result(big, False)
    assert result is not None
    assert len(result) == 4000


def test_small_payload_untouched():
    assert _trim_stored_result("hello", False) == "hello"


def test_envelope_payload_exempt_from_truncation():
    # Inline-mode emit_html_widget returns a large envelope body that must
    # stay re-parseable — mid-string slicing would break the preview.
    body = "<div>" + ("x" * 10_000) + "</div>"
    payload = json.dumps({
        "_envelope": {
            "content_type": "application/vnd.spindrel.html+interactive",
            "body": body,
            "plain_body": "hi",
            "display": "inline",
        },
        "llm": "Emitted HTML widget (10010 chars).",
    })
    assert len(payload) > 4000
    result = _trim_stored_result(payload, False)
    assert result == payload
    # Round-trips back to a parseable object.
    parsed = json.loads(result)
    assert "_envelope" in parsed


def test_envelope_with_leading_whitespace_still_exempt():
    # Defensive — dispatch could one day pretty-print or indent.
    payload = '  {"_envelope": {"content_type": "x", "body": "' + ("y" * 5000) + '"}}'
    result = _trim_stored_result(payload, False)
    assert result == payload


def test_non_envelope_json_still_capped():
    # Error payloads are short, but arbitrary large JSON (e.g. a tool that
    # returned a multi-MB list) should still hit the cap.
    huge_list = json.dumps({"items": list(range(10_000))})
    assert len(huge_list) > 4000
    result = _trim_stored_result(huge_list, False)
    assert result is not None
    assert len(result) == 4000


def test_string_that_merely_contains_envelope_word_is_still_capped():
    # Prefix match is anchored so a normal string that happens to mention
    # _envelope in the middle doesn't accidentally bypass the cap.
    text = ("raw log output " * 1000) + ' _envelope mention '
    assert len(text) > 4000
    result = _trim_stored_result(text, False)
    assert result is not None
    assert len(result) == 4000
