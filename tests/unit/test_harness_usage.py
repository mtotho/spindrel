from __future__ import annotations

import uuid

from app.services.agent_harnesses.usage import _harness_usage_data


def test_codex_harness_usage_prefers_last_turn_totals_for_usage_breakdown():
    channel_id = uuid.uuid4()

    data = _harness_usage_data(
        runtime="codex",
        model="gpt-5.4-mini",
        channel_id=channel_id,
        cost_usd=None,
        usage={
            "input_tokens": 100_000,
            "output_tokens": 5_000,
            "total_tokens": 105_000,
            "last_input_tokens": 1_200,
            "last_output_tokens": 30,
            "last_total_tokens": 1_230,
            "context_window_tokens": 200_000,
        },
    )

    assert data is not None
    assert data["provider_id"] == "harness:codex-sdk"
    assert data["usage_source"] == "harness_sdk"
    assert data["billing_mode"] == "non_billable"
    assert data["total_tokens"] == 1_230
    assert data["prompt_tokens"] == 1_200
    assert data["completion_tokens"] == 30
    assert data["channel_id"] == str(channel_id)
    assert data["context_window_tokens"] == 200_000
    assert data["raw_usage"]["total_tokens"] == 105_000
