"""Flagship-8 capture specs.

Each spec carries its own readiness strategy; silent ``sleep`` is banned so
flake is visible. Routes use format-string substitution against a
``StagedState`` dict keyed on channel/task labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


WaitKind = Literal["selector", "function", "network_idle", "pin_count"]


@dataclass
class ScreenshotSpec:
    name: str                                  # output file stem
    route: str                                 # path; placeholders like {chat_main}
    viewport: dict                             # {"width": W, "height": H}
    wait_kind: WaitKind
    wait_arg: str | int                        # selector | JS function | pin count
    output: str                                # relative to docs_images_dir
    color_scheme: Literal["light", "dark"] = "light"
    pre_capture_js: str | None = None          # JS run after nav, before screenshot
    extra_init_scripts: list[str] = field(default_factory=list)
    full_page: bool = False


FLAGSHIP_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="home",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="selector",
        wait_arg='[data-testid="channel-row"]:nth-of-type(4)',
        output="home.png",
    ),
    ScreenshotSpec(
        name="chat-main",
        route="/channels/{chat_main}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg="window.__spindrel_pin_count() >= 2",
        output="chat-main.png",
    ),
    ScreenshotSpec(
        name="widget-dashboard",
        route="/widgets/channel/{demo_dashboard}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg="window.__spindrel_pin_count() >= 6",
        output="widget-dashboard.png",
    ),
    ScreenshotSpec(
        name="chat-pipeline-live",
        route="/channels/{pipeline}?run={pipeline_live}",
        viewport={"width": 1440, "height": 900},
        wait_kind="selector",
        wait_arg='[data-status="running"]',
        output="chat-pipeline-live.png",
    ),
    # html-widget-hero reuses the demo dashboard with a focused interactive
    # HTML pin. Phase 2 will promote one bot-authored HTML bundle into its
    # own dashboard; for flagship we reuse the demo-dashboard's first HTML
    # pin if present.
    ScreenshotSpec(
        name="html-widget-hero",
        route="/widgets/channel/{demo_dashboard}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg="window.__spindrel_ready >= 1 || window.__spindrel_pin_count() >= 6",
        output="html-widget-hero.png",
    ),
    ScreenshotSpec(
        name="dev-panel-tools",
        route="/widgets/dev",
        viewport={"width": 1440, "height": 900},
        wait_kind="selector",
        wait_arg='[data-testid="rendered-envelope"], [data-testid="raw-result"]',
        output="dev-panel-tools.png",
    ),
    ScreenshotSpec(
        name="omnipanel-mobile",
        route="/channels/{chat_main}",
        viewport={"width": 375, "height": 812},
        wait_kind="selector",
        wait_arg='[data-testid="channel-row"], [data-pin-id]',
        pre_capture_js="""
        (async () => {
          const btn = document.querySelector('[data-testid="mobile-menu"], button[aria-label*="menu" i]');
          if (btn) btn.click();
        })()
        """,
        output="omnipanel-mobile.png",
    ),
    ScreenshotSpec(
        name="admin-bots-list",
        route="/admin/bots",
        viewport={"width": 1440, "height": 900},
        wait_kind="selector",
        wait_arg='[data-testid="bot-row"]:nth-of-type(3)',
        output="admin-bots-list.png",
    ),
]


def resolve_specs(specs: list[ScreenshotSpec], staged: dict[str, str]) -> list[ScreenshotSpec]:
    """Return new specs with ``route`` placeholders substituted from ``staged``.

    Missing placeholders raise ``KeyError`` — better to fail loudly than to
    silently point at the wrong route.
    """
    out: list[ScreenshotSpec] = []
    for s in specs:
        try:
            route = s.route.format(**staged)
        except KeyError as e:
            raise KeyError(
                f"spec {s.name!r} references unstaged placeholder: {e}. "
                f"Did you run `stage --only flagship` first?"
            ) from None
        out.append(
            ScreenshotSpec(
                name=s.name,
                route=route,
                viewport=s.viewport,
                wait_kind=s.wait_kind,
                wait_arg=s.wait_arg,
                output=s.output,
                color_scheme=s.color_scheme,
                pre_capture_js=s.pre_capture_js,
                extra_init_scripts=s.extra_init_scripts,
                full_page=s.full_page,
            )
        )
    return out
