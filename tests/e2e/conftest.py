"""Pytest fixtures for E2E tests.

Session-scoped environment (compose stack starts once per pytest session).
Function-scoped client (fresh per test, with unique channel IDs for isolation).
Automatic cleanup of test-created channels after each session.
Tiered JSON results output for structured reporting.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio

from .harness.config import E2EConfig
from .harness.environment import E2EEnvironment
from .harness.client import E2EClient

logger = logging.getLogger(__name__)

# Map test file stems to tier names
_FILE_TO_TIER = {
    "test_api_contract": "api_contract",
    "test_regressions": "api_contract",
    "test_server_behavior": "server_behavior",
    "test_workspace_memory": "server_behavior",
    "test_model_smoke": "model_smoke",
}


class _ResultCollector:
    """Collects per-test results and writes tiered JSON summary."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.start_time = time.monotonic()

    def add(self, nodeid: str, outcome: str) -> None:
        # nodeid looks like "tests/e2e/scenarios/test_foo.py::test_bar[param]"
        parts = nodeid.split("::")
        file_stem = parts[0].rsplit("/", 1)[-1].replace(".py", "") if parts else ""
        test_name = parts[-1] if len(parts) > 1 else nodeid
        tier = _FILE_TO_TIER.get(file_stem, "unknown")
        self.results.append({
            "tier": tier,
            "file": file_stem,
            "test": test_name,
            "outcome": outcome,
        })

    def build_summary(self, config: E2EConfig) -> dict:
        duration = time.monotonic() - self.start_time

        # Build tier summaries
        tiers: dict = {}
        for r in self.results:
            tier = r["tier"]
            if tier == "model_smoke":
                # Group by model param: test_name[model]
                model = "unknown"
                if "[" in r["test"] and r["test"].endswith("]"):
                    model = r["test"].rsplit("[", 1)[1][:-1]
                if "model_smoke" not in tiers:
                    tiers["model_smoke"] = {}
                bucket = tiers["model_smoke"].setdefault(model, {
                    "passed": 0, "failed": 0, "tests": [],
                })
                if r["outcome"] == "passed":
                    bucket["passed"] += 1
                else:
                    bucket["failed"] += 1
                    bucket["tests"].append(r["test"])
            else:
                bucket = tiers.setdefault(tier, {"passed": 0, "failed": 0, "tests": []})
                if tier == "server_behavior" and "model" not in bucket:
                    bucket["model"] = config.default_model
                if r["outcome"] == "passed":
                    bucket["passed"] += 1
                else:
                    bucket["failed"] += 1
                    bucket["tests"].append(r["test"])

        total_passed = sum(
            r["outcome"] == "passed" for r in self.results
        )
        total_failed = sum(
            r["outcome"] != "passed" for r in self.results
        )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": f"{duration:.0f}s",
            "status": "pass" if total_failed == 0 else "fail",
            "tiers": tiers,
            "total_passed": total_passed,
            "total_failed": total_failed,
        }


# Session-level collector instance
_collector = _ResultCollector()


def pytest_configure(config: pytest.Config) -> None:
    """Override the default '-m not e2e' when targeting e2e tests directly."""
    # If any of the specified paths are under tests/e2e/, remove the marker filter
    args = config.invocation_params.args
    if any("tests/e2e" in str(a) or "e2e/" in str(a) for a in args):
        # Clear the marker expression that was set by addopts
        config.option.markexpr = ""


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Collect per-test results for tiered JSON output."""
    if report.when == "call":
        _collector.add(report.nodeid, report.outcome)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write tiered JSON results to workspace summary path."""
    summary_path = os.environ.get(
        "E2E_WORKSPACE_SUMMARY",
        os.path.expanduser(
            "~/logs/e2e/e2e-results.json"
        ),
    )
    try:
        config = E2EConfig.from_env()
        summary = _collector.build_summary(config)
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info("E2E results written to %s", summary_path)
    except Exception:
        logger.warning("Failed to write E2E results summary", exc_info=True)


@pytest.fixture(scope="session")
def e2e_config() -> E2EConfig:
    """Load E2E configuration from environment variables."""
    return E2EConfig.from_env()


@pytest_asyncio.fixture(scope="session")
async def e2e_env(e2e_config: E2EConfig) -> AsyncGenerator[E2EEnvironment, None]:
    """Start the E2E compose stack once for the entire test session."""
    env = E2EEnvironment(e2e_config)
    await env.setup()
    yield env
    await env.teardown()


@pytest.fixture(scope="session")
def _channel_tracker() -> list[str]:
    """Session-scoped list to track channel IDs created during tests."""
    return []


@pytest_asyncio.fixture
async def client(
    e2e_config: E2EConfig,
    e2e_env: E2EEnvironment,  # noqa: ARG001 — ensures stack is up
    _channel_tracker: list[str],
) -> AsyncGenerator[E2EClient, None]:
    """Fresh E2E client per test. Tracks created channels for cleanup."""
    c = E2EClient(e2e_config)
    # Wrap chat methods to track channels created via client_id
    _original_chat = c.chat
    _original_stream = c.chat_stream

    async def _tracking_chat(*args, **kwargs):
        result = await _original_chat(*args, **kwargs)
        cid = kwargs.get("client_id")
        if cid:
            _channel_tracker.append(c.derive_channel_id(cid))
        return result

    async def _tracking_stream(*args, **kwargs):
        result = await _original_stream(*args, **kwargs)
        cid = kwargs.get("client_id")
        if cid:
            _channel_tracker.append(c.derive_channel_id(cid))
        return result

    c.chat = _tracking_chat
    c.chat_stream = _tracking_stream
    yield c
    await c.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _cleanup_test_channels(
    e2e_config: E2EConfig,
    e2e_env: E2EEnvironment,  # noqa: ARG001
    _channel_tracker: list[str],
) -> AsyncGenerator[None, None]:
    """Delete all channels created during tests after the session ends."""
    yield
    if not _channel_tracker:
        return

    unique_ids = list(set(_channel_tracker))
    logger.info("Cleaning up %d test channels", len(unique_ids))

    import httpx
    async with httpx.AsyncClient(
        base_url=e2e_config.base_url,
        headers={"Authorization": f"Bearer {e2e_config.api_key}"},
        timeout=30,
    ) as http:
        for ch_id in unique_ids:
            try:
                resp = await http.delete(f"/api/v1/channels/{ch_id}")
                if resp.status_code in (200, 204, 404):
                    logger.debug("Cleaned up channel %s", ch_id)
                else:
                    logger.warning("Failed to delete channel %s: %s", ch_id, resp.status_code)
            except Exception:
                logger.warning("Error cleaning up channel %s", ch_id, exc_info=True)
