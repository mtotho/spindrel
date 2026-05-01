"""Capture runner: walks a ScreenshotSpec list and writes PNGs to disk.

One spec at a time — the browser context is reopened per viewport group so
mobile/desktop viewports don't step on each other. Failures per-spec report
``wait-timeout`` / ``selector-missing`` / ``nav-error`` rather than crashing
the whole batch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import TimeoutError as PWTimeoutError

from .browser import AuthBundle, browser_context
from .specs import Action, ScreenshotSpec

logger = logging.getLogger(__name__)

NAV_TIMEOUT_MS = 20_000
WAIT_TIMEOUT_MS = 15_000


@dataclass
class CaptureResult:
    name: str
    output: Path
    status: str                    # "ok" | "wait-timeout" | "nav-error" | "assertion-failed" | "other"
    detail: str | None = None


async def _run_actions(page, actions: list[Action]) -> None:
    """Execute pre-capture interactions in order.

    Each action either succeeds or raises — no silent skips, no sleeps. Waits
    use Playwright's default per-call timeout (5s) which is tight enough to
    fail fast when a selector is wrong.
    """
    for a in actions:
        if a.kind == "click":
            if not a.selector:
                raise ValueError("action kind='click' requires selector")
            await page.click(a.selector, timeout=WAIT_TIMEOUT_MS)
        elif a.kind == "dblclick":
            if not a.selector:
                raise ValueError("action kind='dblclick' requires selector")
            await page.dblclick(a.selector, timeout=WAIT_TIMEOUT_MS)
        elif a.kind == "fill":
            if not a.selector or a.value is None:
                raise ValueError("action kind='fill' requires selector and value")
            await page.fill(a.selector, a.value, timeout=WAIT_TIMEOUT_MS)
        elif a.kind == "type":
            if not a.selector or a.value is None:
                raise ValueError("action kind='type' requires selector and value")
            await page.type(a.selector, a.value, timeout=WAIT_TIMEOUT_MS)
        elif a.kind == "press":
            if a.value is None:
                raise ValueError("action kind='press' requires value (key)")
            if a.selector:
                await page.press(a.selector, a.value, timeout=WAIT_TIMEOUT_MS)
            else:
                await page.keyboard.press(a.value)
        elif a.kind == "select":
            if not a.selector or a.value is None:
                raise ValueError("action kind='select' requires selector and value")
            await page.select_option(a.selector, a.value, timeout=WAIT_TIMEOUT_MS)
        elif a.kind == "wait":
            if a.value is None:
                raise ValueError("action kind='wait' requires value (milliseconds)")
            await page.wait_for_timeout(int(a.value))
        elif a.kind == "wait_for":
            if not a.selector:
                raise ValueError("action kind='wait_for' requires selector")
            await page.wait_for_selector(a.selector, timeout=WAIT_TIMEOUT_MS)
        else:
            raise ValueError(f"unknown action kind: {a.kind!r}")


async def _wait_for(page, spec: ScreenshotSpec) -> None:
    if spec.wait_kind == "selector":
        await page.wait_for_selector(str(spec.wait_arg), timeout=WAIT_TIMEOUT_MS)
    elif spec.wait_kind == "function":
        await page.wait_for_function(str(spec.wait_arg), timeout=WAIT_TIMEOUT_MS)
    elif spec.wait_kind == "network_idle":
        await page.wait_for_load_state("networkidle", timeout=WAIT_TIMEOUT_MS)
    elif spec.wait_kind == "pin_count":
        await page.wait_for_function(
            f"window.__spindrel_pin_count() >= {int(spec.wait_arg)}",
            timeout=WAIT_TIMEOUT_MS,
        )
    else:  # pragma: no cover
        raise ValueError(f"unknown wait_kind: {spec.wait_kind}")


async def _run_assertion(page, spec: ScreenshotSpec) -> None:
    if not spec.assert_js:
        return
    result = await page.evaluate(f"(async () => {{ {spec.assert_js} }})()")
    if result is False:
        raise AssertionError("assert_js returned false")
    if isinstance(result, dict) and result.get("ok") is False:
        detail = result.get("detail") or result.get("message") or "assert_js returned ok=false"
        raise AssertionError(str(detail))


async def _screenshot_best_effort(page, out_path: Path, *, full_page: bool) -> None:
    try:
        await page.screenshot(path=str(out_path), full_page=full_page)
    except Exception:  # pragma: no cover
        logger.exception("failed to capture assertion artifact at %s", out_path)


async def capture_batch(
    *,
    specs: list[ScreenshotSpec],
    ui_base: str,
    bundle: AuthBundle,
    output_root: Path,
    extra_init_scripts: list[str] | None = None,
) -> list[CaptureResult]:
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[CaptureResult] = []

    # Group by viewport so one browser context serves all same-viewport specs.
    def _key(s: ScreenshotSpec) -> tuple[int, int, str]:
        return (s.viewport["width"], s.viewport["height"], s.color_scheme)

    groups: dict[tuple[int, int, str], list[ScreenshotSpec]] = {}
    for s in specs:
        groups.setdefault(_key(s), []).append(s)

    for (w, h, scheme), group in groups.items():
        async with browser_context(
            ui_base=ui_base,
            bundle=bundle,
            viewport={"width": w, "height": h},
            color_scheme=scheme,
            extra_init_scripts=extra_init_scripts,
        ) as (_browser, context):
            for spec in group:
                out_path = output_root / spec.output
                try:
                    page = await context.new_page()
                    # Per-spec init scripts run before navigation so any
                    # localStorage seeding (e.g. mobile drawer state) hydrates
                    # stores on first mount — no reload dance required.
                    for js in spec.extra_init_scripts:
                        await page.add_init_script(js)
                    await page.goto(spec.route, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                    try:
                        await _wait_for(page, spec)
                    except PWTimeoutError:
                        results.append(
                            CaptureResult(
                                name=spec.name,
                                output=out_path,
                                status="wait-timeout",
                                detail=f"{spec.wait_kind}={spec.wait_arg!r}",
                            )
                        )
                        await page.close()
                        continue

                    if spec.pre_capture_js:
                        try:
                            # Wrap in async IIFE so `await` at the top level
                            # is valid. page.evaluate's bare-expression mode
                            # rejects top-level await with a SyntaxError.
                            await page.evaluate(
                                f"(async () => {{ {spec.pre_capture_js} }})()"
                            )
                            await page.wait_for_timeout(250)  # settle after synthetic click
                        except Exception as e:  # pragma: no cover
                            if spec.assert_js:
                                await _screenshot_best_effort(page, out_path, full_page=spec.full_page)
                                results.append(
                                    CaptureResult(
                                        name=spec.name,
                                        output=out_path,
                                        status="assertion-failed",
                                        detail=f"pre_capture_js: {e}",
                                    )
                                )
                                await page.close()
                                continue
                            logger.warning("pre_capture_js failed for %s: %s", spec.name, e)

                    if spec.actions:
                        try:
                            await _run_actions(page, spec.actions)
                        except PWTimeoutError as e:
                            results.append(
                                CaptureResult(
                                    name=spec.name,
                                    output=out_path,
                                    status="wait-timeout",
                                    detail=f"action: {e}",
                                )
                            )
                            await page.close()
                            continue

                    try:
                        await _run_assertion(page, spec)
                    except Exception as e:
                        await _screenshot_best_effort(page, out_path, full_page=spec.full_page)
                        results.append(
                            CaptureResult(
                                name=spec.name,
                                output=out_path,
                                status="assertion-failed",
                                detail=str(e),
                            )
                        )
                        await page.close()
                        continue

                    await page.screenshot(path=str(out_path), full_page=spec.full_page)
                    results.append(CaptureResult(name=spec.name, output=out_path, status="ok"))
                    await page.close()
                except PWTimeoutError as e:
                    results.append(
                        CaptureResult(
                            name=spec.name, output=out_path, status="nav-error", detail=str(e)
                        )
                    )
                except Exception as e:  # pragma: no cover
                    results.append(
                        CaptureResult(
                            name=spec.name, output=out_path, status="other", detail=repr(e)
                        )
                    )
    return results
