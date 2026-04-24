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
        wait_kind="function",
        # Primary signal is the data-testid I added to HomeGridTile /
        # HomeChannelsList. Until the e2e instance rebuilds with those
        # attributes, fall back to the stable role="gridcell" or the
        # seeded channel names.
        wait_arg=(
            '(document.querySelectorAll(\'[data-testid="channel-row"]\').length >= 4)'
            ' || (document.querySelectorAll(\'[role="gridcell"]\').length >= 4)'
            ' || /Evening check-in/.test(document.body.innerText)'
        ),
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
        route="/channels/{pipeline}/runs/{pipeline_live}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg='!!document.querySelector(\'header [class*="Workflow"], .lucide-workflow, [aria-label="Close"]\') || /running|pending|complete/.test(document.body.innerText)',
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
        route="/widgets/dev#tools",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # The sandbox's "Rendered widget" + "Raw result" panes only mount after
        # a tool run — that requires bot/channel selection + Run click, which
        # is too complex for this spec. For flagship we settle for the tool
        # picker + arg form, which is itself a representative shot. Wait for
        # the search input (confirms the route mounted) and a tool row.
        wait_arg=(
            '!!document.querySelector(\'input[placeholder="Search tools\\u2026"]\')'
            ' && document.querySelectorAll(\'button\').length > 10'
        ),
        output="dev-panel-tools.png",
    ),
    ScreenshotSpec(
        name="omnipanel-mobile",
        route="/channels/{chat_main}",
        viewport={"width": 375, "height": 812},
        wait_kind="function",
        # Drawer renders via ReactDOM.createPortal with role="dialog" and
        # aria-label="Channel menu". Wait for that portal to mount.
        wait_arg='!!document.querySelector(\'[role="dialog"][aria-label="Channel menu"]\')',
        output="omnipanel-mobile.png",
        # Init script is parameterized at resolve time with the chat_main
        # channel id so the Zustand ui store hydrates with mobileDrawerOpen=true
        # and leftTab="widgets" for that channel.
        extra_init_scripts=[
            "OMNIPANEL_MOBILE_INIT"  # placeholder — resolved in resolve_specs
        ],
    ),
    ScreenshotSpec(
        name="admin-bots-list",
        route="/admin/bots",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # data-testid lands post-rebuild; fall back to the seeded bot names
        # (Orion/Vega/Lyra) which we know are unique to the screenshot bots.
        wait_arg=(
            '(document.querySelectorAll(\'[data-testid="bot-row"]\').length >= 3)'
            ' || (/Orion/.test(document.body.innerText) && /Vega/.test(document.body.innerText) && /Lyra/.test(document.body.innerText))'
        ),
        output="admin-bots-list.png",
    ),
]


def _omnipanel_mobile_init_script(chat_main_id: str) -> str:
    """Seed localStorage["spindrel-ui"] so the channel mounts with drawer open.

    Written as a single IIFE injected via Playwright's ``add_init_script`` so
    the Zustand ``persist`` middleware reads our seeded state on first hydrate
    — no reload dance required.
    """
    return (
        "(() => {\n"
        "  const KEY = 'spindrel-ui';\n"
        "  let raw = localStorage.getItem(KEY);\n"
        "  let obj = raw ? JSON.parse(raw) : { state: {}, version: 0 };\n"
        "  obj.state = obj.state || {};\n"
        "  obj.state.channelPanelPrefs = obj.state.channelPanelPrefs || {};\n"
        f"  obj.state.channelPanelPrefs[{chat_main_id!r}] = Object.assign(\n"
        f"    obj.state.channelPanelPrefs[{chat_main_id!r}] || {{}},\n"
        "    { leftTab: 'widgets', mobileDrawerOpen: true, leftOpen: true, rightOpen: true }\n"
        "  );\n"
        "  obj.state.omniPanelTab = 'widgets';\n"
        "  localStorage.setItem(KEY, JSON.stringify(obj));\n"
        "})();"
    )


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

        # Per-spec init-script placeholder resolution.
        init_scripts: list[str] = []
        for js in s.extra_init_scripts:
            if js == "OMNIPANEL_MOBILE_INIT":
                chat_main_id = staged.get("chat_main")
                if not chat_main_id:
                    raise KeyError(
                        f"spec {s.name!r} needs chat_main in staged state"
                    )
                init_scripts.append(_omnipanel_mobile_init_script(chat_main_id))
            else:
                init_scripts.append(js)

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
                extra_init_scripts=init_scripts,
                full_page=s.full_page,
            )
        )
    return out
