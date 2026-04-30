#!/usr/bin/env python3
"""Prepare and inspect local Spindrel agent e2e development environments."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV = REPO_ROOT / ".env.agent-e2e"
SCRATCH_DIR = REPO_ROOT / "scratch" / "agent-e2e"
AUTH_OVERRIDE = SCRATCH_DIR / "compose.auth.override.yml"
SCREENSHOT_ENV = REPO_ROOT / "scripts" / "screenshots" / ".env"
DEFAULT_API_KEY = "e2e-test-key-12345"
DEFAULT_PORT = 18000
SUBSCRIPTION_DUMMY_BASE_URL = "http://127.0.0.1:9/v1"
SUBSCRIPTION_DEFAULT_MODEL = "gpt-5.4-mini"


PRODUCTION_PORTS = {8000}


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


def _merged_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({k: v for k, v in _read_env_file(LOCAL_ENV).items() if k not in env})
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


def _check_url(url: str, api_key: str) -> tuple[bool, str]:
    try:
        data = _request_json("GET", f"{url.rstrip('/')}/health", api_key=api_key, timeout=5)
        return True, json.dumps(data, sort_keys=True)[:180]
    except Exception as exc:
        return False, str(exc)


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
    provider = env.get("SPINDREL_AGENT_E2E_PROVIDER", "")
    if provider == "subscription":
        print("  provider mode: subscription")
        print("  provider key: subscription oauth")
        if env.get("E2E_LLM_BASE_URL") == SUBSCRIPTION_DUMMY_BASE_URL:
            print("  subscription bootstrap: pending or local fallback placeholder active")
    elif env.get("E2E_LLM_API_KEY"):
        print("  provider mode: openai-compatible")
        print(f"  provider key: {_redact(env['E2E_LLM_API_KEY'])}")
    else:
        print("  provider mode: unspecified")
        print("  provider key: missing or not needed")
    return 0 if ok else 1


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
    lines = [
        "# Local Spindrel agent e2e development env. Gitignored.",
        f"E2E_MODE=compose",
        f"E2E_HOST={args.host}",
        f"E2E_PORT={args.port}",
        f"E2E_API_KEY={args.api_key}",
        f"E2E_LLM_BASE_URL={llm_base_url}",
        f"E2E_LLM_API_KEY={llm_api_key}",
        f"E2E_DEFAULT_MODEL={model}",
        f"E2E_KEEP_RUNNING=1",
        f"SPINDREL_AGENT_E2E_PROVIDER={provider}",
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
        "  agent-server:",
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
    provider_id = args.provider_id
    try:
        _ensure_provider(api_url, api_key, provider_id)
    except RuntimeError as exc:
        if "Invalid provider_type" in str(exc) and "openai-subscription" not in str(exc):
            raise SystemExit(
                "The running Spindrel server does not support provider_type='openai-subscription'. "
                "Rebuild the local e2e image from current source, then restart the e2e stack:\n"
                "  docker build -t agent-server:e2e --build-arg BUILD_DASHBOARDS=false .\n"
                "  set -a && source .env.agent-e2e && set +a && "
                "E2E_COMPOSE_OVERRIDES=\"$PWD/scratch/agent-e2e/compose.auth.override.yml\" "
                "E2E_KEEP_RUNNING=1 pytest tests/e2e/ -k \"test_health\" -v"
            ) from exc
        raise
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
    print("  docker build -t agent-server:e2e --build-arg BUILD_DASHBOARDS=false .")
    print(f"  {prefix}{overrides}E2E_KEEP_RUNNING=1 pytest tests/e2e/ -k \"test_health\" -v")
    if subscription:
        print("subscription handoff:")
        print("  python scripts/agent_e2e_dev.py bootstrap-subscription --api-url http://localhost:18000")
        print("  pytest tests/e2e/ -k \"test_chat_basic or test_tool_usage\" -v")
    print("project workspace screenshots:")
    print("  python -m scripts.screenshots stage --only project-workspace")
    print("  python -m scripts.screenshots capture --only project-workspace")
    print("  python -m scripts.screenshots check")
    print("external target status from a Spindrel bot:")
    print('  run_e2e_tests(action="status")')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor")
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
    oauth.add_argument("--allow-production", action="store_true")
    oauth.set_defaults(func=cmd_bootstrap_subscription)

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
