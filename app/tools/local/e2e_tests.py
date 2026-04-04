"""Agent tool for running E2E tests against a live Spindrel server instance."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from app.tools.registry import register

E2E_DIR = Path(__file__).parent.parent.parent.parent / "tests" / "e2e"


@register({
    "type": "function",
    "function": {
        "name": "run_e2e_tests",
        "description": (
            "Run end-to-end tests against a live Spindrel server instance. "
            "Tests exercise the full pipeline: message → context assembly → LLM → tools → response. "
            "Actions: 'status' (check if test env is running), 'run' (start env + run tests), "
            "'stop' (tear down test env), 'run_scenario' (execute an ad-hoc inline YAML scenario)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "run", "stop", "run_scenario"],
                    "description": "Action to perform.",
                },
                "scenarios": {
                    "type": "string",
                    "description": (
                        "Optional filter: specific scenario file or keyword "
                        "(e.g. 'test_health' or 'test_tool_usage'). "
                        "Omit to run all scenarios."
                    ),
                },
                "scenario_yaml": {
                    "type": "string",
                    "description": (
                        "YAML content defining a scenario to run ad-hoc (for action='run_scenario'). "
                        "Must define a single scenario dict with 'name', 'steps', and optionally "
                        "'bot_id', 'bot' (inline bot config), 'tags', 'timeout'."
                    ),
                },
                "keep_running": {
                    "type": "boolean",
                    "description": "Keep the test environment running after tests complete (for debugging).",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Show verbose test output.",
                },
            },
            "required": ["action"],
        },
    },
})
async def run_e2e_tests(
    action: str,
    scenarios: str = "",
    scenario_yaml: str = "",
    keep_running: bool = False,
    verbose: bool = False,
) -> str:
    if action == "status":
        return await _status()
    elif action == "run":
        return await _run(scenarios, keep_running, verbose)
    elif action == "stop":
        return await _stop()
    elif action == "run_scenario":
        return await _run_ad_hoc(scenario_yaml)
    else:
        return json.dumps({"error": f"Unknown action: {action}"})


async def _status() -> str:
    """Check if the E2E test environment is running."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "http://localhost:18000/health",
                headers={"Authorization": "Bearer e2e-test-key-12345"},
            )
            if resp.status_code == 200:
                return json.dumps({
                    "running": True,
                    "health": resp.json(),
                })
    except Exception:
        pass
    return json.dumps({"running": False})


async def _run(scenarios: str, keep_running: bool, verbose: bool) -> str:
    """Run E2E tests via pytest subprocess."""
    import os

    cmd = ["python", "-m", "pytest", str(E2E_DIR)]

    if scenarios:
        cmd.extend(["-k", scenarios])
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")

    # Pass through E2E config
    env = os.environ.copy()
    if keep_running:
        env["E2E_KEEP_RUNNING"] = "1"

    def _subprocess() -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
            cwd=str(E2E_DIR.parent.parent),  # project root
        )

    result = await asyncio.to_thread(_subprocess)

    # Parse pytest output for summary
    output = result.stdout + result.stderr
    summary_line = ""
    for line in output.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            summary_line = line.strip()

    return json.dumps({
        "passed": result.returncode == 0,
        "exit_code": result.returncode,
        "summary": summary_line or ("All tests passed" if result.returncode == 0 else "Tests failed"),
        "output": output[-3000:] if verbose else output[-1000:],
    })


async def _run_ad_hoc(scenario_yaml: str) -> str:
    """Execute an ad-hoc scenario defined as inline YAML against the running E2E stack."""
    if not scenario_yaml:
        return json.dumps({"error": "scenario_yaml is required for run_scenario action"})

    try:
        import yaml
        raw = yaml.safe_load(scenario_yaml)
    except Exception as e:
        return json.dumps({"error": f"Failed to parse scenario YAML: {e}"})

    if not isinstance(raw, dict):
        return json.dumps({"error": "scenario_yaml must be a YAML mapping with scenario fields"})

    # Import harness components
    try:
        from tests.e2e.harness.scenario import parse_scenario_from_dict
        from tests.e2e.harness.runner import run_scenario
        from tests.e2e.harness.client import E2EClient
        from tests.e2e.harness.config import E2EConfig
    except ImportError as e:
        return json.dumps({"error": f"Failed to import E2E harness: {e}"})

    # Parse scenario
    try:
        scenario = parse_scenario_from_dict(raw, source="<ad-hoc>")
    except Exception as e:
        return json.dumps({"error": f"Failed to parse scenario: {e}"})

    # Build client from env/defaults
    config = E2EConfig.from_env()
    client = E2EClient(config)

    try:
        result = await run_scenario(client, scenario)
    finally:
        await client.close()

    # Format result
    step_details = []
    for sr in result.step_results:
        step_details.append({
            "step": sr.step_index,
            "passed": sr.passed,
            "tools_used": sr.tools_used,
            "response_preview": sr.response_text[:300] if sr.response_text else "",
            "failures": sr.failures,
        })

    return json.dumps({
        "passed": result.passed,
        "scenario": result.scenario.name,
        "error": result.error,
        "steps": step_details,
    })


async def _stop() -> str:
    """Tear down the E2E test environment."""
    compose_file = E2E_DIR / "docker-compose.e2e.yml"

    def _subprocess() -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "docker", "compose",
                "-f", str(compose_file),
                "-p", "spindrel-e2e",
                "down", "-v", "--remove-orphans",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

    result = await asyncio.to_thread(_subprocess)
    return json.dumps({
        "stopped": result.returncode == 0,
        "output": (result.stdout + result.stderr)[-500:],
    })
