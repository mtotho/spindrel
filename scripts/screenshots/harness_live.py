"""Capture live harness parity screenshots into docs/images.

This utility is intentionally separate from the staged screenshot pipeline:
Claude Code and Codex parity screenshots need real harness sessions, while the
main ``scripts.screenshots`` runner stages synthetic e2e data and refuses to
touch production-like state.

The script reads existing harness parity sessions from the configured channels,
temporarily toggles channel chat style for default/terminal captures, then
restores the prior channel config. It uses API-key browser auth, so user-owned
scratch/unread routes may 401 in the console; the capture assertions only gate
on the harness UI surfaces under test.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import fnmatch
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx
from playwright.async_api import Browser, Page, async_playwright

from scripts.screenshots.playwright_runtime import launch_async_browser


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("/tmp/spindrel-harness-live-screenshots")

DEFAULT_CODEX_CHANNEL_ID = "41fc9132-0e6a-4f95-bcf3-8b1edaf2dabc"
DEFAULT_CLAUDE_CHANNEL_ID = "71eb14fd-a482-5bdd-a9a2-e60d9e951169"
TERMINAL_WRITE_NOT_CONTAINS = ("harness-spindrel:", "assistant:e2e-test", "tool calls")
HARNESS_CONTEXT_CHIP_SELECTOR = (
    '[data-testid="harness-context-chip-mobile"], '
    '[data-testid="harness-context-chip"]'
)
HARNESS_CONTEXT_PANEL_READY_JS = (
    "(() => {"
    "const panel = document.querySelector('[data-testid=\"harness-context-panel-mobile\"], "
    "[data-testid=\"harness-context-panel\"]');"
    "if (!panel) return false;"
    "const rect = panel.getBoundingClientRect();"
    "return rect.width > 0 && rect.height > 0 && rect.left >= 0 && rect.top >= 0 "
    "&& rect.right <= window.innerWidth + 1 && rect.bottom <= window.innerHeight + 1;"
    "})()"
)


@dataclass(frozen=True)
class RuntimeTarget:
    name: str
    channel_id: str
    bridge_label_fragment: str
    write_label_fragment: str
    project_label_fragment: str


@dataclass(frozen=True)
class CaptureSpec:
    name: str
    route: str
    wait_js: str
    contains: tuple[str, ...]
    not_contains: tuple[str, ...] = ()
    theme: str = "dark"
    channel_id: str | None = None
    chat_mode: str | None = None
    slash_query: str | None = None
    submit_slash: bool = False
    submit_ready_js: str | None = None
    viewport: tuple[int, int] = (1440, 900)
    click_selector: str | None = None
    after_click_selector: str | None = None
    after_click_wait_js: str | None = None


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def _require_env(name: str) -> str:
    value = _env(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _parse_only_patterns(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    patterns = tuple(part.strip() for part in raw.split(",") if part.strip())
    return patterns


def _filter_specs(specs: list[CaptureSpec], only: str | None) -> list[CaptureSpec]:
    patterns = _parse_only_patterns(only)
    if not patterns:
        return specs
    selected = [
        spec
        for spec in specs
        if any(fnmatch.fnmatchcase(spec.name, pattern) for pattern in patterns)
    ]
    if not selected:
        available = ", ".join(spec.name for spec in specs)
        raise SystemExit(f"No harness screenshot specs matched --only={only!r}. Available specs: {available}")
    return selected


def _should_include(only: str | None, *names: str) -> bool:
    patterns = _parse_only_patterns(only)
    if not patterns:
        return True
    return any(fnmatch.fnmatchcase(name, pattern) for name in names for pattern in patterns)


def _auth_init_script(*, api_url: str, api_key: str, theme: str) -> str:
    auth_state = {
        "serverUrl": api_url,
        "apiKey": api_key,
        "accessToken": "",
        "refreshToken": "",
        "user": {
            "id": "harness-visual-capture",
            "email": "harness-visual@spindrel.local",
            "display_name": "Harness Visual Capture",
            "avatar_url": None,
            "integration_config": {},
            "is_admin": True,
            "auth_method": "api_key",
            "scopes": ["*"],
        },
        "isConfigured": True,
    }
    theme_state = {"mode": theme}
    return "\n".join((
        f"localStorage.setItem('agent-auth', {json.dumps(json.dumps({'state': auth_state, 'version': 0}))});",
        f"localStorage.setItem('agent-theme', {json.dumps(json.dumps({'state': theme_state, 'version': 0}))});",
    ))


async def _api(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    resp = await client.request(method, path, **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else None


async def _find_session(
    client: httpx.AsyncClient,
    *,
    channel_id: str,
    label_fragment: str,
) -> str:
    data = await _api(client, "GET", f"/api/v1/channels/{channel_id}/sessions", params={"limit": 100})
    fragment = label_fragment.lower()
    sessions = list(data.get("sessions", []))
    for session in sessions:
        haystack = f"{session.get('label') or ''} {session.get('preview') or ''}".lower()
        if fragment in haystack:
            return str(session["session_id"])
    for session in sessions[:25]:
        session_id = str(session["session_id"])
        messages = await _api(client, "GET", f"/api/v1/sessions/{session_id}/messages", params={"limit": 30})
        haystack = json.dumps(messages, default=str).lower()
        if fragment in haystack:
            return session_id
    raise SystemExit(f"No session in {channel_id} matched {label_fragment!r}")


async def _create_channel_session(client: httpx.AsyncClient, *, channel_id: str) -> str:
    data = await _api(client, "POST", f"/api/v1/channels/{channel_id}/sessions")
    return str(data["new_session_id"])


async def _capture_one(
    browser: Browser,
    spec: CaptureSpec,
    *,
    browser_api_url: str,
    api_key: str,
    output_dir: Path,
) -> Path:
    context = await browser.new_context(
        base_url=spec.route,
        color_scheme=spec.theme,
    )
    try:
        await context.add_init_script(_auth_init_script(api_url=browser_api_url, api_key=api_key, theme=spec.theme))
        page: Page = await context.new_page()
        # CDP-backed remote Playwright can ignore the context-level viewport.
        # Apply the viewport both before and after navigation so the SPA mounts
        # and remains in the intended responsive layout.
        await page.set_viewport_size({"width": spec.viewport[0], "height": spec.viewport[1]})
        await page.goto(spec.route, wait_until="domcontentloaded", timeout=45_000)
        await page.set_viewport_size({"width": spec.viewport[0], "height": spec.viewport[1]})
        if spec.slash_query:
            editor = page.locator(".tiptap-chat-input [contenteditable='true']").last
            await editor.wait_for(state="visible", timeout=60_000)
            await editor.click()
            await page.keyboard.type(spec.slash_query)
            if spec.submit_slash:
                if spec.submit_ready_js:
                    await page.wait_for_function(spec.submit_ready_js, timeout=60_000)
                await page.keyboard.press("Enter")
        await page.wait_for_function(spec.wait_js, timeout=60_000)
        if spec.click_selector:
            target = page.locator(spec.click_selector).first
            await target.wait_for(state="visible", timeout=60_000)
            await target.click()
            if spec.after_click_selector:
                await page.locator(spec.after_click_selector).first.wait_for(state="visible", timeout=60_000)
            elif spec.after_click_wait_js:
                await page.wait_for_function(spec.after_click_wait_js, timeout=60_000)
        await page.wait_for_timeout(4500 if spec.submit_slash else 750)
        text = await page.locator("body").inner_text(timeout=5_000)
        lower = text.lower()
        missing = [needle for needle in spec.contains if needle.lower() not in lower]
        if missing:
            raise AssertionError(f"{spec.name}: missing visible text {missing!r}")
        forbidden = [needle for needle in spec.not_contains if needle.lower() in lower]
        if forbidden:
            raise AssertionError(f"{spec.name}: unexpected visible text {forbidden!r}")
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{spec.name}.png"
        await page.screenshot(path=str(path), full_page=False)
        return path
    finally:
        with contextlib.suppress(Exception):
            await context.close()


def _question_specs(ui_url: str, channel_id: str) -> list[CaptureSpec]:
    session_id = _env("HARNESS_VISUAL_QUESTION_SESSION_ID")
    if not session_id:
        return []
    route = f"{ui_url}/channels/{channel_id}/session/{session_id}"
    wait = (
        "document.body.innerText.toLowerCase().includes('waiting for your answer') "
        "|| document.body.innerText.toLowerCase().includes('paused for input')"
    )
    return [
        CaptureSpec(
            name="harness-question-default-dark",
            route=route,
            wait_js=wait,
            contains=("Harness has a question", "Waiting for your answer"),
            theme="dark",
            channel_id=channel_id,
            chat_mode="default",
        ),
        CaptureSpec(
            name="harness-question-default-light",
            route=route,
            wait_js=wait,
            contains=("Harness has a question", "Waiting for your answer"),
            theme="light",
            channel_id=channel_id,
            chat_mode="default",
        ),
        CaptureSpec(
            name="harness-question-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Harness has a question", "Waiting for your answer"),
            theme="dark",
            channel_id=channel_id,
            chat_mode="terminal",
        ),
    ]


def _style_command_specs(ui_url: str, channel_id: str, session_id: str) -> list[CaptureSpec]:
    route = f"{ui_url}/channels/{channel_id}/session/{session_id}"
    wait = (
        "document.body.innerText.toLowerCase().includes('switch chat style') "
        "&& document.body.innerText.toLowerCase().includes('terminal')"
    )
    return [
        CaptureSpec(
            name="harness-style-command-default-dark",
            route=route,
            wait_js=wait,
            contains=("style", "Switch chat style", "terminal"),
            theme="dark",
            channel_id=channel_id,
            chat_mode="default",
            slash_query="/style",
        ),
        CaptureSpec(
            name="harness-style-command-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("style", "Switch chat style", "terminal"),
            theme="dark",
            channel_id=channel_id,
            chat_mode="terminal",
            slash_query="/style",
        ),
    ]


def _native_slash_specs(
    ui_url: str,
    *,
    codex_channel_id: str,
    codex_session_id: str,
    claude_channel_id: str,
    claude_session_id: str,
) -> list[CaptureSpec]:
    codex_route = f"{ui_url}/channels/{codex_channel_id}/session/{codex_session_id}"
    claude_route = f"{ui_url}/channels/{claude_channel_id}/session/{claude_session_id}"
    picker_wait = (
        "document.body.innerText.toLowerCase().includes('list codex plugins') "
        "&& document.body.innerText.toLowerCase().includes('/plugins')"
    )
    claude_picker_wait = (
        "document.body.innerText.toLowerCase().includes('list claude code native skills') "
        "&& document.body.innerText.toLowerCase().includes('/skills')"
    )
    codex_result_wait = (
        "document.body.innerText.toLowerCase().includes('codex plugins') "
        "|| document.body.innerText.toLowerCase().includes('codex native command failed')"
    )
    claude_result_wait = "document.body.innerText.toLowerCase().includes('claude code skills')"
    return [
        CaptureSpec(
            name="harness-native-slash-picker-dark",
            route=codex_route,
            wait_js=picker_wait,
            contains=("/plugins", "List Codex plugins"),
            theme="dark",
            channel_id=codex_channel_id,
            chat_mode="default",
            slash_query="/plugins",
        ),
        CaptureSpec(
            name="harness-codex-native-plugins-result-dark",
            route=codex_route,
            wait_js=codex_result_wait,
            contains=("Codex", "plugins"),
            theme="dark",
            channel_id=codex_channel_id,
            chat_mode="default",
            slash_query="/plugins",
            submit_slash=True,
            submit_ready_js=picker_wait,
        ),
        CaptureSpec(
            name="harness-claude-native-skills-result-dark",
            route=claude_route,
            wait_js=claude_result_wait,
            contains=("Claude Code", "skills"),
            theme="dark",
            channel_id=claude_channel_id,
            chat_mode="default",
            slash_query="/skills",
            submit_slash=True,
            submit_ready_js=claude_picker_wait,
        ),
    ]


def _mobile_context_specs(ui_url: str, target: RuntimeTarget, session_id: str) -> list[CaptureSpec]:
    route = f"{ui_url}/channels/{target.channel_id}/session/{session_id}"
    return [
        CaptureSpec(
            name=f"harness-{target.name}-mobile-context",
            route=route,
            wait_js=f"document.querySelector({json.dumps(HARNESS_CONTEXT_CHIP_SELECTOR)}) !== null",
            click_selector=HARNESS_CONTEXT_CHIP_SELECTOR,
            after_click_selector='[data-testid="harness-context-panel-mobile"], [data-testid="harness-context-panel"]',
            after_click_wait_js=HARNESS_CONTEXT_PANEL_READY_JS,
            contains=("Harness context", "Context", "CWD"),
            theme="dark",
            channel_id=target.channel_id,
            chat_mode="terminal",
            viewport=(390, 844),
        ),
    ]


def _plan_mode_switcher_specs(ui_url: str, target: RuntimeTarget, session_id: str) -> list[CaptureSpec]:
    route = f"{ui_url}/channels/{target.channel_id}/session/{session_id}"
    return [
        CaptureSpec(
            name=f"harness-{target.name}-plan-mode-switcher",
            route=route,
            wait_js=(
                "document.querySelector('[data-testid=\"composer-plan-mode-control\"]') !== null "
                "&& document.body.innerText.includes('Harness Project Parity')"
            ),
            click_selector='[data-testid="composer-plan-mode-control"]',
            after_click_wait_js="document.body.innerText.toLowerCase().includes('plan mode')",
            contains=("Harness Project Parity", "plan mode"),
            theme="dark",
            channel_id=target.channel_id,
            chat_mode="terminal",
        ),
    ]


def _usage_log_specs(browser_url: str, channel_id: str) -> list[CaptureSpec]:
    route = f"{browser_url}/admin/usage?channel_id={channel_id}&after=30d#Logs"
    wait = (
        "document.body.innerText.toLowerCase().includes('trace runs') "
        "&& document.body.innerText.toLowerCase().includes('harness sdk')"
    )
    return [
        CaptureSpec(
            name="harness-usage-logs-dark",
            route=route,
            wait_js=wait,
            contains=("Usage", "Trace Runs", "harness SDK"),
            theme="dark",
        ),
        CaptureSpec(
            name="harness-usage-logs-light",
            route=route,
            wait_js=wait,
            contains=("Usage", "Trace Runs", "harness SDK"),
            theme="light",
        ),
    ]


def _project_terminal_specs(ui_url: str, target: RuntimeTarget, session_id: str) -> list[CaptureSpec]:
    route = f"{ui_url}/channels/{target.channel_id}/session/{session_id}"
    wait = (
        "document.body.innerText.includes('Harness Project Parity') "
        "&& document.body.innerText.toLowerCase().includes('index.html')"
    )
    return [
        CaptureSpec(
            name=f"harness-{target.name}-project-terminal",
            route=route,
            wait_js=wait,
            contains=("Harness Project Parity", "index.html"),
            not_contains=TERMINAL_WRITE_NOT_CONTAINS,
            theme="dark",
            channel_id=target.channel_id,
            chat_mode="terminal",
        ),
    ]


def _native_edit_terminal_specs(ui_url: str, channel_id: str, session_id: str) -> list[CaptureSpec]:
    route = f"{ui_url}/channels/{channel_id}/session/{session_id}"
    wait = (
        "document.body.innerText.includes('Harness Native Diff Preview') "
        "&& document.body.innerText.includes('Before native diff') "
        "&& document.body.innerText.includes('After native diff')"
    )
    return [
        CaptureSpec(
            name="harness-claude-native-edit-terminal",
            route=route,
            wait_js=wait,
            contains=("Harness Native Diff Preview", "Before native diff", "After native diff"),
            not_contains=TERMINAL_WRITE_NOT_CONTAINS,
            theme="dark",
            channel_id=channel_id,
            chat_mode="terminal",
        ),
    ]


async def capture(args: argparse.Namespace) -> list[Path]:
    api_url = args.api_url.rstrip("/")
    browser_url = args.browser_url.rstrip("/")
    browser_api_url = args.browser_api_url.rstrip("/")
    api_key = args.api_key
    output_dir = Path(args.output_dir)
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = httpx.Timeout(60.0, read=300.0)
    targets = (
        RuntimeTarget(
            name="codex",
            channel_id=args.codex_channel_id,
            bridge_label_fragment="Bridge parity diagnostic",
            write_label_fragment="Use the Spindrel host file bridge tool",
            project_label_fragment="Harness Project Parity",
        ),
        RuntimeTarget(
            name="claude",
            channel_id=args.claude_channel_id,
            bridge_label_fragment="Bridge parity diagnostic",
            write_label_fragment="Use the Spindrel host file bridge tool",
            project_label_fragment="Harness Project Parity",
        ),
    )

    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=timeout) as client:
        original_configs = {
            target.channel_id: await _api(client, "GET", f"/api/v1/channels/{target.channel_id}/config")
            for target in targets
        }
        sessions: dict[tuple[str, str], str] = {}

        specs: list[CaptureSpec] = _usage_log_specs(browser_url, args.codex_channel_id)

        for target in targets:
            bridge_name = f"harness-{target.name}-bridge-default"
            if _should_include(args.only, bridge_name):
                bridge_session = await _find_session(
                    client,
                    channel_id=target.channel_id,
                    label_fragment=target.bridge_label_fragment,
                )
                sessions[(target.name, "bridge")] = bridge_session
                specs.append(CaptureSpec(
                    name=bridge_name,
                    route=f"{browser_url}/channels/{target.channel_id}/session/{bridge_session}",
                    wait_js="document.body.innerText.includes('get_tool_info') && document.body.innerText.includes('list_channels')",
                    contains=("get_tool_info", "list_channels"),
                    not_contains=("harness-spindrel:",),
                    theme="dark",
                    channel_id=target.channel_id,
                    chat_mode="default",
                ))

            write_name = f"harness-{target.name}-terminal-write"
            if _should_include(args.only, write_name):
                write_session = await _find_session(
                    client,
                    channel_id=target.channel_id,
                    label_fragment=target.write_label_fragment,
                )
                sessions[(target.name, "write")] = write_session
                specs.append(CaptureSpec(
                    name=write_name,
                    route=f"{browser_url}/channels/{target.channel_id}/session/{write_session}",
                    wait_js=(
                        "document.body.innerText.toLowerCase().includes('file') "
                        "&& document.body.innerText.toLowerCase().includes('spindrel harness approval')"
                    ),
                    contains=("file", "spindrel harness approval"),
                    not_contains=TERMINAL_WRITE_NOT_CONTAINS,
                    theme="dark",
                    channel_id=target.channel_id,
                    chat_mode="terminal",
                ))

            project_names = (
                f"harness-{target.name}-project-terminal",
                f"harness-{target.name}-mobile-context",
                f"harness-{target.name}-plan-mode-switcher",
            )
            if _should_include(args.only, *project_names):
                project_session = await _find_session(
                    client,
                    channel_id=target.channel_id,
                    label_fragment=target.project_label_fragment,
                )
                sessions[(target.name, "project")] = project_session
                specs.extend(_project_terminal_specs(browser_url, target, project_session))
                specs.extend(_mobile_context_specs(browser_url, target, project_session))
                specs.extend(_plan_mode_switcher_specs(browser_url, target, project_session))

        style_names = (
            "harness-style-command-default-dark",
            "harness-style-command-terminal-dark",
        )
        if _should_include(args.only, *style_names):
            codex_bridge_session = sessions.get(("codex", "bridge")) or await _find_session(
                client,
                channel_id=args.codex_channel_id,
                label_fragment=targets[0].bridge_label_fragment,
            )
            sessions[("codex", "bridge")] = codex_bridge_session
            specs.extend(_style_command_specs(browser_url, args.codex_channel_id, codex_bridge_session))

        native_slash_names = (
            "harness-native-slash-picker-dark",
            "harness-codex-native-plugins-result-dark",
            "harness-claude-native-skills-result-dark",
        )
        if _should_include(args.only, *native_slash_names):
            codex_native_session = await _create_channel_session(
                client,
                channel_id=args.codex_channel_id,
            )
            claude_native_session = await _create_channel_session(
                client,
                channel_id=args.claude_channel_id,
            )
            sessions[("codex", "native_slash")] = codex_native_session
            sessions[("claude", "native_slash")] = claude_native_session
            specs.extend(_native_slash_specs(
                browser_url,
                codex_channel_id=args.codex_channel_id,
                codex_session_id=codex_native_session,
                claude_channel_id=args.claude_channel_id,
                claude_session_id=claude_native_session,
            ))

        if _should_include(args.only, "harness-claude-native-edit-terminal"):
            native_edit_session = await _find_session(
                client,
                channel_id=args.claude_channel_id,
                label_fragment="Harness Native Diff Preview",
            )
            sessions[("claude", "native_edit")] = native_edit_session
            specs.extend(_native_edit_terminal_specs(browser_url, args.claude_channel_id, native_edit_session))
        specs.extend(_question_specs(browser_url, args.claude_channel_id))
        specs = _filter_specs(specs, args.only)

        paths: list[Path] = []
        failures: list[tuple[str, str]] = []
        async with async_playwright() as pw:
            browser = await launch_async_browser(pw, headless=True)
            try:
                for spec in specs:
                    print(f"capturing {spec.name}", flush=True)
                    if spec.channel_id and spec.chat_mode:
                        await _api(
                            client,
                            "PATCH",
                            f"/api/v1/channels/{spec.channel_id}/config",
                            json={"chat_mode": spec.chat_mode},
                        )
                    try:
                        path = await _capture_one(
                            browser,
                            spec,
                            browser_api_url=browser_api_url,
                            api_key=api_key,
                            output_dir=output_dir,
                        )
                    except Exception as exc:
                        message = f"{type(exc).__name__}: {exc}"
                        print(f"failed {spec.name}: {message}", flush=True)
                        failures.append((spec.name, message))
                        is_connected = getattr(browser, "is_connected", None)
                        if callable(is_connected) and not is_connected():
                            browser = await launch_async_browser(pw, headless=True)
                        continue
                    print(f"captured {spec.name}: {path}", flush=True)
                    paths.append(path)
            finally:
                await browser.close()
                for channel_id, config in original_configs.items():
                    await _api(
                        client,
                        "PATCH",
                        f"/api/v1/channels/{channel_id}/config",
                        json={"chat_mode": config.get("chat_mode") or "default"},
                    )
            if failures:
                summary = "; ".join(f"{name}: {message}" for name, message in failures)
                raise SystemExit(f"{len(failures)} harness screenshot capture(s) failed: {summary}")
        return paths


def _parse(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="harness_live_screenshots")
    default_api_url = _env("SPINDREL_URL", "http://10.10.30.208:8000")
    default_ui_url = _env("SPINDREL_UI_URL", default_api_url)
    default_browser_url = _env("SPINDREL_BROWSER_URL", default_ui_url)
    default_browser_api_url = _env("SPINDREL_BROWSER_API_URL", default_browser_url)
    parser.add_argument("--api-url", default=default_api_url)
    parser.add_argument("--ui-url", default=default_ui_url)
    parser.add_argument("--browser-url", default=default_browser_url)
    parser.add_argument("--browser-api-url", default=default_browser_api_url)
    parser.add_argument("--api-key", default=_env("SPINDREL_API_KEY") or _env("E2E_API_KEY"))
    parser.add_argument("--output-dir", default=_env("HARNESS_VISUAL_OUTPUT_DIR", _env("DOCS_IMAGES_DIR", str(DEFAULT_OUTPUT_DIR))))
    parser.add_argument("--codex-channel-id", default=_env("HARNESS_PARITY_CODEX_CHANNEL_ID", DEFAULT_CODEX_CHANNEL_ID))
    parser.add_argument("--claude-channel-id", default=_env("HARNESS_PARITY_CLAUDE_CHANNEL_ID", DEFAULT_CLAUDE_CHANNEL_ID))
    parser.add_argument(
        "--only",
        default=_env("HARNESS_VISUAL_ONLY") or _env("HARNESS_PARITY_SCREENSHOT_ONLY"),
        help="Comma-separated exact names or shell globs of screenshot specs to capture.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.api_key:
        args.api_key = _require_env("SPINDREL_API_KEY")
    return args


def main(argv: Iterable[str] | None = None) -> None:
    asyncio.run(capture(_parse(argv)))


if __name__ == "__main__":
    main()
