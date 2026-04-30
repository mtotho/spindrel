import json

import pytest

from app.services.tool_error_contract import (
    BENIGN_REVIEW_ERROR_KINDS,
    build_tool_error,
    default_fallback_for_kind,
    error_for_http_status,
    infer_error_kind,
    parse_retry_after,
    tool_error_contract,
)


def test_build_tool_error_preserves_legacy_error_and_adds_contract_fields():
    payload = build_tool_error(
        message="File is currently locked",
        error_code="RESOURCE_LOCKED",
        error_kind="conflict",
        tool_name="file",
    )

    assert payload["error"] == "File is currently locked"
    assert payload["success"] is False
    assert payload["error_code"] == "resource_locked"
    assert payload["error_kind"] == "conflict"
    assert payload["retryable"] is False
    assert payload["fallback"]


def test_error_kind_classification_distinguishes_review_noise_from_platform_bugs():
    assert infer_error_kind("invalid_json_body", "bad request") == "validation"
    assert infer_error_kind("missing_api_permissions", "not configured") == "config_missing"
    assert infer_error_kind("tool_dispatch_timeout", "timed out") == "timeout"
    assert infer_error_kind("local_tool_exception", "unexpected exception") == "internal"
    assert "validation" in BENIGN_REVIEW_ERROR_KINDS
    assert "internal" not in BENIGN_REVIEW_ERROR_KINDS


def test_http_status_contract_marks_retryable_and_retry_after():
    rate_limited = error_for_http_status(429, retry_after="17")
    unavailable = error_for_http_status(503)
    not_found = error_for_http_status(404)

    assert rate_limited["error_kind"] == "rate_limited"
    assert rate_limited["retryable"] is True
    assert rate_limited["retry_after_seconds"] == 17
    assert unavailable["retryable"] is True
    assert not_found["error_kind"] == "not_found"
    assert not_found["retryable"] is False


def test_retry_after_parser_handles_empty_values():
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("0") == 0


def test_manifest_contract_documents_filtering_categories():
    contract = tool_error_contract()

    assert contract["version"] == "tool-error.v1"
    assert "retryable" in contract["fields"]
    assert "validation" in contract["benign_review_kinds"]
    assert "timeout" in contract["retryable_kinds"]


@pytest.mark.asyncio
async def test_unknown_local_tool_returns_standard_error_contract():
    from app.tools.registry import call_local_tool

    payload = json.loads(await call_local_tool("__missing_tool__", "{}"))

    assert payload["error"]
    assert payload["error_code"] == "unknown_local_tool"
    assert payload["error_kind"] == "not_found"
    assert payload["retryable"] is False
    assert "Do not retry __missing_tool__ under invented aliases" in payload["fallback"]


def test_not_found_fallback_discourages_invented_tool_names():
    fallback = default_fallback_for_kind("not_found")

    assert fallback is not None
    assert "use only exact listed tool names" in fallback.lower()
    assert "Do not invent alternate workspace/file helper names" in fallback
