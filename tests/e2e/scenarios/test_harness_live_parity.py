"""Live parity diagnostics for Codex and Claude Code harness channels.

These tests target real deployed harness channels and create a fresh detached
Spindrel session per scenario. They are skipped unless channel ids are supplied.

Tiers are controlled by ``HARNESS_PARITY_TIER``:

- ``core`` (default): runtime controls, trace, status, basic context telemetry.
- ``bridge``: core plus Spindrel bridge discovery/invocation persistence.
- ``terminal``: bridge plus terminal-mode UI transcript parity.
- ``plan``: terminal plus native plan-mode round-trip checks.
- ``heartbeat``: plan plus channel prompt and manual heartbeat harness runs.
- ``automation``: heartbeat plus harness scheduled/manual task automation.
- ``writes``: automation plus safe temporary workspace write/read/delete.
- ``context``: writes plus context-pressure and native compaction checks.
- ``project``: context plus a plan-confirm-build static app workflow with screenshots.
- ``memory``: project plus explicit workspace memory reads through the bridge.
- ``skills``: memory plus tagged skill hints and bridged get_skill fetches.
- ``replay``: skills plus persisted tool transcript replay after refetch.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import pytest
import websockets

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.parity_runner import TIER_ORDER
from tests.e2e.harness.streaming import StreamResult


pytestmark = pytest.mark.e2e


CORE_BRIDGE_BASELINE_TOOLS = (
    "get_tool_info",
    "list_channels",
    "read_conversation_history",
    "list_sub_sessions",
    "read_sub_session",
)

HEADLESS_BROWSER_TOOLS = (
    "headless_browser_open",
    "headless_browser_goto",
    "headless_browser_snapshot",
    "headless_browser_click",
    "headless_browser_type",
    "headless_browser_screenshot",
    "headless_browser_eval",
    "headless_browser_close",
    "headless_browser_status",
)


@dataclass(frozen=True)
class HarnessCase:
    name: str
    runtime: str
    channel_env: str
    bot_env: str
    default_bot_id: str
    native_commands: tuple[str, ...]
    direct_native_commands: tuple[tuple[str, str], ...]
    native_terminal_handoff_commands: tuple[tuple[str, tuple[str, ...], str], ...]
    model_candidates: tuple[str, ...]
    effort_env: str
    model_env: str


HARNESSES = (
    HarnessCase(
        name="codex",
        runtime="codex",
        channel_env="HARNESS_PARITY_CODEX_CHANNEL_ID",
        bot_env="HARNESS_PARITY_CODEX_BOT_ID",
        default_bot_id="codex-bot",
        native_commands=(
            "config", "mcp-status", "plugins", "skills", "features",
            "status", "hooks", "apps", "fs", "diff", "resume", "cloud", "approvals",
        ),
        direct_native_commands=(
            ("agents", "agents"),
            ("plugins", "plugins"),
            ("skills", "skills"),
            ("mcp", "mcp-status"),
            ("status", "status"),
            ("hooks", "hooks"),
            ("apps", "apps"),
            ("app", "apps"),
            ("diff", "diff"),
            ("resume", "resume"),
            ("cloud", "cloud"),
            ("approvals", "approvals"),
        ),
        native_terminal_handoff_commands=(
            ("plugin", ("install", "spindrel-fixture-nonexistent"), "codex plugin install spindrel-fixture-nonexistent"),
        ),
        model_candidates=(
            "gpt-5.4-mini",
            "gpt-5.3-codex-spark",
        ),
        effort_env="HARNESS_PARITY_CODEX_EFFORT",
        model_env="HARNESS_PARITY_CODEX_MODEL",
    ),
    HarnessCase(
        name="claude",
        runtime="claude-code",
        channel_env="HARNESS_PARITY_CLAUDE_CHANNEL_ID",
        bot_env="HARNESS_PARITY_CLAUDE_BOT_ID",
        default_bot_id="claude-code-bot",
        native_commands=(
            "version", "auth", "skills", "plugins", "mcp",
            "agents", "hooks", "status", "doctor",
        ),
        direct_native_commands=(
            ("skills", "skills"),
            ("plugin", "plugins"),
            ("mcp", "mcp"),
            ("agents", "agents"),
            ("hooks", "hooks"),
            ("status", "status"),
            ("doctor", "doctor"),
        ),
        native_terminal_handoff_commands=(
            ("plugin", ("install", "spindrel-fixture-nonexistent"), "claude plugin install spindrel-fixture-nonexistent"),
        ),
        model_candidates=("claude-haiku-4-5",),
        effort_env="HARNESS_PARITY_CLAUDE_EFFORT",
        model_env="HARNESS_PARITY_CLAUDE_MODEL",
    ),
)


HARNESS_PARAMS = tuple(
    pytest.param(
        case,
        id=case.name,
        marks=pytest.mark.skipif(
            not os.environ.get(case.channel_env, "").strip(),
            reason=f"{case.channel_env} is not set",
        ),
    )
    for case in HARNESSES
)


def _tier() -> str:
    value = os.environ.get("HARNESS_PARITY_TIER", "core").strip().lower() or "core"
    return value if value in TIER_ORDER else "core"


def _requires_tier(required: str) -> None:
    if TIER_ORDER[_tier()] < TIER_ORDER[required]:
        pytest.skip(f"HARNESS_PARITY_TIER={required!r} or higher is required")


def _timeout() -> float:
    return float(os.environ.get("HARNESS_PARITY_TIMEOUT", "300"))


def _project_path() -> str:
    return os.environ.get("HARNESS_PARITY_PROJECT_PATH", "common/projects").strip() or "common/projects"


def _artifact_root() -> Path:
    return Path(
        os.environ.get("HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR")
        or os.environ.get("HARNESS_PARITY_ARTIFACT_DIR", "/tmp/spindrel-harness-parity")
    )


def _should_capture_screenshots(name: str) -> bool:
    capture = os.environ.get("HARNESS_PARITY_CAPTURE_SCREENSHOTS", "auto").strip().lower()
    if capture in {"0", "false", "no", "off"}:
        return False
    only = os.environ.get("HARNESS_PARITY_SCREENSHOT_ONLY", "").strip()
    if only and only not in name:
        return False
    return capture in {"1", "true", "yes", "on", "auto"}


def _project_timeout() -> float:
    return max(_timeout(), float(os.environ.get("HARNESS_PARITY_PROJECT_TIMEOUT", "600")))


def _plan_timeout() -> float:
    return max(_timeout(), float(os.environ.get("HARNESS_PARITY_PLAN_TIMEOUT", "450")))


def _bridge_tool_name() -> str:
    return os.environ.get("HARNESS_PARITY_BRIDGE_TOOL", "list_channels").strip() or "list_channels"


def _bridge_tool_args() -> dict[str, Any]:
    raw = os.environ.get("HARNESS_PARITY_BRIDGE_TOOL_ARGS", "{}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"HARNESS_PARITY_BRIDGE_TOOL_ARGS is not JSON: {exc}") from exc
    assert isinstance(parsed, dict), "HARNESS_PARITY_BRIDGE_TOOL_ARGS must be a JSON object"
    return parsed


def _bridge_visible_names(tool_name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((
        tool_name,
        f"mcp__spindrel__{tool_name}",
    )))


def _local_tool_prompt(tool_name: str) -> str:
    return f"@tool:{tool_name}"


def _configured_case(case: HarnessCase) -> tuple[str, str]:
    channel_id = os.environ.get(case.channel_env, "").strip()
    if not channel_id:
        pytest.skip(f"{case.channel_env} is not set")
    return channel_id, os.environ.get(case.bot_env, case.default_bot_id).strip()


async def _shared_workspace_id_for_bot(client: E2EClient, bot_id: str) -> str:
    bot = await client.get_bot(bot_id)
    workspace_id = str(bot.get("shared_workspace_id") or "").strip()
    if not workspace_id:
        pytest.skip(f"bot {bot_id!r} is not attached to a shared workspace")
    return workspace_id


def _expected_usage_provider(case: HarnessCase) -> str:
    if case.runtime == "codex":
        return "harness:codex-sdk"
    if case.runtime == "claude-code":
        return "harness:claude-code-sdk"
    return f"harness:{case.runtime}-sdk"


async def _fresh_session(client: E2EClient, case: HarnessCase) -> tuple[str, str, str]:
    channel_id, bot_id = _configured_case(case)
    session_id = await client.create_channel_session(channel_id)
    return channel_id, session_id, bot_id


def _assert_clean_turn(result: StreamResult) -> None:
    assert result.response_text.strip(), "turn ended without assistant text"
    assert not result.error_events, [event.data for event in result.error_events]


def _turn_id(result: StreamResult) -> str | None:
    for event in reversed(result.events):
        if event.type == "response":
            value = event.data.get("turn_id")
            return str(value) if value else None
    return None


def _all_nested_values(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _all_nested_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_nested_values(nested)
    else:
        yield value


def _message_mentions_any_tool(message: dict, names: tuple[str, ...]) -> bool:
    values = {str(value) for value in _all_nested_values(message)}
    return any(name in values for name in names)


def _assistant_messages(messages: list[dict]) -> list[dict]:
    return [message for message in messages if message.get("role") == "assistant"]


def _user_messages(messages: list[dict]) -> list[dict]:
    return [message for message in messages if message.get("role") == "user"]


def _message_metadata(message: dict) -> dict:
    meta = message.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _heartbeat_restore_patch(config: dict | None) -> dict[str, Any]:
    if not config:
        return {
            "enabled": False,
            "prompt": "",
            "dispatch_results": False,
            "runner_mode": None,
            "harness_effort": None,
        }
    keys = (
        "enabled",
        "interval_minutes",
        "model",
        "model_provider_id",
        "fallback_models",
        "prompt",
        "prompt_template_id",
        "workspace_file_path",
        "workspace_id",
        "dispatch_results",
        "dispatch_mode",
        "trigger_response",
        "quiet_start",
        "quiet_end",
        "timezone",
        "max_run_seconds",
        "previous_result_max_chars",
        "repetition_detection",
        "workflow_id",
        "workflow_session_mode",
        "skip_tool_approval",
        "append_spatial_prompt",
        "append_spatial_map_overview",
        "include_pinned_widgets",
        "execution_policy",
        "execution_config",
        "runner_mode",
        "harness_effort",
    )
    return {key: config.get(key) for key in keys if key in config}


async def _wait_for_new_heartbeat_run(
    client: E2EClient,
    channel_id: str,
    *,
    previous_ids: set[str],
    timeout: float,
) -> dict:
    deadline = time.monotonic() + timeout
    terminal = {"complete", "failed", "cancelled", "deferred"}
    latest: dict | None = None
    while time.monotonic() < deadline:
        payload = await client.get_channel_heartbeat(channel_id)
        history = payload.get("history") or []
        for run in history:
            if str(run.get("id")) in previous_ids:
                continue
            latest = run
            if str(run.get("status")) in terminal:
                return run
            break
        await asyncio.sleep(2)
    raise AssertionError(f"heartbeat run did not finish within {timeout}s; latest={latest}")


def _has_persisted_tool_transcript(message: dict) -> bool:
    tool_calls = message.get("tool_calls")
    meta = message.get("metadata") or {}
    body = meta.get("assistant_turn_body") if isinstance(meta, dict) else None
    items = body.get("items") if isinstance(body, dict) else None
    return bool(tool_calls) and any(
        isinstance(item, dict) and item.get("kind") == "tool_call"
        for item in (items or [])
    )


def _has_persisted_tool_result_envelope(message: dict) -> bool:
    tool_call_ids = {
        call.get("id")
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict) and isinstance(call.get("id"), str)
    }
    meta = message.get("metadata") or {}
    tool_results = meta.get("tool_results") if isinstance(meta, dict) else None
    return any(
        isinstance(result, dict) and isinstance(result.get("content_type"), str)
        and (
            not tool_call_ids
            or not result.get("tool_call_id")
            or result.get("tool_call_id") in tool_call_ids
        )
        for result in (tool_results or [])
    )


def _has_persisted_tool_result_containing(message: dict, expected: str) -> bool:
    tool_call_ids = {
        call.get("id")
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict) and isinstance(call.get("id"), str)
    }
    meta = message.get("metadata") or {}
    tool_results = meta.get("tool_results") if isinstance(meta, dict) else None
    return any(
        isinstance(result, dict)
        and (
            not tool_call_ids
            or not result.get("tool_call_id")
            or result.get("tool_call_id") in tool_call_ids
        )
        and expected in str(result.get("body") or result.get("plain_body") or "")
        for result in (tool_results or [])
    )


def _assistant_turn_body_preserves_tool_then_text_order(message: dict, expected: str) -> bool:
    meta = message.get("metadata") or {}
    body = meta.get("assistant_turn_body") if isinstance(meta, dict) else None
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return False
    tool_indexes = [
        index for index, item in enumerate(items)
        if isinstance(item, dict) and item.get("kind") == "tool_call"
    ]
    text_indexes = [
        index for index, item in enumerate(items)
        if isinstance(item, dict)
        and item.get("kind") == "text"
        and expected in str(item.get("text") or "")
    ]
    return bool(tool_indexes) and bool(text_indexes) and max(tool_indexes) < max(text_indexes)


def _has_harness_hint_containing(message: dict, kind: str, expected: str) -> bool:
    harness = _message_metadata(message).get("harness") or {}
    hints = harness.get("last_hints_sent") or []
    return any(
        isinstance(hint, dict)
        and hint.get("kind") == kind
        and expected in str(hint.get("text") or hint.get("preview") or "")
        for hint in hints
    )


def _assert_persisted_bridge_tool_result(
    messages: list[dict],
    *,
    tool_name: str,
    expected: str | None = None,
) -> None:
    assistants = _assistant_messages(messages)
    visible_names = _bridge_visible_names(tool_name)
    matching = [
        message for message in assistants
        if _message_mentions_any_tool(message, visible_names)
    ]
    assert matching, f"{visible_names} was not visible in persisted assistant messages"
    assert any(_has_persisted_tool_transcript(message) for message in matching), (
        f"{tool_name} did not persist canonical tool call transcript"
    )
    assert any(_has_persisted_tool_result_envelope(message) for message in matching), (
        f"{tool_name} did not persist a ToolResultEnvelope for replay/UI rendering"
    )
    if expected is not None:
        assert any(_has_persisted_tool_result_containing(message, expected) for message in matching), (
            f"{tool_name} persisted results did not include expected content {expected!r}"
        )


def _has_get_tool_info_schema_envelope(message: dict, tool_name: str) -> bool:
    meta = message.get("metadata") or {}
    tool_results = meta.get("tool_results") if isinstance(meta, dict) else None
    for result in tool_results or []:
        if not isinstance(result, dict):
            continue
        if result.get("tool_name") != "get_tool_info":
            continue
        body = result.get("body")
        if not isinstance(body, str):
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        schema = parsed.get("schema") if isinstance(parsed, dict) else None
        fn = schema.get("function") if isinstance(schema, dict) else None
        if isinstance(fn, dict) and fn.get("name") == tool_name:
            return True
    return False


def _assert_bridge_baseline(
    status: dict,
    *,
    required: tuple[str, ...] = CORE_BRIDGE_BASELINE_TOOLS,
) -> None:
    bridge = status.get("bridge_status") or {}
    exported = set(str(name) for name in bridge.get("exported_tools") or [])
    required_seen = set(str(name) for name in bridge.get("required_baseline_tools") or [])
    missing = set(str(name) for name in bridge.get("missing_baseline_tools") or [])
    assert not missing, f"missing harness bridge baseline tools: {sorted(missing)}"
    for tool_name in required:
        assert tool_name in exported or tool_name in required_seen, (
            f"{tool_name!r} was not visible in harness bridge status: {bridge}"
        )


def _model_option_map(caps: dict) -> dict[str, dict]:
    options = caps.get("model_options") or []
    return {
        str(option.get("id")): option
        for option in options
        if isinstance(option, dict) and option.get("id")
    }


def _choose_model_and_effort(case: HarnessCase, caps: dict) -> tuple[str | None, str | None]:
    options = _model_option_map(caps)
    available = set(str(model) for model in (caps.get("available_models") or []))
    available.update(options)
    available.update(str(model) for model in (caps.get("supported_models") or []))

    requested_model = os.environ.get(case.model_env, "").strip()
    candidates = (requested_model,) if requested_model else case.model_candidates
    model = next((candidate for candidate in candidates if candidate in available), None)
    if model is None and options:
        model = next(iter(options))
    if model is None and available:
        model = sorted(available)[0]

    option = options.get(model or "")
    effort_values = []
    if isinstance(option, dict):
        effort_values = [str(value) for value in option.get("effort_values") or []]
    if not effort_values:
        effort_values = [str(value) for value in caps.get("effort_values") or []]

    requested_effort = os.environ.get(case.effort_env, "").strip()
    if requested_effort and requested_effort in effort_values:
        return model, requested_effort
    for effort in ("minimal", "low", "medium", "high", "xhigh", "max"):
        if effort in effort_values:
            return model, effort
    return model, None


async def _configure_low_cost_session(
    client: E2EClient,
    case: HarnessCase,
    session_id: str,
) -> tuple[str | None, str | None, dict]:
    caps = await client.get_runtime_capabilities(case.runtime)
    model, effort = _choose_model_and_effort(case, caps)
    if model:
        result = await client.execute_slash_command("model", session_id=session_id, args=[model])
        assert result["payload"]["effect"] == "model"
    if effort:
        result = await client.execute_slash_command("effort", session_id=session_id, args=[effort])
        assert result["payload"]["effect"] == "effort"
    settings = await client.get_session_harness_settings(session_id)
    if model:
        assert settings["model"] == model
    if effort:
        assert settings["effort"] == effort
    return model, effort, caps


async def _assert_trace_has_turn_context(client: E2EClient, result: StreamResult) -> dict:
    turn_id = _turn_id(result)
    assert turn_id, "turn stream did not expose a turn/correlation id"
    trace = await client.get_trace_detail(turn_id)
    assert trace["correlation_id"] == turn_id
    kinds = {event["kind"] for event in trace["events"]}
    assert "message" in kinds or "trace_event" in kinds
    return trace


async def _assert_usage_surfaces_harness_channel(
    client: E2EClient,
    case: HarnessCase,
    channel_id: str,
) -> None:
    provider_id = _expected_usage_provider(case)
    logs = await client.get_usage_logs(
        provider_id=provider_id,
        channel_id=channel_id,
        page_size=20,
    )
    entries = logs.get("entries") or []
    assert any(
        entry.get("provider_id") == provider_id
        and entry.get("channel_id") == channel_id
        and entry.get("billing_source") == "harness_sdk"
        and entry.get("has_cost_data") is True
        for entry in entries
    ), f"harness usage log row not found for {provider_id} in channel {channel_id}: {entries}"

    breakdown = await client.get_usage_breakdown(
        group_by="channel",
        provider_id=provider_id,
        channel_id=channel_id,
    )
    groups = breakdown.get("groups") or []
    assert any(
        group.get("key") == channel_id
        and int(group.get("tokens") or 0) > 0
        for group in groups
    ), f"harness usage did not contribute to channel breakdown for {channel_id}: {groups}"


def _is_local_e2e_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    return (
        normalized in {"", "localhost", "0.0.0.0", "::1", "host.docker.internal"}
        or normalized.startswith("127.")
    )


async def _assert_browser_runtime_live_diagnostics(
    client: E2EClient,
    *,
    require_shared_runtime: bool = True,
) -> None:
    stacks = await client.list_docker_stacks()
    browser_stacks = [s for s in stacks if s.get("integration_id") == "browser_automation"]
    if os.environ.get("HARNESS_PARITY_LOCAL") == "1":
        running_browser_stacks = [s for s in browser_stacks if s.get("status") == "running"]
        if not browser_stacks and require_shared_runtime:
            pytest.skip("local harness parity stack does not expose browser_automation docker stacks")
        if not require_shared_runtime and not running_browser_stacks:
            return
    assert browser_stacks, "browser_automation docker stack is not registered"
    stack = browser_stacks[0]
    assert stack.get("status") == "running", f"browser_automation stack is not running: {stack}"

    services = await client.get_docker_stack_status(str(stack["id"]))
    assert any(
        service.get("name") == "playwright" and service.get("state") == "running"
        for service in services
    ), f"playwright service is not running: {services}"

    tools = await client.list_admin_tools()
    tool_names = {str(tool.get("tool_name") or tool.get("name") or "") for tool in tools}
    missing = [tool for tool in HEADLESS_BROWSER_TOOLS if tool not in tool_names]
    assert not missing, f"headless browser tools are not indexed: {missing}"

    if client.config.is_external and not _is_local_e2e_host(client.config.host):
        return

    if not shutil.which("docker"):
        pytest.skip("docker CLI is not available for container DNS diagnostics")
    container = os.environ.get("HARNESS_PARITY_AGENT_CONTAINER", "")
    if not container:
        return
    host = os.environ.get("HARNESS_PARITY_PLAYWRIGHT_HOST", "playwright-local")
    proc = subprocess.run(
        ["docker", "exec", container, "getent", "hosts", host],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, (
        f"agent container could not resolve {host!r}; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


def _start_project_http_server(directory: str) -> tuple[subprocess.Popen, str]:
    container = os.environ.get("HARNESS_PARITY_AGENT_CONTAINER", "")
    base_port = int(os.environ.get("HARNESS_PARITY_APP_PORT_BASE", "18500"))
    offset = int(uuid.uuid4().hex[:4], 16) % 200
    last_error = ""
    for index in range(20):
        port = base_port + offset + index
        if container:
            if not shutil.which("docker"):
                pytest.skip("docker CLI is not available for project screenshot diagnostics")
            cmd = [
                "docker",
                "exec",
                container,
                "python",
                "-m",
                "http.server",
                str(port),
                "--bind",
                "0.0.0.0",
                "--directory",
                directory,
            ]
            probe_cmd = [
                "docker",
                "exec",
                container,
                "python",
                "-c",
                (
                    "import urllib.request; "
                    f"urllib.request.urlopen('http://127.0.0.1:{port}/', timeout=1).read(32)"
                ),
            ]
            url = f"http://agent-server:{port}/"
        else:
            cmd = [
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                "127.0.0.1",
                "--directory",
                directory,
            ]
            probe_cmd = [
                sys.executable,
                "-c",
                (
                    "import urllib.request; "
                    f"urllib.request.urlopen('http://127.0.0.1:{port}/', timeout=1).read(32)"
                ),
            ]
            url = f"http://127.0.0.1:{port}/"
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stderr = proc.stderr.read() if proc.stderr else ""
                last_error = stderr or f"server exited with code {proc.returncode}"
                break
            probe = subprocess.run(
                probe_cmd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=4,
                check=False,
            )
            if probe.returncode == 0:
                return proc, url
            last_error = probe.stderr
            time.sleep(0.25)
        if proc.poll() is None:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=3)
            if proc.poll() is None:
                proc.kill()
    raise AssertionError(f"could not start project HTTP server for {directory!r}: {last_error}")


async def _capture_project_screenshot(*, url: str, out_path: Path, marker: str) -> None:
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright
    from scripts.screenshots.playwright_runtime import launch_async_browser

    out_path.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await launch_async_browser(pw)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=1)
            await page.goto(url, wait_until="networkidle")
            body_text = await page.locator("body").inner_text()
            assert marker.lower() in body_text.lower(), (
                f"generated app marker {marker!r} was not visible at {url}"
            )
            await page.screenshot(path=str(out_path), full_page=True)
        finally:
            await browser.close()


async def _capture_session_marker_screenshot(
    client: E2EClient,
    *,
    channel_id: str,
    session_id: str,
    marker: str,
    screenshot_name: str,
) -> Path:
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright
    from scripts.screenshots.playwright_runtime import launch_async_browser

    ui_url = _browser_ui_url(client)
    api_url = _browser_api_url(client)
    route = f"{ui_url}/channels/{channel_id}/session/{session_id}?surface=channel"
    out_path = _artifact_root() / "native-cli" / f"{Path(screenshot_name).stem}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await launch_async_browser(pw)
        try:
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="dark",
            )
            await context.add_init_script(
                _browser_auth_init_script(api_url=api_url, api_key=client.config.api_key)
            )
            page = await context.new_page()
            await page.goto(route, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_function(
                "(marker) => document.body.innerText.includes(marker)",
                arg=marker,
                timeout=60_000,
            )
            await _assert_no_horizontal_overflow(page, "native-cli-mirror")
            assert await page.get_by_role("button", name=re.compile("Native CLI|Spindrel chat")).count() >= 1
            await page.screenshot(path=str(out_path), full_page=False)
            await context.close()
        finally:
            await browser.close()
    return out_path


async def _send_native_cli_prompt_via_ui(
    client: E2EClient,
    *,
    runtime_name: str,
    channel_id: str,
    session_id: str,
    prompt: str,
    marker: str,
    terminal_screenshot_name: str | None = None,
    mirror_screenshot_name: str | None = None,
    toggle_to_chat_after_submit: bool = True,
) -> tuple[Path | None, Path | None, dict[str, Any] | None]:
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright
    from scripts.screenshots.playwright_runtime import launch_async_browser

    ui_url = _browser_ui_url(client)
    api_url = _browser_api_url(client)
    route = f"{ui_url}/channels/{channel_id}/session/{session_id}?surface=channel"
    terminal_out_path = (
        _artifact_root() / "native-cli" / f"{Path(terminal_screenshot_name).stem}.png"
        if terminal_screenshot_name
        else None
    )
    mirror_out_path = (
        _artifact_root() / "native-cli" / f"{Path(mirror_screenshot_name).stem}.png"
        if mirror_screenshot_name
        else None
    )
    for out_path in (terminal_out_path, mirror_out_path):
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await launch_async_browser(pw)
        try:
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="dark",
            )
            await context.add_init_script(
                _browser_auth_init_script(api_url=api_url, api_key=client.config.api_key)
            )
            page = await context.new_page()
            await page.goto(route, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_function(
                "(marker) => document.body.innerText.includes(marker)",
                arg=marker,
                timeout=60_000,
            )
            native_toggle = page.get_by_role("button", name=re.compile(r"^Native CLI$")).first
            try:
                await native_toggle.wait_for(state="visible", timeout=30_000)
            except Exception:
                debug_path = _artifact_root() / "native-cli" / f"harness-{runtime_name}-native-cli-toggle-missing.png"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(Exception):
                    await page.screenshot(path=str(debug_path), full_page=False)
                body = await page.locator("body").inner_text(timeout=10_000)
                raise AssertionError(
                    "Native CLI toggle was not visible on the channel session surface; "
                    f"debug screenshot: {debug_path}; body tail:\n{body[-2000:]}"
                )
            await native_toggle.click(timeout=30_000)
            panel = page.locator('[data-testid="admin-terminal-panel"]').first
            try:
                await panel.wait_for(state="visible", timeout=60_000)
            except Exception:
                debug_path = _artifact_root() / "native-cli" / f"harness-{runtime_name}-native-cli-mount-failed.png"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(Exception):
                    await page.screenshot(path=str(debug_path), full_page=False)
                body = await page.locator("body").inner_text(timeout=10_000)
                raise AssertionError(
                    "Native CLI toggle did not mount the terminal panel; "
                    f"debug screenshot: {debug_path}; body tail:\n{body[-2000:]}"
                )
            xterm = page.locator('[data-testid="admin-terminal-xterm"] .xterm').first
            await xterm.wait_for(state="visible", timeout=60_000)
            if runtime_name == "claude-code":
                try:
                    await page.wait_for_function(
                        """() => {
                            const text = document.body.innerText.toLowerCase();
                            return (
                                text.includes("yes, i trust this folder")
                                || text.includes("enter to confirm")
                                || text.includes("type /")
                                || text.includes("use /skills")
                                || text.includes("? for shortcuts")
                                || text.includes("esc to interrupt")
                            );
                        }""",
                        timeout=30_000,
                    )
                    body_text = await page.locator("body").inner_text(timeout=10_000)
                    if "yes, i trust this folder" in body_text.lower() or "enter to confirm" in body_text.lower():
                        await xterm.click(position={"x": 80, "y": 120})
                        await page.keyboard.press("Enter")
                except Exception:
                    pass
            try:
                await page.wait_for_function(
                    """() => {
                        const text = document.body.innerText.toLowerCase();
                        return (
                            text.includes("tab to queue message")
                            || text.includes("type /")
                            || text.includes("use /skills")
                            || text.includes("context left")
                            || text.includes("? for shortcuts")
                            || text.includes("esc to interrupt")
                            || text.includes("bypassing permissions")
                            || text.includes("bypass permissions")
                            || text.includes("cwd:")
                        );
                    }""",
                    timeout=90_000,
                )
            except Exception:
                debug_path = _artifact_root() / "native-cli" / f"harness-{runtime_name}-native-cli-ready-timeout.png"
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(Exception):
                    await page.screenshot(path=str(debug_path), full_page=False)
                body = await page.locator("body").inner_text(timeout=10_000)
                raise AssertionError(
                    "Native CLI did not become ready before input; "
                    f"debug screenshot: {debug_path}; body tail:\n{body[-2000:]}"
                )
            await _assert_no_horizontal_overflow(page, "native-cli-terminal")
            if terminal_out_path is not None:
                await page.screenshot(path=str(terminal_out_path), full_page=False)
            await xterm.click(position={"x": 80, "y": 120})
            await page.keyboard.type(prompt, delay=8)
            await page.keyboard.press("Enter")
            if toggle_to_chat_after_submit:
                await page.get_by_role("button", name=re.compile(r"^Spindrel chat$")).click(timeout=30_000)
            await page.wait_for_function(
                "(marker) => document.body.innerText.toLowerCase().includes(marker.toLowerCase())",
                arg=marker,
                timeout=60_000,
            )
            await _assert_no_horizontal_overflow(page, "native-cli-ui")
            if mirror_out_path is not None:
                await page.screenshot(path=str(mirror_out_path), full_page=False)
            mirrored_message: dict[str, Any] | None = None
            deadline = time.monotonic() + _timeout()
            while time.monotonic() < deadline:
                messages = await client.get_session_messages(session_id, limit=80)
                for message in reversed(messages):
                    if message.get("role") != "assistant":
                        continue
                    if marker not in str(message.get("content") or ""):
                        continue
                    metadata = _message_metadata(message)
                    native_meta = metadata.get("harness_native_cli")
                    if isinstance(native_meta, dict) and native_meta.get("runtime") == runtime_name:
                        mirrored_message = message
                        break
                if mirrored_message is not None:
                    break
                await asyncio.sleep(2)
            if mirrored_message is None and mirror_out_path is not None:
                timeout_path = mirror_out_path.with_name(f"{mirror_out_path.stem}-mirror-timeout{mirror_out_path.suffix}")
                with contextlib.suppress(Exception):
                    await page.screenshot(path=str(timeout_path), full_page=False)
            if mirrored_message is not None and toggle_to_chat_after_submit:
                mirrored_text = str(mirrored_message.get("content") or "")
                try:
                    await page.wait_for_function(
                        "(text) => document.body.innerText.toLowerCase().includes(text.toLowerCase())",
                        arg=mirrored_text,
                        timeout=60_000,
                    )
                except Exception:
                    debug_path = _artifact_root() / "native-cli" / f"harness-{runtime_name}-native-cli-chat-mirror-timeout.png"
                    debug_path.parent.mkdir(parents=True, exist_ok=True)
                    with contextlib.suppress(Exception):
                        await page.screenshot(path=str(debug_path), full_page=False)
                    body = await page.locator("body").inner_text(timeout=10_000)
                    raise AssertionError(
                        "Native CLI mirror persisted but did not appear in Spindrel chat after toggling back; "
                        f"debug screenshot: {debug_path}; body tail:\n{body[-2000:]}"
                    )
                if mirror_out_path is not None:
                    await page.screenshot(path=str(mirror_out_path), full_page=False)
            await context.close()
        finally:
            await browser.close()
    return terminal_out_path, mirror_out_path, mirrored_message


def _browser_ui_url(client: E2EClient) -> str:
    return (
        os.environ.get("SPINDREL_BROWSER_URL")
        or os.environ.get("SPINDREL_UI_URL")
        or client.config.base_url
    ).rstrip("/")


def _browser_api_url(client: E2EClient) -> str:
    return (
        os.environ.get("SPINDREL_BROWSER_API_URL")
        or os.environ.get("SPINDREL_BROWSER_URL")
        or os.environ.get("SPINDREL_UI_URL")
        or client.config.base_url
    ).rstrip("/")


def _browser_auth_init_script(*, api_url: str, api_key: str) -> str:
    auth_state = {
        "serverUrl": api_url,
        "apiKey": api_key,
        "accessToken": "",
        "refreshToken": "",
        "user": {
            "id": "harness-terminal-parity",
            "email": "harness-terminal-parity@spindrel.local",
            "display_name": "Harness Terminal Parity",
            "avatar_url": None,
            "integration_config": {},
            "is_admin": True,
            "auth_method": "api_key",
            "scopes": ["*"],
        },
        "isConfigured": True,
    }
    theme_state = {"mode": "dark"}
    return "\n".join((
        f"localStorage.setItem('agent-auth', {json.dumps(json.dumps({'state': auth_state, 'version': 0}))});",
        f"localStorage.setItem('agent-theme', {json.dumps(json.dumps({'state': theme_state, 'version': 0}))});",
    ))


def _terminal_ws_url(client: E2EClient, terminal_session_id: str) -> str:
    parsed = urlparse(client.config.base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((
        scheme,
        parsed.netloc,
        f"/api/v1/admin/terminal/{terminal_session_id}",
        "",
        f"token={client.config.api_key}",
        "",
    ))


async def _send_terminal_input(
    client: E2EClient,
    *,
    terminal_session_id: str,
    text: str,
    wait_for: str | None = None,
    timeout: float,
) -> str:
    seen = bytearray()
    async with websockets.connect(_terminal_ws_url(client, terminal_session_id), open_timeout=20) as ws:
        await ws.send(json.dumps({"type": "resize", "rows": 42, "cols": 140}))
        ready_deadline = time.monotonic() + 8
        while time.monotonic() < ready_deadline:
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            try:
                payload = json.loads(frame)
            except Exception:
                continue
            if payload.get("type") == "data":
                try:
                    seen.extend(base64.b64decode(str(payload.get("data") or "")))
                except Exception:
                    pass
                lower = seen.decode("utf-8", errors="replace").lower()
                if "codex" in lower or "claude" in lower or "›" in lower:
                    break
            elif payload.get("type") == "exit":
                break
        await asyncio.sleep(8)
        chunks = [text]
        if text.endswith("\r") and len(text) > 1:
            chunks = [text[:-1], "\r"]
        for idx, chunk in enumerate(chunks):
            await ws.send(json.dumps({
                "type": "data",
                "data": base64.b64encode(chunk.encode()).decode("ascii"),
            }))
            if idx < len(chunks) - 1:
                await asyncio.sleep(0.75)
        deadline = time.monotonic() + timeout
        started_waiting = time.monotonic()
        extra_enter_sent = False
        expected = (wait_for or text.strip()).encode()
        while time.monotonic() < deadline:
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                if not extra_enter_sent and time.monotonic() - started_waiting > 10:
                    extra_enter_sent = True
                    await ws.send(json.dumps({
                        "type": "data",
                        "data": base64.b64encode(b"\r").decode("ascii"),
                    }))
                continue
            try:
                payload = json.loads(frame)
            except Exception:
                continue
            if payload.get("type") == "data":
                try:
                    seen.extend(base64.b64decode(str(payload.get("data") or "")))
                except Exception:
                    pass
            elif payload.get("type") == "exit":
                break
            if expected in seen:
                break
    return seen.decode("utf-8", errors="replace")


async def _assert_terminal_transcript_ui(
    client: E2EClient,
    *,
    channel_id: str,
    session_id: str,
    marker: str,
    min_rows: int,
    screenshot_name: str,
) -> Path:
    paths = await _assert_harness_chat_mode_ui(
        client,
        channel_id=channel_id,
        session_id=session_id,
        marker=marker,
        chat_mode="terminal",
        min_rows=min_rows,
        screenshot_name=screenshot_name,
    )
    assert paths, "terminal parity screenshot helper did not return screenshots"
    return paths[0]


async def _assert_no_horizontal_overflow(page: Any, label: str) -> None:
    metrics = await page.evaluate(
        """() => ({
            viewportWidth: window.innerWidth,
            documentScrollWidth: document.documentElement.scrollWidth,
            bodyScrollWidth: document.body ? document.body.scrollWidth : 0,
        })"""
    )
    max_scroll = max(
        int(metrics.get("documentScrollWidth") or 0),
        int(metrics.get("bodyScrollWidth") or 0),
    )
    viewport = int(metrics.get("viewportWidth") or 0)
    assert max_scroll <= viewport + 2, f"{label} has horizontal overflow: {metrics}"


async def _assert_terminal_rows_fit_viewport(page: Any, *, label: str, min_rows: int) -> None:
    rows = page.locator('[data-testid="tool-transcript-row"]')
    row_count = await rows.count()
    assert row_count >= min_rows, f"expected at least {min_rows} terminal tool rows, saw {row_count}"
    boxes = await rows.evaluate_all(
        """(nodes) => nodes.map((node) => {
            const rect = node.getBoundingClientRect();
            return { left: rect.left, right: rect.right, width: rect.width };
        })"""
    )
    viewport_width = await page.evaluate("() => window.innerWidth")
    for idx, box in enumerate(boxes):
        assert box["left"] >= -1, f"{label} terminal row {idx} starts offscreen: {box}"
        assert box["right"] <= viewport_width + 1, f"{label} terminal row {idx} overflows viewport: {box}"


async def _assert_mobile_header_safe(page: Any, *, label: str) -> None:
    viewport = page.viewport_size or {}
    if int(viewport.get("width") or 0) > 600:
        return
    title = page.locator('[data-testid="channel-header-title-region"]').first
    await title.click(position={"x": 16, "y": 16})
    await page.wait_for_timeout(150)
    assert await page.get_by_text("Harness context").count() == 0, (
        f"{label} mobile title click opened harness context chrome"
    )
    assert await page.get_by_text("Configuration overhead").count() == 0, (
        f"{label} mobile title click opened bot info chrome"
    )
    assert await page.get_by_text("View full context details").count() == 0, (
        f"{label} mobile title click opened bot info context details"
    )

    mobile_context_chip = page.locator('[data-testid="harness-context-chip-mobile"]').first
    desktop_context_chip = page.locator('[data-testid="harness-context-chip"]').first
    context_chip = mobile_context_chip
    context_panel = page.locator('[data-testid="harness-context-panel-mobile"]').first
    try:
        await mobile_context_chip.wait_for(state="visible", timeout=10_000)
    except Exception:
        await desktop_context_chip.wait_for(state="visible", timeout=10_000)
        context_chip = desktop_context_chip
        context_panel = page.locator('[data-testid="harness-context-panel"]').first
    await context_chip.click()
    await context_panel.wait_for(state="visible", timeout=5_000)
    panel_box = await context_panel.bounding_box()
    viewport_width = int(viewport.get("width") or 0)
    viewport_height = int(viewport.get("height") or 0)
    assert panel_box, f"{label} mobile harness context did not produce a bounding box"
    assert panel_box["x"] >= 0 and panel_box["x"] + panel_box["width"] <= viewport_width + 1, (
        f"{label} mobile harness context is horizontally offscreen: {panel_box}"
    )
    assert panel_box["y"] >= 0 and panel_box["y"] + panel_box["height"] <= viewport_height + 1, (
        f"{label} mobile harness context is vertically offscreen: {panel_box}"
    )
    await page.locator('[aria-label="Close context details"]').first.click()
    await page.wait_for_timeout(100)

    more = page.locator('[aria-label="More actions"]').first
    if await more.count() == 0:
        return
    await more.click()
    menu = page.locator('[data-testid="channel-header-mobile-overflow-menu"]').first
    await menu.wait_for(state="visible", timeout=5_000)
    box = await menu.bounding_box()
    assert box, f"{label} mobile overflow menu did not produce a bounding box"
    assert box["x"] >= 0 and box["x"] + box["width"] <= viewport_width + 1, (
        f"{label} mobile overflow menu is horizontally offscreen: {box}"
    )
    assert box["y"] >= 0 and box["y"] + box["height"] <= viewport_height + 1, (
        f"{label} mobile overflow menu is vertically offscreen: {box}"
    )
    await page.keyboard.press("Escape")


async def _assert_harness_chat_mode_ui(
    client: E2EClient,
    *,
    channel_id: str,
    session_id: str,
    marker: str,
    chat_mode: str,
    min_rows: int,
    screenshot_name: str,
) -> list[Path]:
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright
    from scripts.screenshots.playwright_runtime import launch_async_browser

    ui_url = _browser_ui_url(client)
    api_url = _browser_api_url(client)
    route = f"{ui_url}/channels/{channel_id}/session/{session_id}"
    screenshot_stem = Path(screenshot_name).stem
    screenshots: list[Path] = []
    viewport_cases = (
        ("desktop", {"width": 1440, "height": 900}),
        ("mobile", {"width": 390, "height": 844}),
    )

    async with async_playwright() as pw:
        browser = await launch_async_browser(pw)
        try:
            for viewport_name, viewport in viewport_cases:
                context = await browser.new_context(
                    viewport=viewport,
                    color_scheme="dark",
                )
                await context.add_init_script(
                    _browser_auth_init_script(api_url=api_url, api_key=client.config.api_key)
                )
                page = await context.new_page()
                await page.goto(route, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_function(
                    "(marker) => document.body.innerText.includes(marker)",
                    arg=marker,
                    timeout=60_000,
                )
                await page.reload(wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_function(
                    "(marker) => document.body.innerText.includes(marker)",
                    arg=marker,
                    timeout=60_000,
                )

                label = f"{chat_mode}/{viewport_name}"
                await _assert_no_horizontal_overflow(page, label)
                await _assert_mobile_header_safe(page, label=label)

                if chat_mode == "terminal":
                    await page.wait_for_selector('[data-testid="terminal-tool-transcript"]', timeout=60_000)
                    await _assert_terminal_rows_fit_viewport(page, label=label, min_rows=min_rows)
                    assert await page.locator('[data-testid="terminal-tool-output"]').count() > 0
                    assert await page.locator('[data-testid="tool-trace-strip"]').count() == 0

                    transcript_text = await page.locator(
                        '[data-testid="terminal-tool-transcript"]'
                    ).inner_text(timeout=10_000)
                    lower = transcript_text.lower()
                    assert "harness-spindrel:" not in lower
                    assert "tool calls" not in lower
                else:
                    assert await page.locator('[data-testid="terminal-tool-transcript"]').count() == 0
                    await page.wait_for_selector('[data-testid="tool-trace-strip"]', timeout=60_000)
                    assert await page.locator('[data-testid="tool-trace-strip"]').count() > 0

                screenshot_path = _artifact_root() / chat_mode / f"{screenshot_stem}-{viewport_name}.png"
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshot_path), full_page=False)
                screenshots.append(screenshot_path)
                await context.close()
        finally:
            await browser.close()
    return screenshots


async def _read_workspace_file_with_retry(
    client: E2EClient,
    workspace_id: str,
    path: str,
    *,
    timeout: float = 10.0,
) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return await client.read_workspace_file(workspace_id, path)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.5)
    if last_error is not None:
        raise last_error
    raise AssertionError(f"workspace file was not readable: {path}")


def _status_context_tokens(status: dict[str, Any]) -> int | None:
    diagnostics = status.get("context_diagnostics") or {}
    value = diagnostics.get("context_tokens") if isinstance(diagnostics, dict) else None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


def _status_remaining_pct(status: dict[str, Any]) -> float | None:
    value = status.get("context_remaining_pct")
    if isinstance(value, (int, float)):
        return float(value)
    diagnostics = status.get("context_diagnostics") or {}
    diag_value = diagnostics.get("remaining_pct") if isinstance(diagnostics, dict) else None
    if isinstance(diag_value, (int, float)):
        return float(diag_value)
    return None


def _context_snapshot_tokens(snapshot: dict[str, Any] | None) -> int | None:
    if not isinstance(snapshot, dict):
        return None
    for key in ("context_tokens", "last_total_tokens", "context_total_tokens"):
        value = snapshot.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    usage = snapshot.get("usage")
    if isinstance(usage, dict):
        for key in ("context_tokens", "last_total_tokens", "context_total_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
    return None


def _context_snapshot_remaining_pct(snapshot: dict[str, Any] | None) -> float | None:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get("remaining_pct")
    if isinstance(value, (int, float)):
        return float(value)
    usage = snapshot.get("usage")
    if isinstance(usage, dict):
        for key in ("context_remaining_pct", "context_remaining_percent", "remaining_pct"):
            usage_value = usage.get(key)
            if isinstance(usage_value, (int, float)):
                return float(usage_value)
    return None


async def _assert_harness_project_cwd(
    client: E2EClient,
    *,
    channel_id: str,
    session_id: str,
    expected_project_path: str,
) -> dict:
    status = await client.get_session_harness_status(session_id)
    assert status["effective_cwd_source"] == "channel_project_dir", status
    project_dir = status.get("project_dir") or {}
    assert project_dir.get("path") == expected_project_path, status
    effective_cwd = str(status.get("effective_cwd") or "")
    assert effective_cwd.endswith(f"/{expected_project_path}"), status
    assert "/opt/thoth-server" not in effective_cwd, status

    settings = await client.get_channel_settings(channel_id)
    expected_project_id = os.environ.get("HARNESS_PARITY_PROJECT_ID", "").strip()
    if expected_project_id:
        assert str(settings.get("project_id") or "") == expected_project_id
    assert settings.get("project_path") == expected_project_path
    assert settings.get("resolved_project_workspace_id") == project_dir.get("workspace_id")
    return status


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_core_parity_controls_trace_and_context(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    original_config = await client.get_channel_config(channel_id)

    try:
        model, effort, caps = await _configure_low_cost_session(client, case, session_id)
        approval_mode = await client.set_session_approval_mode(session_id, "acceptEdits")
        assert approval_mode["mode"] == "acceptEdits"

        style = await client.execute_slash_command("style", session_id=session_id, args=["terminal"])
        assert style["payload"]["effect"] == "style"
        assert style["payload"]["scope_id"] == channel_id
        terminal_config = await client.get_channel_config(channel_id)
        assert terminal_config.get("chat_mode") == "terminal"

        for command in case.native_commands:
            result = await client.execute_slash_command("runtime", session_id=session_id, args=[command])
            assert result["result_type"] == "harness_runtime_command"
            assert result["payload"]["command"] == command
            assert result["payload"]["status"] in {"ok", "error", "terminal_handoff"}
            assert result["payload"].get("detail") or result.get("fallback_text")

        initial_context = await client.execute_slash_command("context", session_id=session_id)
        assert initial_context["result_type"] == "harness_runtime_command"
        assert initial_context["payload"]["runtime"] == case.runtime
        assert initial_context["payload"]["command"] == "context"
        assert initial_context["payload"].get("title"), initial_context
        assert initial_context["payload"].get("status") in {"ok", "empty", "terminal_handoff", "error"}
        assert "host_context" not in initial_context["payload"]
        assert "native_context" not in initial_context["payload"]
        assert "[object Object]" not in json.dumps(initial_context)
        assert "Spindrel bridge tools" not in initial_context.get("fallback_text", "")

        marker = uuid.uuid4().hex[:12]
        result = await client.chat_session_stream(
            (
                f"Harness parity core check. The marker is {marker}. "
                "Do not call tools, write files, or persist it anywhere. "
                f"For this turn only, reply exactly: parity core ready {marker}"
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert f"parity core ready {marker}" in result.response_text.lower()
        await _assert_trace_has_turn_context(client, result)

        resumed = await client.chat_session_stream(
            "Reply with only the marker you acknowledged in your previous answer. Do not call tools or read files. Do not repeat any other prior phrase.",
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(resumed)
        assert marker in resumed.response_text
        await _assert_trace_has_turn_context(client, resumed)

        status = await client.get_session_harness_status(session_id)
        assert status["runtime"] == case.runtime
        assert status["harness_session_id"], "native harness session id was not persisted"
        assert status["usage"], "harness status did not expose latest runtime usage"
        inspector = status.get("run_inspector") or {}
        assert inspector.get("runtime") == case.runtime
        assert inspector.get("native_session_id") == status["harness_session_id"]
        assert inspector.get("cwd") == status.get("effective_cwd")

        native_context = await client.execute_slash_command("context", session_id=session_id)
        assert native_context["result_type"] == "harness_runtime_command"
        assert native_context["payload"]["runtime"] == case.runtime
        assert native_context["payload"]["command"] == "context"
        assert native_context["payload"].get("title"), native_context
        assert "host_context" not in native_context["payload"]
        assert "native_context" not in native_context["payload"]
        assert "[object Object]" not in json.dumps(native_context)
        assert "Spindrel bridge tools" not in native_context.get("fallback_text", "")
        if case.runtime == "claude-code":
            assert native_context["payload"].get("status") in {"ok", "empty"}, native_context
            assert native_context["payload"].get("data", {}).get("native_slash") == "/context"
        elif case.runtime == "codex":
            assert native_context["payload"].get("status") == "terminal_handoff", native_context
        assert isinstance((inspector.get("input_manifest") or {}), dict)
        _assert_bridge_baseline(status)
        if model:
            assert status["model"] == model
        if effort:
            assert status["effort"] == effort
        diagnostics = status.get("context_diagnostics") or {}
        assert diagnostics.get("confidence") in {"medium", "high", "low"}
        assert status.get("context_window_tokens") or caps.get("context_window_tokens")

        budget = await client.get_context_budget(channel_id, session_id=session_id)
        assert {"utilization", "consumed_tokens", "total_tokens"} <= set(budget.keys())
        await _assert_usage_surfaces_harness_channel(client, case, channel_id)

        messages = await client.get_session_messages(session_id)
        assert _assistant_messages(messages), "assistant message did not persist"
    finally:
        await client.patch_channel_config(
            channel_id,
            {"chat_mode": original_config.get("chat_mode") or "default"},
        )


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_core_native_slash_direct_commands(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, _bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)

    catalog = await client.get_runtime_capabilities(case.runtime)
    native_catalog = {command["id"] for command in catalog.get("native_commands", [])}
    aliases = {
        alias
        for command in catalog.get("native_commands", [])
        for alias in command.get("aliases", [])
    }
    for slash_name, runtime_command in case.direct_native_commands:
        assert slash_name in native_catalog or slash_name in aliases
        result = await client.execute_slash_command(
            slash_name,
            session_id=session_id,
            args=[],
        )
        assert result["result_type"] == "harness_runtime_command"
        assert result["command_id"] == slash_name
        assert result["payload"]["command"] == runtime_command
        expected_status = "ok"
        if case.name == "codex" and runtime_command in {"diff"}:
            expected_status = "terminal_handoff"
        if case.name == "codex" and runtime_command in {"apps", "hooks", "approvals"}:
            assert result["payload"]["status"] in {"ok", "terminal_handoff"}
            continue
        if case.name == "claude" and runtime_command in {
            "plugins", "mcp", "agents", "hooks", "status", "doctor",
        }:
            assert result["payload"]["status"] in {"ok", "terminal_handoff"}
        else:
            assert result["payload"]["status"] == expected_status
        assert result["payload"].get("detail") or result.get("fallback_text")
        if case.name == "codex" and runtime_command == "skills":
            status = await client.get_session_harness_status(session_id)
            expected_cwd = status.get("effective_cwd")
            data = result["payload"].get("data") or {}
            cwd_entries = data.get("data") if isinstance(data, dict) else None
            assert expected_cwd
            assert any(
                isinstance(entry, dict) and entry.get("cwd") == expected_cwd
                for entry in (cwd_entries or [])
            ), f"Codex /skills did not use harness cwd {expected_cwd!r}: {data}"


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_core_model_selection_is_plan_mode_scoped(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, _bot_id = await _fresh_session(client, case)
    default_model = f"e2e-default-{case.name}-{uuid.uuid4().hex[:8]}"
    plan_model = f"e2e-plan-{case.name}-{uuid.uuid4().hex[:8]}"

    default_result = await client.execute_slash_command(
        "model",
        session_id=session_id,
        args=[default_model],
    )
    assert default_result["result_type"] == "side_effect"
    assert default_result["payload"]["effect"] == "model"

    default_settings = await client.get_session_harness_settings(session_id)
    assert default_settings["model"] == default_model
    assert default_settings.get("mode_models", {}).get("default") == default_model
    assert default_settings.get("mode_models", {}).get("plan") is None

    await client.start_session_plan_mode(session_id)
    planning_before = await client.get_session_harness_settings(session_id)
    assert planning_before["model"] is None
    assert planning_before.get("mode_models", {}).get("default") == default_model

    plan_result = await client.execute_slash_command(
        "model",
        session_id=session_id,
        args=[plan_model],
    )
    assert plan_result["result_type"] == "side_effect"
    assert plan_result["payload"]["effect"] == "model"

    planning_settings = await client.get_session_harness_settings(session_id)
    assert planning_settings["model"] == plan_model
    assert planning_settings.get("mode_models", {}).get("default") == default_model
    assert planning_settings.get("mode_models", {}).get("plan") == plan_model

    await client.exit_session_plan_mode(session_id)
    chat_settings = await client.get_session_harness_settings(session_id)
    assert chat_settings["model"] == default_model
    assert chat_settings.get("mode_models", {}).get("default") == default_model
    assert chat_settings.get("mode_models", {}).get("plan") == plan_model

    await client.start_session_plan_mode(session_id)
    resumed_plan_settings = await client.get_session_harness_settings(session_id)
    assert resumed_plan_settings["model"] == plan_model


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_core_streams_partial_text_before_final(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    marker = uuid.uuid4().hex[:10]

    result = await client.chat_session_stream(
        (
            "Streaming parity check. Do not call tools. Reply with exactly four short lines. "
            f"Each line must include this marker: {marker}. "
            "Use this shape:\n"
            f"line one {marker}\n"
            f"line two {marker}\n"
            f"line three {marker}\n"
            f"line four {marker}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert marker in result.response_text
    text_deltas = [event for event in result.events if event.type == "text_delta"]
    assert len(text_deltas) >= 2, (
        f"{case.name} did not stream partial text before the final response; "
        f"saw {len(text_deltas)} text delta event(s)"
    )


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_core_native_slash_mutating_commands_handoff(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, _bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)

    for slash_name, args, suggested_command in case.native_terminal_handoff_commands:
        result = await client.execute_slash_command(
            slash_name,
            session_id=session_id,
            args=list(args),
        )
        assert result["result_type"] == "harness_runtime_command"
        assert result["command_id"] == slash_name
        assert result["payload"]["status"] == "terminal_handoff"
        assert result["payload"]["data"]["suggested_command"] == suggested_command
        assert result["payload"].get("detail") or result.get("fallback_text")


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_claude_project_local_native_skill_invocation(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("skills")
    if case.name != "claude":
        pytest.skip("project-local native skill invocation is Claude Code-specific")

    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    await client.set_session_approval_mode(session_id, "bypassPermissions")
    original_settings = await client.get_channel_settings(channel_id)
    expected_project_path = _project_path()
    marker = uuid.uuid4().hex[:12]
    skill_name = f"harness-native-slash-{marker}"
    expected_phrase = f"NATIVE_SKILL_LOADED_{marker}"
    skill_root = f"{expected_project_path}/.claude/skills/{skill_name}"
    skill_path = f"{skill_root}/SKILL.md"
    workspace_id: str | None = None
    restored = False

    try:
        await client.patch_channel_settings(channel_id, {"project_path": expected_project_path})
        status = await _assert_harness_project_cwd(
            client,
            channel_id=channel_id,
            session_id=session_id,
            expected_project_path=expected_project_path,
        )
        project_dir = status.get("project_dir") or {}
        workspace_id = str(project_dir.get("workspace_id") or "")
        assert workspace_id, status

        await client.mkdir_workspace_path(workspace_id, f"{expected_project_path}/.claude")
        await client.mkdir_workspace_path(workspace_id, f"{expected_project_path}/.claude/skills")
        await client.mkdir_workspace_path(workspace_id, skill_root)
        await client.write_workspace_file(
            workspace_id,
            skill_path,
            (
                "---\n"
                f"name: {skill_name}\n"
                "description: Harness parity fixture proving project-local Claude native slash skill invocation.\n"
                "---\n\n"
                "# Harness Native Slash Fixture\n\n"
                "When this skill is invoked, reply exactly with this text and nothing else:\n"
                f"{expected_phrase}\n"
            ),
        )

        result = await client.chat_session_stream(
            f"/{skill_name}",
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert expected_phrase in result.response_text

        messages = await client.get_session_messages(session_id, limit=20)
        assert any(
            expected_phrase in str(message.get("content") or "")
            for message in _assistant_messages(messages)
        ), "project-local Claude native skill invocation did not persist in assistant transcript"
    finally:
        if workspace_id:
            with contextlib.suppress(Exception):
                await client.delete_workspace_path(workspace_id, skill_root)
        await client.patch_channel_settings(
            channel_id,
            {
                "project_workspace_id": original_settings.get("project_workspace_id"),
                "project_path": original_settings.get("project_path"),
            },
        )
        restored = True
    assert restored


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_codex_native_input_manifest_skill_and_image(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("skills")
    if case.name != "codex":
        pytest.skip("Codex app-server owns skill and image input items")

    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)

    skills_result = await client.execute_slash_command(
        "skills",
        session_id=session_id,
        args=[],
    )
    data = ((skills_result.get("payload") or {}).get("data") or {}).get("data") or []
    skill_name = ""
    for cwd_entry in data:
        if not isinstance(cwd_entry, dict):
            continue
        for skill in cwd_entry.get("skills") or []:
            if isinstance(skill, dict) and isinstance(skill.get("name"), str):
                skill_name = skill["name"]
                break
        if skill_name:
            break
    if not skill_name:
        pytest.skip("deployed Codex runtime has no skills/list entries to invoke")

    pixel_png = (
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2"
        "AAAAGUlEQVQoz2M0TjvDQApgIkn1qIZRDUNKAwB2OQGFz8rhgwAAAABJRU5ErkJggg=="
    )
    marker = uuid.uuid4().hex[:10]
    result = await client.chat_session_stream(
        f"${skill_name} Do not use tools. Reply exactly: codex input manifest {marker}",
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
        attachments=[
            {
                "type": "image",
                "content": pixel_png,
                "mime_type": "image/png",
                "name": "pixel.png",
            }
        ],
    )
    _assert_clean_turn(result)

    messages = await client.get_session_messages(session_id, limit=10)
    harness_meta = (_message_metadata(_assistant_messages(messages)[-1]).get("harness") or {})
    input_manifest = harness_meta.get("input_manifest") or {}
    item_counts = input_manifest.get("runtime_item_counts") or {}
    assert item_counts.get("skill") == 1, input_manifest
    assert item_counts.get("image") == 1, input_manifest
    assert "base64" not in json.dumps(input_manifest).lower()


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_native_image_input_manifest(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)

    pixel_png = "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAGUlEQVQoz2M0TjvDQApgIkn1qIZRDUNKAwB2OQGFz8rhgwAAAABJRU5ErkJggg=="
    marker = uuid.uuid4().hex[:10]
    result = await client.chat_session_stream(
        f"Do not use tools. Reply exactly: image input manifest {marker}",
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
        attachments=[
            {
                "type": "image",
                "content": pixel_png,
                "mime_type": "image/png",
                "name": "pixel.png",
            }
        ],
    )
    _assert_clean_turn(result)

    messages = await client.get_session_messages(session_id, limit=10)
    harness_meta = (_message_metadata(_assistant_messages(messages)[-1]).get("harness") or {})
    input_manifest = harness_meta.get("input_manifest") or {}
    item_counts = input_manifest.get("runtime_item_counts") or {}
    assert item_counts.get("image") == 1, input_manifest
    assert "base64" not in json.dumps(input_manifest).lower()


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_native_image_semantic_reasoning(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("skills")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)

    red_dominant_png = (
        "iVBORw0KGgoAAAANSUhEUgAAAKAAAABgCAIAAAAVRe7O"
        "AAAAqElEQVR42u3RAQkAAAjAsPcvrQ0MIIMn+JrS4ywALMACLMACLMACDFiABViABViABRiw"
        "AAuwAAuwAAuwAAMWYAEWYAEWYAEGLMACLMACLMACDFiABViABViABViAAQuwAAuwAAuw"
        "AAMWYAEWYAEWYAEGbAFgARZgARZgARZgwAIswAIswAIswIAFWIAFWIAFWIAFGLAAC7AA"
        "C7AACzBgARZgARZgAdbZAiIbx3ZNPALMAAAAAElFTkSuQmCC"
    )
    marker = uuid.uuid4().hex[:10]
    result = await client.chat_session_stream(
        (
            "Look at the attached image. Do not use tools. "
            f"Reply exactly: dominant color red {marker}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
        attachments=[
            {
                "type": "image",
                "content": red_dominant_png,
                "mime_type": "image/png",
                "name": "red-dominant.png",
            }
        ],
    )
    _assert_clean_turn(result)
    assert f"dominant color red {marker}" in result.response_text.lower()

    messages = await client.get_session_messages(session_id, limit=10)
    user_messages = _user_messages(messages)
    assert user_messages, messages
    attachments = user_messages[-1].get("attachments") or []
    assert attachments, messages
    assert attachments[0].get("filename") == "red-dominant.png"
    assert attachments[0].get("type") == "image"
    assert attachments[0].get("has_file_data") is True


@pytest.mark.asyncio
async def test_live_browser_automation_runtime_diagnostics(client: E2EClient) -> None:
    _requires_tier("bridge")
    await _assert_browser_runtime_live_diagnostics(client)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_bridge_tools_persist_and_renderable(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("bridge")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    tool_name = _bridge_tool_name()
    tool_args = _bridge_tool_args()
    visible_names = _bridge_visible_names(tool_name)
    discovery_args = json.dumps({"tool_name": tool_name}, sort_keys=True)

    discovery = await client.chat_session_stream(
        (
            f"@tool:get_tool_info Bridge parity diagnostic. You must call exactly the host-provided "
            f"get_tool_info tool now with JSON arguments "
            f"{discovery_args}. Do not call {tool_name} in this turn. "
            "Do not use shell commands. Do not modify files. Briefly say whether "
            "get_tool_info returned a callable schema."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(discovery)

    invocation = await client.chat_session_stream(
        (
            f"Now call the host-provided {tool_name} tool with this exact JSON object as "
            f"arguments: {json.dumps(tool_args, sort_keys=True)}. Do not use shell commands. "
            "Do not modify files. Summarize whether the call succeeded."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(invocation)
    await _assert_trace_has_turn_context(client, invocation)

    messages = await client.get_session_messages(session_id, limit=30)
    assistants = _assistant_messages(messages)
    assert any(_has_get_tool_info_schema_envelope(message, tool_name) for message in assistants), (
        f"get_tool_info did not persist a callable schema envelope for {tool_name!r}"
    )
    assert any(_message_mentions_any_tool(message, visible_names) for message in assistants), (
        f"{visible_names} was not visible in persisted assistant messages for {session_id}"
    )
    assert any(_has_persisted_tool_transcript(message) for message in assistants), (
        "bridge tool calls did not persist canonical tool_calls + assistant_turn_body"
    )
    bridge_messages = [
        message for message in assistants if _message_mentions_any_tool(message, visible_names)
    ]
    assert any(_has_persisted_tool_result_envelope(message) for message in bridge_messages), (
        "bridge tool calls did not persist ToolResultEnvelope metadata for UI rendering"
    )
    status = await client.get_session_harness_status(session_id)
    _assert_bridge_baseline(status)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_browser_tool_call_uses_shared_runtime(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("bridge")
    await _assert_browser_runtime_live_diagnostics(client)
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    await client.set_session_approval_mode(session_id, "bypassPermissions")

    result = await client.chat_session_stream(
        (
            "Browser runtime diagnostic. Use @tool:headless_browser_open. "
            "You must call the host-provided headless_browser_open tool exactly once "
            "with url \"https://example.com\". Do not use shell commands. "
            "After the tool result, reply with the page title and whether the URL opened."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert any(
        event.type == "tool_start"
        and event.data.get("tool") in {"headless_browser_open", "mcp__spindrel__headless_browser_open"}
        for event in result.events
    ), "harness did not call headless_browser_open"

    cleanup = await client.chat_session_stream(
        (
            "Use @tool:headless_browser_close. Call the host-provided "
            "headless_browser_close tool once to close the browser session. "
            "Do not use shell commands."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(cleanup)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_claude_native_todo_progress_persists(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("skills")
    if case.name != "claude":
        pytest.skip("Claude Code-specific TodoWrite SDK surface")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    await client.set_session_approval_mode(session_id, "bypassPermissions")
    marker = uuid.uuid4().hex[:10]

    result = await client.chat_session_stream(
        (
            "Claude SDK TodoWrite parity. Use TodoWrite exactly once to create three todos: "
            f"Inspect SDK docs {marker}; Add parity scenario {marker}; Report result {marker}. "
            f"Mark the first completed, second in_progress, third pending. Then reply exactly: todo progress ok {marker}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert f"todo progress ok {marker}" in result.response_text.lower()
    assert any(
        event.type == "tool_start" and event.data.get("tool") == "TodoWrite"
        for event in result.events
    ), "Claude did not emit a native TodoWrite tool_start"

    messages = await client.get_session_messages(session_id, limit=20)
    assistants = _assistant_messages(messages)
    todo_messages = [
        message for message in assistants
        if _message_mentions_any_tool(message, ("TodoWrite",))
    ]
    assert todo_messages, "Claude TodoWrite did not persist in assistant transcript"
    assert any(_has_persisted_tool_result_envelope(message) for message in todo_messages), (
        "Claude TodoWrite did not persist a renderable progress envelope"
    )
    assert any(
        "progress" in json.dumps(_message_metadata(message)).lower()
        and "todo" in json.dumps(_message_metadata(message)).lower()
        for message in todo_messages
    ), "Claude TodoWrite metadata was not classified as todo progress"


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_claude_native_toolsearch_persists(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("skills")
    if case.name != "claude":
        pytest.skip("Claude Code-specific ToolSearch SDK surface")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    await client.execute_slash_command(
        "model",
        session_id=session_id,
        args=["claude-sonnet-4-5"],
    )
    await client.set_session_approval_mode(session_id, "bypassPermissions")
    marker = uuid.uuid4().hex[:10]

    result = await client.chat_session_stream(
        (
            "Claude SDK ToolSearch parity. Use ToolSearch exactly once to search "
            "for the native tool named TodoWrite. Do not call TodoWrite, Bash, "
            "Read, Write, Edit, Agent, or Task. After ToolSearch returns, reply "
            f"exactly: toolsearch ok {marker}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert f"toolsearch ok {marker}" in result.response_text.lower()
    assert any(
        event.type == "tool_start" and event.data.get("tool") == "ToolSearch"
        for event in result.events
    ), "Claude did not emit a native ToolSearch tool_start"

    messages = await client.get_session_messages(session_id, limit=20)
    assistants = _assistant_messages(messages)
    toolsearch_messages = [
        message for message in assistants
        if _message_mentions_any_tool(message, ("ToolSearch",))
    ]
    assert toolsearch_messages, "Claude ToolSearch did not persist in assistant transcript"
    assert any(_has_persisted_tool_result_envelope(message) for message in toolsearch_messages), (
        "Claude ToolSearch did not persist a renderable discovery result envelope"
    )


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_claude_native_subagent_persists(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("skills")
    if case.name != "claude":
        pytest.skip("Claude Code-specific Agent/Task SDK surface")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    await client.set_session_approval_mode(session_id, "bypassPermissions")
    marker = uuid.uuid4().hex[:10]

    result = await client.chat_session_stream(
        (
            "Claude SDK subagent parity. Use the native Task or Agent tool exactly once "
            "with a general-purpose subagent to answer this tiny read-only question: "
            f"return the marker {marker}. Do not modify files. "
            f"After the subagent result, reply exactly: subagent ok {marker}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_project_timeout(),
    )
    _assert_clean_turn(result)
    assert f"subagent ok {marker}" in result.response_text.lower()
    assert any(
        event.type == "tool_start" and event.data.get("tool") in {"Task", "Agent"}
        for event in result.events
    ), "Claude did not emit a native Task/Agent subagent tool_start"

    messages = await client.get_session_messages(session_id, limit=20)
    assistants = _assistant_messages(messages)
    subagent_messages = [
        message for message in assistants
        if _message_mentions_any_tool(message, ("Task", "Agent"))
    ]
    assert subagent_messages, "Claude native subagent did not persist in assistant transcript"
    assert any(_has_persisted_tool_result_envelope(message) for message in subagent_messages), (
        "Claude native subagent did not persist a renderable result envelope"
    )
    assert any(
        "subagent" in json.dumps(_message_metadata(message)).lower()
        for message in subagent_messages
    ), "Claude subagent metadata was not classified as a subagent"


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_terminal_tool_output_is_sequential(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("terminal")
    await _assert_browser_runtime_live_diagnostics(client, require_shared_runtime=False)
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    original_config = await client.get_channel_config(channel_id)
    marker = uuid.uuid4().hex[:12]
    expected_tools = (
        "get_tool_info",
        "list_channels",
        "list_sub_sessions",
        "read_conversation_history",
    )

    try:
        await client.patch_channel_config(channel_id, {"chat_mode": "terminal"})
        await _configure_low_cost_session(client, case, session_id)
        await client.set_session_approval_mode(session_id, "bypassPermissions")

        result = await client.chat_session_stream(
            (
                "@tool:get_tool_info @tool:list_channels @tool:list_sub_sessions "
                "@tool:read_conversation_history "
                "Terminal transcript parity. Use exactly these host-provided tools in order, "
                "with no shell commands and no file modifications: "
                '1. get_tool_info with {"tool_name":"list_channels"}; '
                "2. list_channels with {}; "
                '3. list_sub_sessions with {"limit":3}; '
                '4. read_conversation_history with {"section":"recent"}. '
                f"After all four tool results, reply exactly: terminal transcript ok {marker}"
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert f"terminal transcript ok {marker}" in result.response_text.lower()

        started_tools = [
            str(event.data.get("tool") or "")
            for event in result.events
            if event.type == "tool_start"
        ]
        for expected in expected_tools:
            assert any(name in _bridge_visible_names(expected) for name in started_tools), (
                f"{case.name} did not call expected tool {expected!r}; saw {started_tools}"
            )

        messages = await client.get_session_messages(session_id, limit=40)
        assistants = _assistant_messages(messages)
        assert any(_has_persisted_tool_transcript(message) for message in assistants), (
            "terminal parity turn did not persist canonical tool transcript"
        )
        screenshot_path = await _assert_terminal_transcript_ui(
            client,
            channel_id=channel_id,
            session_id=session_id,
            marker=marker,
            min_rows=len(expected_tools),
            screenshot_name=f"{case.name}-{marker}.png",
        )
        assert screenshot_path.is_file(), f"terminal parity screenshot was not written: {screenshot_path}"
        await client.patch_channel_config(channel_id, {"chat_mode": "default"})
        default_paths = await _assert_harness_chat_mode_ui(
            client,
            channel_id=channel_id,
            session_id=session_id,
            marker=marker,
            chat_mode="default",
            min_rows=len(expected_tools),
            screenshot_name=f"{case.name}-{marker}.png",
        )
        assert all(path.is_file() for path in default_paths), (
            f"default parity screenshots were not all written: {default_paths}"
        )
    finally:
        await client.patch_channel_config(
            channel_id,
            {"chat_mode": original_config.get("chat_mode") or "default"},
        )


@pytest.mark.asyncio
async def test_live_codex_native_cli_terminal_mirrors_to_spindrel(
    client: E2EClient,
) -> None:
    _requires_tier("terminal")
    case = next(harness for harness in HARNESSES if harness.name == "codex")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    marker = f"native-cli-mirror-{uuid.uuid4().hex[:8]}"
    bootstrap = await client.chat_session_stream(
        f"Native CLI mirror bootstrap {marker}. Do not use tools. Reply exactly: bootstrap ready {marker}",
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(bootstrap)
    assert f"bootstrap ready {marker}" in bootstrap.response_text.lower()

    terminal_screenshot, mirror_screenshot, mirrored_message = await _send_native_cli_prompt_via_ui(
        client,
        runtime_name=case.runtime,
        channel_id=channel_id,
        session_id=session_id,
        prompt=f"Reply exactly: native cli mirror ok {marker}",
        marker=marker,
        terminal_screenshot_name=(
            "harness-codex-native-cli-terminal-dark"
            if _should_capture_screenshots("harness-codex-native-cli-terminal")
            else None
        ),
        mirror_screenshot_name=(
            "harness-codex-native-cli-mirror-dark"
            if _should_capture_screenshots("harness-codex-native-cli-mirror")
            else None
        ),
    )
    if terminal_screenshot is not None:
        assert terminal_screenshot.is_file(), (
            f"native CLI terminal screenshot was not written: {terminal_screenshot}"
        )

    assert mirrored_message is not None, f"native CLI mirror did not persist marker {marker}"
    assert f"native cli mirror ok {marker}" in str(mirrored_message.get("content") or "").lower()

    if mirror_screenshot is not None:
        assert mirror_screenshot.is_file(), f"native CLI mirror screenshot was not written: {mirror_screenshot}"


@pytest.mark.asyncio
async def test_live_claude_native_cli_terminal_mirrors_to_spindrel(
    client: E2EClient,
) -> None:
    _requires_tier("terminal")
    case = next(harness for harness in HARNESSES if harness.name == "claude")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    marker = f"native-cli-mirror-{uuid.uuid4().hex[:8]}"
    bootstrap = await client.chat_session_stream(
        f"Native CLI mirror bootstrap {marker}. Do not use tools. Reply exactly: bootstrap ready {marker}",
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(bootstrap)
    assert f"bootstrap ready {marker}" in bootstrap.response_text.lower()

    terminal_screenshot, mirror_screenshot, mirrored_message = await _send_native_cli_prompt_via_ui(
        client,
        runtime_name=case.runtime,
        channel_id=channel_id,
        session_id=session_id,
        prompt=f"Reply exactly: native cli mirror ok {marker}",
        marker=marker,
        terminal_screenshot_name=(
            "harness-claude-native-cli-terminal-dark"
            if _should_capture_screenshots("harness-claude-native-cli-terminal")
            else None
        ),
        mirror_screenshot_name=(
            "harness-claude-native-cli-mirror-dark"
            if _should_capture_screenshots("harness-claude-native-cli-mirror")
            else None
        ),
    )
    if terminal_screenshot is not None:
        assert terminal_screenshot.is_file(), (
            f"Claude native CLI terminal screenshot was not written: {terminal_screenshot}"
        )
    if mirror_screenshot is not None:
        assert mirror_screenshot.is_file(), (
            f"Claude native CLI mirror screenshot was not written: {mirror_screenshot}"
        )

    assert mirrored_message is not None, f"Claude native CLI mirror did not persist marker {marker}"
    assert f"native cli mirror ok {marker}" in str(mirrored_message.get("content") or "").lower()


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_plan_mode_round_trip(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("plan")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)

    command_result = await client.execute_slash_command("plan", session_id=session_id)
    assert command_result["result_type"] == "side_effect"
    assert command_result["payload"]["effect"] == "plan"

    plan_status = await client.get_session_harness_status(session_id)
    assert plan_status["session_plan_mode"] == "planning"

    result = await client.chat_session_stream(
        (
            "In native plan mode, give a two-step plan for checking harness diagnostics. "
            "Do not modify files, do not call tools, and do not ask follow-up questions. "
            "Reply immediately with exactly two numbered steps."
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_plan_timeout(),
        harness_question_answer={
            "answer": "General diagnostic scan. Please provide the concise two-step diagnostic plan without modifying files.",
            "selected_options": ["General diagnostic scan"],
            "notes": "E2E plan-mode parity answer.",
        },
    )
    _assert_clean_turn(result)
    response_text = result.response_text.strip()
    assert response_text, "plan-mode turn returned no assistant text"
    lower_response = response_text.lower()
    assert (
        "plan" in lower_response
        or "step" in lower_response
        or bool(re.search(r"(^|\n)\s*1[.)]\s+", response_text))
    ), f"plan-mode turn did not look like a plan: {response_text!r}"
    await _assert_trace_has_turn_context(client, result)

    after_status = await client.get_session_harness_status(session_id)
    assert after_status["session_plan_mode"] == "planning"
    assert after_status["runtime"] == case.runtime
    _assert_bridge_baseline(after_status)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_project_instruction_file_discovery(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("project")
    channel_id, bot_id = _configured_case(case)
    original_settings = await client.get_channel_settings(channel_id)
    expected_project_path = _project_path()
    marker = uuid.uuid4().hex[:12]
    instruction_file = "AGENTS.md" if case.name == "codex" else "CLAUDE.md"
    instruction_path = f"{expected_project_path}/{instruction_file}"
    previous_content: str | None = None
    workspace_id: str | None = None

    try:
        await client.patch_channel_settings(channel_id, {"project_path": expected_project_path})
        session_id = await client.create_channel_session(channel_id)
        await _configure_low_cost_session(client, case, session_id)
        status = await _assert_harness_project_cwd(
            client,
            channel_id=channel_id,
            session_id=session_id,
            expected_project_path=expected_project_path,
        )
        project_dir = status.get("project_dir") or {}
        workspace_id = str(project_dir.get("workspace_id") or "")
        assert workspace_id, status
        with contextlib.suppress(Exception):
            existing = await client.read_workspace_file(workspace_id, instruction_path)
            previous_content = str(existing.get("content") or "")
        await client.write_workspace_file(
            workspace_id,
            instruction_path,
            (
                "# Harness Instruction Discovery\n\n"
                "When the user asks for the harness instruction discovery marker, "
                f"reply exactly: instruction discovery ok {marker}\n"
            ),
        )

        result = await client.chat_session_stream(
            (
                "Use your native project instruction file. Do not call tools. "
                "Reply with only the harness instruction discovery marker."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert f"instruction discovery ok {marker}" in result.response_text.lower()
    finally:
        if workspace_id:
            if previous_content is None:
                with contextlib.suppress(Exception):
                    await client.delete_workspace_path(workspace_id, instruction_path)
            else:
                with contextlib.suppress(Exception):
                    await client.write_workspace_file(workspace_id, instruction_path, previous_content)
        await client.patch_channel_settings(
            channel_id,
            {
                "project_workspace_id": original_settings.get("project_workspace_id"),
                "project_path": original_settings.get("project_path"),
            },
        )


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_channel_prompt_and_manual_heartbeat(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("heartbeat")
    channel_id, bot_id = _configured_case(case)
    original_config = await client.get_channel_config(channel_id)
    original_session_id = str(original_config.get("active_session_id") or "")
    heartbeat_before = await client.get_channel_heartbeat(channel_id)
    original_heartbeat = heartbeat_before.get("config")
    previous_run_ids = {str(run.get("id")) for run in (heartbeat_before.get("history") or [])}
    session_id = await client.create_channel_session(channel_id)
    marker = uuid.uuid4().hex[:12]

    try:
        await client.switch_channel_session(channel_id, session_id)
        _model, effort, _caps = await _configure_low_cost_session(client, case, session_id)
        await client.patch_channel_config(
            channel_id,
            {
                "channel_prompt": (
                    f"Harness channel prompt marker {marker}. "
                    f"When asked for host prompt diagnostics, mention {marker}."
                ),
            },
        )
        await client.patch_channel_heartbeat(
            channel_id,
            {
                "enabled": False,
                "prompt": (
                    f"Harness manual heartbeat marker {marker}. "
                    f"Reply with exactly: heartbeat ok {marker}"
                ),
                "dispatch_results": False,
                "runner_mode": "harness",
                "harness_effort": effort,
                "max_run_seconds": int(_timeout()),
            },
        )

        await client.fire_channel_heartbeat(channel_id)
        run = await _wait_for_new_heartbeat_run(
            client,
            channel_id,
            previous_ids=previous_run_ids,
            timeout=_timeout(),
        )
        assert run["status"] == "complete", run
        assert run.get("correlation_id"), run
        assert marker in str(run.get("result") or ""), run

        messages = await client.get_session_messages(session_id, limit=20)
        assistants = _assistant_messages(messages)
        heartbeat_messages = [
            message for message in assistants
            if _message_metadata(message).get("is_heartbeat") is True
        ]
        assert heartbeat_messages, "manual harness heartbeat did not persist an assistant heartbeat row"
        harness_meta = _message_metadata(heartbeat_messages[-1]).get("harness") or {}
        hints = harness_meta.get("last_hints_sent") or []
        assert any(
            hint.get("kind") == "channel_prompt"
            and hint.get("priority") == "instruction"
            and marker in str(hint.get("preview") or hint.get("text") or "")
            for hint in hints
            if isinstance(hint, dict)
        ), f"channel prompt instruction was not present in heartbeat harness hints: {hints}"

        status = await client.get_session_harness_status(session_id)
        assert status["runtime"] == case.runtime
        assert status["harness_session_id"], "heartbeat did not persist native harness session id"
    finally:
        await client.patch_channel_heartbeat(
            channel_id,
            _heartbeat_restore_patch(original_heartbeat),
        )
        await client.patch_channel_config(
            channel_id,
            {"channel_prompt": original_config.get("channel_prompt")},
        )
        if original_session_id:
            await client.switch_channel_session(channel_id, original_session_id)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_scheduled_task_selected_bridge_tool_existing_session(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("automation")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    marker = uuid.uuid4().hex[:12]
    task_id: str | None = None
    concrete_id: str | None = None

    try:
        task = await client.create_task({
            "bot_id": bot_id,
            "channel_id": channel_id,
            "task_type": "scheduled",
            "title": f"Harness parity selected bridge tool {marker}",
            "prompt": (
                "Automation parity diagnostic. Call the selected host-provided "
                "list_channels tool exactly once. Do not modify files. "
                f"Finish with: automation ok {marker}"
            ),
            "session_target": {"mode": "existing", "session_id": session_id},
            "tools": ["list_channels"],
            "history_mode": "none",
        })
        task_id = str(task["id"])
        assert task["execution_config"]["tools"] == ["list_channels"]
        assert task["session_target"]["mode"] == "existing"

        concrete = await client.run_task_now(task_id)
        concrete_id = str(concrete["id"])
        finished = await client.wait_task_terminal(concrete_id, timeout=_timeout())
        assert finished["status"] == "complete", finished
        assert marker in str(finished.get("result") or ""), finished

        messages = await client.get_session_messages(session_id, limit=30)
        assistants = _assistant_messages(messages)
        assert any(
            _message_mentions_any_tool(message, _bridge_visible_names("list_channels"))
            for message in assistants
        ), "harness automation task did not invoke the selected list_channels bridge tool"
        assert any(_has_persisted_tool_result_envelope(message) for message in assistants), (
            "harness automation task did not persist a renderable bridge tool result"
        )
    finally:
        if concrete_id:
            await client.delete_task(concrete_id)
        if task_id:
            await client.delete_task(task_id)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_safe_workspace_write_read_delete(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("writes")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    marker = uuid.uuid4().hex
    rel_path = f".spindrel-harness-parity/{case.name}-{marker}.txt"
    exact_content = f"spindrel harness parity {marker}"

    try:
        result = await client.chat_session_stream(
            (
                f"Create or overwrite the relative file {rel_path!r} with exactly "
                f"{exact_content!r}. Then read it back and report only the exact file content. "
                "Do not edit anything else."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert marker in result.response_text
        assert result.tool_events, "no live tool events were emitted for the write turn"
        messages = await client.get_session_messages(session_id, limit=20)
        assistants = _assistant_messages(messages)
        persisted_content = any(
            _has_persisted_tool_result_containing(message, exact_content)
            for message in assistants
        )
        persisted_reply = any(
            exact_content in str(message.get("content") or "")
            for message in assistants
        )
        assert persisted_content or persisted_reply, (
            "write/read turn did not persist readable file content in a tool-result envelope "
            "or final assistant text"
        )
    finally:
        cleanup = await client.chat_session_stream(
            (
                f"Delete only the relative file {rel_path!r} if it exists. "
                "If the containing .spindrel-harness-parity directory is empty, "
                "you may remove that directory too. Do not edit anything else."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(cleanup)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_default_mode_bridge_write_approval_resume(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("writes")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    marker = uuid.uuid4().hex
    rel_path = f".spindrel-harness-parity/{case.name}-bridge-approval-{marker}.txt"
    exact_content = f"spindrel harness approval {marker}"

    try:
        approval_mode = await client.set_session_approval_mode(session_id, "default")
        assert approval_mode["mode"] == "default"

        result = await client.chat_session_stream(
            (
                f"{_local_tool_prompt('file')} "
                "Use the Spindrel host file bridge tool for this task "
                "(Codex dynamic tool `file`; Claude MCP tool `mcp__spindrel__file`). "
                f"Create or overwrite the relative file {rel_path!r} with exactly "
                f"{exact_content!r}. Then read it back and report only the exact file content. "
                "Do not use shell commands and do not edit anything else."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
            approval_decision={
                "approved": True,
                "decided_by": "e2e_harness_parity",
                "bypass_rest_of_turn": True,
            },
        )
        _assert_clean_turn(result)
        assert marker in result.response_text
        assert any(event.type == "approval_request" for event in result.events), (
            "Claude default mode write did not request harness approval"
        )
        assert any(
            event.type == "approval_resolved" and event.data.get("decision") == "approved"
            for event in result.events
        ), "Claude harness approval did not resolve as approved"

        messages = await client.get_session_messages(session_id, limit=20)
        assistants = _assistant_messages(messages)
        assert any(
            _message_mentions_any_tool(message, _bridge_visible_names("file"))
            for message in assistants
        ), "default-mode approval smoke did not exercise the Spindrel file bridge"
        assert any(
            _has_persisted_tool_result_containing(message, exact_content)
            for message in assistants
        ), "approved bridge write/read did not persist readable result content"
    finally:
        await client.set_session_approval_mode(session_id, "bypassPermissions")
        cleanup = await client.chat_session_stream(
            (
                f"Delete only the relative file {rel_path!r} if it exists. "
                "Do not delete any other files or directories."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(cleanup)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_context_pressure_and_native_compact(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("context")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    caps = await client.get_runtime_capabilities(case.runtime)
    if not caps.get("native_compaction"):
        pytest.skip(f"{case.runtime} does not advertise native compaction")

    initial_status = await client.get_session_harness_status(session_id)
    filler = "context-pressure-token " * int(os.environ.get("HARNESS_PARITY_CONTEXT_FILL_WORDS", "80"))
    first = await client.chat_session_stream(
        (
            "Context pressure sample one. The payload below is context only; do not repeat it. "
            "Reply with exactly: pressure one ok\n\n"
            f"Payload:\n{filler[:1000]}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(first)
    first_status = await client.get_session_harness_status(session_id)

    second = await client.chat_session_stream(
        (
            "Context pressure sample two. The payload below is context only; do not repeat it. "
            "Reply with exactly: pressure two ok\n\n"
            f"Payload:\n{filler}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(second)
    second_status = await client.get_session_harness_status(session_id)

    first_diag = first_status.get("context_diagnostics") or {}
    second_diag = second_status.get("context_diagnostics") or {}
    first_tokens = first_diag.get("context_tokens")
    second_tokens = second_diag.get("context_tokens")
    if not isinstance(first_tokens, int) or not isinstance(second_tokens, int):
        pytest.skip("runtime did not report comparable context token estimates")
    assert first_tokens >= 0
    assert second_tokens >= 0
    initial_tokens = _status_context_tokens(initial_status)
    if initial_tokens is not None:
        assert first_tokens >= initial_tokens, (
            f"context tokens did not increase after first pressure turn: "
            f"initial={initial_tokens}, first={first_tokens}"
        )
    first_fields = {str(field) for field in (first_diag.get("source_fields") or [])}
    second_fields = {str(field) for field in (second_diag.get("source_fields") or [])}
    per_turn_fields = {"last_total_tokens", "input_tokens", "output_tokens"}
    reports_latest_turn_footprint = bool(
        (first_fields | second_fields) & per_turn_fields
    )
    if not reports_latest_turn_footprint:
        assert second_tokens >= first_tokens, (
            f"context tokens did not increase across pressure turns: "
            f"first={first_tokens}, second={second_tokens}"
        )

    first_remaining = _status_remaining_pct(first_status)
    second_remaining = _status_remaining_pct(second_status)
    if first_remaining is not None and second_remaining is not None:
        assert second_remaining <= first_remaining + 1.0, (
            f"context remaining increased under pressure: "
            f"first={first_remaining}, second={second_remaining}"
        )

    compact = await client.execute_slash_command("compact", session_id=session_id)
    assert compact["result_type"] == "harness_native_compaction"
    assert compact["payload"]["status"] == "completed"

    compact_status = await client.get_session_harness_status(session_id)
    native = compact_status.get("native_compaction") or {}
    assert native.get("status") == "completed"
    remaining = compact_status.get("context_remaining_pct")
    assert remaining is None or remaining >= 50.0
    compact_before = native.get("context_before") if isinstance(native, dict) else None
    compact_after = native.get("context_after") if isinstance(native, dict) else None
    before_tokens = _context_snapshot_tokens(compact_before)
    after_tokens = _context_snapshot_tokens(compact_after)
    before_pct = _context_snapshot_remaining_pct(compact_before)
    after_pct = _context_snapshot_remaining_pct(compact_after)
    compact_remaining = _status_remaining_pct(compact_status)
    compact_tokens = _status_context_tokens(compact_status)

    evidence: list[str] = []
    if before_pct is not None and after_pct is not None:
        assert after_pct >= before_pct, (
            f"native compact reduced remaining percent: before={before_pct}, after={after_pct}"
        )
        evidence.append("native context pct improved")
    if before_tokens is not None and after_tokens is not None:
        assert after_tokens <= before_tokens, (
            f"native compact increased context tokens: before={before_tokens}, after={after_tokens}"
        )
        evidence.append("native context tokens reduced")
    if second_remaining is not None and compact_remaining is not None:
        assert compact_remaining >= second_remaining, (
            f"context remaining did not recover after native compact: "
            f"before={second_remaining}, after={compact_remaining}"
        )
        evidence.append("status remaining recovered")
    if compact_tokens is not None:
        assert compact_tokens <= second_tokens, (
            f"context tokens did not drop after native compact: before={second_tokens}, after={compact_tokens}"
        )
        evidence.append("status context tokens reduced")
    assert evidence, (
        "runtime advertised native compaction but did not expose comparable before/after "
        f"context telemetry; native={native}, compact_status={compact_status}"
    )


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_project_plan_build_and_screenshot(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("project")
    if client.config.is_external and not _is_local_e2e_host(client.config.host):
        pytest.skip(
            "project screenshot diagnostics must run on the target host or with a "
            "container-reachable remote Docker/Playwright setup"
        )
    await _assert_browser_runtime_live_diagnostics(client, require_shared_runtime=False)

    channel_id, bot_id = _configured_case(case)
    expected_project_path = _project_path()
    original_settings = await client.get_channel_settings(channel_id)
    restored = False
    session_id: str | None = None
    workspace_id: str | None = None
    app_rel = ""
    app_workspace_rel = ""
    server_proc: subprocess.Popen | None = None
    marker = uuid.uuid4().hex[:12]

    try:
        await client.patch_channel_settings(channel_id, {"project_path": expected_project_path})
        session_id = await client.create_channel_session(channel_id)
        await _configure_low_cost_session(client, case, session_id)

        status = await _assert_harness_project_cwd(
            client,
            channel_id=channel_id,
            session_id=session_id,
            expected_project_path=expected_project_path,
        )
        project_dir = status.get("project_dir") or {}
        workspace_id = str(project_dir.get("workspace_id") or "")
        assert workspace_id, status
        effective_cwd = str(status.get("effective_cwd") or "").rstrip("/")
        bot_workspace_dir = str(status.get("bot_workspace_dir") or "").rstrip("/")
        assert effective_cwd, status

        plan_command = await client.execute_slash_command("plan", session_id=session_id)
        assert plan_command["payload"]["effect"] == "plan"
        plan_status = await client.get_session_harness_status(session_id)
        assert plan_status["session_plan_mode"] == "planning"

        app_rel = f"e2e-testing/{case.name}-{marker}"
        app_workspace_rel = f"{expected_project_path}/{app_rel}"
        app_abs = f"{effective_cwd}/{app_rel}"
        plan = await client.chat_session_stream(
            (
                "Plan only. Do not create, edit, delete, run files, inspect files, or call tools. "
                "Do not ask clarification questions. Reply with exactly three short bullet points. "
                f"The app is a tiny static harness status page at absolute path {app_abs}. "
                "It must visibly show the title Harness Project Parity, the runtime name, "
                f"and marker {marker}. Use only index.html, styles.css, app.js, and README.md."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_project_timeout(),
            harness_question_answer={
                "answer": "Use a minimal static app with no package install and no external assets.",
                "selected_options": ["Minimal static app"],
                "notes": "E2E project parity plan answer.",
            },
        )
        _assert_clean_turn(plan)
        assert marker in plan.response_text

        exit_command = await client.exit_session_plan_mode(session_id)
        assert exit_command["mode"] == "chat"
        chat_status = await client.get_session_harness_status(session_id)
        assert chat_status["session_plan_mode"] == "chat"
        await client.set_session_approval_mode(session_id, "bypassPermissions")

        build = await client.chat_session_stream(
            (
                f"Proceed with the approved plan. Create the app at absolute path {app_abs} "
                "and write exactly these files: index.html, styles.css, app.js, README.md. "
                f"Do not write under the bot workspace {bot_workspace_dir}. "
                "Do not install packages, do not use external network assets, and do not write outside "
                f"{app_abs}. The rendered page must show title \"Harness Project Parity\", "
                f"runtime \"{case.name}\", and marker \"{marker}\". "
                "Before your final response, verify all four files exist and that index.html contains "
                "the title and marker. If verification fails, fix it before replying. "
                "When done, briefly list the files created."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_project_timeout(),
        )
        _assert_clean_turn(build)
        assert app_rel in build.response_text or marker in build.response_text

        index = await _read_workspace_file_with_retry(client, workspace_id, f"{app_workspace_rel}/index.html")
        styles = await _read_workspace_file_with_retry(client, workspace_id, f"{app_workspace_rel}/styles.css")
        app_js = await _read_workspace_file_with_retry(client, workspace_id, f"{app_workspace_rel}/app.js")
        readme = await _read_workspace_file_with_retry(client, workspace_id, f"{app_workspace_rel}/README.md")
        assert "Harness Project Parity" in str(index.get("content") or "")
        assert marker in str(index.get("content") or "")
        assert str(styles.get("content") or "").strip()
        assert str(app_js.get("content") or "").strip()
        assert str(readme.get("content") or "").strip()

        final_status = await _assert_harness_project_cwd(
            client,
            channel_id=channel_id,
            session_id=session_id,
            expected_project_path=expected_project_path,
        )
        server_dir = f"{final_status['effective_cwd'].rstrip('/')}/{app_rel}"
        server_proc, screenshot_url = _start_project_http_server(server_dir)
        screenshot_path = _artifact_root() / marker / f"{case.name}-project.png"
        await _capture_project_screenshot(
            url=screenshot_url,
            out_path=screenshot_path,
            marker=marker,
        )
        assert screenshot_path.is_file(), f"screenshot was not written: {screenshot_path}"
    finally:
        if server_proc is not None:
            server_proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                server_proc.wait(timeout=3)
            if server_proc.poll() is None:
                server_proc.kill()
        if workspace_id and app_workspace_rel:
            await client.delete_workspace_path(workspace_id, app_workspace_rel)
        await client.patch_channel_settings(
            channel_id,
            {
                "project_workspace_id": original_settings.get("project_workspace_id"),
                "project_path": original_settings.get("project_path"),
            },
        )
        restored = True
    assert restored


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_memory_hint_requires_explicit_read(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("memory")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    await client.set_session_approval_mode(session_id, "bypassPermissions")

    workspace_id = await _shared_workspace_id_for_bot(client, bot_id)
    marker = uuid.uuid4().hex[:12]
    memory_name = f"harness-parity-{case.name}-{marker}"
    tool_name = "get_memory_file"
    memory_tool_arg = f"reference/{memory_name}"
    workspace_path = f"bots/{bot_id}/memory/reference/{memory_name}.md"
    secret = f"harness memory secret {marker}"

    try:
        await client.mkdir_workspace_path(workspace_id, f"bots/{bot_id}/memory/reference")
        await client.write_workspace_file(
            workspace_id,
            workspace_path,
            f"# Harness Memory Parity\n\n{secret}\n",
        )

        unread = await client.chat_session_stream(
            (
                f"A memory reference file exists at {memory_tool_arg}. "
                "Do not call tools, do not read files, and do not infer its contents. "
                "Reply exactly: memory not loaded"
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(unread)
        assert "memory not loaded" in unread.response_text.lower()
        assert secret not in unread.response_text
        assert not unread.tool_events, "memory file content was accessed before explicit tool use"

        read_session_id = await client.create_channel_session(channel_id)
        await _configure_low_cost_session(client, case, read_session_id)
        await client.set_session_approval_mode(read_session_id, "bypassPermissions")
        explicit = await client.chat_session_stream(
            (
                f"{_local_tool_prompt(tool_name)} "
                f"Call the host-provided {tool_name} tool exactly once with "
                f'name="{memory_tool_arg}". Do not use shell commands. '
                "Do not answer from conversation history. After the tool result, reply with only "
                "the exact secret phrase from the file."
            ),
            session_id=read_session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(explicit)
        assert secret in explicit.response_text
        assert any(
            event.type == "tool_start" and event.data.get("tool") in _bridge_visible_names(tool_name)
            for event in explicit.events
        ), f"harness did not call {tool_name}"

        messages = await client.get_session_messages(read_session_id, limit=40)
        assistants = _assistant_messages(messages)
        assert any(_has_harness_hint_containing(message, "workspace_files_memory", "memory") for message in assistants), (
            "workspace-files memory hint was not recorded as a harness hint"
        )
        _assert_persisted_bridge_tool_result(messages, tool_name=tool_name, expected=secret)
    finally:
        await client.delete_workspace_path(workspace_id, workspace_path)


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_tagged_skill_fetch_persists_bridge_result(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("skills")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    await client.set_session_approval_mode(session_id, "bypassPermissions")

    marker = uuid.uuid4().hex[:12]
    skill_id = f"e2e-skill-harness-parity-{case.name}-{marker}"
    tool_name = "get_skill"
    skill_phrase = f"harness skill secret {marker}"
    create_resp = None

    try:
        create_resp = await client.post(
            "/api/v1/admin/skills",
            json={
                "id": skill_id,
                "name": f"Harness Parity Skill {case.name}",
                "description": f"Temporary harness parity skill {marker}",
                "content": f"# Harness Parity Skill\n\n{skill_phrase}\n",
            },
        )
        create_resp.raise_for_status()

        result = await client.chat_session_stream(
            (
                f"@skill:{skill_id} {_local_tool_prompt(tool_name)} "
                f"Call the host-provided {tool_name} tool exactly once with "
                f'skill_id="{skill_id}" and refresh=true. Do not use shell commands. '
                "After the tool result, reply with only the exact secret phrase from the skill."
            ),
            session_id=session_id,
            channel_id=channel_id,
            bot_id=bot_id,
            timeout=_timeout(),
        )
        _assert_clean_turn(result)
        assert skill_phrase in result.response_text
        assert any(
            event.type == "tool_start" and event.data.get("tool") in _bridge_visible_names(tool_name)
            for event in result.events
        ), f"harness did not call {tool_name}"

        messages = await client.get_session_messages(session_id, limit=30)
        assistants = _assistant_messages(messages)
        assert any(_has_harness_hint_containing(message, "tagged_skills", skill_id) for message in assistants), (
            "tagged skill index hint was not recorded for the harness turn"
        )
        _assert_persisted_bridge_tool_result(messages, tool_name=tool_name, expected=skill_phrase)
    finally:
        if create_resp is not None:
            delete_resp = await client.delete(f"/api/v1/admin/skills/{skill_id}")
            if delete_resp.status_code not in (200, 204, 404):
                delete_resp.raise_for_status()


@pytest.mark.parametrize("case", HARNESS_PARAMS)
@pytest.mark.asyncio
async def test_live_harness_persisted_tool_replay_survives_refetch(
    client: E2EClient,
    case: HarnessCase,
) -> None:
    _requires_tier("replay")
    channel_id, session_id, bot_id = await _fresh_session(client, case)
    await _configure_low_cost_session(client, case, session_id)
    marker = uuid.uuid4().hex[:12]
    tool_name = "list_channels"

    result = await client.chat_session_stream(
        (
            f"{_local_tool_prompt(tool_name)} "
            f"Call the host-provided {tool_name} tool exactly once. Do not use shell commands. "
            f"After the tool result, reply exactly: replay ok {marker}"
        ),
        session_id=session_id,
        channel_id=channel_id,
        bot_id=bot_id,
        timeout=_timeout(),
    )
    _assert_clean_turn(result)
    assert f"replay ok {marker}" in result.response_text.lower()

    first_fetch = await client.get_session_messages(session_id, limit=30)
    second_fetch = await client.get_session_messages(session_id, limit=30)
    for messages in (first_fetch, second_fetch):
        assistants = _assistant_messages(messages)
        assert any(marker in str(message.get("content") or "") for message in assistants), (
            "assistant replay marker was not present after message refetch"
        )
        _assert_persisted_bridge_tool_result(messages, tool_name=tool_name)
        assert any(
            _assistant_turn_body_preserves_tool_then_text_order(message, f"replay ok {marker}")
            for message in assistants
        ), "persisted harness transcript did not preserve the tool-before-final-text event order"
