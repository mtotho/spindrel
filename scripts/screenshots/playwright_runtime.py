"""Shared Playwright browser launcher for docs and E2E capture scripts."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable


_INSTALL_HINT = "python -m playwright install chromium"


@dataclass(frozen=True)
class BrowserLaunchCandidate:
    kind: str
    source: str
    endpoint: str | None = None
    protocol: str = "auto"
    executable_path: str | None = None


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _runtime_service_candidate() -> BrowserLaunchCandidate | None:
    try:
        from app.services.runtime_services import resolve_runtime_requirement

        resolution = resolve_runtime_requirement("browser_automation", "browser.playwright")
    except Exception:
        return None
    if not resolution.endpoint:
        return None
    return BrowserLaunchCandidate(
        kind="remote",
        source="runtime-service:browser.playwright",
        endpoint=resolution.endpoint,
        protocol=resolution.protocol or "auto",
    )


def launch_candidates() -> list[BrowserLaunchCandidate]:
    """Return browser backends in supported precedence order."""
    candidates: list[BrowserLaunchCandidate] = []
    explicit_ws = _env("PLAYWRIGHT_WS_URL")
    if explicit_ws:
        candidates.append(
            BrowserLaunchCandidate(
                kind="remote",
                source="PLAYWRIGHT_WS_URL",
                endpoint=explicit_ws,
                protocol=_env("PLAYWRIGHT_CONNECT_PROTOCOL") or "auto",
            )
        )

    runtime = _runtime_service_candidate()
    if runtime and runtime.endpoint not in {candidate.endpoint for candidate in candidates}:
        candidates.append(runtime)

    executable = _env("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if executable:
        candidates.append(
            BrowserLaunchCandidate(
                kind="executable",
                source="PLAYWRIGHT_CHROMIUM_EXECUTABLE",
                executable_path=executable,
            )
        )

    candidates.append(BrowserLaunchCandidate(kind="managed", source="playwright-managed"))
    return candidates


def _managed_missing(exc: BaseException) -> bool:
    message = str(exc)
    return "Executable doesn't exist" in message or "playwright install" in message


def _format_errors(errors: Iterable[tuple[BrowserLaunchCandidate, BaseException]]) -> str:
    parts = [f"{candidate.source}: {type(exc).__name__}: {exc}" for candidate, exc in errors]
    return "; ".join(parts)


async def launch_async_browser(pw: Any, *, headless: bool = True) -> Any:
    """Launch/connect an async Playwright Chromium browser.

    Precedence:
    1. Remote browser endpoint from ``PLAYWRIGHT_WS_URL``.
    2. Manifest runtime-service endpoint for ``browser.playwright``.
    3. Explicit local executable from ``PLAYWRIGHT_CHROMIUM_EXECUTABLE``.
    4. Playwright-managed Chromium.
    """
    errors: list[tuple[BrowserLaunchCandidate, BaseException]] = []
    for candidate in launch_candidates():
        try:
            if candidate.kind == "remote":
                return await _connect_async(pw, candidate.endpoint or "", candidate.protocol)
            if candidate.kind == "executable":
                return await pw.chromium.launch(
                    headless=headless,
                    executable_path=candidate.executable_path,
                )
            return await pw.chromium.launch(headless=headless)
        except Exception as exc:
            errors.append((candidate, exc))

    managed_error = next(
        (exc for candidate, exc in errors if candidate.kind == "managed" and _managed_missing(exc)),
        None,
    )
    if managed_error is not None:
        raise RuntimeError(
            "No Playwright browser backend is available. Start the shared "
            "browser_automation runtime, set PLAYWRIGHT_WS_URL, set "
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE, or install the managed browser with "
            f"`{_INSTALL_HINT}`. Tried: {_format_errors(errors)}"
        ) from managed_error
    raise RuntimeError(f"Unable to start Playwright browser. Tried: {_format_errors(errors)}")


def launch_sync_browser(pw: Any, *, headless: bool = True) -> Any:
    """Launch/connect a sync Playwright Chromium browser."""
    errors: list[tuple[BrowserLaunchCandidate, BaseException]] = []
    for candidate in launch_candidates():
        try:
            if candidate.kind == "remote":
                return _connect_sync(pw, candidate.endpoint or "", candidate.protocol)
            if candidate.kind == "executable":
                return pw.chromium.launch(
                    headless=headless,
                    executable_path=candidate.executable_path,
                )
            return pw.chromium.launch(headless=headless)
        except Exception as exc:
            errors.append((candidate, exc))

    managed_error = next(
        (exc for candidate, exc in errors if candidate.kind == "managed" and _managed_missing(exc)),
        None,
    )
    if managed_error is not None:
        raise RuntimeError(
            "No Playwright browser backend is available. Start the shared "
            "browser_automation runtime, set PLAYWRIGHT_WS_URL, set "
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE, or install the managed browser with "
            f"`{_INSTALL_HINT}`. Tried: {_format_errors(errors)}"
        ) from managed_error
    raise RuntimeError(f"Unable to start Playwright browser. Tried: {_format_errors(errors)}")


async def _connect_async(pw: Any, endpoint: str, protocol: str) -> Any:
    if protocol == "playwright":
        return await pw.chromium.connect(endpoint)
    if protocol == "cdp":
        return await pw.chromium.connect_over_cdp(endpoint)
    try:
        return await pw.chromium.connect(endpoint)
    except Exception:
        return await pw.chromium.connect_over_cdp(endpoint)


def _connect_sync(pw: Any, endpoint: str, protocol: str) -> Any:
    if protocol == "playwright":
        return pw.chromium.connect(endpoint)
    if protocol == "cdp":
        return pw.chromium.connect_over_cdp(endpoint)
    try:
        return pw.chromium.connect(endpoint)
    except Exception:
        return pw.chromium.connect_over_cdp(endpoint)
