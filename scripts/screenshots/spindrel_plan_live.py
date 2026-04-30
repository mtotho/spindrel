"""Capture live native Spindrel plan-mode screenshots into docs/images.

This utility is separate from the staged screenshot pipeline and from harness
captures. It consumes session ids produced by ``run_spindrel_plan_live.sh`` and
opens the real UI against those live native Spindrel plan-mode sessions.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx
from playwright.async_api import Browser, Page, async_playwright

from scripts.screenshots.playwright_runtime import launch_async_browser


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCS_IMAGES = REPO_ROOT / "docs" / "images"
DEFAULT_CHANNEL_ID = "67a06926-87e6-40fb-b85b-7eac36c74b98"
DEFAULT_SESSIONS_JSON = Path("/tmp/spindrel-plan-parity/spindrel-plan-sessions.json")
FORBIDDEN_HARNESS_TEXT = ("harness-spindrel:", "harness has a question", "harness sdk")


@dataclass(frozen=True)
class CaptureSpec:
    name: str
    route: str
    wait_js: str
    contains: tuple[str, ...]
    not_contains: tuple[str, ...] = FORBIDDEN_HARNESS_TEXT
    theme: str = "dark"
    viewport: tuple[int, int] = (1440, 900)
    scroll_text: str | None = None
    scroll_plan_text: str | None = None
    channel_id: str | None = None
    chat_mode: str | None = None


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def _require_env(name: str) -> str:
    value = _env(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _auth_init_script(*, api_url: str, api_key: str, theme: str) -> str:
    auth_state = {
        "serverUrl": api_url,
        "apiKey": api_key,
        "accessToken": "",
        "refreshToken": "",
        "user": {
            "id": "spindrel-plan-visual-capture",
            "email": "spindrel-plan-visual@spindrel.local",
            "display_name": "Spindrel Plan Visual Capture",
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


def _load_session_artifact(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Session artifact is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Session artifact must be a JSON object: {path}")
    return {str(key): str(value) for key, value in data.items() if value is not None}


def _resolve_session_ids(args: argparse.Namespace) -> dict[str, str]:
    artifact = _load_session_artifact(Path(args.sessions_json))
    return {
        "channel_id": args.channel_id or artifact.get("channel_id") or DEFAULT_CHANNEL_ID,
        "question_session_id": args.question_session_id or artifact.get("question_session_id", ""),
        "plan_session_id": args.plan_session_id or artifact.get("plan_session_id", ""),
        "answered_session_id": args.answered_session_id or artifact.get("answered_session_id", ""),
        "progress_session_id": args.progress_session_id or artifact.get("progress_session_id", ""),
        "replan_session_id": (
            args.replan_session_id
            or artifact.get("behavior_replan_session_id", "")
            or artifact.get("replan_session_id", "")
        ),
        "pending_session_id": args.pending_session_id or artifact.get("pending_session_id", ""),
        "quality_session_id": args.quality_session_id or artifact.get("quality_publish_session_id", ""),
        "stress_readability_session_id": (
            args.stress_readability_session_id
            or artifact.get("stress_readability_session_id", "")
        ),
        "adherence_review_session_id": (
            args.adherence_review_session_id
            or artifact.get("adherence_review_session_id", "")
        ),
        "adherence_auto_session_id": (
            args.adherence_auto_session_id
            or artifact.get("adherence_auto_session_id", "")
        ),
        "adherence_negative_session_id": (
            args.adherence_negative_session_id
            or artifact.get("adherence_negative_session_id", "")
        ),
        "adherence_unsupported_fixture_session_id": (
            args.adherence_unsupported_fixture_session_id
            or artifact.get("adherence_unsupported_fixture_session_id", "")
        ),
        "adherence_retry_session_id": (
            args.adherence_retry_session_id
            or artifact.get("adherence_retry_session_id", "")
        ),
    }


def _build_specs(
    browser_url: str,
    *,
    channel_id: str,
    question_session_id: str,
    plan_session_id: str,
    answered_session_id: str = "",
    progress_session_id: str = "",
    replan_session_id: str = "",
    pending_session_id: str = "",
    quality_session_id: str = "",
    stress_readability_session_id: str = "",
    adherence_review_session_id: str = "",
    adherence_auto_session_id: str = "",
    adherence_negative_session_id: str = "",
    adherence_unsupported_fixture_session_id: str = "",
    adherence_retry_session_id: str = "",
) -> list[CaptureSpec]:
    specs: list[CaptureSpec] = []
    if question_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{question_session_id}"
        wait = (
            "document.body.innerText.toLowerCase().includes('plan behavior focus') "
            "&& document.body.innerText.toLowerCase().includes('success signal')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-question-card-dark",
            route=route,
            wait_js=wait,
            contains=("Plan behavior focus", "Success signal"),
            scroll_text="Plan behavior focus",
            channel_id=channel_id,
            chat_mode="default",
        ))
    if plan_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{plan_session_id}"
        wait = (
            "document.querySelector('[data-plan-card-mode]') !== null "
            "&& document.body.innerText.toLowerCase().includes('native spindrel plan parity') "
            "&& (document.body.innerText.toLowerCase().includes('approve & execute') "
            "|| document.body.innerText.toLowerCase().includes('exit plan mode'))"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-card-default-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Plan Parity",),
            scroll_text="Native Spindrel Plan Parity",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-card-mobile-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Plan Parity",),
            viewport=(390, 844),
            scroll_text="Native Spindrel Plan Parity",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-card-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Plan Parity",),
            scroll_text="Native Spindrel Plan Parity",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if answered_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{answered_session_id}"
        wait = (
            "document.querySelector('[data-plan-card-mode]') !== null "
            "&& document.body.innerText.toLowerCase().includes('native spindrel answered plan') "
            "&& document.body.innerText.toLowerCase().includes('answer handoff') "
            "&& document.body.innerText.toLowerCase().includes('read submitted plan answers') "
            "&& document.body.innerText.toLowerCase().includes('publish answered plan')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-answered-questions-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Answered Plan", "answer handoff", "Read submitted plan answers", "Publish answered plan"),
            scroll_plan_text="Read submitted plan answers",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-answered-questions-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Answered Plan", "answer handoff", "Read submitted plan answers", "Publish answered plan"),
            scroll_plan_text="Read submitted plan answers",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if progress_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{progress_session_id}"
        wait = (
            "document.querySelector('[data-plan-card-mode]') !== null "
            "&& document.body.innerText.toLowerCase().includes('native spindrel progress parity') "
            "&& (document.body.innerText.toLowerCase().includes('progress') "
            "|| document.body.innerText.toLowerCase().includes('started step one') "
            "|| document.body.innerText.toLowerCase().includes('done') "
            "|| document.body.innerText.toLowerCase().includes('step_done') "
            "|| document.body.innerText.toLowerCase().includes('completed step one'))"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-progress-executing-mobile-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Progress Parity",),
            viewport=(390, 844),
            scroll_text="Native Spindrel Progress Parity",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-progress-executing-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Progress Parity",),
            scroll_text="Native Spindrel Progress Parity",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if replan_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{replan_session_id}"
        wait = (
            "document.querySelector('[data-plan-card-mode]') !== null "
            "&& document.body.innerText.toLowerCase().includes('replan') "
            "&& document.body.innerText.toLowerCase().includes('accepted rev')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-replan-pending-default-dark",
            route=route,
            wait_js=wait,
            contains=("replan", "accepted rev"),
            scroll_text="replan",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-replan-pending-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("replan", "accepted rev"),
            scroll_text="replan",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if pending_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{pending_session_id}"
        wait = (
            "document.querySelector('[data-plan-card-mode]') !== null "
            "&& (document.body.innerText.toLowerCase().includes('pending outcome') "
            "|| document.body.innerText.toLowerCase().includes('next required action') "
            "|| document.body.innerText.toLowerCase().includes('missing turn outcome'))"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-pending-outcome-default-dark",
            route=route,
            wait_js=wait,
            contains=("Record progress",),
            scroll_plan_text="Record progress",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-pending-outcome-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Record progress",),
            scroll_plan_text="Record progress",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if quality_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{quality_session_id}"
        wait = (
            "document.querySelector('[data-plan-card-mode]') !== null "
            "&& document.body.innerText.toLowerCase().includes('native spindrel quality plan') "
            "&& document.body.innerText.toLowerCase().includes('key changes') "
            "&& document.body.innerText.toLowerCase().includes('test plan')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-quality-contract-default-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Quality Plan", "Key Changes", "Test Plan"),
            scroll_text="Native Spindrel Quality Plan",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-quality-contract-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Quality Plan", "Key Changes", "Test Plan"),
            scroll_text="Native Spindrel Quality Plan",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if stress_readability_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{stress_readability_session_id}"
        wait = (
            "document.querySelector('[data-plan-focus]') !== null "
            "&& document.body.innerText.toLowerCase().includes('native spindrel stress readability') "
            "&& document.body.innerText.toLowerCase().includes('key changes')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-stress-readability-default-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Stress Readability", "Key Changes"),
            scroll_plan_text="Native Spindrel Stress Readability",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-stress-readability-mobile-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Stress Readability", "Key Changes"),
            viewport=(390, 844),
            scroll_plan_text="Native Spindrel Stress Readability",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-stress-readability-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Stress Readability", "Key Changes"),
            scroll_plan_text="Native Spindrel Stress Readability",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if adherence_review_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{adherence_review_session_id}"
        wait = (
            "document.querySelector('[data-plan-card-mode]') !== null "
            "&& document.body.innerText.toLowerCase().includes('native spindrel adherence review') "
            "&& document.body.innerText.toLowerCase().includes('review') "
            "&& document.body.innerText.toLowerCase().includes('supported')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-adherence-review-default-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Adherence Review", "supported"),
            scroll_plan_text="Native Spindrel Adherence Review",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-adherence-review-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Adherence Review", "supported"),
            scroll_plan_text="Native Spindrel Adherence Review",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if adherence_auto_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{adherence_auto_session_id}"
        wait = (
            "document.querySelector('[data-plan-focus]') !== null "
            "&& (document.body.innerText.toLowerCase().includes('native spindrel auto adherence review') "
            "|| document.body.innerText.toLowerCase().includes('native spindrel adherence review')) "
            "&& document.body.innerText.toLowerCase().includes('supported')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-adherence-auto-default-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Adherence Review", "supported"),
            scroll_plan_text="Supported outcome",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-adherence-auto-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel Adherence Review", "supported"),
            scroll_plan_text="Supported outcome",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    unsupported_session_id = adherence_unsupported_fixture_session_id or adherence_negative_session_id
    if unsupported_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{unsupported_session_id}"
        wait = (
            "document.querySelector('[data-plan-focus]') !== null "
            "&& (document.body.innerText.toLowerCase().includes('native spindrel unsupported fixture') "
            "|| document.body.innerText.toLowerCase().includes('native spindrel negative adherence review')) "
            "&& document.body.innerText.toLowerCase().includes('unsupported')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-adherence-unsupported-default-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel", "unsupported"),
            scroll_plan_text="Unsupported",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-adherence-unsupported-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel", "unsupported"),
            scroll_plan_text="Unsupported",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    if adherence_retry_session_id:
        route = f"{browser_url}/channels/{channel_id}/session/{adherence_retry_session_id}"
        wait = (
            "document.querySelector('[data-plan-focus]') !== null "
            "&& (document.body.innerText.toLowerCase().includes('native spindrel unsupported retry') "
            "|| document.body.innerText.toLowerCase().includes('native spindrel unsupported fixture')) "
            "&& document.body.innerText.toLowerCase().includes('supported')"
        )
        specs.append(CaptureSpec(
            name="spindrel-plan-adherence-retry-default-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel", "supported"),
            scroll_plan_text="Supported",
            channel_id=channel_id,
            chat_mode="default",
        ))
        specs.append(CaptureSpec(
            name="spindrel-plan-adherence-retry-terminal-dark",
            route=route,
            wait_js=wait,
            contains=("Native Spindrel", "supported"),
            scroll_plan_text="Supported",
            channel_id=channel_id,
            chat_mode="terminal",
        ))
    return specs


async def _api(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    resp = await client.request(method, path, **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else None


async def _assert_sessions_exist(
    client: httpx.AsyncClient,
    *,
    question_session_id: str,
    plan_session_id: str,
    answered_session_id: str,
    progress_session_id: str,
    replan_session_id: str,
    pending_session_id: str,
    quality_session_id: str,
    stress_readability_session_id: str,
    adherence_review_session_id: str,
    adherence_auto_session_id: str,
    adherence_negative_session_id: str,
    adherence_unsupported_fixture_session_id: str,
    adherence_retry_session_id: str,
) -> None:
    for session_id in (
        question_session_id,
        plan_session_id,
        answered_session_id,
        progress_session_id,
        replan_session_id,
        pending_session_id,
        quality_session_id,
        stress_readability_session_id,
        adherence_review_session_id,
        adherence_auto_session_id,
        adherence_negative_session_id,
        adherence_unsupported_fixture_session_id,
        adherence_retry_session_id,
    ):
        if session_id:
            await _api(client, "GET", f"/sessions/{session_id}/plan-state")


async def _capture_one(
    browser: Browser,
    spec: CaptureSpec,
    *,
    browser_api_url: str,
    api_key: str,
    output_dir: Path,
) -> Path:
    width, height = spec.viewport
    context = await browser.new_context(
        base_url=spec.route,
        viewport={"width": width, "height": height},
        color_scheme=spec.theme,
    )
    await context.add_init_script(_auth_init_script(api_url=browser_api_url, api_key=api_key, theme=spec.theme))
    page: Page = await context.new_page()
    await page.goto(spec.route, wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_function(spec.wait_js, timeout=60_000)
    if spec.scroll_plan_text:
        await page.locator("[data-plan-card-mode]").get_by_text(spec.scroll_plan_text).first.scroll_into_view_if_needed(timeout=10_000)
    elif spec.scroll_text:
        await page.get_by_text(spec.scroll_text).first.scroll_into_view_if_needed(timeout=10_000)
    await page.wait_for_timeout(750)
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
    await context.close()
    return path


async def capture(args: argparse.Namespace) -> list[Path]:
    api_url = args.api_url.rstrip("/")
    browser_url = args.browser_url.rstrip("/")
    browser_api_url = args.browser_api_url.rstrip("/")
    api_key = args.api_key
    output_dir = Path(args.output_dir)
    resolved = _resolve_session_ids(args)
    specs = _build_specs(
        browser_url,
        channel_id=resolved["channel_id"],
        question_session_id=resolved["question_session_id"],
        plan_session_id=resolved["plan_session_id"],
        answered_session_id=resolved["answered_session_id"],
        progress_session_id=resolved["progress_session_id"],
        replan_session_id=resolved["replan_session_id"],
        pending_session_id=resolved["pending_session_id"],
        quality_session_id=resolved["quality_session_id"],
        stress_readability_session_id=resolved["stress_readability_session_id"],
        adherence_review_session_id=resolved["adherence_review_session_id"],
        adherence_auto_session_id=resolved["adherence_auto_session_id"],
        adherence_negative_session_id=resolved["adherence_negative_session_id"],
        adherence_unsupported_fixture_session_id=resolved["adherence_unsupported_fixture_session_id"],
        adherence_retry_session_id=resolved["adherence_retry_session_id"],
    )
    if not specs:
        raise SystemExit(
            "No native plan sessions to capture. Run scripts/run_spindrel_plan_live.sh --tier publish "
            "or pass --question-session-id/--plan-session-id."
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = httpx.Timeout(60.0, read=300.0)
    async with httpx.AsyncClient(base_url=api_url, headers=headers, timeout=timeout) as client:
        channel_ids = sorted({spec.channel_id for spec in specs if spec.channel_id and spec.chat_mode})
        original_configs = {
            channel_id: await _api(client, "GET", f"/api/v1/channels/{channel_id}/config")
            for channel_id in channel_ids
        }
        await _assert_sessions_exist(
            client,
            question_session_id=resolved["question_session_id"],
            plan_session_id=resolved["plan_session_id"],
            answered_session_id=resolved["answered_session_id"],
            progress_session_id=resolved["progress_session_id"],
            replan_session_id=resolved["replan_session_id"],
            pending_session_id=resolved["pending_session_id"],
            quality_session_id=resolved["quality_session_id"],
            stress_readability_session_id=resolved["stress_readability_session_id"],
            adherence_review_session_id=resolved["adherence_review_session_id"],
            adherence_auto_session_id=resolved["adherence_auto_session_id"],
            adherence_negative_session_id=resolved["adherence_negative_session_id"],
            adherence_unsupported_fixture_session_id=resolved["adherence_unsupported_fixture_session_id"],
            adherence_retry_session_id=resolved["adherence_retry_session_id"],
        )

        paths: list[Path] = []
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
                    path = await _capture_one(
                        browser,
                        spec,
                        browser_api_url=browser_api_url,
                        api_key=api_key,
                        output_dir=output_dir,
                    )
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
        return paths


def _parse(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="spindrel_plan_live_screenshots")
    default_api_url = _env("SPINDREL_URL", "http://10.10.30.208:8000")
    default_ui_url = _env("SPINDREL_UI_URL", default_api_url)
    default_browser_url = _env("SPINDREL_BROWSER_URL", default_ui_url)
    default_browser_api_url = _env("SPINDREL_BROWSER_API_URL", default_browser_url)
    parser.add_argument("--api-url", default=default_api_url)
    parser.add_argument("--ui-url", default=default_ui_url)
    parser.add_argument("--browser-url", default=default_browser_url)
    parser.add_argument("--browser-api-url", default=default_browser_api_url)
    parser.add_argument("--api-key", default=_env("SPINDREL_API_KEY") or _env("E2E_API_KEY"))
    parser.add_argument("--output-dir", default=_env("DOCS_IMAGES_DIR", str(DEFAULT_DOCS_IMAGES)))
    parser.add_argument("--channel-id", default=_env("SPINDREL_PLAN_CHANNEL_ID", DEFAULT_CHANNEL_ID))
    parser.add_argument("--sessions-json", default=_env("SPINDREL_PLAN_SESSIONS_JSON", str(DEFAULT_SESSIONS_JSON)))
    parser.add_argument("--question-session-id", default=_env("SPINDREL_PLAN_QUESTION_SESSION_ID"))
    parser.add_argument("--plan-session-id", default=_env("SPINDREL_PLAN_CARD_SESSION_ID"))
    parser.add_argument("--answered-session-id", default=_env("SPINDREL_PLAN_ANSWERED_SESSION_ID"))
    parser.add_argument("--progress-session-id", default=_env("SPINDREL_PLAN_PROGRESS_SESSION_ID"))
    parser.add_argument("--replan-session-id", default=_env("SPINDREL_PLAN_REPLAN_SESSION_ID"))
    parser.add_argument("--pending-session-id", default=_env("SPINDREL_PLAN_PENDING_SESSION_ID"))
    parser.add_argument("--quality-session-id", default=_env("SPINDREL_PLAN_QUALITY_SESSION_ID"))
    parser.add_argument("--stress-readability-session-id", default=_env("SPINDREL_PLAN_STRESS_READABILITY_SESSION_ID"))
    parser.add_argument("--adherence-review-session-id", default=_env("SPINDREL_PLAN_ADHERENCE_REVIEW_SESSION_ID"))
    parser.add_argument("--adherence-auto-session-id", default=_env("SPINDREL_PLAN_ADHERENCE_AUTO_SESSION_ID"))
    parser.add_argument("--adherence-negative-session-id", default=_env("SPINDREL_PLAN_ADHERENCE_NEGATIVE_SESSION_ID"))
    parser.add_argument(
        "--adherence-unsupported-fixture-session-id",
        default=_env("SPINDREL_PLAN_ADHERENCE_UNSUPPORTED_FIXTURE_SESSION_ID"),
    )
    parser.add_argument("--adherence-retry-session-id", default=_env("SPINDREL_PLAN_ADHERENCE_RETRY_SESSION_ID"))
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.api_key:
        args.api_key = _require_env("SPINDREL_API_KEY")
    return args


def main(argv: Iterable[str] | None = None) -> None:
    asyncio.run(capture(_parse(argv)))


if __name__ == "__main__":
    main()
