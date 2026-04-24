"""Flagship-8 capture specs.

Each spec carries its own readiness strategy; silent ``sleep`` is banned so
flake is visible. Routes use format-string substitution against a
``StagedState`` dict keyed on channel/task labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


WaitKind = Literal["selector", "function", "network_idle", "pin_count"]
ActionKind = Literal["click", "fill", "press", "select", "wait_for"]


@dataclass
class Action:
    """A single pre-capture interaction. Runs after nav+ready, before screenshot.

    Shape per kind:
      - click:     selector required; clicks the first match
      - fill:      selector + value; clears and types value into an input
      - press:     value required (e.g. "Escape", "Enter"); selector optional (page-level if omitted)
      - select:    selector + value; chooses an <option> by value
      - wait_for:  selector required; waits for it to attach (default) or match
    """
    kind: ActionKind
    selector: str | None = None
    value: str | None = None


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
    actions: list[Action] = field(default_factory=list)  # pre-capture interactions


FLAGSHIP_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="home",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Wait for both the sidebar channel categories AND a home-grid channel
        # tile to render — the sidebar uses the channel's `category` (DAILY /
        # HOME / WORK / SHOWCASE) as a group header, so presence of one of
        # those labels is a stable signal that the channels API has resolved
        # and the CategoryGroup components have painted.
        # The HomeGridTile component *mis-names* its testid — every tile gets
        # data-testid="channel-row" and role="gridcell", not just real channels.
        # Those fire instantly (admin palette items render first). Gate instead
        # on the real channel Links — the sidebar ChannelItem + home-grid
        # channel tiles both render ``<a href="/channels/<uuid>">`` — which
        # only appear once useChannels resolves.
        wait_arg=(
            'document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
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
        # Wait for seeded sub-session messages to render — look for the
        # ▶ / ✓ step markers in the body text. Falls back to a generic
        # "modal mounted" signal in case message rendering fails so the
        # capture still produces output instead of hanging.
        wait_arg=(
            '/Step \\d\\/3|Collect inputs|Summarize overnight/.test(document.body.innerText)'
        ),
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


# ---------------------------------------------------------------------------
# Docs-repair specs (Phase A2.5) — one per broken image reference in
# ``docs/guides/*.md``. Output filenames match the guide references exactly.
# ---------------------------------------------------------------------------

DOCS_REPAIR_SPECS: list[ScreenshotSpec] = [
    # 1. heartbeats.md — channel Settings → Automation tab (hosts HeartbeatTab)
    ScreenshotSpec(
        name="channel-heartbeat",
        route="/channels/{chat_main}/settings#automation",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # AutomationTabSections renders HeartbeatTab with labels like
        # "Interval", "Quiet hours", "Prompt". Wait on a stable one.
        wait_arg='/Interval|Quiet hours|Dispatch mode/i.test(document.body.innerText)',
        output="channel-heartbeat.png",
    ),
    # 2. chat-history.md — channel Settings → Memory tab (hosts HistoryTab)
    ScreenshotSpec(
        name="channel_history_mode",
        route="/channels/{chat_main}/settings#memory",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg='/History mode|Compaction|file|structured|summary/i.test(document.body.innerText)',
        output="channel_history_mode.png",
    ),
    # 3. mcp-servers.md — /admin/mcp-servers with seeded servers
    ScreenshotSpec(
        name="mcp-list",
        route="/admin/mcp-servers",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg='/Home Assistant|Notes/i.test(document.body.innerText)',
        output="mcp-list.png",
    ),
    # 4. secrets.md — /admin/secret-values vault view (route is plural "values")
    ScreenshotSpec(
        name="secret-store",
        route="/admin/secret-values",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg='/SCREENSHOT_GITHUB_TOKEN|SCREENSHOT_WEATHER_API_KEY/i.test(document.body.innerText)',
        output="secret-store.png",
    ),
    # 5. usage-and-billing.md — /admin/usage Overview (contains cost cards
    # + spend breakdown + forecast panel in one view, matching the filename).
    # The Forecast tab exists but its panel takes longer to resolve with
    # seeded-only data; Overview shipped with the cards and breakdown reads
    # cleaner as a hero image for the guide.
    ScreenshotSpec(
        name="usage-and-forecast",
        route="/admin/usage",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Wait until the Overview panel finishes its initial fetch — the
        # generic spinner uses a .animate-spin class, which must disappear
        # before the cards render. Accept either rendered dollar amounts or
        # a "No usage" zero-state.
        wait_arg=(
            '(!document.querySelector(".animate-spin"))'
            ' && (/\\$\\d|No usage|no usage data|Total cost|Total tokens/i.test(document.body.innerText))'
        ),
        output="usage-and-forecast.png",
    ),
    # 6. ingestion.md — integration detail page for the ingestion slug
    ScreenshotSpec(
        name="integration-edit-v2",
        route="/admin/integrations/ingestion",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg='/Ingestion|ingestion/.test(document.body.innerText)',
        output="integration-edit-v2.png",
    ),
    # 7. bot-skills.md — /admin/learning#Skills (skill catalog)
    # Wait until the bot-authored-skills + catalog queries resolve: both
    # sections render Tailwind ``animate-pulse`` skeletons while loading.
    # We wait for those to disappear, then require the filter input to
    # exist (the page structure is mounted).
    ScreenshotSpec(
        name="bot-skills-learning-1",
        route="/admin/learning#Skills",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(\'input[placeholder*="Filter skills" i]\')'
            ' && document.querySelectorAll(".animate-pulse").length === 0'
            ' && document.querySelectorAll(".animate-spin").length === 0'
        ),
        output="bot-skills-learning-1.png",
    ),
    # 8. bot-skills.md — /admin/learning#History with recent activity rows
    # (alternative to the always-empty Dreaming tab on a fresh e2e instance).
    # History tab shows loop/attribution rows — closer to the "learning
    # analytics with health badges" the guide references.
    ScreenshotSpec(
        name="bot-skills-learning-2",
        route="/admin/learning#History",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '(!document.querySelector(".animate-spin"))'
            ' && /History|Turn|Bot|Channel|No history/i.test(document.body.innerText)'
        ),
        output="bot-skills-learning-2.png",
    ),
    # 9. bluebubbles.md — channel with BlueBubbles binding + seeded messages.
    # The HUD itself surfaces when the integration reports status; for a
    # baseline doc image, a live channel with chat history + binding is
    # representative. Iterate to pin a HUD widget in a later pass.
    ScreenshotSpec(
        name="channel-bluebubbles-hud",
        route="/channels/{bluebubbles}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Wait for at least one message bubble to render.
        wait_arg='document.querySelectorAll("[data-testid=\\"message\\"], .message, [data-message-id]").length >= 1',
        output="channel-bluebubbles-hud.png",
    ),
]


# ---------------------------------------------------------------------------
# Integration hero specs (Phase A2) — one admin-detail capture per integration
# guide currently lacking an image. The detail page renders manifest-derived
# Overview (capability badges) + Manifest editor + Detected Assets + (when
# present) Events / Webhook / Machine Setup, which is enough hero content for
# each integration's docs guide. No staging required — the registry is
# populated from the integrations/ tree on server startup.
# ---------------------------------------------------------------------------

def _integration_spec(*, slug: str, output: str, name_text: str) -> "ScreenshotSpec":
    return ScreenshotSpec(
        name=f"integration-{slug}",
        route=f"/admin/integrations/{slug}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Wait for the integration name in the PageHeader plus the Overview
        # section to mount; both signal the manifest fetch resolved. The
        # Overview heading is part of every detail page.
        wait_arg=(
            f'/{name_text}/i.test(document.body.innerText)'
            ' && /Overview/.test(document.body.innerText)'
        ),
        output=output,
    )


INTEGRATIONS_SPECS: list[ScreenshotSpec] = [
    _integration_spec(slug="slack",        output="integration-slack.png",        name_text="Slack"),
    _integration_spec(slug="discord",      output="integration-discord.png",      name_text="Discord"),
    _integration_spec(slug="github",       output="integration-github.png",       name_text="GitHub"),
    _integration_spec(slug="homeassistant",output="integration-homeassistant.png",name_text="Home ?Assistant"),
    _integration_spec(slug="frigate",      output="integration-frigate.png",      name_text="Frigate"),
    _integration_spec(slug="excalidraw",   output="integration-excalidraw.png",   name_text="Excalidraw"),
    _integration_spec(slug="browser_live", output="integration-browser-live.png", name_text="Browser ?Live"),
    _integration_spec(slug="web_search",   output="integration-web-search.png",   name_text="Web ?Search"),
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
                actions=list(s.actions),
            )
        )
    return out
