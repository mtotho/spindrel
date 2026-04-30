"""Agent tool for running E2E tests against a live Spindrel server instance."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from app.tools.registry import register

E2E_DIR = Path(__file__).parent.parent.parent.parent / "tests" / "e2e"
DEFAULT_E2E_PORT = 18000
DEFAULT_E2E_API_KEY = "e2e-test-key-12345"


@dataclass(frozen=True)
class E2ETarget:
    base_url: str
    host: str
    port: int
    api_key: str
    source: str
    explicit: bool

    @property
    def health_url(self) -> str:
        return f"{self.base_url}/health"


def _normalize_base_url(raw_url: str) -> str:
    value = raw_url.strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")


def _port_for_url(parsed, *, fallback: int) -> int:
    if parsed.port is not None:
        return parsed.port
    return 443 if parsed.scheme == "https" else fallback


def _resolve_e2e_target(environ: Mapping[str, str] | None = None) -> E2ETarget:
    env = environ or os.environ
    api_key = env.get("E2E_API_KEY") or env.get("SPINDREL_E2E_API_KEY") or DEFAULT_E2E_API_KEY

    for name in ("SPINDREL_E2E_URL", "E2E_BASE_URL", "SPINDREL_E2E_BASE_URL"):
        raw_url = env.get(name)
        if raw_url:
            base_url = _normalize_base_url(raw_url)
            parsed = urlparse(base_url)
            return E2ETarget(
                base_url=base_url,
                host=parsed.hostname or "localhost",
                port=_port_for_url(parsed, fallback=DEFAULT_E2E_PORT),
                api_key=api_key,
                source=name,
                explicit=True,
            )

    host = env.get("E2E_HOST") or env.get("SPINDREL_E2E_HOST") or "localhost"
    port_text = env.get("E2E_PORT") or env.get("SPINDREL_E2E_PORT") or str(DEFAULT_E2E_PORT)
    try:
        port = int(port_text)
    except (TypeError, ValueError):
        port = DEFAULT_E2E_PORT
    source = "E2E_HOST/E2E_PORT" if env.get("E2E_HOST") or env.get("E2E_PORT") else "default"
    return E2ETarget(
        base_url=f"http://{host}:{port}",
        host=host,
        port=port,
        api_key=api_key,
        source=source,
        explicit=source != "default",
    )


def _apply_e2e_target_env(env: MutableMapping[str, str], target: E2ETarget) -> None:
    env["E2E_HOST"] = target.host
    env["E2E_PORT"] = str(target.port)
    env["E2E_API_KEY"] = target.api_key
    if target.explicit:
        env.setdefault("E2E_MODE", "external")


@contextmanager
def _patched_e2e_target_env(target: E2ETarget):
    original = {key: os.environ.get(key) for key in ("E2E_HOST", "E2E_PORT", "E2E_API_KEY", "E2E_MODE")}
    _apply_e2e_target_env(os.environ, target)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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
}, safety_tier="exec_capable", returns={
    "type": "object",
    "properties": {
        "running": {"type": "boolean"},
        "health": {"type": "string"},
        "passed": {"type": "boolean"},
        "exit_code": {"type": "integer"},
        "summary": {"type": "string"},
        "output": {"type": "string"},
        "stopped": {"type": "boolean"},
        "scenario": {"type": "string"},
        "steps": {"type": "array"},
        "error": {"type": "string"},
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
        return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)


async def _status() -> str:
    """Check if the E2E test environment is running."""
    target = _resolve_e2e_target()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                target.health_url,
                headers={"Authorization": f"Bearer {target.api_key}"},
            )
            if resp.status_code == 200:
                return json.dumps({
                    "running": True,
                    "target_base_url": target.base_url,
                    "target_source": target.source,
                    "health": resp.json(),
                }, ensure_ascii=False)
            return json.dumps({
                "running": False,
                "target_base_url": target.base_url,
                "target_source": target.source,
                "status_code": resp.status_code,
                "health": resp.text[:500],
            }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "running": False,
            "target_base_url": target.base_url,
            "target_source": target.source,
            "error": str(exc),
        }, ensure_ascii=False)


async def _run(scenarios: str, keep_running: bool, verbose: bool) -> str:
    """Run E2E tests via pytest subprocess."""
    target = _resolve_e2e_target()
    cmd = ["python", "-m", "pytest", str(E2E_DIR)]

    if scenarios:
        cmd.extend(["-k", scenarios])
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")

    # Pass through E2E config
    env = os.environ.copy()
    _apply_e2e_target_env(env, target)
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
        "target_base_url": target.base_url,
        "target_source": target.source,
        "summary": summary_line or ("All tests passed" if result.returncode == 0 else "Tests failed"),
        "output": output[-3000:] if verbose else output[-1000:],
    }, ensure_ascii=False)


async def _run_ad_hoc(scenario_yaml: str) -> str:
    """Execute an ad-hoc scenario defined as inline YAML against the running E2E stack."""
    if not scenario_yaml:
        return json.dumps({"error": "scenario_yaml is required for run_scenario action"}, ensure_ascii=False)

    try:
        import yaml
        raw = yaml.safe_load(scenario_yaml)
    except Exception as e:
        return json.dumps({"error": f"Failed to parse scenario YAML: {e}"}, ensure_ascii=False)

    if not isinstance(raw, dict):
        return json.dumps({"error": "scenario_yaml must be a YAML mapping with scenario fields"}, ensure_ascii=False)

    # Import harness components
    try:
        from tests.e2e.harness.scenario import parse_scenario_from_dict
        from tests.e2e.harness.runner import run_scenario
        from tests.e2e.harness.client import E2EClient
        from tests.e2e.harness.config import E2EConfig
    except ImportError as e:
        return json.dumps({"error": f"Failed to import E2E harness: {e}"}, ensure_ascii=False)

    # Parse scenario
    try:
        scenario = parse_scenario_from_dict(raw, source="<ad-hoc>")
    except Exception as e:
        return json.dumps({"error": f"Failed to parse scenario: {e}"}, ensure_ascii=False)

    # Build client from the same resolved target used by status/run.
    target = _resolve_e2e_target()
    with _patched_e2e_target_env(target):
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
        "target_base_url": target.base_url,
        "target_source": target.source,
        "scenario": result.scenario.name,
        "error": result.error,
        "steps": step_details,
    }, ensure_ascii=False)


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
    }, ensure_ascii=False)
