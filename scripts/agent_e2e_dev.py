#!/usr/bin/env python3
"""Prepare and inspect local Spindrel agent e2e development environments."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV = REPO_ROOT / ".env.agent-e2e"
SCRATCH_DIR = REPO_ROOT / "scratch" / "agent-e2e"
AUTH_OVERRIDE = SCRATCH_DIR / "compose.auth.override.yml"
HARNESS_PARITY_ENV = SCRATCH_DIR / "harness-parity.env"
NATIVE_API_ENV = SCRATCH_DIR / "native-api.env"
NATIVE_API_PID = SCRATCH_DIR / "native-api.pid"
NATIVE_API_LOG = SCRATCH_DIR / "native-api.log"
SCREENSHOT_ENV = REPO_ROOT / "scripts" / "screenshots" / ".env"
DEFAULT_API_KEY = "e2e-test-key-12345"
DEFAULT_PORT = 18000
DEFAULT_IMAGE = "spindrel:e2e"
COMPOSE_PROJECT = "spindrel-local-e2e"
COMPOSE_FILE = REPO_ROOT / "tests" / "e2e" / "docker-compose.e2e.yml"
SUBSCRIPTION_DUMMY_BASE_URL = "http://127.0.0.1:9/v1"
SUBSCRIPTION_DEFAULT_MODEL = "gpt-5.4-mini"
PROJECT_FACTORY_SECRET_NAME = "PROJECT_FACTORY_SMOKE_GITHUB_TOKEN"
HARNESS_PARITY_PROJECT_PATH = "common/projects"
HARNESS_PARITY_DEFAULT_RUNTIMES = ("codex", "claude-code")
HARNESS_PARITY_LOCAL_TOOLS = (
    "get_tool_info",
    "search_memory",
    "get_memory_file",
    "memory",
    "manage_bot_skill",
    "get_skill",
    "get_skill_list",
    "list_agent_capabilities",
    "run_agent_doctor",
    "list_channels",
    "read_conversation_history",
    "list_sub_sessions",
    "read_sub_session",
)
HARNESS_PARITY_RUNTIME_CONFIG = {
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


PRODUCTION_PORTS = {8000}


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _build_arg_flags(source: str) -> list[str]:
    sha = _git_value("rev-parse", "--verify", "HEAD")
    ref = _git_value("branch", "--show-current")
    if not ref:
        ref = _git_value("describe", "--tags", "--exact-match")
    if not ref:
        ref = _git_value("rev-parse", "--short", "HEAD")
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    values = {
        "SPINDREL_BUILD_SHA": sha,
        "SPINDREL_BUILD_REF": ref,
        "SPINDREL_BUILD_TIME": built_at,
        "SPINDREL_BUILD_SOURCE": source,
        "SPINDREL_DEPLOY_ID": "agent-e2e-" + (sha[:12] if sha else "unknown"),
    }
    return [flag for key, value in values.items() for flag in ("--build-arg", f"{key}={value}")]


def _redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _write_text(path: Path, content: str, *, force: bool = False) -> None:
    if path.exists() and not force:
        raise SystemExit(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o600)
    try:
        shown = path.relative_to(REPO_ROOT)
    except ValueError:
        shown = path
    print(f"wrote {shown}")


def _require_non_production(url: str, *, allow_production: bool = False) -> None:
    if allow_production:
        return
    parsed = urllib.parse.urlparse(url if "://" in url else f"http://{url}")
    if parsed.port in PRODUCTION_PORTS:
        raise SystemExit(
            f"refusing production-like target {url!r}; pass --allow-production only for an intentional live run"
        )


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


def _append_local_env_value(key: str, value: str) -> None:
    LOCAL_ENV.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if not LOCAL_ENV.exists() or LOCAL_ENV.read_text().endswith("\n") else "\n"
    with LOCAL_ENV.open("a") as handle:
        handle.write(f"{prefix}{key}={value}\n")
    try:
        LOCAL_ENV.chmod(0o600)
    except OSError:
        pass


def _generate_fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _ensure_local_env_value(env: dict[str, str], key: str, value_factory) -> str:
    if env.get(key):
        return env[key]
    env_values = _read_env_file(LOCAL_ENV)
    if env_values.get(key):
        env[key] = env_values[key]
        return env[key]
    value = value_factory()
    _append_local_env_value(key, value)
    env[key] = value
    print(f"generated stable local {key} in {LOCAL_ENV}")
    return value


def _merged_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({k: v for k, v in _read_env_file(LOCAL_ENV).items() if k not in env})
    if "E2E_COMPOSE_OVERRIDES" not in env and AUTH_OVERRIDE.exists():
        env["E2E_COMPOSE_OVERRIDES"] = str(AUTH_OVERRIDE)
    return env


def _base_url(env: dict[str, str]) -> str:
    if env.get("SPINDREL_E2E_URL"):
        return env["SPINDREL_E2E_URL"].rstrip("/")
    if env.get("E2E_BASE_URL"):
        return env["E2E_BASE_URL"].rstrip("/")
    host = env.get("E2E_HOST", "localhost")
    port = env.get("E2E_PORT", str(DEFAULT_PORT))
    return f"http://{host}:{port}"


def _api_key(env: dict[str, str]) -> str:
    return env.get("E2E_API_KEY") or env.get("SPINDREL_E2E_API_KEY") or DEFAULT_API_KEY


def _request_json(
    method: str,
    url: str,
    *,
    api_key: str = "",
    body: dict | None = None,
    timeout: int = 20,
) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc
    return json.loads(raw) if raw else {}


def _request_json_or_none(
    method: str,
    url: str,
    *,
    api_key: str = "",
    body: dict | None = None,
    timeout: int = 20,
) -> dict | None:
    try:
        return _request_json(method, url, api_key=api_key, body=body, timeout=timeout)
    except Exception:
        return None


def _check_url(url: str, api_key: str) -> tuple[bool, str]:
    try:
        data = _request_json("GET", f"{url.rstrip('/')}/health", api_key=api_key, timeout=5)
        return True, json.dumps(data, sort_keys=True)[:180]
    except Exception as exc:
        return False, str(exc)


def _host_command_output(args: list[str], *, timeout: int = 20) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"{' '.join(args)} failed: {detail}")
    return proc.stdout.strip()


def _is_local_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url if "://" in url else f"http://{url}")
    return parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _compose_overrides(env: dict[str, str]) -> list[Path]:
    return [
        Path(path).expanduser()
        for path in env.get("E2E_COMPOSE_OVERRIDES", "").split(":")
        if path.strip()
    ]


def _compose_cmd(overrides: list[Path], *args: str) -> list[str]:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE)]
    for override in overrides:
        cmd.extend(["-f", str(override)])
    cmd.extend(["-p", COMPOSE_PROJECT])
    cmd.extend(args)
    return cmd


def _compose_env(env: dict[str, str], *, api_url: str, api_key: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(api_url)
    _ensure_local_env_value(env, "ENCRYPTION_KEY", _generate_fernet_key)
    _ensure_local_env_value(env, "JWT_SECRET", lambda: os.urandom(32).hex())
    compose_env = dict(os.environ)
    compose_env.update(env)
    compose_env.setdefault("E2E_IMAGE", DEFAULT_IMAGE)
    compose_env["E2E_PORT"] = str(parsed.port or DEFAULT_PORT)
    compose_env["E2E_API_KEY"] = api_key
    compose_env.setdefault("E2E_BOT_CONFIG", str(REPO_ROOT / "tests" / "e2e" / "bot.e2e.yaml"))
    return compose_env


def _run(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 600) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    if result.returncode == 0:
        return
    output = (result.stdout + result.stderr).strip()
    raise SystemExit(f"command failed ({result.returncode}): {' '.join(cmd)}\n{output[-4000:]}")


def _run_best_effort(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 120) -> None:
    subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)


def _remove_compose_service_containers(service: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={COMPOSE_PROJECT}",
            "--filter",
            f"label=com.docker.compose.service={service}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return
    ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if ids:
        _run_best_effort(["docker", "rm", "-f", *ids], timeout=60)


def _prepare_stack(
    *,
    api_url: str,
    api_key: str,
    env: dict[str, str],
    build: bool,
    startup_timeout: int,
) -> None:
    if not _is_local_url(api_url):
        raise SystemExit(
            f"refusing to manage a non-local e2e stack for {api_url!r}; "
            "use --skip-setup if this is an intentional external target"
        )
    if not shutil.which("docker"):
        raise SystemExit("docker is required to prepare the local Spindrel e2e stack")

    image = env.get("E2E_IMAGE", DEFAULT_IMAGE)
    compose_env = _compose_env(env, api_url=api_url, api_key=api_key)
    overrides = _compose_overrides(env)

    if build:
        print(f"building current source image {image}")
        _run(
            [
                "docker",
                "build",
                "-t",
                image,
                "--build-arg",
                "BUILD_DASHBOARDS=false",
                *_build_arg_flags("agent-e2e-dev"),
                str(REPO_ROOT),
            ],
            timeout=900,
        )

    print(f"starting Spindrel e2e dependencies on {api_url}")
    _run(
        _compose_cmd(overrides, "up", "-d", "--remove-orphans", "postgres", "searxng"),
        env=compose_env,
        timeout=180,
    )
    print("recreating Spindrel e2e app container from current image")
    _run_best_effort(_compose_cmd(overrides, "stop", "spindrel"), env=compose_env)
    _run_best_effort(_compose_cmd(overrides, "rm", "-f", "spindrel"), env=compose_env)
    _remove_compose_service_containers("spindrel")
    _run(
        _compose_cmd(overrides, "up", "-d", "--no-deps", "spindrel"),
        env=compose_env,
        timeout=180,
    )

    deadline = time.time() + startup_timeout
    last_detail = ""
    while time.time() < deadline:
        ok, detail = _check_url(api_url, api_key)
        if ok:
            print(f"Spindrel e2e health ok: {detail}")
            return
        last_detail = detail
        time.sleep(2)
    raise SystemExit(f"Spindrel e2e stack did not become healthy at {api_url}: {last_detail}")


def _prepare_dependencies_only(
    *,
    api_url: str,
    api_key: str,
    env: dict[str, str],
) -> None:
    if not _is_local_url(api_url):
        raise SystemExit(
            f"refusing to manage non-local e2e dependencies for {api_url!r}; "
            "use a local target for dependency bootstrap"
        )
    if not shutil.which("docker"):
        raise SystemExit("docker is required to prepare local Spindrel e2e dependencies")

    compose_env = _compose_env(env, api_url=api_url, api_key=api_key)
    overrides = _compose_overrides(env)
    _run(
        _compose_cmd(overrides, "up", "-d", "--remove-orphans", "postgres", "searxng"),
        env=compose_env,
        timeout=180,
    )
    postgres_port = compose_env.get("E2E_POSTGRES_PORT", "15432")
    searxng_port = compose_env.get("E2E_SEARXNG_PORT", "18080")
    print("Spindrel e2e dependencies are running")
    print(f"  DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:{postgres_port}/agentdb")
    print(f"  SEARXNG_URL=http://localhost:{searxng_port}")
    print("Start the Spindrel app from this source checkout on your own unused port.")


def _restart_spindrel_app_container(api_url: str, api_key: str, env: dict[str, str], *, timeout: int) -> None:
    if not _is_local_url(api_url):
        raise SystemExit(
            f"refusing to restart a non-local e2e app container for {api_url!r}; "
            "rerun against a local target or restart the service manually"
        )
    if not shutil.which("docker"):
        raise SystemExit("docker is required to restart the local Spindrel e2e app container")
    compose_env = _compose_env(env, api_url=api_url, api_key=api_key)
    overrides = _compose_overrides(env)
    print("restarting Spindrel e2e app container so newly installed harness deps load")
    _run(_compose_cmd(overrides, "restart", "spindrel"), env=compose_env, timeout=120)
    deadline = time.time() + timeout
    last_detail = ""
    while time.time() < deadline:
        ok, detail = _check_url(api_url, api_key)
        if ok:
            print(f"Spindrel e2e health ok after restart: {detail}")
            return
        last_detail = detail
        time.sleep(2)
    raise SystemExit(f"Spindrel e2e app did not become healthy after restart at {api_url}: {last_detail}")


def cmd_prepare(args: argparse.Namespace) -> int:
    env = _merged_env()
    api_url = (args.api_url or _base_url(env)).rstrip("/")
    _require_non_production(api_url, allow_production=args.allow_production)
    _prepare_stack(
        api_url=api_url,
        api_key=args.api_key or _api_key(env),
        env=env,
        build=not args.no_build,
        startup_timeout=args.startup_timeout,
    )
    return 0


def cmd_prepare_deps(args: argparse.Namespace) -> int:
    env = _merged_env()
    api_url = (args.api_url or _base_url(env)).rstrip("/")
    _require_non_production(api_url, allow_production=args.allow_production)
    _prepare_dependencies_only(
        api_url=api_url,
        api_key=args.api_key or _api_key(env),
        env=env,
    )
    return 0


def cmd_wipe_db(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit("refusing to wipe local e2e database without --yes")
    env = _merged_env()
    api_url = (args.api_url or _base_url(env)).rstrip("/")
    _require_non_production(api_url, allow_production=args.allow_production)
    if not _is_local_url(api_url):
        raise SystemExit(f"refusing to wipe a non-local e2e database for {api_url!r}")
    compose_env = _compose_env(env, api_url=api_url, api_key=args.api_key or _api_key(env))
    overrides = _compose_overrides(env)
    print("wiping local Spindrel e2e database volume")
    _run(_compose_cmd(overrides, "down", "-v", "--remove-orphans"), env=compose_env, timeout=180)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    env = _merged_env()
    url = _base_url(env)
    _require_non_production(url, allow_production=args.allow_production)
    key = _api_key(env)
    print("agent e2e doctor")
    print(f"  target: {url}")
    print(f"  api key: {_redact(key)}")
    print(f"  docker: {'ok' if shutil.which('docker') else 'missing'}")
    print(f"  python: {sys.executable}")
    for binary in ("codex", "claude"):
        path = shutil.which(binary)
        print(f"  {binary}: {path or 'missing'}")
    print(f"  local env: {'present' if LOCAL_ENV.exists() else 'missing'}")
    print(f"  screenshot env: {'present' if SCREENSHOT_ENV.exists() else 'missing'}")
    print(f"  compose override: {'present' if AUTH_OVERRIDE.exists() else 'missing'}")
    ok, detail = _check_url(url, key)
    print(f"  health: {'ok' if ok else 'failed'} {detail}")
    if ok:
        harnesses = _request_json_or_none("GET", f"{url}/api/v1/admin/harnesses", api_key=key)
        if isinstance(harnesses, dict):
            runtimes = harnesses.get("runtimes") or []
            labels = [
                f"{item.get('name')}:{'ok' if item.get('ok') else 'blocked'}"
                for item in runtimes
                if isinstance(item, dict)
            ]
            print(f"  harness runtimes: {', '.join(labels) if labels else 'none registered'}")
        for runtime in ("codex", "claude-code"):
            caps = _request_json_or_none("GET", f"{url}/api/v1/runtimes/{runtime}/capabilities", api_key=key)
            print(f"  runtime {runtime}: {'registered' if caps else 'missing'}")
        secrets = _request_json_or_none("GET", f"{url}/api/v1/admin/secret-values/", api_key=key)
        secret_rows = secrets if isinstance(secrets, list) else secrets.get("items") if isinstance(secrets, dict) else []
        has_smoke_secret = any(
            isinstance(row, dict) and row.get("name") == PROJECT_FACTORY_SECRET_NAME
            for row in (secret_rows or [])
        )
        print(f"  project factory GitHub secret: {'present' if has_smoke_secret else 'missing'}")
    provider = env.get("SPINDREL_AGENT_E2E_PROVIDER", "")
    if provider == "subscription":
        print("  provider mode: subscription")
        print("  provider key: subscription oauth")
        if ok:
            status = _subscription_status(url, key, args.provider_id)
            if status.get("connected"):
                identity = status.get("email") or status.get("plan") or "connected account"
                print(f"  subscription bootstrap: connected ({identity})")
            elif status.get("missing"):
                print("  subscription bootstrap: provider missing")
            else:
                print("  subscription bootstrap: pending or local fallback placeholder active")
        elif env.get("E2E_LLM_BASE_URL") == SUBSCRIPTION_DUMMY_BASE_URL:
            print("  subscription bootstrap: pending or local fallback placeholder active")
    elif env.get("E2E_LLM_API_KEY"):
        print("  provider mode: openai-compatible")
        print(f"  provider key: {_redact(env['E2E_LLM_API_KEY'])}")
    else:
        print("  provider mode: unspecified")
        print("  provider key: missing or not needed")
    return 0 if ok else 1


def _ensure_auth_override() -> None:
    if AUTH_OVERRIDE.exists():
        return
    mounts: list[str] = []
    for name in (".codex", ".claude"):
        path = Path.home() / name
        if path.exists():
            mounts.append(f"      - {path}:/home/spindrel/{name}:rw")
    if not mounts:
        raise SystemExit("no Codex or Claude auth/config directory exists to mount")
    content = "\n".join(["services:", "  spindrel:", "    volumes:", *mounts, ""])
    _write_text(AUTH_OVERRIDE, content, force=False)


def _set_integration_enabled(api_url: str, api_key: str, integration_id: str) -> None:
    _request_json(
        "PUT",
        f"{api_url}/api/v1/admin/integrations/{integration_id}/status",
        api_key=api_key,
        body={"status": "enabled"},
        timeout=120,
    )
    print(f"enabled integration {integration_id!r}")


def _install_system_dependency(api_url: str, api_key: str, integration_id: str, apt_package: str) -> None:
    _request_json(
        "POST",
        f"{api_url}/api/v1/admin/integrations/{integration_id}/install-system-deps",
        api_key=api_key,
        body={"apt_package": apt_package},
        timeout=180,
    )
    print(f"ensured system package {apt_package!r} for integration {integration_id!r}")


def _install_integration_dependencies(api_url: str, api_key: str, integration_id: str, endpoints: tuple[str, ...]) -> None:
    for endpoint in endpoints:
        _request_json(
            "POST",
            f"{api_url}/api/v1/admin/integrations/{integration_id}{endpoint}",
            api_key=api_key,
            timeout=300,
        )
        print(f"ensured integration {integration_id!r} dependencies via {endpoint}")


def _runtime_status(api_url: str, api_key: str, runtime: str) -> dict | None:
    harnesses = _request_json("GET", f"{api_url}/api/v1/admin/harnesses", api_key=api_key, timeout=60)
    for item in harnesses.get("runtimes") or []:
        if isinstance(item, dict) and item.get("name") == runtime:
            return item
    return None


def _wait_for_harness_runtime(api_url: str, api_key: str, runtime: str, *, timeout: int) -> dict:
    deadline = time.time() + timeout
    latest: dict | None = None
    while time.time() < deadline:
        latest = _runtime_status(api_url, api_key, runtime)
        if latest and latest.get("ok"):
            print(f"harness runtime {runtime!r}: ok ({latest.get('detail') or 'ready'})")
            return latest
        time.sleep(3)
    if latest is None:
        raise SystemExit(f"harness runtime {runtime!r} is not registered on the local e2e server")
    raise SystemExit(f"harness runtime {runtime!r} is registered but not ready: {latest.get('detail')}")


def _validate_claude_live_auth(container_name: str) -> None:
    """Run a tiny noninteractive Claude turn so stale OAuth fails early."""
    if not shutil.which("docker"):
        return
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-u",
            "spindrel",
            container_name,
            "claude",
            "--print",
            "Reply with exactly: auth-ok",
            "--max-turns",
            "1",
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode == 0 and "authentication_failed" not in output and "Invalid authentication credentials" not in output:
        print("claude live auth smoke: ok")
        return
    detail = output[-1000:] if output else f"claude exited {proc.returncode}"
    raise SystemExit(
        "claude live auth smoke failed. Refresh the mounted Claude Code auth, then rerun prepare-harness-parity:\n"
        f"  docker exec -it -u spindrel {container_name} claude auth login\n"
        f"Failure detail: {detail}"
    )


def _get_json_or_404(method: str, url: str, *, api_key: str) -> dict | None:
    try:
        return _request_json(method, url, api_key=api_key)
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def _ensure_harness_parity_bot(
    api_url: str,
    api_key: str,
    *,
    bot_id: str,
    name: str,
    runtime: str,
    model: str,
) -> None:
    existing = _get_json_or_404("GET", f"{api_url}/api/v1/admin/bots/{bot_id}", api_key=api_key)
    body = {
        "id": bot_id,
        "name": name,
        "model": model,
        "system_prompt": "",
        "harness_runtime": runtime,
        "local_tools": list(HARNESS_PARITY_LOCAL_TOOLS),
        "tool_retrieval": False,
        "tool_discovery": False,
        "persona": False,
    }
    if existing is None:
        _request_json("POST", f"{api_url}/api/v1/admin/bots", api_key=api_key, body=body, timeout=60)
        print(f"created harness parity bot {bot_id!r}")
        return
    patch = {key: value for key, value in body.items() if key != "id"}
    _request_json("PATCH", f"{api_url}/api/v1/admin/bots/{bot_id}", api_key=api_key, body=patch, timeout=60)
    print(f"updated harness parity bot {bot_id!r}")


def _ensure_harness_parity_channel(
    api_url: str,
    api_key: str,
    *,
    client_id: str,
    name: str,
    bot_id: str,
    project_path: str,
) -> str:
    channel = _request_json(
        "POST",
        f"{api_url}/api/v1/channels",
        api_key=api_key,
        body={
            "client_id": client_id,
            "bot_id": bot_id,
            "name": name,
            "private": False,
            "category": "Harness Parity",
        },
        timeout=60,
    )
    channel_id = str(channel.get("id") or channel.get("channel_id") or "")
    if not channel_id:
        raise SystemExit(f"channel create response did not include an id: {channel}")
    _request_json(
        "PATCH",
        f"{api_url}/api/v1/admin/channels/{channel_id}/settings",
        api_key=api_key,
        body={"bot_id": bot_id, "project_path": project_path},
        timeout=60,
    )
    print(f"ensured harness parity channel {name!r}: {channel_id}")
    return channel_id


def _write_harness_parity_env(
    *,
    api_url: str,
    api_key: str,
    channel_ids_by_runtime: dict[str, str],
    project_path: str,
) -> None:
    existing = _read_env_file(HARNESS_PARITY_ENV)
    parsed = urllib.parse.urlparse(api_url)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or DEFAULT_PORT)
    lines = [
        "# Local harness parity e2e env. Gitignored.",
        "E2E_MODE=external",
        f"E2E_HOST={host}",
        f"E2E_PORT={port}",
        f"E2E_API_KEY={api_key}",
        "E2E_BOT_ID=e2e",
        "E2E_KEEP_RUNNING=1",
        "HARNESS_PARITY_LOCAL=1",
        f"HARNESS_PARITY_PROJECT_PATH={project_path}",
        f"HARNESS_PARITY_AGENT_CONTAINER={COMPOSE_PROJECT}-spindrel-1",
        "HARNESS_PARITY_CAPTURE_SCREENSHOTS=auto",
        "HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR=/tmp/spindrel-harness-local-screenshots",
        f"SPINDREL_BROWSER_URL={api_url}",
        f"SPINDREL_BROWSER_API_URL={api_url}",
        "",
    ]
    for runtime in HARNESS_PARITY_DEFAULT_RUNTIMES:
        config = HARNESS_PARITY_RUNTIME_CONFIG[runtime]
        channel_id = channel_ids_by_runtime.get(runtime) or existing.get(str(config["channel_env"]))
        bot_id = str(config["bot_id"])
        if not channel_id:
            continue
        lines.append(f"{config['channel_env']}={channel_id}")
        lines.append(f"{config['bot_env']}={existing.get(str(config['bot_env']), bot_id)}")
    _write_text(HARNESS_PARITY_ENV, "\n".join(lines) + "\n", force=True)


def cmd_prepare_harness_parity(args: argparse.Namespace) -> int:
    env = _merged_env()
    api_url = (args.api_url or _base_url(env)).rstrip("/")
    _require_non_production(api_url, allow_production=args.allow_production)
    api_key = args.api_key or _api_key(env)
    runtimes = tuple(args.runtime or HARNESS_PARITY_DEFAULT_RUNTIMES)
    unknown = sorted(set(runtimes) - set(HARNESS_PARITY_RUNTIME_CONFIG))
    if unknown:
        raise SystemExit(f"unsupported harness parity runtime(s): {', '.join(unknown)}")

    _ensure_auth_override()
    env = _merged_env()
    if not args.skip_setup:
        _prepare_stack(
            api_url=api_url,
            api_key=api_key,
            env=env,
            build=not args.no_build,
            startup_timeout=args.startup_timeout,
        )

    for runtime in runtimes:
        config = HARNESS_PARITY_RUNTIME_CONFIG[runtime]
        integration_id = str(config["integration_id"])
        _set_integration_enabled(api_url, api_key, integration_id)
        _install_integration_dependencies(
            api_url,
            api_key,
            integration_id,
            tuple(config.get("install_endpoints") or ()),
        )

    _restart_spindrel_app_container(
        api_url,
        api_key,
        env,
        timeout=args.startup_timeout,
    )

    channel_ids: dict[str, str] = {}
    for runtime in runtimes:
        config = HARNESS_PARITY_RUNTIME_CONFIG[runtime]
        _wait_for_harness_runtime(
            api_url,
            api_key,
            runtime,
            timeout=args.runtime_timeout,
        )
        if runtime == "claude-code" and not args.skip_live_auth_check:
            _validate_claude_live_auth(f"{COMPOSE_PROJECT}-spindrel-1")
        _ensure_harness_parity_bot(
            api_url,
            api_key,
            bot_id=str(config["bot_id"]),
            name=str(config["bot_name"]),
            runtime=runtime,
            model=str(config["bot_model"]),
        )
        channel_ids[runtime] = _ensure_harness_parity_channel(
            api_url,
            api_key,
            client_id=str(config["channel_client_id"]),
            name=str(config["channel_name"]),
            bot_id=str(config["bot_id"]),
            project_path=args.project_path,
        )

    _write_harness_parity_env(
        api_url=api_url,
        api_key=api_key,
        channel_ids_by_runtime=channel_ids,
        project_path=args.project_path,
    )
    print("Local harness parity readiness: ok")
    print(f"  target: {api_url}")
    print(f"  env: {HARNESS_PARITY_ENV}")
    print("  run: ./scripts/run_harness_parity_local.sh --tier core")
    return 0


def _seed_github_secret(api_url: str, api_key: str, *, secret_name: str) -> None:
    token = _host_command_output(["gh", "auth", "token"])
    if not token:
        raise SystemExit("host gh auth token was empty")
    rows = _request_json("GET", f"{api_url}/api/v1/admin/secret-values/", api_key=api_key)
    existing = None
    for row in rows if isinstance(rows, list) else rows.get("items", []):
        if isinstance(row, dict) and row.get("name") == secret_name:
            existing = row
            break
    body = {
        "name": secret_name,
        "value": token,
        "description": "Local e2e Project Factory smoke GitHub token seeded from host gh auth.",
    }
    if existing:
        _request_json(
            "PUT",
            f"{api_url}/api/v1/admin/secret-values/{existing['id']}",
            api_key=api_key,
            body=body,
        )
        print(f"updated local e2e secret {secret_name!r}")
    else:
        _request_json("POST", f"{api_url}/api/v1/admin/secret-values/", api_key=api_key, body=body)
        print(f"created local e2e secret {secret_name!r}")


def cmd_prepare_project_factory_smoke(args: argparse.Namespace) -> int:
    env = _merged_env()
    api_url = (args.api_url or _base_url(env)).rstrip("/")
    _require_non_production(api_url, allow_production=args.allow_production)
    api_key = args.api_key or _api_key(env)
    if args.runtime != "codex":
        raise SystemExit("only --runtime codex is supported for the Project Factory smoke")
    _ensure_auth_override()
    env = _merged_env()
    if not args.skip_setup:
        _prepare_stack(
            api_url=api_url,
            api_key=api_key,
            env=env,
            build=not args.no_build,
            startup_timeout=args.startup_timeout,
        )
    _set_integration_enabled(api_url, api_key, "codex")
    _install_system_dependency(api_url, api_key, "codex", "gh")
    if args.seed_github_token_from_gh:
        _seed_github_secret(api_url, api_key, secret_name=args.github_secret_name)
    harnesses = _request_json("GET", f"{api_url}/api/v1/admin/harnesses", api_key=api_key, timeout=60)
    runtimes = harnesses.get("runtimes") or []
    codex = next((item for item in runtimes if isinstance(item, dict) and item.get("name") == "codex"), None)
    if not codex:
        raise SystemExit("codex harness runtime is not registered on the local e2e server")
    if not codex.get("ok"):
        raise SystemExit(f"codex harness runtime is registered but not ready: {codex.get('detail')}")
    print("Project Factory local e2e smoke readiness: ok")
    print(f"  target: {api_url}")
    print(f"  runtime: {args.runtime}")
    print(f"  github repo: {args.github_repo}")
    print(f"  base branch: {args.base_branch}")
    print(f"  github secret: {args.github_secret_name}")
    return 0


def cmd_write_env(args: argparse.Namespace) -> int:
    if args.base_url:
        _require_non_production(args.base_url, allow_production=args.allow_production)
    provider = getattr(args, "provider", "openai-compatible")
    llm_base_url = args.llm_base_url
    llm_api_key = args.llm_api_key
    model = args.model
    if provider == "subscription":
        llm_base_url = llm_base_url or SUBSCRIPTION_DUMMY_BASE_URL
        llm_api_key = ""
        model = model or SUBSCRIPTION_DEFAULT_MODEL
    elif not model:
        model = os.environ.get("E2E_DEFAULT_MODEL", "gemini-2.5-flash-lite")
    env_values = _read_env_file(LOCAL_ENV)
    encryption_key = env_values.get("ENCRYPTION_KEY") or _generate_fernet_key()
    jwt_secret = env_values.get("JWT_SECRET") or os.urandom(32).hex()
    lines = [
        "# Local Spindrel agent e2e development env. Gitignored.",
        f"E2E_MODE=compose",
        f"E2E_HOST={args.host}",
        f"E2E_PORT={args.port}",
        f"E2E_API_KEY={args.api_key}",
        f"E2E_LLM_BASE_URL={llm_base_url}",
        f"E2E_LLM_API_KEY={llm_api_key}",
        f"E2E_DEFAULT_MODEL={model}",
        f"E2E_IMAGE={DEFAULT_IMAGE}",
        "E2E_KEEP_RUNNING=1",
        f"SPINDREL_AGENT_E2E_PROVIDER={provider}",
        f"ENCRYPTION_KEY={encryption_key}",
        f"JWT_SECRET={jwt_secret}",
    ]
    if provider == "subscription":
        lines.append("SPINDREL_PROVIDER=chatgpt-subscription")
    if args.base_url:
        lines.append(f"SPINDREL_E2E_URL={args.base_url.rstrip('/')}")
    _write_text(LOCAL_ENV, "\n".join(lines) + "\n", force=args.force)
    if provider == "subscription":
        print(
            "subscription mode: start the local stack, then run "
            "`python scripts/agent_e2e_dev.py bootstrap-subscription`"
        )
    return 0


def cmd_write_auth_override(args: argparse.Namespace) -> int:
    mounts: list[str] = []
    codex_home = Path(args.codex_home).expanduser() if args.codex_home else Path.home() / ".codex"
    claude_home = Path(args.claude_home).expanduser() if args.claude_home else Path.home() / ".claude"
    if codex_home.exists():
        mounts.append(f"      - {codex_home}:/home/spindrel/.codex:rw")
    if claude_home.exists():
        mounts.append(f"      - {claude_home}:/home/spindrel/.claude:rw")
    if not mounts:
        raise SystemExit("no Codex or Claude auth/config directory exists to mount")
    content = "\n".join([
        "services:",
        "  spindrel:",
        "    volumes:",
        *mounts,
        "",
    ])
    _write_text(AUTH_OVERRIDE, content, force=args.force)
    print(f"export E2E_COMPOSE_OVERRIDES={AUTH_OVERRIDE}")
    return 0


def cmd_write_screenshot_env(args: argparse.Namespace) -> int:
    env = _merged_env()
    api_url = args.api_url or _base_url(env)
    ui_url = args.ui_url or api_url
    _require_non_production(api_url, allow_production=args.allow_production)
    api_key = args.api_key or _api_key(env)
    email = args.email
    password = args.password
    if args.setup_user:
        status = _request_json("GET", f"{api_url.rstrip('/')}/auth/status")
        if status.get("setup_required"):
            _request_json(
                "POST",
                f"{api_url.rstrip('/')}/auth/setup",
                body={
                    "method": "local",
                    "email": email,
                    "password": password,
                    "display_name": "Screenshot Admin",
                },
            )
            print("created local screenshot admin via /auth/setup")
    content = "\n".join([
        "# Local screenshot pipeline env. Gitignored.",
        f"SPINDREL_URL={api_url.rstrip('/')}",
        f"SPINDREL_UI_URL={ui_url.rstrip('/')}",
        f"SPINDREL_API_KEY={api_key}",
        f"SPINDREL_LOGIN_EMAIL={email}",
        f"SPINDREL_LOGIN_PASSWORD={password}",
        "SSH_ALIAS=",
        "SSH_CONTAINER=",
        "DOCS_IMAGES_DIR=docs/images",
        "WEBSITE_IMAGES_DIR=../spindrel-website/public/images/screenshots",
        "",
    ])
    _write_text(SCREENSHOT_ENV, content, force=args.force)
    return 0


def _ensure_provider(api_url: str, api_key: str, provider_id: str) -> None:
    try:
        _request_json("GET", f"{api_url}/api/v1/admin/providers/{provider_id}", api_key=api_key)
        print(f"provider {provider_id!r} already exists")
        return
    except RuntimeError as exc:
        message = str(exc)
        if "HTTP 404" not in message:
            raise
    _request_json(
        "POST",
        f"{api_url}/api/v1/admin/providers",
        api_key=api_key,
        body={
            "id": provider_id,
            "provider_type": "openai-subscription",
            "display_name": "ChatGPT Subscription",
            "base_url": "",
            "api_key": "",
            "is_enabled": True,
            "billing_type": "plan",
            "plan_cost": 20,
            "plan_period": "monthly",
        },
    )
    print(f"created provider {provider_id!r}")


def _subscription_status(api_url: str, api_key: str, provider_id: str) -> dict:
    try:
        return _request_json(
            "GET",
            f"{api_url}/api/v1/admin/providers/openai-oauth/status/{provider_id}",
            api_key=api_key,
        )
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return {"missing": True, "connected": False}
        return {"error": str(exc), "connected": False}
    except Exception as exc:
        return {"error": str(exc), "connected": False}


def _patch_bot_provider(api_url: str, api_key: str, bot_id: str, provider_id: str, model: str) -> None:
    _request_json(
        "PATCH",
        f"{api_url}/api/v1/admin/bots/{bot_id}",
        api_key=api_key,
        body={"model_provider_id": provider_id, "model": model},
    )
    print(f"patched bot {bot_id!r} to {provider_id}/{model}")


def cmd_bootstrap_subscription(args: argparse.Namespace) -> int:
    env = _merged_env()
    api_url = (args.api_url or _base_url(env)).rstrip("/")
    _require_non_production(api_url, allow_production=args.allow_production)
    api_key = args.api_key or _api_key(env)
    if not args.skip_setup:
        _prepare_stack(
            api_url=api_url,
            api_key=api_key,
            env=env,
            build=not args.no_build,
            startup_timeout=args.startup_timeout,
        )
    provider_id = args.provider_id
    try:
        _ensure_provider(api_url, api_key, provider_id)
    except RuntimeError as exc:
        if "Invalid provider_type" in str(exc) and "openai-subscription" not in str(exc):
            raise SystemExit(
                "The running Spindrel server does not support provider_type='openai-subscription'. "
                "Run this command again without --skip-setup so it rebuilds and recreates "
                "the local Spindrel e2e stack from current source."
            ) from exc
        raise
    status = _subscription_status(api_url, api_key, provider_id)
    if status.get("connected"):
        identity = status.get("email") or status.get("plan") or "connected account"
        print(f"subscription provider {provider_id!r} already connected ({identity})")
        for bot_id in args.bot:
            _patch_bot_provider(api_url, api_key, bot_id, provider_id, args.model)
        return 0
    start = _request_json(
        "POST",
        f"{api_url}/api/v1/admin/providers/openai-oauth/start/{provider_id}",
        api_key=api_key,
    )
    print("ChatGPT subscription sign-in")
    print(f"  open: {start.get('verification_uri')}")
    print(f"  code: {start.get('user_code')}")
    interval = max(1, int(start.get("interval") or 2))
    expires_at = time.time() + int(start.get("expires_in") or 900)
    while time.time() < expires_at:
        time.sleep(interval)
        result = _request_json(
            "POST",
            f"{api_url}/api/v1/admin/providers/openai-oauth/poll/{provider_id}",
            api_key=api_key,
        )
        if result.get("status") == "pending":
            print("  waiting for approval...")
            continue
        if result.get("status") == "success":
            print(f"connected {result.get('email') or 'account'} ({result.get('plan') or 'plan'})")
            for bot_id in args.bot:
                _patch_bot_provider(api_url, api_key, bot_id, provider_id, args.model)
            return 0
        raise SystemExit(f"unexpected OAuth status: {result}")
    raise SystemExit("OAuth flow expired before approval")


def cmd_commands(args: argparse.Namespace) -> int:
    env_file = args.env_file
    prefix = f"set -a && source {env_file} && set +a && "
    overrides = ""
    if AUTH_OVERRIDE.exists():
        overrides = f"E2E_COMPOSE_OVERRIDES={AUTH_OVERRIDE} "
    env = _merged_env()
    subscription = env.get("SPINDREL_AGENT_E2E_PROVIDER") == "subscription"
    print("fresh local e2e:")
    print("  python scripts/agent_e2e_dev.py prepare-deps")
    print("  # then start the API/UI from this checkout on unused ports")
    print("  python scripts/agent_e2e_dev.py prepare")
    print(f"  {prefix}{overrides}E2E_KEEP_RUNNING=1 pytest tests/e2e/ -k \"test_health\" -v")
    if subscription:
        print("subscription handoff:")
        print("  python scripts/agent_e2e_dev.py bootstrap-subscription --api-url http://localhost:18000")
        print("  pytest tests/e2e/ -k \"test_chat_basic or test_tool_usage\" -v")
    print("project workspace screenshots:")
    print("  python -m scripts.screenshots stage --only project-workspace")
    print("  python -m scripts.screenshots capture --only project-workspace")
    print("  python -m scripts.screenshots check")
    print("local harness parity:")
    print("  python scripts/agent_e2e_dev.py prepare-harness-parity")
    print("  ./scripts/run_harness_parity_local.sh --tier core")
    print("  ./scripts/run_harness_parity_local.sh --tier skills -k \"native_image_input_manifest\"")
    print("external target status from a Spindrel bot:")
    print('  run_e2e_tests(action="status")')
    print("project factory local PR smoke:")
    print(
        "  python scripts/agent_e2e_dev.py prepare-project-factory-smoke "
        "--runtime codex --github-repo mtotho/vault --base-branch master --seed-github-token-from-gh"
    )
    print("  PROJECT_FACTORY_LIVE_PR=1 E2E_KEEP_RUNNING=1 pytest tests/e2e/scenarios/test_project_factory_live_pr_smoke.py -v -s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--api-url", default="")
    prepare.add_argument("--api-key", default="")
    prepare.add_argument("--no-build", action="store_true")
    prepare.add_argument("--startup-timeout", type=int, default=180)
    prepare.add_argument("--allow-production", action="store_true")
    prepare.set_defaults(func=cmd_prepare)

    prepare_deps = sub.add_parser("prepare-deps")
    prepare_deps.add_argument("--api-url", default="")
    prepare_deps.add_argument("--api-key", default="")
    prepare_deps.add_argument("--allow-production", action="store_true")
    prepare_deps.set_defaults(func=cmd_prepare_deps)

    wipe_db = sub.add_parser("wipe-db")
    wipe_db.add_argument("--api-url", default="")
    wipe_db.add_argument("--api-key", default="")
    wipe_db.add_argument("--yes", action="store_true")
    wipe_db.add_argument("--allow-production", action="store_true")
    wipe_db.set_defaults(func=cmd_wipe_db)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--provider-id", default="chatgpt-subscription")
    doctor.add_argument("--allow-production", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    write_env = sub.add_parser("write-env")
    write_env.add_argument("--host", default="localhost")
    write_env.add_argument("--port", default=str(DEFAULT_PORT))
    write_env.add_argument("--api-key", default=DEFAULT_API_KEY)
    write_env.add_argument("--base-url", default="")
    write_env.add_argument(
        "--provider",
        choices=["openai-compatible", "subscription"],
        default="openai-compatible",
        help="Main model-provider mode for this local e2e stack.",
    )
    write_env.add_argument("--llm-base-url", default=os.environ.get("E2E_LLM_BASE_URL", ""))
    write_env.add_argument("--llm-api-key", default=os.environ.get("E2E_LLM_API_KEY", ""))
    write_env.add_argument("--model", default=os.environ.get("E2E_DEFAULT_MODEL", ""))
    write_env.add_argument("--force", action="store_true")
    write_env.add_argument("--allow-production", action="store_true")
    write_env.set_defaults(func=cmd_write_env)

    auth = sub.add_parser("write-auth-override")
    auth.add_argument("--codex-home", default="")
    auth.add_argument("--claude-home", default="")
    auth.add_argument("--force", action="store_true")
    auth.set_defaults(func=cmd_write_auth_override)

    ss = sub.add_parser("write-screenshot-env")
    ss.add_argument("--api-url", default="")
    ss.add_argument("--ui-url", default="")
    ss.add_argument("--api-key", default="")
    ss.add_argument("--email", default="screenshot@local.e2e")
    ss.add_argument("--password", default="screenshot-local-e2e")
    ss.add_argument("--setup-user", action="store_true")
    ss.add_argument("--force", action="store_true")
    ss.add_argument("--allow-production", action="store_true")
    ss.set_defaults(func=cmd_write_screenshot_env)

    oauth = sub.add_parser("bootstrap-subscription")
    oauth.add_argument("--api-url", default="")
    oauth.add_argument("--api-key", default="")
    oauth.add_argument("--provider-id", default="chatgpt-subscription")
    oauth.add_argument("--model", default="gpt-5.4-mini")
    oauth.add_argument("--bot", action="append", default=["e2e", "e2e-tools"])
    oauth.add_argument("--skip-setup", action="store_true")
    oauth.add_argument("--no-build", action="store_true")
    oauth.add_argument("--startup-timeout", type=int, default=180)
    oauth.add_argument("--allow-production", action="store_true")
    oauth.set_defaults(func=cmd_bootstrap_subscription)

    factory = sub.add_parser("prepare-project-factory-smoke")
    factory.add_argument("--api-url", default="")
    factory.add_argument("--api-key", default="")
    factory.add_argument("--runtime", choices=["codex"], default="codex")
    factory.add_argument("--github-repo", default="mtotho/vault")
    factory.add_argument("--base-branch", default="master")
    factory.add_argument("--github-secret-name", default=PROJECT_FACTORY_SECRET_NAME)
    factory.add_argument("--seed-github-token-from-gh", action="store_true")
    factory.add_argument("--skip-setup", action="store_true")
    factory.add_argument("--no-build", action="store_true")
    factory.add_argument("--startup-timeout", type=int, default=180)
    factory.add_argument("--allow-production", action="store_true")
    factory.set_defaults(func=cmd_prepare_project_factory_smoke)

    harness = sub.add_parser("prepare-harness-parity")
    harness.add_argument("--api-url", default="")
    harness.add_argument("--api-key", default="")
    harness.add_argument(
        "--runtime",
        action="append",
        choices=sorted(HARNESS_PARITY_RUNTIME_CONFIG),
        default=None,
        help="Runtime to prepare. May be repeated. Defaults to Codex and Claude Code.",
    )
    harness.add_argument("--project-path", default=HARNESS_PARITY_PROJECT_PATH)
    harness.add_argument("--skip-setup", action="store_true")
    harness.add_argument("--no-build", action="store_true")
    harness.add_argument("--skip-live-auth-check", action="store_true")
    harness.add_argument("--startup-timeout", type=int, default=180)
    harness.add_argument("--runtime-timeout", type=int, default=180)
    harness.add_argument("--allow-production", action="store_true")
    harness.set_defaults(func=cmd_prepare_harness_parity)

    commands = sub.add_parser("commands")
    commands.add_argument("--env-file", default=".env.agent-e2e")
    commands.set_defaults(func=cmd_commands)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
