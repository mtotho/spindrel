"""Sync Playwright recording for kind=playwright scenes.

Drives a list of action dicts, captures the viewport via Playwright's
``record_video_dir`` (webm), then transcodes to h264 mp4 trimmed/padded
to the scene's declared ``duration``.

Action vocabulary (one verb per dict; first matching key wins):

    {goto: "/some/path"}                  # path joined onto base_url
    {wait_ms: 500}                        # plain sleep
    {wait_for: "css=...", state: "visible"}  # wait for selector state
    {click: "css=..."}
    {hover: "css=..."}
    {fill: "input.x", text: "hello"}      # instant fill
    {type: "input.x", text: "h", delay_ms: 30}  # char-by-char
    {press: "Enter"}
    {scroll_to: "css=..."}                # scrollIntoView
    {scroll_y: 400}                       # window.scrollBy
    {js: "document.body.style.zoom='1.05'"}  # eval an expression

Each entry is a dict; we read the verb from the first key in the keys
listed above. Unknown verbs raise loudly so typos surface fast.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from scripts.screenshots.playwright_runtime import launch_sync_browser


logger = logging.getLogger("screenshots.video.recording")


_VERBS = (
    "goto",
    "wait_ms",
    "wait_for",
    "click",
    "hover",
    "fill",
    "type",
    "press",
    "scroll_to",
    "scroll_y",
    "js",
)


@dataclass
class AuthBundle:
    """Auth payload seeded into the browser's localStorage. Mirrors
    ``capture/browser.AuthBundle`` but as a sync-friendly dataclass so
    the recording path doesn't pull the async capture stack."""
    api_url: str
    access_token: str
    refresh_token: str
    user: dict


def record_actions(
    *,
    scene_id: str,
    actions: list[dict[str, Any]],
    base_url: str,
    duration: float,
    viewport: tuple[int, int],
    fps: int,
    output_dir: Path,
    auth: AuthBundle | None = None,
    color_scheme: str = "dark",
) -> Path:
    """Record `actions` against `base_url`. Returns an mp4 path of length
    `duration` seconds. Caller is responsible for asset hygiene."""
    output_dir.mkdir(parents=True, exist_ok=True)
    webm_dir = output_dir / f"_webm-{scene_id}"
    if webm_dir.exists():
        shutil.rmtree(webm_dir)
    webm_dir.mkdir(parents=True)

    width, height = viewport
    logger.info(
        "recording scene %r → %dx%d @ %dfps for %.1fs",
        scene_id, width, height, fps, duration,
    )

    with sync_playwright() as pw:
        browser = launch_sync_browser(pw, headless=True)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                color_scheme=color_scheme,
                base_url=base_url,
                record_video_dir=str(webm_dir),
                record_video_size={"width": width, "height": height},
            )
            if auth is not None:
                context.add_init_script(_storage_init_script(auth))
            page = context.new_page()
            _run_actions(page, actions, scene_id=scene_id)
            # Pad to scene duration so the recorded clip is at least
            # `duration` long. We trim later, so erring long is fine.
            elapsed = _action_clock(actions)
            if elapsed < duration:
                time.sleep(duration - elapsed + 0.2)
            context.close()
        finally:
            browser.close()

    # Playwright writes one webm per Page. We assert exactly one and grab it.
    webms = sorted(webm_dir.glob("*.webm"))
    if not webms:
        raise RuntimeError(f"no recording produced for scene {scene_id!r}")
    if len(webms) > 1:
        logger.warning(
            "multiple webms in %s; keeping the first: %s", webm_dir, webms[0]
        )
    src_webm = webms[0]

    out_mp4 = output_dir / f"{scene_id}.mp4"
    _transcode(src_webm, out_mp4, duration=duration, fps=fps)
    # Clean intermediate webm dir; the mp4 is the canonical artifact.
    shutil.rmtree(webm_dir, ignore_errors=True)
    return out_mp4


# ------------------------------------------------------------------ actions


