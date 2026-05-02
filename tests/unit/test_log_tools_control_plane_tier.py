"""R3 — pin the safety tier on raw-log tools.

`read_container_logs` and `get_recent_server_errors` return raw / lightly-
deduplicated server log content. The pattern-scoped secret redactor cannot
guarantee env-dump / stack-trace / integration-init coverage, so policy treats
both as ``control_plane`` (admin-grant only). A future refactor must not
silently revert them to the default ``readonly`` tier.

``get_latest_health_summary`` and ``get_system_health_preflight`` stay
``readonly`` — they return dedup findings / preflight summaries, not raw
bodies, so they aren't the exfil surface.
"""
from __future__ import annotations

import pytest

# Importing the tool modules registers the tools with the global registry.
import app.tools.local.read_container_logs  # noqa: F401
import app.tools.local.get_recent_server_errors  # noqa: F401
import app.tools.local.system_health_tools  # noqa: F401
from app.tools.registry import get_tool_safety_tier


class TestRawLogToolsAreControlPlane:
    def test_read_container_logs_is_control_plane(self) -> None:
        assert get_tool_safety_tier("read_container_logs") == "control_plane"

    def test_get_recent_server_errors_is_control_plane(self) -> None:
        assert get_tool_safety_tier("get_recent_server_errors") == "control_plane"


class TestSystemHealthSummaryStaysReadonly:
    """Regression pin: bumping the dedup-summary tools would break the morning
    health glance with no security gain. They do not return raw log bodies."""

    def test_get_latest_health_summary_stays_readonly(self) -> None:
        assert get_tool_safety_tier("get_latest_health_summary") == "readonly"

    def test_get_system_health_preflight_stays_readonly(self) -> None:
        assert get_tool_safety_tier("get_system_health_preflight") == "readonly"
