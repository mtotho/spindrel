"""Integration depth contracts for rich-result capable renderers.

These tests pin the shared thin interface that prime integrations expose:
YAML declares host-visible capability truth, while the renderer exposes the
same contract to runtime delivery.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.domain.capability import Capability
from integrations.sdk import renderer_registry


ROOT = Path(__file__).resolve().parents[2]
RICH_RESULT_INTEGRATIONS = ("slack", "discord")
EXPECTED_RICH_CONTENT_TYPES = frozenset({
    "text/plain",
    "text/markdown",
    "application/json",
    "application/vnd.spindrel.components+json",
    "application/vnd.spindrel.diff+text",
    "application/vnd.spindrel.file-listing+json",
})
EXPECTED_RICH_VIEW_KEYS = frozenset({
    "core.search_results",
    "core.command_result",
    "core.machine_target_status",
})


def _manifest(integration_id: str) -> dict:
    path = ROOT / "integrations" / integration_id / "integration.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _renderer(integration_id: str):
    if integration_id == "slack":
        import integrations.slack.renderer  # noqa: F401
    if integration_id == "discord":
        import integrations.discord.renderer  # noqa: F401
    renderer = renderer_registry.get(integration_id)
    if renderer is None:
        raise AssertionError(f"{integration_id} renderer was not registered")
    return renderer


@pytest.mark.parametrize("integration_id", RICH_RESULT_INTEGRATIONS)
def test_renderer_capabilities_match_manifest(integration_id: str) -> None:
    manifest = _manifest(integration_id)
    renderer = _renderer(integration_id)

    manifest_caps = frozenset(manifest["capabilities"])
    renderer_caps = frozenset(cap.value for cap in renderer.capabilities)

    assert renderer.integration_id == integration_id
    assert renderer_caps == manifest_caps
    assert Capability.RICH_TOOL_RESULTS.value in manifest_caps


@pytest.mark.parametrize("integration_id", RICH_RESULT_INTEGRATIONS)
def test_rich_tool_result_contract_matches_renderer(integration_id: str) -> None:
    manifest = _manifest(integration_id)
    manifest_support = manifest["tool_result_rendering"]
    renderer_support = _renderer(integration_id).tool_result_rendering

    assert manifest_support["modes"] == ["compact", "full", "none"]
    assert manifest_support["interactive"] is False
    assert manifest_support["unsupported_fallback"] == "badge"
    assert manifest_support["placement"] == "same_message"
    assert frozenset(manifest_support["content_types"]) == EXPECTED_RICH_CONTENT_TYPES
    assert frozenset(manifest_support["view_keys"]) == EXPECTED_RICH_VIEW_KEYS

    assert renderer_support is not None
    assert renderer_support.modes == frozenset(manifest_support["modes"])
    assert renderer_support.content_types == EXPECTED_RICH_CONTENT_TYPES
    assert renderer_support.view_keys == EXPECTED_RICH_VIEW_KEYS
    assert renderer_support.interactive == manifest_support["interactive"]
    assert renderer_support.unsupported_fallback == manifest_support["unsupported_fallback"]
    assert renderer_support.placement == manifest_support["placement"]
    assert renderer_support.limits == manifest_support["limits"]
