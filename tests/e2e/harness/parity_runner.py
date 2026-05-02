"""Canonical Module for harness parity tier orchestration.

Owns:

- ``TIER_ORDER`` — single source of truth for harness parity tier ranks.
- ``HARNESS_PARITY_RUNTIME_CONFIG`` — codex/claude-code runtime metadata.
- ``HarnessEnv`` — typed env builder consumed by run_tier and the bash preflight.
- ``DEFAULT_ALLOWED_SKIP_REGEX`` — regex of pytest skips intentionally permitted.
- ``validate_skips`` — JUnit skip validator (replaces the body of
  ``scripts.harness_parity_junit_skips``; the script is now a thin re-export shim).
- ``validate_tier_requirements`` — preflight check that the deployed API exposes
  the routes a tier needs (replaces the inline-Python in
  ``scripts/run_harness_parity_live.sh``).

Phase 1 lands the registries + validators. Later phases add ``run_tier``,
``run_batch``, ``cmd_prepare`` and a CLI entry so the bash wrappers can shell
out to ``python -m tests.e2e.harness.parity_runner``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence, TypedDict


TIER_ORDER: dict[str, int] = {
    "core": 0,
    "bridge": 1,
    "terminal": 2,
    "plan": 3,
    "heartbeat": 4,
    "automation": 5,
    "writes": 6,
    "context": 7,
    "project": 8,
    "memory": 9,
    "skills": 10,
    "replay": 11,
}


def tier_rank(tier: str) -> int:
    """Return the numeric rank of ``tier``; unknown tiers map to 0."""
    return TIER_ORDER.get(tier, 0)


def tier_at_least(current: str, required: str) -> bool:
    """True when ``current`` covers ``required`` per ``TIER_ORDER``."""
    return tier_rank(current) >= TIER_ORDER[required]


class RuntimeConfig(TypedDict):
    integration_id: str
    bot_id: str
    bot_name: str
    bot_model: str
    channel_client_id: str
    channel_name: str
    channel_env: str
    bot_env: str
    install_endpoints: tuple[str, ...]


HARNESS_PARITY_RUNTIME_CONFIG: dict[str, RuntimeConfig] = {
    "codex": {
        "integration_id": "codex",
        "bot_id": "harness-parity-codex",
        "bot_name": "Harness Parity Codex",
        "bot_model": "gpt-5.4-mini",
        "channel_client_id": "harness-parity:codex",
        "channel_name": "Harness Parity - Codex",
        "channel_env": "HARNESS_PARITY_CODEX_CHANNEL_ID",
        "bot_env": "HARNESS_PARITY_CODEX_BOT_ID",
        "install_endpoints": ("/install-npm-deps",),
    },
    "claude-code": {
        "integration_id": "claude_code",
        "bot_id": "harness-parity-claude",
        "bot_name": "Harness Parity Claude",
        "bot_model": "claude-haiku-4-5",
        "channel_client_id": "harness-parity:claude",
        "channel_name": "Harness Parity - Claude",
        "channel_env": "HARNESS_PARITY_CLAUDE_CHANNEL_ID",
        "bot_env": "HARNESS_PARITY_CLAUDE_BOT_ID",
        "install_endpoints": ("/install-deps",),
    },
}


HARNESS_PARITY_DEFAULT_RUNTIMES: tuple[str, ...] = ("codex", "claude-code")


DEFAULT_ALLOWED_SKIP_REGEX: str = (
    r"Claude Code-specific|Codex app-server owns|does not advertise native compaction"
)


Skip = tuple[str, str]


def validate_skips(
    path: str | os.PathLike[str],
    allowed_skip_regex: str | None = DEFAULT_ALLOWED_SKIP_REGEX,
) -> list[Skip]:
    """Return JUnit ``<testcase>`` skips not matching ``allowed_skip_regex``."""
    allowed_re = re.compile(allowed_skip_regex) if allowed_skip_regex else None
    root = ET.parse(os.fspath(path)).getroot()
    unexpected: list[Skip] = []
    for node in root.iter():
        if node.tag != "testcase":
            continue
        skipped_nodes = [child for child in node if child.tag == "skipped"]
        if not skipped_nodes:
            continue
        name = f"{node.attrib.get('classname', '')}.{node.attrib.get('name', '')}"
        message = " ".join(
            str(child.attrib.get("message", "")) for child in skipped_nodes
        )
        if allowed_re and allowed_re.search(f"{name} {message}"):
            continue
        unexpected.append((name, message))
    return unexpected


def required_routes(tier: str) -> tuple[str, ...]:
    """Return OpenAPI paths the deployed server must expose for ``tier``."""
    routes: list[str] = [
        "/api/v1/channels/{channel_id}/sessions",
    ]
    if tier_at_least(tier, "terminal"):
        routes.append("/api/v1/admin/docker-stacks")
    return tuple(routes)


def validate_tier_requirements(
    tier: str,
    openapi_paths: Iterable[str],
) -> list[str]:
    """Return required routes that are missing from ``openapi_paths``.

    The legacy ``/api/v1/channels/{channel_id}/reset`` route can substitute for
    ``/api/v1/channels/{channel_id}/sessions``; both being absent counts as
    one missing route.
    """
    paths = set(openapi_paths)
    missing: list[str] = []
    if (
        "/api/v1/channels/{channel_id}/sessions" not in paths
        and "/api/v1/channels/{channel_id}/reset" not in paths
    ):
        missing.append(
            "/api/v1/channels/{channel_id}/sessions "
            "(or legacy /api/v1/channels/{channel_id}/reset)"
        )
    if tier_at_least(tier, "terminal") and "/api/v1/admin/docker-stacks" not in paths:
        missing.append("/api/v1/admin/docker-stacks")
    return missing


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


@dataclass
class HarnessEnv:
    """Resolved env for one harness parity invocation.

    Built from the env-file chain ``.env.agent-e2e`` →
    ``${AGENT_STATE_DIR}/native-api.env`` → ``${AGENT_STATE_DIR}/harness-parity.env``
    plus the live process environment. The agent-owned port strategy means
    ``E2E_PORT`` MUST resolve from that chain — there is no shared default.
    """

    e2e_host: str
    e2e_port: int
    e2e_api_key: str
    e2e_mode: str = "external"
    e2e_bot_id: str = "default"
    e2e_request_timeout: int = 300
    e2e_startup_timeout: int = 120

    tier: str = "core"
    timeout: int = 300
    health_wait_timeout: int = 120
    codex_channel_id: str = ""
    claude_channel_id: str = ""
    agent_container: str = ""
    playwright_host: str = "playwright-local"
    playwright_container: str = "spindrel-local-browser-automation-playwright-1"
    project_path: str = "common/projects"
    project_timeout: int = 600
    capture_screenshots: str = "auto"
    screenshot_output_dir: str = "/tmp/spindrel-harness-live-screenshots"
    screenshot_only: str = ""
    fail_on_skips: bool = False
    pytest_junit_xml: str = ""
    allowed_skip_regex: str = DEFAULT_ALLOWED_SKIP_REGEX

    spindrel_browser_url: str = ""
    spindrel_browser_api_url: str = ""
    spindrel_ui_url: str = ""

    extras: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        repo_root: Path | None = None,
        env_files: Iterable[Path] | None = None,
        require_port: bool = True,
    ) -> "HarnessEnv":
        """Resolve ``HarnessEnv`` from env files + process environment.

        ``env_files`` defaults to the agent-owned chain rooted at
        ``$SPINDREL_AGENT_E2E_STATE_DIR``. If ``require_port`` is True and
        ``E2E_PORT`` cannot be resolved, raises ``RuntimeError`` — never falls
        back to a shared default port.
        """
        env: dict[str, str] = {}
        repo_root = repo_root or Path.cwd()

        if env_files is None:
            chain: list[Path] = [repo_root / ".env.agent-e2e"]
            state_dir_raw = (
                (environ or os.environ).get("SPINDREL_AGENT_E2E_STATE_DIR", "").strip()
            )
            if state_dir_raw:
                state_dir = Path(state_dir_raw)
                if not state_dir.is_absolute():
                    state_dir = repo_root / state_dir
                chain.append(state_dir / "native-api.env")
                chain.append(state_dir / "harness-parity.env")
            env_files = chain

        for path in env_files:
            for key, value in _read_env_file(Path(path)).items():
                env.setdefault(key, value)

        for key, value in (environ or os.environ).items():
            env[key] = value

        port_raw = env.get("E2E_PORT", "").strip()
        if not port_raw:
            if require_port:
                raise RuntimeError(
                    "E2E_PORT is not set; the agent-owned port strategy requires "
                    "running `python scripts/agent_e2e_dev.py write-env --port auto` "
                    "before invoking the harness parity runner. Refusing to fall "
                    "back to a shared default."
                )
            port = 0
        else:
            try:
                port = int(port_raw)
            except ValueError as exc:
                raise RuntimeError(f"E2E_PORT={port_raw!r} is not an integer") from exc

        api_key = env.get("E2E_API_KEY", "").strip()
        if require_port and not api_key:
            raise RuntimeError(
                "E2E_API_KEY is required; set it in .env.agent-e2e or the process env."
            )

        host = env.get("E2E_HOST", "127.0.0.1").strip() or "127.0.0.1"

        return cls(
            e2e_host=host,
            e2e_port=port,
            e2e_api_key=api_key,
            e2e_mode=env.get("E2E_MODE", "external"),
            e2e_bot_id=env.get("E2E_BOT_ID", "default"),
            e2e_request_timeout=_int(env.get("E2E_REQUEST_TIMEOUT"), 300),
            e2e_startup_timeout=_int(env.get("E2E_STARTUP_TIMEOUT"), 120),
            tier=env.get("HARNESS_PARITY_TIER", "core"),
            timeout=_int(env.get("HARNESS_PARITY_TIMEOUT"), 300),
            health_wait_timeout=_int(env.get("HARNESS_PARITY_HEALTH_WAIT_TIMEOUT"), 120),
            codex_channel_id=env.get("HARNESS_PARITY_CODEX_CHANNEL_ID", ""),
            claude_channel_id=env.get("HARNESS_PARITY_CLAUDE_CHANNEL_ID", ""),
            agent_container=env.get("HARNESS_PARITY_AGENT_CONTAINER", ""),
            playwright_host=env.get("HARNESS_PARITY_PLAYWRIGHT_HOST", "playwright-local"),
            playwright_container=env.get(
                "HARNESS_PARITY_PLAYWRIGHT_CONTAINER",
                "spindrel-local-browser-automation-playwright-1",
            ),
            project_path=env.get("HARNESS_PARITY_PROJECT_PATH", "common/projects"),
            project_timeout=_int(env.get("HARNESS_PARITY_PROJECT_TIMEOUT"), 600),
            capture_screenshots=env.get("HARNESS_PARITY_CAPTURE_SCREENSHOTS", "auto"),
            screenshot_output_dir=env.get(
                "HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR",
                "/tmp/spindrel-harness-live-screenshots",
            ),
            screenshot_only=env.get("HARNESS_PARITY_SCREENSHOT_ONLY", ""),
            fail_on_skips=_bool(env.get("HARNESS_PARITY_FAIL_ON_SKIPS"), False),
            pytest_junit_xml=env.get("HARNESS_PARITY_PYTEST_JUNIT_XML", ""),
            allowed_skip_regex=env.get(
                "HARNESS_PARITY_ALLOWED_SKIP_REGEX", DEFAULT_ALLOWED_SKIP_REGEX
            ),
            spindrel_browser_url=env.get("SPINDREL_BROWSER_URL", ""),
            spindrel_browser_api_url=env.get("SPINDREL_BROWSER_API_URL", ""),
            spindrel_ui_url=env.get("SPINDREL_UI_URL", ""),
        )

    def to_env(self) -> dict[str, str]:
        """Serialize to a flat ``dict[str, str]`` for subprocess passing."""
        result: dict[str, str] = {
            "E2E_MODE": self.e2e_mode,
            "E2E_HOST": self.e2e_host,
            "E2E_PORT": str(self.e2e_port),
            "E2E_API_KEY": self.e2e_api_key,
            "E2E_BOT_ID": self.e2e_bot_id,
            "E2E_REQUEST_TIMEOUT": str(self.e2e_request_timeout),
            "E2E_STARTUP_TIMEOUT": str(self.e2e_startup_timeout),
            "HARNESS_PARITY_TIER": self.tier,
            "HARNESS_PARITY_TIMEOUT": str(self.timeout),
            "HARNESS_PARITY_HEALTH_WAIT_TIMEOUT": str(self.health_wait_timeout),
            "HARNESS_PARITY_CODEX_CHANNEL_ID": self.codex_channel_id,
            "HARNESS_PARITY_CLAUDE_CHANNEL_ID": self.claude_channel_id,
            "HARNESS_PARITY_PLAYWRIGHT_HOST": self.playwright_host,
            "HARNESS_PARITY_PLAYWRIGHT_CONTAINER": self.playwright_container,
            "HARNESS_PARITY_PROJECT_PATH": self.project_path,
            "HARNESS_PARITY_PROJECT_TIMEOUT": str(self.project_timeout),
            "HARNESS_PARITY_CAPTURE_SCREENSHOTS": self.capture_screenshots,
            "HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR": self.screenshot_output_dir,
            "HARNESS_PARITY_SCREENSHOT_ONLY": self.screenshot_only,
            "HARNESS_PARITY_FAIL_ON_SKIPS": "true" if self.fail_on_skips else "false",
            "HARNESS_PARITY_PYTEST_JUNIT_XML": self.pytest_junit_xml,
            "HARNESS_PARITY_ALLOWED_SKIP_REGEX": self.allowed_skip_regex,
        }
        if self.agent_container:
            result["HARNESS_PARITY_AGENT_CONTAINER"] = self.agent_container
        if self.spindrel_browser_url:
            result["SPINDREL_BROWSER_URL"] = self.spindrel_browser_url
        if self.spindrel_browser_api_url:
            result["SPINDREL_BROWSER_API_URL"] = self.spindrel_browser_api_url
        if self.spindrel_ui_url:
            result["SPINDREL_UI_URL"] = self.spindrel_ui_url
        result.update(self.extras)
        return result


def _int(value: str | None, default: int) -> int:
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def cmd_prepare(args) -> int:
    """Provision local harness parity stack/channels and write the env file.

    Moved from ``scripts.agent_e2e_dev.cmd_prepare_harness_parity``. Behavior is
    byte-equivalent; helpers still live in ``agent_e2e_dev`` and are imported
    lazily here to avoid a top-level cycle (``agent_e2e_dev`` imports
    ``HARNESS_PARITY_RUNTIME_CONFIG`` from this module at top level).
    """
    from scripts import agent_e2e_dev as dev

    env = dev._merged_env()
    native_app = not args.docker_app
    if native_app and args.skip_setup:
        env = dev._merge_previous_native_api_env(env)
    api_url = (args.api_url or dev._base_url(env)).rstrip("/")
    dev._require_non_production(api_url, allow_production=args.allow_production)
    api_key = args.api_key or dev._api_key(env)
    runtimes = tuple(args.runtime or HARNESS_PARITY_DEFAULT_RUNTIMES)
    unknown = sorted(set(runtimes) - set(HARNESS_PARITY_RUNTIME_CONFIG))
    if unknown:
        raise SystemExit(
            f"unsupported harness parity runtime(s): {', '.join(unknown)}"
        )

    if args.docker_app:
        dev._ensure_auth_override()
        env = dev._merged_env()
    if not args.skip_setup:
        if native_app and not args.skip_ui_build:
            dev._ensure_built_ui()
        if native_app:
            api_url = dev._ensure_native_api(
                api_url=api_url,
                api_key=api_key,
                env=env,
                startup_timeout=args.startup_timeout,
            )
        else:
            dev._prepare_stack(
                api_url=api_url,
                api_key=api_key,
                env=env,
                build=not args.no_build,
                startup_timeout=args.startup_timeout,
            )
    elif native_app:
        api_url = dev._start_native_api(
            api_url, api_key, env, startup_timeout=args.startup_timeout
        )

    for runtime in runtimes:
        config = HARNESS_PARITY_RUNTIME_CONFIG[runtime]
        integration_id = str(config["integration_id"])
        dev._set_integration_enabled(api_url, api_key, integration_id)
        dev._install_integration_dependencies(
            api_url,
            api_key,
            integration_id,
            tuple(config.get("install_endpoints") or ()),
        )
    dev._set_integration_enabled(api_url, api_key, "browser_automation")

    if native_app:
        api_url = dev._restart_native_api(
            api_url, api_key, env, timeout=args.startup_timeout
        )
    else:
        dev._restart_spindrel_app_container(
            api_url,
            api_key,
            env,
            timeout=args.startup_timeout,
        )
    dev._ensure_browser_automation_stack(api_url, api_key)

    project = dev._ensure_project(
        api_url,
        api_key,
        slug=dev.HARNESS_PARITY_PROJECT_SLUG,
        name=dev.HARNESS_PARITY_PROJECT_NAME,
        root_path=args.project_path,
        metadata={
            "scenario": "harness_parity",
            "dev_targets": dev._project_dev_targets(),
        },
    )
    project_id = str(project.get("id") or "")
    if not project_id:
        raise SystemExit(
            f"project create/update response did not include an id: {project}"
        )

    channel_ids: dict[str, str] = {}
    for runtime in runtimes:
        config = HARNESS_PARITY_RUNTIME_CONFIG[runtime]
        dev._wait_for_harness_runtime(
            api_url,
            api_key,
            runtime,
            timeout=args.runtime_timeout,
        )
        if runtime == "claude-code" and not args.skip_live_auth_check:
            if native_app:
                dev._validate_claude_live_auth_native()
            else:
                dev._validate_claude_live_auth(
                    f"{dev.APP_COMPOSE_PROJECT}-spindrel-1"
                )
        dev._ensure_harness_parity_bot(
            api_url,
            api_key,
            bot_id=str(config["bot_id"]),
            name=str(config["bot_name"]),
            runtime=runtime,
            model=str(config["bot_model"]),
        )
        channel_ids[runtime] = dev._ensure_harness_parity_channel(
            api_url,
            api_key,
            client_id=str(config["channel_client_id"]),
            name=str(config["channel_name"]),
            bot_id=str(config["bot_id"]),
            project_id=project_id,
        )

    dev._write_harness_parity_env(
        api_url=api_url,
        api_key=api_key,
        channel_ids_by_runtime=channel_ids,
        project_id=project_id,
        project_path=args.project_path,
        native_app=native_app,
    )
    print("Local harness parity readiness: ok")
    print(f"  target: {api_url}")
    print(f"  env: {dev.HARNESS_PARITY_ENV}")
    print("  run: ./scripts/run_harness_parity_local.sh --tier core")
    return 0


PARITY_TEST_FILE: str = "tests/e2e/scenarios/test_harness_live_parity.py"


def run_tier(
    tier: str,
    *,
    selector: str | None = None,
    junit_xml: str | os.PathLike[str] | None = None,
    pytest_args: Sequence[str] = (),
    pytest_bin: str | None = None,
    extra_env: Mapping[str, str] | None = None,
    runner: "_PytestRunner | None" = None,
) -> int:
    """Invoke pytest for one harness parity tier.

    Builds ``pytest tests/e2e/scenarios/test_harness_live_parity.py -q -rs
    [--junitxml ...] [-k SELECTOR]`` with ``HARNESS_PARITY_TIER=tier`` exported.
    Returns the pytest exit code.

    The bash wrappers shell out to this via ``python -m
    tests.e2e.harness.parity_runner live --tier ...``; tests inject ``runner``
    to assert command shape without spawning a subprocess.
    """
    pytest_bin = pytest_bin or _resolve_pytest_bin()
    cmd: list[str] = [pytest_bin, PARITY_TEST_FILE, "-q", "-rs"]
    if junit_xml:
        Path(os.fspath(junit_xml)).parent.mkdir(parents=True, exist_ok=True)
        cmd += ["--junitxml", str(junit_xml)]
    if selector:
        cmd += ["-k", selector]
    cmd += list(pytest_args)

    proc_env = dict(os.environ)
    if extra_env:
        proc_env.update(extra_env)
    proc_env["HARNESS_PARITY_TIER"] = tier
    if junit_xml:
        proc_env["HARNESS_PARITY_PYTEST_JUNIT_XML"] = str(junit_xml)

    if runner is not None:
        return runner(cmd, proc_env)
    return subprocess.call(cmd, env=proc_env)


_PytestRunner = "callable[[list[str], dict[str, str]], int]"


def _resolve_pytest_bin() -> str:
    candidate = Path(".venv/bin/pytest")
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return "pytest"


def _read_openapi_paths(path: str | os.PathLike[str]) -> set[str]:
    with open(os.fspath(path), "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    paths = doc.get("paths") or {}
    return set(paths)


def _cmd_live(args: argparse.Namespace) -> int:
    return run_tier(
        args.tier,
        selector=args.selector,
        junit_xml=args.junit_xml,
        pytest_args=args.pytest_args,
        pytest_bin=args.pytest_bin,
    )


def _cmd_tier_rank(args: argparse.Namespace) -> int:
    print(tier_rank(args.tier))
    return 0


def _cmd_tier_at_least(args: argparse.Namespace) -> int:
    if args.required not in TIER_ORDER:
        print(f"unknown required tier: {args.required}", file=sys.stderr)
        return 2
    return 0 if tier_at_least(args.current, args.required) else 1


def _cmd_validate_routes(args: argparse.Namespace) -> int:
    paths = _read_openapi_paths(args.openapi_paths_file)
    missing = validate_tier_requirements(args.tier, paths)
    if not missing:
        return 0
    print(
        "Harness parity preflight failed: deployed API is missing required routes:",
        file=sys.stderr,
    )
    for route in missing:
        print(f"  - {route}", file=sys.stderr)
    print(
        "Redeploy/restart the server image that contains the current harness "
        "parity API surface before running this tier.",
        file=sys.stderr,
    )
    return 1


def _cmd_expand_slices(args: argparse.Namespace) -> int:
    from tests.e2e.harness import parity_presets

    if args.preset not in parity_presets.PRESETS:
        print(
            f"Unknown preset {args.preset!r}; use {sorted(parity_presets.PRESETS)}",
            file=sys.stderr,
        )
        return 2

    if args.list_presets:
        for name in sorted(parity_presets.PRESETS):
            print(name)
        return 0

    for slice_ in parity_presets.PRESETS[args.preset]:
        if slice_.screenshot_filter is not None and slice_.screenshot_filter != "":
            filter_value = slice_.screenshot_filter
        else:
            filter_value = parity_presets.screenshot_filter_for_selector(
                slice_.selector
            )
        print(f"{slice_.tier}|{slice_.selector}|{filter_value}")
    return 0


def _cmd_is_full_suite(args: argparse.Namespace) -> int:
    from tests.e2e.harness import parity_presets

    return 0 if args.preset in parity_presets.FULL_SUITE_PRESETS else 1


def _cmd_validate_skips(args: argparse.Namespace) -> int:
    unexpected = validate_skips(args.junit_xml, args.allowed_skip_regex)
    if not unexpected:
        return 0
    print(
        f"Harness parity strict mode failed: {len(unexpected)} unexpected "
        f"skipped test(s) in {args.junit_xml}",
        file=sys.stderr,
    )
    for name, message in unexpected[:20]:
        print(f"  - {name}: {message}", file=sys.stderr)
    if len(unexpected) > 20:
        print(f"  ... {len(unexpected) - 20} more", file=sys.stderr)
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parity_runner",
        description="Harness parity tier runner. The bash wrappers shell out "
        "to this; the Module owns tier registry, env builder, pytest "
        "invocation, JUnit skip validation, and route preflight.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    live = sub.add_parser("live", help="Run pytest for one tier")
    live.add_argument("--tier", default="core")
    live.add_argument("-k", dest="selector", default=None)
    live.add_argument("--junit-xml", dest="junit_xml", default=None)
    live.add_argument("--pytest-bin", dest="pytest_bin", default=None)
    live.add_argument("pytest_args", nargs=argparse.REMAINDER)
    live.set_defaults(func=_cmd_live)

    tier_rank_p = sub.add_parser(
        "tier-rank", help="Print the numeric rank of TIER (0..11)"
    )
    tier_rank_p.add_argument("--tier", required=True)
    tier_rank_p.set_defaults(func=_cmd_tier_rank)

    tier_at_least_p = sub.add_parser(
        "tier-at-least",
        help="Exit 0 if CURRENT covers REQUIRED per TIER_ORDER, else 1",
    )
    tier_at_least_p.add_argument("current")
    tier_at_least_p.add_argument("required")
    tier_at_least_p.set_defaults(func=_cmd_tier_at_least)

    validate_routes = sub.add_parser(
        "validate-routes",
        help="Verify deployed OpenAPI exposes routes the tier requires",
    )
    validate_routes.add_argument("--tier", required=True)
    validate_routes.add_argument(
        "--openapi-paths-file",
        dest="openapi_paths_file",
        required=True,
        help="Path to a file containing the OpenAPI JSON (with a 'paths' object).",
    )
    validate_routes.set_defaults(func=_cmd_validate_routes)

    expand_slices = sub.add_parser(
        "expand-slices",
        help="Print TIER|SELECTOR|SCREENSHOT_FILTER rows for a batch preset",
    )
    expand_slices.add_argument("--preset", required=True)
    expand_slices.add_argument(
        "--list-presets",
        dest="list_presets",
        action="store_true",
        help="Print the preset names instead of slices",
    )
    expand_slices.set_defaults(func=_cmd_expand_slices)

    is_full_suite = sub.add_parser(
        "is-full-suite",
        help="Exit 0 if PRESET is a full-suite preset (no -k selector), else 1",
    )
    is_full_suite.add_argument("--preset", required=True)
    is_full_suite.set_defaults(func=_cmd_is_full_suite)

    validate_skips_p = sub.add_parser(
        "validate-skips", help="Fail on unexpected pytest skips in JUnit XML"
    )
    validate_skips_p.add_argument("junit_xml")
    validate_skips_p.add_argument(
        "--allowed-skip-regex",
        dest="allowed_skip_regex",
        default=DEFAULT_ALLOWED_SKIP_REGEX,
    )
    validate_skips_p.set_defaults(func=_cmd_validate_skips)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args, remainder = parser.parse_known_args(argv)
    if args.cmd == "live" and remainder:
        args.pytest_args.extend(remainder)
    elif remainder:
        parser.error(f"unrecognized arguments: {' '.join(remainder)}")
    return int(args.func(args) or 0)


__all__ = [
    "TIER_ORDER",
    "tier_rank",
    "tier_at_least",
    "RuntimeConfig",
    "HARNESS_PARITY_RUNTIME_CONFIG",
    "HARNESS_PARITY_DEFAULT_RUNTIMES",
    "DEFAULT_ALLOWED_SKIP_REGEX",
    "Skip",
    "validate_skips",
    "required_routes",
    "validate_tier_requirements",
    "HarnessEnv",
    "PARITY_TEST_FILE",
    "run_tier",
    "cmd_prepare",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - thin CLI dispatch
    raise SystemExit(main())
