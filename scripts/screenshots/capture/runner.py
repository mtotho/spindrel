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
from .specs import ScreenshotSpec

logger = logging.getLogger(__name__)

NAV_TIMEOUT_MS = 20_000
WAIT_TIMEOUT_MS = 15_000


@dataclass
class CaptureResult:
    name: str
    output: Path
    status: str                    # "ok" | "wait-timeout" | "nav-error" | "other"
    detail: str | None = None


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
                            await page.evaluate(spec.pre_capture_js)
                            await page.wait_for_timeout(250)  # settle after synthetic click
                        except Exception as e:  # pragma: no cover
                            logger.warning("pre_capture_js failed for %s: %s", spec.name, e)

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