def _run_actions(page, actions: list[dict[str, Any]], *, scene_id: str) -> None:
    for idx, raw in enumerate(actions):
        verb, arg = _parse_action(raw, scene_id=scene_id, idx=idx)
        logger.debug("scene %s step %d: %s %r", scene_id, idx, verb, arg)
        if verb == "goto":
            page.goto(str(arg), wait_until="domcontentloaded", timeout=30_000)
        elif verb == "wait_ms":
            time.sleep(float(arg) / 1000.0)
        elif verb == "wait_for":
            state = raw.get("state", "visible")
            page.wait_for_selector(str(arg), state=state, timeout=20_000)
        elif verb == "click":
            page.click(str(arg), timeout=15_000)
        elif verb == "hover":
            page.hover(str(arg), timeout=15_000)
        elif verb == "fill":
            page.fill(str(arg), str(raw.get("text", "")), timeout=15_000)
        elif verb == "type":
            delay = float(raw.get("delay_ms", 30))
            page.type(str(arg), str(raw.get("text", "")), delay=delay, timeout=15_000)
        elif verb == "press":
            page.keyboard.press(str(arg))
        elif verb == "scroll_to":
            page.eval_on_selector(
                str(arg),
                "el => el.scrollIntoView({block: 'center', behavior: 'smooth'})",
            )
            time.sleep(0.4)  # let the smooth scroll settle on tape
        elif verb == "scroll_y":
            page.evaluate(f"window.scrollBy(0, {float(arg)})")
            time.sleep(0.3)
        elif verb == "js":
            page.evaluate(str(arg))
        else:
            raise ValueError(
                f"scene {scene_id!r} step {idx}: unknown verb {verb!r}"
            )


def _parse_action(raw: dict[str, Any], *, scene_id: str, idx: int) -> tuple[str, Any]:
    """Find the first known verb key in `raw`. Returns (verb, arg)."""
    for verb in _VERBS:
        if verb in raw:
            return verb, raw[verb]
    raise ValueError(
        f"scene {scene_id!r} step {idx}: no known verb in {sorted(raw)!r}; "
        f"expected one of {_VERBS}"
    )


def _action_clock(actions: list[dict[str, Any]]) -> float:
    """Conservative lower bound on real time spent. Most verbs take ~0
    deterministic time so we just count the explicit waits + typing."""
    total = 0.0
    for raw in actions:
        if "wait_ms" in raw:
            total += float(raw["wait_ms"]) / 1000.0
        if "type" in raw:
            text = str(raw.get("text", ""))
            delay = float(raw.get("delay_ms", 30))
            total += len(text) * delay / 1000.0
    return total


# ------------------------------------------------------------------ storage


def _storage_init_script(auth: AuthBundle) -> str:
    """Mirror of ``capture/browser._storage_init_script`` but for the sync
    recording context. Seeds the Zustand persist key under ``agent-auth``."""
    import json

    state = {
        "serverUrl": auth.api_url,
        "apiKey": "",
        "accessToken": auth.access_token,
        "refreshToken": auth.refresh_token,
        "user": auth.user,
        "isConfigured": True,
    }
    zustand_payload = json.dumps({"state": state, "version": 0})
    return f"""
try {{
  localStorage.setItem("agent-auth", {json.dumps(zustand_payload)});
}} catch (e) {{
  console.error("seed agent-auth failed", e);
}}
"""


# ------------------------------------------------------------------ transcode


def _transcode(src: Path, dst: Path, *, duration: float, fps: int) -> None:
    """Webm → mp4 (h264, yuv420p), trimmed to `duration` seconds.

    If the source is shorter than duration, ffmpeg's ``-t`` simply outputs
    what's there; we tpad to freeze on the last frame so downstream
    composition gets a clip of exactly the requested length.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(src),
        "-vf", f"tpad=stop_mode=clone:stop_duration={max(duration, 0.1)},fps={fps}",
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        "-movflags", "+faststart",
        "-an",
        str(dst),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg transcode failed:\n"
            + proc.stderr.decode("utf-8", errors="replace")[-2000:]
        )
