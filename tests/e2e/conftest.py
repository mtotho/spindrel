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
    "test_multibot_channels": "multibot",
    "test_server_behavior": "server_behavior",
    "test_workspace_memory": "server_behavior",
    "test_model_smoke": "model_smoke",
    "test_settings_config": "api_contract",
    "test_providers_models": "api_contract",
    "test_channel_details": "api_contract",
    "test_search_indexing": "api_contract",
    "test_tool_policies": "api_contract",
    "test_bot_hooks": "api_contract",
    "test_memory_behavior": "server_behavior",
    "test_workflows": "server_behavior",
    "test_chat_basic": "server_behavior",
    "test_voice_input": "server_behavior",
    "test_chat_stream": "server_behavior",
    "test_skill_loading": "server_behavior",
    "test_harness_live_smoke": "server_behavior",
    "test_harness_live_parity": "server_behavior",
    "test_spindrel_plan_live": "server_behavior",
    "test_widget_improvement_loop": "server_behavior",
}


class _ResultCollector:
    """Collects per-test results and writes tiered JSON summary."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.start_time = time.monotonic()
        self.start_utc = datetime.now(timezone.utc)

    def add(self, nodeid: str, outcome: str, duration: float = 0.0) -> None:
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
            "duration_s": round(duration, 2),
        })

    def build_summary(self, config: E2EConfig) -> dict:
        duration = time.monotonic() - self.start_time

        # Build tier summaries with per-test detail
        tiers: dict = {}
        for r in self.results:
            tier = r["tier"]
            test_entry = {
                "name": r["test"],
                "outcome": r["outcome"],
                "duration_s": r["duration_s"],
            }
            if tier == "model_smoke":
                # Group by model param: test_name[model]
                model = "unknown"
                if "[" in r["test"] and r["test"].endswith("]"):
                    model = r["test"].rsplit("[", 1)[1][:-1]
                    test_entry["name"] = r["test"].rsplit("[", 1)[0]
                if "model_smoke" not in tiers:
                    tiers["model_smoke"] = {}
                bucket = tiers["model_smoke"].setdefault(model, {
                    "passed": 0, "failed": 0, "tests": [],
                })
                if r["outcome"] == "passed":
                    bucket["passed"] += 1
                else:
                    bucket["failed"] += 1
                bucket["tests"].append(test_entry)
            else:
                bucket = tiers.setdefault(tier, {"passed": 0, "failed": 0, "tests": []})
                if tier == "server_behavior" and "model" not in bucket:
                    bucket["model"] = config.default_model
                if r["outcome"] == "passed":
                    bucket["passed"] += 1
                else:
                    bucket["failed"] += 1
                bucket["tests"].append(test_entry)

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

    def fetch_usage(self, config: E2EConfig) -> dict | None:
        """Query the server's usage API for cost/token totals since run start."""
        import httpx

        after = self.start_utc.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            resp = httpx.get(
                f"{config.base_url}/api/v1/admin/usage/summary",
                params={"after": after},
                headers={"Authorization": f"Bearer {config.api_key}"},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("Usage API returned %s", resp.status_code)
                return None
            data = resp.json()
            return {
                "total_calls": data.get("total_calls", 0),
                "total_tokens": data.get("total_tokens", 0),
                "prompt_tokens": data.get("total_prompt_tokens", 0),
                "completion_tokens": data.get("total_completion_tokens", 0),
                "cost_usd": data.get("total_cost"),
                "by_model": [
                    {
                        "model": m.get("label"),
                        "calls": m.get("calls", 0),
                        "tokens": m.get("total_tokens", 0),
                        "cost_usd": m.get("cost"),
                    }
                    for m in data.get("cost_by_model", [])
                ],
            }
        except Exception:
            logger.warning("Failed to fetch usage data", exc_info=True)
            return None


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
        _collector.add(report.nodeid, report.outcome, report.duration)


def _write_results(summary: dict, base_dir: str, ts: str) -> None:
    """Write latest results + timestamped history copy to a directory."""
    os.makedirs(base_dir, exist_ok=True)
    with open(os.path.join(base_dir, "e2e-results.json"), "w") as f:
        json.dump(summary, f, indent=2)
    history_dir = os.path.join(base_dir, "e2e-history")
    os.makedirs(history_dir, exist_ok=True)
    with open(os.path.join(history_dir, f"{ts}.json"), "w") as f:
        json.dump(summary, f, indent=2)
    _update_status(summary, history_dir, base_dir)


def _update_status(current: dict, history_dir: str, base_dir: str) -> None:
    """Update e2e-status.json — lightweight summary a bot can quick-scan.

    Includes current run headline + per-test failure rates across recent history.
    """
    from collections import defaultdict
    from pathlib import Path

    # Load recent history (last 20 runs)
    history_files = sorted(Path(history_dir).glob("*.json"), reverse=True)[:20]
    runs = []
    for f in history_files:
        try:
            with open(f) as fh:
                runs.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue

    # Build per-test stats across runs
    stats: dict[str, dict] = defaultdict(lambda: {"runs": 0, "failures": 0})
    for run in runs:
        for tier_data in run.get("tiers", {}).values():
            tests = tier_data.get("tests", [])
            if not tests and isinstance(tier_data, dict):
                # model_smoke nesting
                for bucket in tier_data.values():
                    if isinstance(bucket, dict):
                        for t in bucket.get("tests", []):
                            s = stats[t["name"]]
                            s["runs"] += 1
                            if t["outcome"] != "passed":
                                s["failures"] += 1
                continue
            for t in tests:
                s = stats[t["name"]]
                s["runs"] += 1
                if t["outcome"] != "passed":
                    s["failures"] += 1

    # Identify problem tests
    flaky = []
    for name, s in stats.items():
        if s["failures"] > 0:
            rate = round(s["failures"] / s["runs"], 2)
            flaky.append({
                "test": name,
                "failure_rate": rate,
                "failures": s["failures"],
                "runs": s["runs"],
            })
    flaky.sort(key=lambda x: -x["failure_rate"])

    # Current run failures
    current_failures = []
    for tier_data in current.get("tiers", {}).values():
        for t in tier_data.get("tests", []):
            if t.get("outcome") != "passed":
                current_failures.append(t["name"])

    status = {
        "last_run": current.get("timestamp"),
        "last_duration": current.get("duration"),
        "last_status": current.get("status"),
        "passed": current.get("total_passed", 0),
        "failed": current.get("total_failed", 0),
        "current_failures": current_failures,
        "runs_analyzed": len(runs),
        "flaky_tests": flaky,
    }

    with open(os.path.join(base_dir, "e2e-status.json"), "w") as f:
        json.dump(status, f, indent=2)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write tiered JSON results to logs dir and workspace (if set)."""
    try:
        config = E2EConfig.from_env()
        summary = _collector.build_summary(config)

        # Fetch cost/token usage from the server
        usage = _collector.fetch_usage(config)
        if usage:
            summary["usage"] = usage

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

        # Always write to ~/logs/e2e/
        logs_dir = os.path.expanduser("~/logs/e2e")
        _write_results(summary, logs_dir, ts)
        logger.info("E2E results written to %s", logs_dir)

        # Also write to workspace if E2E_WORKSPACE_DIR is set
        ws_dir = os.environ.get("E2E_WORKSPACE_DIR")
        if ws_dir:
            _write_results(summary, ws_dir, ts)
            logger.info("E2E results mirrored to workspace %s", ws_dir)
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


def _is_e2e_channel(channel: dict) -> bool:
    """Check if a channel was created by E2E tests."""
    client_id = channel.get("client_id") or ""
    name = channel.get("name") or ""
    bot_id = channel.get("bot_id") or ""
    return (
        client_id.startswith("e2e-")
        or name.startswith("chat:e2e")
        or bot_id.startswith("e2e-tmp-")
    )


async def _sweep_stale_e2e_channels(base_url: str, api_key: str) -> None:
    """Delete any e2e channels left over from prior interrupted runs.

    Matches on client_id prefix, channel name, or bot_id since channels
    created via chat may have client_id=None but a recognizable name.
    """
    import httpx
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    ) as http:
        try:
            resp = await http.get("/api/v1/admin/channels?page_size=100")
            if resp.status_code != 200:
                return
            channels = resp.json().get("channels", [])
            stale = [c["id"] for c in channels if _is_e2e_channel(c)]
            if stale:
                logger.info("Sweeping %d stale e2e channels from prior runs", len(stale))
                for ch_id in stale:
                    await http.delete(f"/api/v1/channels/{ch_id}")
        except Exception:
            logger.warning("Failed to sweep stale e2e channels", exc_info=True)


async def _sweep_stale_e2e_resources(base_url: str, api_key: str) -> None:
    """Delete stale e2e-* bots and skills from prior runs."""
    import httpx
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    ) as http:
        try:
            # Sweep temp bots (e2e-tmp-*)
            resp = await http.get("/api/v1/admin/bots")
            if resp.status_code == 200:
                bots = resp.json()
                if isinstance(bots, list):
                    stale = [b["id"] for b in bots if (b.get("id") or "").startswith("e2e-tmp-")]
                    if stale:
                        logger.info("Sweeping %d stale e2e bots", len(stale))
                        for bot_id in stale:
                            await http.delete(f"/api/v1/admin/bots/{bot_id}?force=true")

            # Sweep test skills (e2e-skill-*)
            resp = await http.get("/api/v1/admin/skills")
            if resp.status_code == 200:
                skills = resp.json()
                if isinstance(skills, list):
                    stale = [s["id"] for s in skills if (s.get("id") or "").startswith("e2e-skill-")]
                    if stale:
                        logger.info("Sweeping %d stale e2e skills", len(stale))
                        for skill_id in stale:
                            await http.delete(f"/api/v1/admin/skills/{skill_id}")
        except Exception:
            logger.warning("Failed to sweep stale e2e resources", exc_info=True)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _cleanup_test_channels(
    e2e_config: E2EConfig,
    e2e_env: E2EEnvironment,  # noqa: ARG001
    _channel_tracker: list[str],
) -> AsyncGenerator[None, None]:
    """Sweep stale channels/resources at start, delete tracked channels at end."""
    preserve_harness_parity = (
        os.environ.get("HARNESS_PARITY_LOCAL") == "1"
        and os.environ.get("HARNESS_PARITY_NATIVE_APP") == "1"
    )

    # Clean up leftovers from interrupted prior runs
    await _sweep_stale_e2e_channels(e2e_config.base_url, e2e_config.api_key)
    await _sweep_stale_e2e_resources(e2e_config.base_url, e2e_config.api_key)

    yield

    if preserve_harness_parity:
        logger.info("Preserving local harness parity fixture channels after focused run")
        return

    # Clean up channels created during this session (broad sweep catches all)
    await _sweep_stale_e2e_channels(e2e_config.base_url, e2e_config.api_key)
    await _sweep_stale_e2e_resources(e2e_config.base_url, e2e_config.api_key)

    # Also clean tracked channels that might not match the sweep patterns
    unique_ids = list(set(_channel_tracker))
    if not unique_ids:
        return

    logger.info("Cleaning up %d tracked test channels", len(unique_ids))

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
