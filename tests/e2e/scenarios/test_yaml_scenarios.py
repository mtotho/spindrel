"""Run YAML-defined E2E scenarios via pytest parametrize.

Discovers all .yaml files in the yaml/ subdirectory at import time.
If the directory is missing or empty, no tests are collected (silent skip).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.runner import run_scenario
from tests.e2e.harness.scenario import Scenario, load_scenarios_from_directory

YAML_DIR = Path(__file__).parent / "yaml"


def _collect_scenarios() -> list[Scenario]:
    """Load all scenarios from the yaml/ directory at module level."""
    return load_scenarios_from_directory(YAML_DIR)


_ALL_SCENARIOS = _collect_scenarios()


@pytest.mark.e2e
@pytest.mark.parametrize(
    "scenario",
    _ALL_SCENARIOS,
    ids=[s.test_id for s in _ALL_SCENARIOS],
)
async def test_yaml_scenario(client: E2EClient, scenario: Scenario) -> None:
    """Execute a single YAML scenario and assert all steps pass."""
    # Scenarios with inline bots can't run in external mode (no bot creation)
    if client.config.is_external and scenario.bot:
        pytest.skip("Inline bot scenario — requires compose mode")

    result = await run_scenario(client, scenario)

    if result.error:
        pytest.fail(f"Scenario {scenario.name!r} failed: {result.error}")

    if not result.passed:
        lines = [f"Scenario {scenario.name!r} failed:"]
        for sr in result.step_results:
            if not sr.passed:
                lines.append(f"  Step {sr.step_index}:")
                for f in sr.failures:
                    lines.append(f"    - {f}")
                if sr.tools_used:
                    lines.append(f"    tools_used: {sr.tools_used}")
                if sr.response_text:
                    lines.append(
                        f"    response: {sr.response_text[:200]!r}"
                    )
        pytest.fail("\n".join(lines))
