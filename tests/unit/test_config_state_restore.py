from __future__ import annotations

from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import SharedWorkspace
from app.services.config_state_restore import (
    _channel_heartbeat_values,
    _bot_values,
    _provider_model_values,
    _provider_values,
    _workspace_values,
    restore_config_state_snapshot,
)


def _heartbeat_row(**overrides):
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "channel_id": "00000000-0000-0000-0000-000000000002",
        "enabled": True,
        "interval_minutes": 15,
        "model": "gpt-test",
        "prompt": "Check status",
    }
    row.update(overrides)
    return row


def test_channel_heartbeat_values_uses_row_local_policy_and_spatial_flags():
    vals = _channel_heartbeat_values(
        _heartbeat_row(
            quiet_start="09:30:00",
            quiet_end="17:45:00",
            append_spatial_prompt=True,
            append_spatial_map_overview=True,
            execution_policy={
                "preset": "low",
                "tool_surface": "invalid",
                "soft_max_llm_calls": 99,
            },
        )
    )

    assert vals["quiet_start"] == dt_time(9, 30)
    assert vals["quiet_end"] == dt_time(17, 45)
    assert vals["append_spatial_prompt"] is True
    assert vals["append_spatial_map_overview"] is True
    assert vals["execution_policy"]["tool_surface"] == "focused_escape"
    assert vals["execution_policy"]["soft_max_llm_calls"] == 50
    assert vals["execution_policy"]["preset"] == "custom"


def test_channel_heartbeat_values_keeps_runtime_defaults_out_of_snapshot_restore():
    vals = _channel_heartbeat_values(_heartbeat_row())

    assert vals["execution_policy"] is None
    assert vals["append_spatial_prompt"] is False
    assert vals["append_spatial_map_overview"] is False


def test_provider_values_restore_billing_fields():
    vals = _provider_values(
        {
            "display_name": "Provider",
            "provider_type": "openai-compatible",
            "billing_type": "plan",
            "plan_cost": 20.0,
            "plan_period": "monthly",
        }
    )

    assert vals["billing_type"] == "plan"
    assert vals["plan_cost"] == 20.0
    assert vals["plan_period"] == "monthly"


def test_provider_model_values_restore_runtime_capability_fields():
    vals = _provider_model_values(
        "provider-1",
        {
            "model_id": "gpt-test",
            "context_window": 128000,
            "max_output_tokens": 8192,
            "cached_input_cost_per_1m": "0.10",
            "supports_tools": False,
            "supports_vision": False,
            "supports_reasoning": True,
            "supports_prompt_caching": True,
            "supports_structured_output": True,
            "supports_image_generation": True,
            "prompt_style": "xml",
            "extra_body": {"reasoning": {"effort": "medium"}},
        },
    )

    assert vals["context_window"] == 128000
    assert vals["max_output_tokens"] == 8192
    assert vals["cached_input_cost_per_1m"] == "0.10"
    assert vals["supports_tools"] is False
    assert vals["supports_vision"] is False
    assert vals["supports_reasoning"] is True
    assert vals["supports_prompt_caching"] is True
    assert vals["supports_structured_output"] is True
    assert vals["supports_image_generation"] is True
    assert vals["prompt_style"] == "xml"
    assert vals["extra_body"] == {"reasoning": {"effort": "medium"}}


def test_bot_values_restore_provider_companion_fields():
    vals = _bot_values(
        {
            "name": "Bot",
            "model": "gpt-test",
            "compaction_model_provider_id": "provider-compact",
            "attachment_summary_model_provider_id": "provider-vision",
        }
    )

    assert vals["compaction_model_provider_id"] == "provider-compact"
    assert vals["attachment_summary_model_provider_id"] == "provider-vision"


def test_workspace_values_compile_against_current_model_and_preserve_write_protection():
    vals = _workspace_values(
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "name": "Workspace",
            "write_protected_paths": ["/secrets"],
        }
    )

    pg_insert(SharedWorkspace).values(
        id="00000000-0000-0000-0000-000000000003",
        **vals,
    ).compile()
    assert vals["write_protected_paths"] == ["/secrets"]
    assert "image" not in vals
    assert "mounts" not in vals


@pytest.mark.asyncio
async def test_restore_channel_heartbeat_without_users_does_not_require_outer_policy():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))

    summary = await restore_config_state_snapshot(
        {"channel_heartbeats": [_heartbeat_row(execution_policy={"preset": "high"})]},
        db,
    )

    assert summary == {"channel_heartbeats": {"created": 0, "updated": 1}}
    db.execute.assert_awaited_once()
