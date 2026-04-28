from __future__ import annotations

from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.config_state_restore import (
    _channel_heartbeat_values,
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
