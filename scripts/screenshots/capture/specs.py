"""Flagship-8 capture specs.

Each spec carries its own readiness strategy; silent ``sleep`` is banned so
flake is visible. Routes use format-string substitution against a
``StagedState`` dict keyed on channel/task labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


WaitKind = Literal["selector", "function", "network_idle", "pin_count"]
ActionKind = Literal["click", "dblclick", "fill", "press", "select", "wait", "wait_for"]


@dataclass
class Action:
    """A single pre-capture interaction. Runs after nav+ready, before screenshot.

    Shape per kind:
      - click:     selector required; clicks the first match
      - dblclick:  selector required; double-clicks the first match
      - fill:      selector + value; clears and types value into an input
      - press:     value required (e.g. "Escape", "Enter"); selector optional (page-level if omitted)
      - select:    selector + value; chooses an <option> by value
      - wait:      value required; waits that many milliseconds
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
    assert_js: str | None = None               # JS assertion run before screenshot; throw on failure
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
        # Pin count alone fires before messages paint — chat area then
        # captures with `bg-skeleton/[0.04] animate-pulse` placeholders.
        # Gate on (a) pins mounted, (b) at least one real message bubble
        # rendered (≥40 chars of non-whitespace text in the chat surface,
        # which the skeleton placeholder bars never satisfy), and (c)
        # chat skeleton has finished animating away.
        wait_arg=(
            'window.__spindrel_pin_count() >= 2 '
            '&& document.querySelectorAll(\'[class*="bg-skeleton"]\').length === 0 '
            '&& document.body.innerText.length > 800'
        ),
        output="chat-main.png",
    ),
    ScreenshotSpec(
        name="widget-dashboard",
        route="/widgets/channel/{demo_dashboard}",
        viewport={"width": 1600, "height": 1000},
        wait_kind="function",
        wait_arg="window.__spindrel_pin_count() >= 5",
        output="widget-dashboard.png",
        # Collapse the secondary channels-list sidebar so the dashboard
        # fills the viewport instead of leaving a blank ~360px column on
        # the left. ``spindrel-ui`` is the Zustand persist key for the UI
        # store; ``sidebarCollapsed`` is what the AppShell's Sidebar reads.
        extra_init_scripts=[
            "(() => {"
            "  const KEY = 'spindrel-ui';"
            "  let raw = localStorage.getItem(KEY);"
            "  let obj = raw ? JSON.parse(raw) : { state: {}, version: 0 };"
            "  obj.state = obj.state || {};"
            "  obj.state.sidebarCollapsed = true;"
            "  localStorage.setItem(KEY, JSON.stringify(obj));"
            "})();"
        ],
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
        wait_arg="window.__spindrel_ready >= 1 || window.__spindrel_pin_count() >= 5",
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
    # The skeletons are plain `bg-surface-raised/35` divs (NOT animate-pulse),
    # so the old wait predicate never gated on actual data resolution. The
    # SettingsStatGrid rendered post-load shows "Surfacings", "Auto-injects",
    # "Unused" labels — those only appear when isLoading=false. The skill
    # catalog area then renders rows OR the "No bot-authored skills..."
    # empty-state. We also gate on the channel sidebar settling.
    ScreenshotSpec(
        name="bot-skills-learning-1",
        route="/admin/learning#Skills",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            # Stat-grid labels are CSS-uppercased ("SURFACINGS"); innerText
            # reflects text-transform in Chromium so we use case-insensitive
            # regex to match either form.
            '/Surfacings/i.test(document.body.innerText)'
            ' && /Auto.injects/i.test(document.body.innerText)'
            ' && /Unused/i.test(document.body.innerText)'
            # Skill catalog has resolved when at least one row's "X uses"
            # meta is in the DOM — those only render once `parsed` is built.
            ' && /\\d+\\s*uses/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="bot-skills-learning-1.png",
    ),
    # 8. bot-skills.md — /admin/learning#History
    # Same channel-sidebar settling gate as -1. The History tab renders the
    # search-results-or-empty surface; "Archived Sections" header is the
    # post-mount marker (only renders once the History panel mounts).
    ScreenshotSpec(
        name="bot-skills-learning-2",
        route="/admin/learning#History",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Archived Sections/.test(document.body.innerText)'
            ' && /Run a history search|Bot|Channel/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
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
# Integration hero specs (Phase A2). Curated for differentiation — eight
# clones of the same admin-detail template aren't useful. We keep:
#
#   1. integrations-library.png — the Library tab grid (cross-cutting hero
#      for `docs/guides/integrations.md`; works without staging)
#   2. integrations-active.png  — the Active tab populated with adopted
#      integrations (requires the `integrations` stager so the list is
#      non-empty)
#   3. integration-{github, homeassistant, frigate}.png — three detail-page
#      heroes chosen because each has distinctive content the docs reference:
#      GitHub's 9 webhook events, HomeAssistant's 6 tool widgets, Frigate's
#      webhook + machine-control surfaces. Captured ``full_page=True`` so the
#      manifest editor + events + detected assets are all visible.
#
# Adoption staging is via ``stage_integrations`` (PUT
# /admin/integrations/<id>/status -> enabled). Teardown reverts to
# ``available``. Slack / Discord / Excalidraw / Browser-Live / Web-Search
# detail captures were dropped — their pages were ~80% identical scaffolding;
# their guide heroes need the in-channel rendered tool result, deferred to
# A2-channel.
# ---------------------------------------------------------------------------


INTEGRATIONS_SPECS: list[ScreenshotSpec] = [
    # 1. Library tab — the catalog grid (route uses hash routing via
    # ``useHashTab``). Cards show every shipped integration with their
    # adoption state, making this the canonical "what-can-Spindrel-do" hero
    # for `integrations.md`.
    ScreenshotSpec(
        name="integrations-library",
        route="/admin/integrations#library",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # When ``useIntegrations`` is loading the page renders ONLY a Spinner
        # (early return), so neither tab label is in the DOM. Once both
        # "Active" and "Library" labels appear, the segmented control is
        # mounted and the integration list has resolved. We additionally
        # wait on a Library-only integration name (Bluebubbles is in Library,
        # not Active) so we know the hash routed to the right list.
        wait_arg=(
            '/Active/.test(document.body.innerText)'
            ' && /Library/.test(document.body.innerText)'
            ' && /Bluebubbles|Excalidraw|Slack/.test(document.body.innerText)'
        ),
        output="integrations-library.png",
    ),
    # 2. Active tab — adopted integrations after staging. Shows the user's
    # populated environment, which is the state all docs prose assumes. The
    # default hash is ``#active``; we set it explicitly for symmetry.
    ScreenshotSpec(
        name="integrations-active",
        route="/admin/integrations#active",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Wait for the segmented control mount + at least one adopted
        # integration name + the section header ("Needs Setup" or "Ready").
        # The section headers only render once filtering completes, so they
        # gate against the "data loaded but list filter mid-flight" case.
        wait_arg=(
            '/Active/.test(document.body.innerText)'
            ' && /Library/.test(document.body.innerText)'
            ' && /Frigate|GitHub|Github|Home ?Assistant|Web ?Search/i.test(document.body.innerText)'
            ' && /Needs Setup|Ready/i.test(document.body.innerText)'
        ),
        output="integrations-active.png",
    ),
    # 3. GitHub detail — full_page so all 9 events are visible alongside the
    # manifest editor + env vars block. The events list is the docs-relevant
    # surface (it's what task triggers / binding filters key off of).
    ScreenshotSpec(
        name="integration-github",
        route="/admin/integrations/github",
        viewport={"width": 1440, "height": 1100},
        wait_kind="function",
        wait_arg=(
            '/Github|GitHub/.test(document.body.innerText)'
            ' && /Events \\(9\\)|pull_request/.test(document.body.innerText)'
        ),
        full_page=True,
        output="integration-github.png",
    ),
    # 4. HomeAssistant detail — full_page so the 6 tool widgets list is
    # visible. HomeAssistant guide explicitly mentions tool widgets.
    ScreenshotSpec(
        name="integration-homeassistant",
        route="/admin/integrations/homeassistant",
        viewport={"width": 1440, "height": 1100},
        wait_kind="function",
        wait_arg=(
            '/Home ?assistant/i.test(document.body.innerText)'
            ' && /TOOL WIDGETS|haSearchEntities|hassTurnOn/i.test(document.body.innerText)'
        ),
        full_page=True,
        output="integration-homeassistant.png",
    ),
    # 5. Frigate detail — full_page so webhook URL + skill + machine-control
    # surfaces are all in frame.
    ScreenshotSpec(
        name="integration-frigate",
        route="/admin/integrations/frigate",
        viewport={"width": 1440, "height": 1100},
        wait_kind="function",
        wait_arg=(
            '/Frigate/.test(document.body.innerText)'
            ' && /Webhook|object_detected/i.test(document.body.innerText)'
        ),
        full_page=True,
        output="integration-frigate.png",
    ),
]


# ---------------------------------------------------------------------------
# A3-docs: feature deep-dives ordered by docs-guide gap.
#
# Admin slice — all routes are static; the registry/auth/data is whatever the
# server has in it. No staging. Each capture targets a guide that currently
# has zero images, or a README TODO placeholder.
# ---------------------------------------------------------------------------


A3_DOCS_SPECS: list[ScreenshotSpec] = [
    # Providers list — feeds `docs/guides/providers.md` and README TODO #3
    # ("providers/usage screenshot"). PageHeader title is "Providers"; once
    # the content surface mounts the title is in the DOM.
    ScreenshotSpec(
        name="providers-settings",
        route="/admin/providers",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Title + at least one provider name renders once useProviders resolves.
        # Provider rows include common names like "OpenAI" / "Anthropic" /
        # "Ollama" / "Groq"; we wait for any of them to confirm list mount.
        wait_arg=(
            '/Providers/.test(document.body.innerText)'
            ' && /OpenAI|Anthropic|Ollama|Groq|Gemini/i.test(document.body.innerText)'
        ),
        output="providers-settings.png",
    ),
    # Approvals queue — feeds `docs/guides/tool-policies.md` and
    # `docs/guides/development-process.md`. Even with no pending approvals the
    # page shows the queue UI + history; non-empty would be ideal but doesn't
    # block the docs hero.
    ScreenshotSpec(
        name="approvals-queue",
        route="/admin/approvals",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # First: wait for the chrome to settle (page title + sidebar links).
        # The list query (`/api/v1/approvals` with no status filter) returns
        # hundreds of historical e2e-test rows on this instance which makes
        # the spinner stick — we'll switch to the Pending tab via action so
        # the hero is both fast and the actionable surface that
        # tool-policies.md wants.
        wait_arg=(
            '/Approvals/.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        actions=[
            Action(kind="click", selector="button:has-text('Pending')"),
            # After the click, useApprovals re-runs with status=pending.
            # Pending is typically empty on a quiet instance — empty-state
            # text "No approvals with status \"pending\"." is a stable
            # signal the new query resolved.
            Action(
                kind="wait_for",
                selector='text=/No approvals|requested by/i',
            ),
        ],
        output="approvals-queue.png",
    ),
    # Task definitions (pipeline library equivalent) — feeds
    # `docs/guides/pipelines.md`. The Tasks page with `view=definitions` is
    # the closest UI surface to a "pipeline library" — it lists every
    # registered task definition including pipeline-shaped ones.
    ScreenshotSpec(
        name="pipeline-library",
        route="/admin/automations?view=definitions",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # The Definitions tab label sits in the page chrome and matches even
        # while the list query is loading. Wait for the actual definitions
        # surface: either a "No task definitions yet." empty-state OR a
        # task row marker (the table header includes "Trigger" / "Bot" /
        # "Status" columns once the desktop view renders). Also gate on the
        # sidebar leaving its skeleton state so chrome looks settled.
        wait_arg=(
            '/Tasks/.test(document.body.innerText)'
            ' && /No task definitions|Trigger|Last run|Next run/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="pipeline-library.png",
    ),
    # Workspace files browser — feeds `templates-and-activation.md` and
    # `how-spindrel-works.md`. Hero shows the canonical workspace tree
    # (`bots/`, `channels/`, `common/`, `integrations/`, `users/`) so the
    # caption can explain the mental model: "every bot has a home in here."
    # `{default_workspace}` is resolved from `client.list_workspaces()` at
    # capture time — first workspace is always the Default.
    ScreenshotSpec(
        name="workspace-files",
        route="/admin/workspaces/{default_workspace}/files",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Wait for the file tree to mount — `bots`, `channels`, `common`,
        # `integrations`, `users` are the canonical top-level dirs. The
        # presence of all five is a strong signal that the directory listing
        # query resolved (vs. showing only chrome).
        wait_arg=(
            '/bots/.test(document.body.innerText)'
            ' && /channels/.test(document.body.innerText)'
            ' && /integrations/.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="workspace-files.png",
    ),
    # Skill detail — feeds `bot-skills.md`. We point at a rich library skill
    # (`widgets/html`, 27 chunks + 12 triggers) so the hero shows a populated
    # skill page rather than a stub. Skill IDs are slashy paths and need URL
    # encoding when used as route segments — `widgets%2Fhtml`.
    ScreenshotSpec(
        name="skill-detail",
        route="/admin/skills/widgets%2Fhtml",
        viewport={"width": 1440, "height": 1100},
        wait_kind="function",
        # Wait for the skill name + at least one of the rich-content
        # markers (triggers list, chunk count, or the markdown body
        # heading). Also gate on the channel sidebar settling.
        wait_arg=(
            '/HTML Widgets|widgets\\/html|HTML widget/i.test(document.body.innerText)'
            ' && /Triggers|Chunks|Source/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        full_page=True,
        output="skill-detail.png",
    ),
]


# ---------------------------------------------------------------------------
# Core-feature specs (Track A3-docs continuation, sub-pass 1).
#
# Admin-page heroes for guides that today have zero images. Two captures in
# this pass; KB + chat-content captures land in a follow-up sub-pass with
# their own staging primitives.
# ---------------------------------------------------------------------------


CORE_FEATURE_SPECS: list[ScreenshotSpec] = [
    # Webhooks — feeds `docs/guides/webhooks.md`. WebhooksScreen renders a
    # PageHeader title "Webhooks" then either a Spinner or a card grid. With
    # the seed scenario, three named cards are present; their names contain
    # the literal "screenshot:" prefix so the predicate is unique.
    ScreenshotSpec(
        name="webhooks-list",
        route="/admin/webhooks",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Webhooks/.test(document.body.innerText)'
            ' && /GitHub Actions trigger|Datadog tool-call traces|Slack status pings/'
            '.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="webhooks-list.png",
    ),
    # Tools library — feeds `docs/guides/custom-tools.md`. ToolsScreen has a
    # PageHeader title "Tools", a "{N} tools" count chip, a search input, and
    # the ToolsTab list. The chip displays "0 tools" while useTools is in
    # flight, and the count regex would otherwise gate on the loading state.
    # Gate strictly: count must be > 0 AND a section header ("Local") must
    # have rendered (only present once the list mounted with real rows).
    ScreenshotSpec(
        name="tools-library",
        route="/admin/tools",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Tools/.test(document.body.innerText)'
            # Match "<N> tools" where N is a positive integer (excludes "0 tools").
            ' && /(?:^|\\s)([1-9]\\d*)\\s+tools?\\b/i.test(document.body.innerText)'
            # Section headers use `text-transform: uppercase`; innerText reflects
            # the rendered casing in Chromium, so case-insensitive match.
            ' && /\\bLocal\\b/i.test(document.body.innerText)'
            ' && !!document.querySelector(\'input[placeholder="Filter tools..."]\')'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="tools-library.png",
    ),
    # Memory & Knowledge — feeds `docs/guides/knowledge-bases.md`. The page is
    # ``/admin/learning`` and uses ``useHashTab`` so ``#Knowledge`` lands on
    # the Knowledge Library tab on first paint. The default sort is alphabetical
    # by ``owner_name``, so without filtering the seeded "Orion" row sits below
    # the visible viewport behind a stack of unrelated zero-state rows. Use
    # the filter input to narrow to the seeded bot — same UI control a real
    # admin would use to inspect a single bot's KB inventory. Predicate gates
    # on the exact file/chunk counts the seeder produces (4 files / 8 chunks).
    ScreenshotSpec(
        name="kb-detail",
        route="/admin/learning#Knowledge",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Memory\\s*&\\s*Knowledge/.test(document.body.innerText)'
            ' && /Knowledge Library/.test(document.body.innerText)'
            ' && /Orion/.test(document.body.innerText)'
            ' && /\\b4\\s+files\\b/.test(document.body.innerText)'
            ' && /\\b8\\s+chunks\\b/.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        actions=[
            Action(
                kind="fill",
                selector='input[placeholder="Filter knowledge bases..."]',
                value="Orion",
            ),
        ],
        output="kb-detail.png",
    ),
    # chat-delegation — feeds `docs/guides/delegation.md`. Routes to the
    # dedicated ``screenshot:chat-delegation`` channel which carries one
    # seeded turn driven via ``client.seed_turn`` before capture: user asks
    # Orion to delegate, Orion calls ``delegate_to_agent`` and the persisted
    # assistant message renders the DelegationCard ("Delegated to vega").
    # Predicate gates on the card's literal text — ``MessageBubble`` only
    # mounts the card when ``metadata.delegations`` is non-empty, which the
    # backend only populates when ``delegate_to_agent`` was actually invoked
    # (see ``app/services/sessions.py``). No need to gate on the loading
    # state here because the message is already persisted at capture time.
    ScreenshotSpec(
        name="chat-delegation",
        route="/channels/{chat_delegation}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Delegated to/.test(document.body.innerText)'
            ' && /DELEGATE TO AGENT/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="chat-delegation.png",
    ),
    # chat-command-execution — feeds `docs/guides/command-execution.md`. The
    # seed_turn prompt asks the bot to run a small `python -c` snippet via
    # ``exec_command`` and quote the raw stdout in a fenced code block, so
    # the hero shows tool badge + short explanation + the actual shell-output
    # block. Predicate gates on the EXEC COMMAND badge plus the literal
    # "Linux" string from the seeded stdout — uniquely present only after
    # the agent loop ran the command and persisted its result.
    # chat-plan-card — feeds `docs/guides/plan-mode.md` (or whichever guide
    # in the planning area picks up this hero next). The seed helper flips
    # the channel's session into plan mode before sending so ``publish_plan``
    # is accepted; the bot publishes a 4-step Postgres-backup plan and the
    # SessionPlanCard renders inline above the assistant text. Predicate
    # gates on the plan title + the PLANNING status pill.
    ScreenshotSpec(
        name="chat-plan-card",
        route="/channels/{chat_plan}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Postgres backup pipeline/i.test(document.body.innerText)'
            ' && /\\bPLANNING\\b/.test(document.body.innerText)'
            ' && /Approve\\s*&\\s*Execute/.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="chat-plan-card.png",
    ),
    ScreenshotSpec(
        name="chat-command-execution",
        route="/channels/{chat_cmd_exec}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/EXEC COMMAND/i.test(document.body.innerText)'
            ' && /Linux/.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="chat-command-execution.png",
    ),
    # chat-subagents — feeds `docs/guides/subagents.md`. Bot calls
    # ``spawn_subagents`` with two preset-driven children (summarizer +
    # researcher); after the tool returns, the parent emits a one-sentence
    # synthesis. The seed helper passes ``wait_subagents=True`` so subagent
    # turns (which inline-render WEB SEARCH rows on the parent channel
    # while running) finish painting before capture. Predicate gates on
    # the SPAWN SUBAGENTS badge plus the synthesis substring, both of
    # which only exist after the parent turn fully resolved.
    ScreenshotSpec(
        name="chat-subagents",
        route="/channels/{chat_subagents}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/SPAWN SUBAGENTS/i.test(document.body.innerText)'
            ' && /(HNSW|vector\\s+search)/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="chat-subagents.png",
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


def _channel_session_tabs_init_script(channel_id: str, latest_session_id: str, older_session_id: str) -> str:
    """Seed local browser recents for the desktop channel session tab strip."""
    import json as _json

    latest_href = f"/channels/{channel_id}/session/{latest_session_id}?surface=channel"
    older_href = f"/channels/{channel_id}/session/{older_session_id}?surface=channel"
    primary_href = f"/channels/{channel_id}"
    older_key = f"channel:{older_session_id}"
    latest_key = f"channel:{latest_session_id}"
    split_key = f"split:{older_key}|{latest_key}"
    split_layout = {
        "panes": [
            {"id": older_key, "surface": {"kind": "channel", "sessionId": older_session_id}},
            {"id": latest_key, "surface": {"kind": "channel", "sessionId": latest_session_id}},
        ],
        "focusedPaneId": latest_key,
        "widths": {older_key: 0.5, latest_key: 0.5},
        "maximizedPaneId": None,
        "miniPane": None,
    }
    panel_prefs = {
        "hiddenSessionTabKeys": [],
        "sessionTabOrderKeys": [older_key, split_key, latest_key, "primary"],
        "sessionTabLayouts": [{"key": split_key, "layout": split_layout}],
        "chatPaneLayout": split_layout,
    }
    recent_pages = [
        {"href": latest_href, "label": "Latest session · #Session tabs demo", "version": 2},
        {"href": older_href, "label": "Planning session · #Session tabs demo", "version": 2},
        {"href": primary_href, "label": "Session tabs demo", "version": 2},
    ]
    return (
        "(() => {\n"
        "  const KEY = 'spindrel-ui';\n"
        "  let raw = localStorage.getItem(KEY);\n"
        "  let obj = raw ? JSON.parse(raw) : { state: {}, version: 0 };\n"
        "  const originalFetch = window.fetch.bind(window);\n"
        "  window.fetch = async (input, init) => {\n"
        "    const url = typeof input === 'string' ? input : input?.url || '';\n"
        "    if (url.includes('/api/v1/unread/state')) {\n"
        "      return new Response(JSON.stringify({\n"
        f"        states: [{{ user_id: 'screenshot', session_id: {older_session_id!r}, channel_id: {channel_id!r}, last_read_message_id: null, last_read_at: null, first_unread_at: new Date().toISOString(), latest_unread_at: new Date().toISOString(), latest_unread_message_id: null, latest_unread_correlation_id: null, unread_agent_reply_count: 2, reminder_due_at: null, reminder_sent_at: null }}],\n"
        f"        channels: [{{ channel_id: {channel_id!r}, unread_agent_reply_count: 2, latest_unread_at: new Date().toISOString() }}]\n"
        "      }), { status: 200, headers: { 'Content-Type': 'application/json' } });\n"
        "    }\n"
        "    return originalFetch(input, init);\n"
        "  };\n"
        "  obj.state = obj.state || {};\n"
        "  obj.state.channelPanelPrefs = obj.state.channelPanelPrefs || {};\n"
        f"  const panelPrefs = {_json.dumps(panel_prefs)};\n"
        f"  obj.state.channelPanelPrefs[{channel_id!r}] = Object.assign(\n"
        f"    obj.state.channelPanelPrefs[{channel_id!r}] || {{}},\n"
        "    panelPrefs\n"
        "  );\n"
        f"  obj.state.recentPages = {_json.dumps(recent_pages)};\n"
        "  localStorage.setItem(KEY, JSON.stringify(obj));\n"
        "})();"
    )


# ---------------------------------------------------------------------------
# Spatial Canvas specs — five hero captures referenced by
# ``docs/guides/spatial-canvas.md``. Each spec seeds the canvas's
# ``localStorage`` camera + chrome prefs in an init script so the canvas
# mounts already framed for the shot — no fragile pan/zoom DOM choreography.
#
# Camera math: viewport is 1440x900; world transform is
# ``translate(camera.x, camera.y) scale(camera.scale)``. To land world point
# ``(wx, wy)`` at screen center ``(720, 450)``:
#   camera.x = 720 - wx*scale
#   camera.y = 450 - wy*scale
# ---------------------------------------------------------------------------


def _spatial_camera_init(camera: dict, *, density: str = "bold", connections: bool = True) -> str:
    """Seed ``spatial.camera`` and chrome prefs before the canvas mounts.

    `camera` is the persisted ``{x, y, scale}`` dict; the canvas reads it via
    ``loadStoredCamera`` on mount. ``density`` is one of subtle|bold|off and
    ``connections`` toggles widget→channel curves.
    """
    import json as _json
    return (
        "(() => {\n"
        f"  localStorage.setItem('spatial.camera', {_json.dumps(_json.dumps(camera))});\n"
        f"  localStorage.setItem('spatial.density.intensity', {_json.dumps(density)});\n"
        f"  localStorage.setItem('spatial.connections.enabled', {_json.dumps('1' if connections else '0')});\n"
        "  localStorage.setItem('spatial.density.window', '24h');\n"
        "  localStorage.setItem('spatial.bots.visible', '1');\n"
        "})();"
    )


# Wait predicate shared across all spatial specs: canvas mounted AND at
# least four canvas-tile elements painted. The earlier predicate counted
# ``a[href^="/channels/"]`` which the sidebar already satisfies before
# any canvas tile mounts — captures fired against an empty world. Gating
# on ``[data-tile-kind="channel"]`` (set in ``ChannelTile.tsx:329``)
# guarantees the canvas has actually rendered tiles in the seeded camera
# viewport.
_SPATIAL_READY = (
    '!!document.querySelector(\'[data-spatial-canvas="true"]\')'
    ' && document.querySelectorAll(\'[data-tile-kind="channel"]\').length >= 4'
)
# Well-focused shots pan the camera away from the channel constellation, so
# channel tiles are out of viewport (and viewport-culled). Gate instead on
# the upcoming-orbit diamond glyphs that render around the well — stage_spatial
# seeds 8 heartbeats so this is reliably populated.
_SPATIAL_WELL_READY = (
    '!!document.querySelector(\'[data-spatial-canvas="true"]\')'
    ' && document.querySelectorAll(\'[data-tile-kind="upcoming"]\').length >= 2'
)


SPATIAL_SPECS: list[ScreenshotSpec] = [
    # 1. spatial-overview-1.png — wide shot of the canvas, channels +
    # widgets + halos all visible. Default scale 0.7 frames most of the
    # constellation around the origin.
    ScreenshotSpec(
        name="spatial-overview-1",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-overview-1.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": 450, "scale": 0.7}),
        ],
    ),
    # 2. spatial-channel-zoomed-out.png — channels at "dot" zoom level
    # (scale < 0.4). Each channel is a colored disc + name label.
    ScreenshotSpec(
        name="spatial-channel-zoomed-out",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-channel-zoomed-out.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": 450, "scale": 0.32}),
        ],
    ),
    # 3. spatial-channel-zoomed-in-1.png — close zoom showing a channel
    # tile + outgoing widget connection lines. Centered on origin with a
    # high scale so connection curves brighten clearly.
    ScreenshotSpec(
        name="spatial-channel-zoomed-in-1",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-channel-zoomed-in-1.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": 450, "scale": 1.3}),
        ],
    ),
    # 4. spatial-zoom-widgets.png — three widget tiles at live-iframe zoom
    # (scale ≥ 0.6). Centered on the QA-channel cluster where stage_spatial
    # places Notes / Todos / Standing-order pins.
    ScreenshotSpec(
        name="spatial-zoom-widgets",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-zoom-widgets.png",
        color_scheme="dark",
        extra_init_scripts=[
            # Center on (-280, -190) — midpoint of Notes/Todos pins seeded
            # by stage_spatial — at scale 1.6.
            _spatial_camera_init({"x": 1168, "y": 754, "scale": 1.6}),
        ],
    ),
    # 5. spatial-blackhole.png — Now Well close-up. WELL_X=0, WELL_Y=2200
    # in spatialGeometry.ts. Frame at scale 0.85.
    ScreenshotSpec(
        name="spatial-blackhole",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_WELL_READY,
        output="spatial-blackhole.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": -1420, "scale": 0.85}),
        ],
    ),
    # 6. spatial-zoom-out-01.png — mid-zoom (~0.55), panned upper-left so a
    # cluster of channels + bots fills the frame with their density halos
    # clearly visible. Reference: user capture 2026-04-26.
    ScreenshotSpec(
        name="spatial-zoom-out-01",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-zoom-out-01.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 920, "y": 650, "scale": 0.55}),
        ],
    ),
    # 7. spatial-zoom-out-02.png — wider view (~0.42) panned so the upper
    # constellation AND the Now Well's nebula glow share the frame.
    ScreenshotSpec(
        name="spatial-zoom-out-02",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-zoom-out-02.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": 100, "scale": 0.42}),
        ],
    ),
    # 8. spatial-zoom-out-in-01.png — close-up (~1.5) on a channel + its
    # widget tiles, with curved connection lines showing relationships.
    # Centered on the QA-channel cluster where stage_spatial pins widgets.
    ScreenshotSpec(
        name="spatial-zoom-out-in-01",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-zoom-out-in-01.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 1135, "y": 735, "scale": 1.5}),
        ],
    ),
    # 9. spatial-zoom-well-01.png — Now Well close-up at high zoom (~1.1)
    # showing orbit-ring labels (1m / 5m / 10m...) and labeled diamonds
    # for any imminent heartbeats / dreaming items.
    ScreenshotSpec(
        name="spatial-zoom-well-01",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_WELL_READY,
        output="spatial-zoom-well-01.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": -1970, "scale": 1.1}),
        ],
    ),
]


_OPEN_STARBOARD_OBJECTS_JS = (
    "localStorage.setItem('spatial.starboard.width', '600');"
    "const btn = document.querySelector('button[title=\"Open Starboard\"]');"
    " if (btn && btn.getAttribute('aria-expanded') !== 'true') btn.click();"
    " const t0 = Date.now();"
    " while (Date.now() - t0 < 5000) {"
    "   if (document.querySelector('[data-starboard-panel=\"true\"]')"
    "       && document.querySelector('[data-testid=\"starboard-map-brief\"]')) break;"
    "   await new Promise(r => setTimeout(r, 100));"
    " }"
)


_SELECT_QA_CHANNEL_JS = (
    "const channel = document.querySelector('[data-spatial-object-label=\"#quality-assurance\"], [data-spatial-object-label=\"quality-assurance\"]');"
    "let row = Array.from(document.querySelectorAll('[data-testid=\"map-brief-object-row\"]'))"
    "  .find((el) => /#?quality-assurance/.test(el.textContent || ''));"
    " if (!channel && !row) {"
    "   const search = document.querySelector('[data-testid=\"starboard-map-brief\"] input');"
    "   if (search) {"
    "     search.focus();"
    "     const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
    "     setter.call(search, 'quality-assurance');"
    "     search.dispatchEvent(new Event('input', { bubbles: true }));"
    "     await new Promise(r => setTimeout(r, 250));"
    "     row = Array.from(document.querySelectorAll('[data-testid=\"map-brief-object-row\"]'))"
    "       .find((el) => /#?quality-assurance/.test(el.textContent || ''));"
    "   }"
    " }"
    "const target = channel || row;"
    " if (!target) throw new Error('quality-assurance map object not found');"
    " target.click();"
    " const search = document.querySelector('[data-testid=\"starboard-map-brief\"] input');"
    " if (search) {"
    "   const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
    "   setter.call(search, '');"
    "   search.dispatchEvent(new Event('input', { bubbles: true }));"
    " }"
    " const t1 = Date.now();"
    " while (Date.now() - t1 < 5000) {"
    "   if (document.querySelector('[data-testid=\"map-brief-selected-object\"]')"
    "       && /#quality-assurance/.test(document.body.innerText)) break;"
    "   await new Promise(r => setTimeout(r, 100));"
    " }"
)


_ASSERT_MAP_BRIEF_SELECTION_JS = (
    "const panel = document.querySelector('[data-starboard-panel=\"true\"]');"
    "const brief = document.querySelector('[data-testid=\"starboard-map-brief\"]');"
    "const body = document.querySelector('[data-testid=\"starboard-scroll-body\"]');"
    "const selected = document.querySelector('[data-testid=\"map-brief-selected-object\"]');"
    "const anchor = document.querySelector('[data-spatial-selected-anchor=\"true\"]');"
    "if (!panel) throw new Error('Starboard panel did not open');"
    "if (!brief) throw new Error('Starboard object inspector did not render');"
    "if (!selected || !/#quality-assurance/.test(selected.textContent || '')) throw new Error('QA channel is not selected in Map Brief');"
    "if (!document.querySelector('[data-testid=\"map-brief-attention-actions\"]')) throw new Error('selected brief does not expose inline attention actions');"
    "if (!/Acknowledge target/.test(selected.textContent || '')) throw new Error('selected brief cannot acknowledge the active target');"
    "if (!/(Investigate|Next up|Recently changed|Quiet nearby|Nearby quiet)/.test(brief.textContent || '')) throw new Error('Map Brief object list is not grouped by actionable cue');"
    "if (!anchor) throw new Error('selected spatial anchor did not render');"
    "if (!document.querySelector('[data-testid=\"spatial-action-cue-marker\"]')) throw new Error('spatial action cue marker did not render');"
    "if (document.querySelector('[data-spatial-action-cue-halo=\"true\"]')) throw new Error('persistent action cue halo rendered over the map');"
    "const compass = document.querySelector('[data-testid=\"spatial-action-compass\"]');"
    "if (!compass) throw new Error('spatial action compass did not render');"
    "if (compass.getAttribute('data-spatial-action-compass-collapsed') !== 'true') throw new Error('action compass should collapse while Map Brief owns the detail view');"
    "if (document.querySelector('[data-spatial-selected-anchor-label=\"true\"]')) throw new Error('selected channel rendered duplicate anchor label');"
    "const selectedStyle = getComputedStyle(selected);"
    "const leftBorder = parseFloat(selectedStyle.borderLeftWidth || '0');"
    "if (leftBorder > 1) throw new Error(`selected brief uses side-stripe chrome: ${leftBorder}px`);"
    "if (!selected.getAttribute('data-brief-tone')) throw new Error('selected brief tone marker missing');"
    "if (body) {"
    "  const bodyRect = body.getBoundingClientRect();"
    "  const selectedRect = selected.getBoundingClientRect();"
    "  if (selectedRect.top < bodyRect.top + 2) throw new Error(`selected brief clipped at top: ${selectedRect.top} < ${bodyRect.top}`);"
    "}"
)


_ASSERT_JUMP_LEFT_OF_STARBOARD_JS = (
    "const jump = document.querySelector('[data-testid=\"map-brief-action\"][data-action-label=\"Jump here\"]')"
    "  || Array.from(document.querySelectorAll('button')).find((el) => (el.textContent || '').includes('Jump here'));"
    "if (!jump) throw new Error('Jump here action not found');"
    "jump.click();"
    "await new Promise(r => setTimeout(r, 900));"
    "const panel = document.querySelector('[data-starboard-panel=\"true\"]');"
    "const anchor = document.querySelector('[data-spatial-selected-anchor=\"true\"]');"
    "if (!panel || !anchor) throw new Error('panel or selected anchor missing after jump');"
    "const panelRect = panel.getBoundingClientRect();"
    "const anchorRect = anchor.getBoundingClientRect();"
    "if (!(anchorRect.right < panelRect.left - 24)) {"
    "  throw new Error(`jump target is under Starboard: anchor.right=${anchorRect.right}, panel.left=${panelRect.left}`);"
    "}"
)

_OPEN_CANVAS_VIEW_CONTROLS_JS = (
    "const view = document.querySelector('summary[aria-label=\"Canvas view controls\"]');"
    " if (!view) throw new Error('canvas view controls button not found');"
    " view.click();"
    " const t0 = Date.now();"
    " while (Date.now() - t0 < 3000) {"
    "   if (document.querySelector('[data-testid=\"canvas-view-controls\"]')) break;"
    "   await new Promise(r => setTimeout(r, 100));"
    " }"
    " await new Promise(r => setTimeout(r, 250));"
)

_ASSERT_CANVAS_VIEW_CONTROLS_JS = (
    "const panel = document.querySelector('[data-testid=\"canvas-view-controls\"]');"
    "if (!panel) throw new Error('canvas view controls popover did not open');"
    "const text = panel.textContent || '';"
    "for (const label of ['Attention markers', 'Connection lines', 'Activity halos', 'Window', 'Show bots', 'Trails']) {"
    "  if (!text.includes(label)) throw new Error(`missing canvas view control: ${label}`);"
    "}"
    "if (!text.includes('View settings stay on the canvas.')) throw new Error('view controls do not explain their ownership');"
    "if (document.querySelector('[data-starboard-panel=\"true\"]')) throw new Error('view controls opened Starboard');"
)

_ASSERT_CHANNEL_SCHEDULE_SATELLITES_JS = (
    "const satellites = Array.from(document.querySelectorAll('[data-tile-kind=\"channel-schedule-satellite\"]'));"
    "const heartbeat = satellites.find((el) => el.getAttribute('data-schedule-kind') === 'heartbeat');"
    "const task = satellites.find((el) => el.getAttribute('data-schedule-kind') === 'task');"
    "if (!heartbeat) throw new Error('channel heartbeat satellite did not render');"
    "if (!task) throw new Error('channel task satellite did not render');"
    "const hbHref = heartbeat.getAttribute('data-schedule-href') || '';"
    "const taskHref = task.getAttribute('data-schedule-href') || '';"
    "if (!/\\/channels\\/[^/]+\\/settings#automation$/.test(hbHref)) throw new Error(`heartbeat satellite target is wrong: ${hbHref}`);"
    "if (!/\\/admin\\/automations\\//.test(taskHref)) throw new Error(`task satellite target is wrong: ${taskHref}`);"
    "if (!document.querySelector('[data-testid=\"channel-schedule-tether\"]')) throw new Error('schedule satellite tether did not render');"
    "for (const el of satellites) {"
    "  const style = getComputedStyle(el.querySelector('button') || el);"
    "  const left = parseFloat(style.borderLeftWidth || '0');"
    "  if (left > 1) throw new Error(`schedule satellite uses side-stripe chrome: ${left}px`);"
    "}"
)

_JUMP_TO_SELECTED_AND_WAIT_SCHEDULE_SATELLITES_JS = (
    "const jumpForSchedule = document.querySelector('[data-testid=\"map-brief-action\"][data-action-label=\"Jump here\"]')"
    "  || Array.from(document.querySelectorAll('button')).find((el) => (el.textContent || '').includes('Jump here'));"
    "if (!jumpForSchedule) throw new Error('Jump here action not found before schedule satellite capture');"
    "jumpForSchedule.click();"
    " const tSchedule = Date.now();"
    " while (Date.now() - tSchedule < 5000) {"
    "   const sats = document.querySelectorAll('[data-tile-kind=\"channel-schedule-satellite\"]');"
    "   const hasHeartbeat = Array.from(sats).some((el) => el.getAttribute('data-schedule-kind') === 'heartbeat');"
    "   const hasTask = Array.from(sats).some((el) => el.getAttribute('data-schedule-kind') === 'task');"
    "   if (hasHeartbeat && hasTask) break;"
    "   await new Promise(r => setTimeout(r, 100));"
    " }"
)


SPATIAL_CHECK_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="spatial-check-map-brief-selection",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-check-map-brief-selection.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 920, "y": 650, "scale": 0.55}),
        ],
        pre_capture_js=_OPEN_STARBOARD_OBJECTS_JS + _SELECT_QA_CHANNEL_JS,
        assert_js=_ASSERT_MAP_BRIEF_SELECTION_JS,
    ),
    ScreenshotSpec(
        name="spatial-check-canvas-view-controls",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-check-canvas-view-controls.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 920, "y": 650, "scale": 0.55}),
        ],
        pre_capture_js=_OPEN_CANVAS_VIEW_CONTROLS_JS,
        assert_js=_ASSERT_CANVAS_VIEW_CONTROLS_JS,
    ),
    ScreenshotSpec(
        name="spatial-check-jump-starboard-framing",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-check-jump-starboard-framing.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": 450, "scale": 0.7}),
        ],
        pre_capture_js=_OPEN_STARBOARD_OBJECTS_JS + _SELECT_QA_CHANNEL_JS,
        assert_js=_ASSERT_JUMP_LEFT_OF_STARBOARD_JS,
    ),
    ScreenshotSpec(
        name="spatial-check-channel-schedule-satellites",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-check-channel-schedule-satellites.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 920, "y": 650, "scale": 0.55}, connections=True),
        ],
        pre_capture_js=_OPEN_STARBOARD_OBJECTS_JS + _SELECT_QA_CHANNEL_JS + _JUMP_TO_SELECTED_AND_WAIT_SCHEDULE_SATELLITES_JS,
        assert_js=_ASSERT_CHANNEL_SCHEDULE_SATELLITES_JS,
    ),
    ScreenshotSpec(
        name="spatial-check-attention-badge",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            _SPATIAL_READY
            + ' && !!document.querySelector(\'[data-testid="spatial-attention-badge"]\')'
        ),
        output="spatial-check-attention-badge.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 920, "y": 650, "scale": 0.55}),
            "(() => { localStorage.setItem('spatial.starboard.activeTab', 'objects'); localStorage.setItem('spatial.starboard.width', '600'); })();",
        ],
        pre_capture_js=(
            "const badge = document.querySelector('[data-testid=\"spatial-attention-badge\"]');"
            " if (!badge) throw new Error('attention badge not found');"
            " badge.click();"
            " const t0 = Date.now();"
            " while (Date.now() - t0 < 5000) {"
            "   if (document.querySelector('[data-starboard-panel=\"true\"]')"
            "       && document.querySelector('[data-testid=\"map-brief-selected-object\"]')) break;"
            "   await new Promise(r => setTimeout(r, 100));"
            " }"
        ),
        assert_js=(
            "const panel = document.querySelector('[data-starboard-panel=\"true\"]');"
            "const selected = document.querySelector('[data-testid=\"map-brief-selected-object\"]');"
            "const attention = document.querySelector('[data-testid=\"spatial-attention-badge\"]');"
            "if (!panel) throw new Error('Starboard did not open from attention badge');"
            "if (!selected) throw new Error('attention badge did not select its map object');"
            "if (!attention) throw new Error('attention badge disappeared unexpectedly');"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-hover-suppression",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-check-hover-suppression.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 920, "y": 650, "scale": 0.55}),
        ],
        pre_capture_js=(
            _OPEN_STARBOARD_OBJECTS_JS
            + _SELECT_QA_CHANNEL_JS
            + "const other = Array.from(document.querySelectorAll('[data-tile-kind=\"channel\"]'))"
            + "  .find((el) => !/#?quality-assurance/.test(el.getAttribute('data-spatial-object-label') || el.textContent || ''));"
            + " if (!other) throw new Error('second visible channel tile not found');"
            + " other.dispatchEvent(new PointerEvent('pointerenter', { bubbles: true }));"
            + " await new Promise(r => setTimeout(r, 650));"
        ),
        assert_js=(
            "const selected = document.querySelector('[data-testid=\"map-brief-selected-object\"]');"
            "if (!selected || !/#quality-assurance/.test(selected.textContent || '')) throw new Error('QA channel is not selected before hover check');"
            "if (document.querySelector('[data-testid=\"spatial-object-hover-card\"]')) {"
            "  throw new Error('hover card rendered while Map Brief selection is active');"
            "}"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-overview-hover-calm",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SPATIAL_READY,
        output="spatial-check-overview-hover-calm.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": 450, "scale": 0.32}),
        ],
        pre_capture_js=(
            "const tile = document.querySelector('[data-tile-kind=\"channel\"]');"
            " if (!tile) throw new Error('overview channel tile not found');"
            " tile.dispatchEvent(new PointerEvent('pointerenter', { bubbles: true }));"
            " await new Promise(r => setTimeout(r, 650));"
        ),
        assert_js=(
            "if (document.querySelector('[data-testid=\"spatial-object-hover-card\"]')) {"
            "  throw new Error('overview hover card rendered at low zoom');"
            "}"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-cluster-focus-calm",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(\'[data-spatial-canvas="true"]\')'
            ' && !!document.querySelector(\'[data-tile-kind="channel-cluster"]\')'
        ),
        output="spatial-check-cluster-focus-calm.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": 450, "scale": 0.18}),
        ],
        pre_capture_js=(
            "const world = document.querySelector('[data-testid=\"spatial-world\"]');"
            " if (!world) throw new Error('spatial world not found');"
            " const beforeMatch = String(world.style.transform || '').match(/scale\\(([^)]+)\\)/);"
            " window.__spatialClusterClickScaleBefore = beforeMatch ? Number(beforeMatch[1]) : 0;"
            "const cluster = document.querySelector('[data-tile-kind=\"channel-cluster\"]');"
            " if (!cluster) throw new Error('channel cluster not found');"
            " cluster.click();"
            " await new Promise(r => setTimeout(r, 80));"
            " const midMatch = String(world.style.transform || '').match(/scale\\(([^)]+)\\)/);"
            " window.__spatialClusterClickScaleMid = midMatch ? Number(midMatch[1]) : 0;"
            " await new Promise(r => setTimeout(r, 570));"
        ),
        assert_js=(
            "const world = document.querySelector('[data-testid=\"spatial-world\"]');"
            "const afterMatch = String(world?.style.transform || '').match(/scale\\(([^)]+)\\)/);"
            "const afterScale = afterMatch ? Number(afterMatch[1]) : 0;"
            "if (!(window.__spatialClusterClickScaleMid > window.__spatialClusterClickScaleBefore)) throw new Error(`cluster click did not animate away from starting scale: ${window.__spatialClusterClickScaleBefore} -> ${window.__spatialClusterClickScaleMid}`);"
            "if (!(window.__spatialClusterClickScaleMid < afterScale)) throw new Error(`cluster click jumped to final scale instead of tweening: mid ${window.__spatialClusterClickScaleMid}, final ${afterScale}`);"
            "if (!(afterScale > 0.26)) throw new Error(`cluster click did not cross uncluster threshold: ${afterScale}`);"
            "if (!(afterScale < 0.4)) throw new Error(`cluster click zoomed too far into preview range: ${afterScale}`);"
            "if (!document.querySelector('[data-spatial-cluster-focus-cue=\"true\"]')) throw new Error('cluster click did not render revealed-member focus cues');"
            "if (document.querySelector('[data-testid=\"spatial-selection-rail\"]')) throw new Error('cluster click opened floating selection rail');"
            "if (document.querySelector('[data-spatial-selected-anchor=\"true\"]')) throw new Error('cluster click created a selected-object anchor');"
            "if (document.querySelector('[data-testid=\"spatial-object-hover-card\"]')) throw new Error('cluster click created a hover card');"
            "if (document.querySelector('[data-testid=\"spatial-lens-hint\"]')) throw new Error('cluster overview showed the focus lens hint');"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-cluster-doubleclick-focus",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(\'[data-spatial-canvas="true"]\')'
            ' && !!document.querySelector(\'[data-tile-kind="channel-cluster"]\')'
        ),
        output="spatial-check-cluster-doubleclick-focus.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": 450, "scale": 0.18}),
        ],
        pre_capture_js=(
            "const world = document.querySelector('[data-testid=\"spatial-world\"]');"
            " if (!world) throw new Error('spatial world not found');"
            " const beforeMatch = String(world.style.transform || '').match(/scale\\(([^)]+)\\)/);"
            " window.__spatialClusterScaleBefore = beforeMatch ? Number(beforeMatch[1]) : 0;"
            "const before = location.pathname;"
            " window.__spatialClusterPathBefore = before;"
        ),
        actions=[
            Action(kind="dblclick", selector='[data-tile-kind="channel-cluster"]'),
            Action(kind="wait", value="900"),
        ],
        assert_js=(
            "const world = document.querySelector('[data-testid=\"spatial-world\"]');"
            "const afterMatch = String(world?.style.transform || '').match(/scale\\(([^)]+)\\)/);"
            "const afterScale = afterMatch ? Number(afterMatch[1]) : 0;"
            "if (!(afterScale > window.__spatialClusterScaleBefore + 0.05)) throw new Error(`cluster double-click did not zoom toward the cluster: ${window.__spatialClusterScaleBefore} -> ${afterScale}`);"
            "if (!(afterScale > 0.26)) throw new Error(`cluster double-click did not cross uncluster threshold: ${afterScale}`);"
            "if (!(afterScale < 0.4)) throw new Error(`cluster double-click zoomed too far into preview range: ${afterScale}`);"
            "if (location.pathname !== window.__spatialClusterPathBefore) throw new Error('cluster double-click navigated directly to a channel');"
            "if (document.querySelector('[data-testid=\"spatial-selection-rail\"]')) throw new Error('cluster double-click opened floating selection rail');"
            "if (document.querySelector('[data-spatial-selected-anchor=\"true\"]')) throw new Error('cluster double-click created a selected-object anchor');"
            "if (document.querySelector('[data-testid=\"spatial-object-hover-card\"]')) throw new Error('cluster double-click created a hover card');"
            "if (document.querySelector('[data-testid=\"spatial-lens-hint\"]')) throw new Error('cluster overview showed the focus lens hint');"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-attention-review-deck",
        route="/hub/attention?mode=review",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"attention-command-deck-what-now\"]')"
            " && document.body.innerText.includes('Mission Control Review')"
        ),
        output="spatial-check-attention-review-deck.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "if (!text.includes('Findings') || !text.includes('Unreviewed') || !text.includes('Sweeps') || !text.includes('Cleared')) throw new Error('review deck queue chips missing');"
            "if (!document.querySelector('[data-testid=\"attention-command-deck-what-now\"]')) throw new Error('what-now lane missing');"
            "if (text.includes('Reviewing now')) throw new Error('stale reviewing-now copy is visible');"
            "if (text.includes('Open in Attention') || text.includes('Open deck')) throw new Error('legacy attention launcher copy is visible');"
            "if (text.includes('Raw signal') || text.includes('raw signal') || text.includes('Next best click')) throw new Error('legacy review language is visible');"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-attention-run-log",
        route="/hub/attention?mode=runs",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"attention-command-deck-what-now\"]')"
            " && document.body.innerText.includes('Sweep history')"
        ),
        output="spatial-check-attention-run-log.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "if (!text.includes('Operator sweeps')) throw new Error('sweep history workspace missing');"
            "if (text.includes('Transcript') && !text.includes('Transcript evidence')) throw new Error('transcript disclosure does not use evidence copy');"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-density-smoke",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(\'[data-spatial-canvas="true"]\')'
            ' && document.querySelectorAll(\'[data-tile-kind="channel"]\').length >= 4'
            ' && document.querySelectorAll(\'[data-tile-kind="bot"]\').length >= 2'
            ' && document.querySelectorAll(\'[data-tile-kind="widget"]\').length >= 2'
        ),
        output="spatial-check-density-smoke.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 920, "y": 650, "scale": 0.55}),
        ],
        assert_js=(
            "const canvas = document.querySelector('[data-spatial-canvas=\"true\"]');"
            "if (!canvas) throw new Error('spatial canvas missing');"
            "const rect = canvas.getBoundingClientRect();"
            "if (rect.width < 900 || rect.height < 650) throw new Error(`canvas too small: ${rect.width}x${rect.height}`);"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Attachment checks — browser-driven composer drag/drop + upload screenshots.
# These intentionally use Playwright-side File/DataTransfer objects instead of
# API-seeded message rows so the real composer routing, upload status, and
# optimistic receipt UI are exercised.
# ---------------------------------------------------------------------------

_ATTACHMENT_READY = (
    '!!document.querySelector(\'[data-testid="chat-composer-drop-zone"]\')'
    ' && !document.querySelector(\'[class*="bg-skeleton"]\')'
)


_ATTACHMENT_HELPERS_JS = r"""
window.__attachmentChecks = (() => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const tinyPngBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lH9SwAAAAABJRU5ErkJggg==";
  const pngBytes = () => {
    const raw = atob(tinyPngBase64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
  };
  const smallImage = () => new File([pngBytes()], "small-floorplan.png", { type: "image/png" });
  const largeImage = () => new File(
    [pngBytes(), new Uint8Array((8 * 1024 * 1024) + 4096)],
    "large-diagram.png",
    { type: "image/png" }
  );
  const notesFile = () => new File(
    [
      "# Meeting notes\n\n",
      "Attachment handling screenshot fixture.\n\n",
      "- Routes non-image files to channel data.\n",
      "- Leaves a receipt in the sent message.\n",
    ],
    "meeting-notes.txt",
    { type: "text/plain" }
  );
  const waitFor = async (predicate, label, timeout = 25000) => {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      if (predicate()) return true;
      await sleep(100);
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const rows = () => Array.from(document.querySelectorAll('[data-testid="chat-attachment-pending"]'));
  const row = (name) => rows().find((el) => el.getAttribute("data-attachment-name") === name);
  const drop = async (files, { hold = false } = {}) => {
    const zone = document.querySelector('[data-testid="chat-composer-drop-zone"]');
    if (!zone) throw new Error("composer drop zone not found");
    const dataTransfer = new DataTransfer();
    for (const file of files) dataTransfer.items.add(file);
    for (const type of ["dragenter", "dragover"]) {
      zone.dispatchEvent(new DragEvent(type, {
        bubbles: true,
        cancelable: true,
        dataTransfer,
      }));
    }
    if (!hold) {
      zone.dispatchEvent(new DragEvent("drop", {
        bubbles: true,
        cancelable: true,
        dataTransfer,
      }));
    }
  };
  const dropSet = async () => {
    await drop([smallImage(), largeImage(), notesFile()]);
    await waitFor(() => rows().length >= 3, "three pending attachment rows");
    await waitFor(() => {
      const large = row("large-diagram.png");
      const notes = row("meeting-notes.txt");
      return large?.getAttribute("data-attachment-status") === "uploaded"
        && notes?.getAttribute("data-attachment-status") === "uploaded";
    }, "channel-data uploads to finish");
  };
  const setComposerText = (text) => {
    const editor = document.querySelector('.tiptap-chat-input [contenteditable="true"]');
    if (!editor) throw new Error("composer editor not found");
    editor.focus();
    document.execCommand("selectAll", false);
    document.execCommand("insertText", false, text);
    editor.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      cancelable: true,
      inputType: "insertText",
      data: text,
    }));
  };
  const installFakeChatSubmit = () => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input?.url || "";
      if (url.endsWith("/chat") && String(init?.method || "GET").toUpperCase() === "POST") {
        return new Response(JSON.stringify({
          session_id: "00000000-0000-0000-0000-000000000001",
          channel_id: location.pathname.split("/").filter(Boolean).pop() || "",
          turn_id: "screenshot-attachment-turn"
        }), {
          status: 202,
          headers: { "Content-Type": "application/json" }
        });
      }
      return originalFetch(input, init);
    };
  };
  const send = async () => {
    const button = document.querySelector('[data-testid="chat-composer-send"]');
    if (!button) throw new Error("send button not found");
    button.click();
  };
  return {
    smallImage,
    largeImage,
    notesFile,
    waitFor,
    row,
    rows,
    drop,
    dropSet,
    setComposerText,
    installFakeChatSubmit,
    send,
  };
})();
"""

_ATTACHMENT_TERMINAL_MODE_INIT = r"""
(() => {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const response = await originalFetch(input, init);
    const url = typeof input === "string" ? input : input?.url || "";
    const method = String(init?.method || "GET").toUpperCase();
    if (method !== "GET" || !/\/api\/v1\/channels\/[^/?]+$/.test(url)) return response;
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) return response;
    const data = await response.clone().json();
    const headers = new Headers(response.headers);
    headers.set("content-type", "application/json");
    return new Response(JSON.stringify({
      ...data,
      config: {
        ...(data.config || {}),
        chat_mode: "terminal"
      }
    }), {
      status: response.status,
      statusText: response.statusText,
      headers
    });
  };
})();
"""


_ASSERT_ATTACHMENT_ROUTING_JS = (
    "const rows = window.__attachmentChecks.rows();"
    "if (rows.length < 3) throw new Error(`expected 3 pending rows, got ${rows.length}`);"
    "const small = window.__attachmentChecks.row('small-floorplan.png');"
    "const large = window.__attachmentChecks.row('large-diagram.png');"
    "const notes = window.__attachmentChecks.row('meeting-notes.txt');"
    "if (!small || small.getAttribute('data-attachment-route') !== 'inline_image') throw new Error('small image did not route inline');"
    "if (!large || large.getAttribute('data-attachment-route') !== 'channel_data') throw new Error('large image did not route to channel data');"
    "if (!notes || notes.getAttribute('data-attachment-route') !== 'channel_data') throw new Error('text file did not route to channel data');"
    "if (large.getAttribute('data-attachment-status') !== 'uploaded') throw new Error('large image upload did not finish');"
    "if (notes.getAttribute('data-attachment-status') !== 'uploaded') throw new Error('text upload did not finish');"
    "if (!/data\\/uploads\\//.test(large.textContent || '')) throw new Error('uploaded path missing from large image row');"
    "if (!/data\\/uploads\\//.test(notes.textContent || '')) throw new Error('uploaded path missing from text file row');"
)


_ASSERT_ATTACHMENT_SENT_RECEIPTS_JS = (
    "await window.__attachmentChecks.waitFor(() => {"
    "  const image = document.querySelector('[data-testid=\"chat-attachment-image-local\"][data-attachment-name=\"small-floorplan.png\"]');"
    "  const receipt = document.querySelector('[data-testid=\"chat-attachment-receipt-local\"][data-attachment-name=\"meeting-notes.txt\"]');"
    "  return !!image && !!receipt && /data\\/uploads\\//.test(receipt.getAttribute('data-attachment-detail') || receipt.textContent || '');"
    "}, 'sent attachment receipts', 10000);"
    "if (document.querySelector('[data-testid=\"chat-attachment-pending\"]')) throw new Error('pending tray stayed visible after send');"
)


ATTACHMENT_CHECK_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="chat-attachments-drop-overlay",
        route="/channels/{attachments}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_ATTACHMENT_READY,
        output="chat-attachments-drop-overlay.png",
        color_scheme="dark",
        pre_capture_js=(
            _ATTACHMENT_HELPERS_JS
            + "await window.__attachmentChecks.drop([window.__attachmentChecks.smallImage()], { hold: true });"
            + "await window.__attachmentChecks.waitFor(() => !!document.querySelector('[data-testid=\"chat-composer-drop-overlay\"]'), 'drop overlay');"
        ),
        assert_js=(
            "if (!document.querySelector('[data-testid=\"chat-composer-drop-overlay\"]')) throw new Error('drop overlay missing');"
            "if (!/Drop files to add/.test(document.body.innerText)) throw new Error('drop overlay copy missing');"
        ),
    ),
    ScreenshotSpec(
        name="chat-attachments-routing-tray",
        route="/channels/{attachments}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_ATTACHMENT_READY,
        output="chat-attachments-routing-tray.png",
        color_scheme="dark",
        pre_capture_js=_ATTACHMENT_HELPERS_JS + "await window.__attachmentChecks.dropSet();",
        assert_js=_ASSERT_ATTACHMENT_ROUTING_JS,
    ),
    ScreenshotSpec(
        name="chat-attachments-sent-receipts",
        route="/channels/{attachments}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_ATTACHMENT_READY,
        output="chat-attachments-sent-receipts.png",
        color_scheme="dark",
        pre_capture_js=(
            _ATTACHMENT_HELPERS_JS
            + "await window.__attachmentChecks.dropSet();"
            + "window.__attachmentChecks.installFakeChatSubmit();"
            + "window.__attachmentChecks.setComposerText('Please inspect the uploaded files.');"
            + "await window.__attachmentChecks.send();"
        ),
        assert_js=_ASSERT_ATTACHMENT_SENT_RECEIPTS_JS,
    ),
    ScreenshotSpec(
        name="chat-attachments-terminal-sent-receipts",
        route="/channels/{attachments}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_ATTACHMENT_READY,
        output="chat-attachments-terminal-sent-receipts.png",
        color_scheme="dark",
        extra_init_scripts=[_ATTACHMENT_TERMINAL_MODE_INIT],
        pre_capture_js=(
            _ATTACHMENT_HELPERS_JS
            + "await window.__attachmentChecks.dropSet();"
            + "window.__attachmentChecks.installFakeChatSubmit();"
            + "window.__attachmentChecks.setComposerText('Please inspect the uploaded files.');"
            + "await window.__attachmentChecks.send();"
        ),
        assert_js=(
            _ASSERT_ATTACHMENT_SENT_RECEIPTS_JS
            + "if (!/message/.test(document.body.innerText)) throw new Error('terminal composer status missing');"
        ),
    ),
]


_VOICE_READY = (
    '!!document.querySelector(\'[data-testid="chat-composer-send"][aria-label="Record audio"]\')'
)

_VOICE_MEDIA_INIT = r"""
(() => {
  class FakeMediaRecorder {
    static isTypeSupported(mime) {
      return !mime || String(mime).startsWith("audio/webm");
    }
    constructor(stream, options = {}) {
      this.stream = stream;
      this.mimeType = options.mimeType || "audio/webm";
      this.state = "inactive";
      this.ondataavailable = null;
      this.onstop = null;
    }
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      const blob = new Blob(["synthetic webm audio"], { type: this.mimeType });
      this.ondataavailable?.({ data: blob });
      setTimeout(() => this.onstop?.(), 0);
    }
  }
  Object.defineProperty(window, "MediaRecorder", {
    configurable: true,
    writable: true,
    value: FakeMediaRecorder,
  });
  Object.defineProperty(window.navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: async () => ({
        getTracks: () => [{ stop() {} }]
      })
    },
  });
})();
"""

_VOICE_HELPERS_JS = r"""
window.__voiceChecks = (() => {
  const waitFor = async (predicate, label, timeout = 10000) => {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      const result = await predicate();
      if (result) return result;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(`timed out waiting for ${label}`);
  };
  const installFakeChatSubmit = () => {
    const originalFetch = window.fetch.bind(window);
    window.__voiceChecksPayload = null;
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input?.url || "";
      if (url.endsWith("/chat") && String(init?.method || "GET").toUpperCase() === "POST") {
        window.__voiceChecksPayload = JSON.parse(String(init?.body || "{}"));
        return new Response(JSON.stringify({
          session_id: "00000000-0000-0000-0000-000000000002",
          channel_id: location.pathname.split("/").filter(Boolean).pop() || "",
          turn_id: "screenshot-voice-turn"
        }), {
          status: 202,
          headers: { "Content-Type": "application/json" }
        });
      }
      return originalFetch(input, init);
    };
  };
  const button = () => document.querySelector('[data-testid="chat-composer-send"]');
  const record = async () => {
    const btn = button();
    if (!btn) throw new Error("voice button not found");
    btn.click();
    await waitFor(() => document.querySelector('[data-testid="chat-composer-recording"]'), "recording overlay");
  };
  const send = async () => {
    const btn = button();
    if (!btn) throw new Error("send recording button not found");
    btn.click();
    await waitFor(() => window.__voiceChecksPayload, "voice payload");
  };
  return { waitFor, installFakeChatSubmit, record, send };
})();
"""


VOICE_INPUT_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="chat-voice-recording",
        route="/channels/{voice_input}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_VOICE_READY,
        output="chat-voice-recording.png",
        color_scheme="dark",
        extra_init_scripts=[_VOICE_MEDIA_INIT],
        pre_capture_js=_VOICE_HELPERS_JS + "await window.__voiceChecks.record();",
        assert_js=(
            "if (!document.querySelector('[data-testid=\"chat-composer-recording\"]')) throw new Error('recording overlay missing');"
            "if (!document.querySelector('[data-testid=\"chat-composer-send\"][aria-label=\"Send recording\"]')) throw new Error('send recording button label missing');"
            "if (!document.querySelector('[data-testid=\"chat-composer-recording-cancel\"][aria-label=\"Cancel recording\"]')) throw new Error('cancel recording label missing');"
        ),
    ),
    ScreenshotSpec(
        name="chat-voice-payload",
        route="/channels/{voice_input}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_VOICE_READY,
        output="chat-voice-payload.png",
        color_scheme="dark",
        extra_init_scripts=[_VOICE_MEDIA_INIT],
        pre_capture_js=(
            _VOICE_HELPERS_JS
            + "window.__voiceChecks.installFakeChatSubmit();"
            + "await window.__voiceChecks.record();"
            + "await window.__voiceChecks.send();"
        ),
        assert_js=(
            "const payload = window.__voiceChecksPayload;"
            "if (!payload) throw new Error('voice payload missing');"
            "if (!payload.audio_data || payload.audio_data.length < 10) throw new Error('audio_data missing');"
            "if (payload.audio_format !== 'webm') throw new Error(`audio_format mismatch: ${payload.audio_format}`);"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Channel session-tab checks — local browser recents + close-to-inline-picker.
# ---------------------------------------------------------------------------

_SESSION_TABS_READY = (
    "document.querySelectorAll('[data-testid=\"channel-session-tab\"]').length >= 4"
    " && document.querySelector('[data-testid=\"channel-session-tab-strip\"]')"
    " && document.querySelectorAll('[class*=\"bg-skeleton\"]').length === 0"
    " && /What's on the radar|Three things worth/.test(document.body.innerText)"
)

_ASSERT_SESSION_TABS_JS = (
    "const strip = document.querySelector('[data-testid=\"channel-session-tab-strip\"]');"
    "if (!strip) throw new Error('session tab strip missing');"
    "const tabs = [...document.querySelectorAll('[data-testid=\"channel-session-tab\"]')];"
    "if (tabs.length < 3) throw new Error(`expected at least 3 visible session tabs, saw ${tabs.length}`);"
    "if (strip.scrollWidth > strip.clientWidth + 2) throw new Error('tab strip still horizontally scrolls');"
    "if (!tabs.some((tab) => tab.getAttribute('data-active') === 'true')) throw new Error('active session indicator missing');"
    "if (!tabs.some((tab) => tab.getAttribute('data-primary') === 'true')) throw new Error('primary session indicator missing');"
    "if (!tabs.every((tab) => tab.getAttribute('data-reorderable') === 'true')) throw new Error('session tabs are not reorderable');"
    "if (!tabs.every((tab) => tab.hasAttribute('data-loading'))) throw new Error('session tabs missing pending loading marker');"
    "const splitTab = document.querySelector('[data-testid=\"channel-session-split-tab\"]')?.closest('[data-testid=\"channel-session-tab\"]');"
    "if (!splitTab) throw new Error('split session tab missing');"
    "if (splitTab.querySelectorAll('[data-testid=\"channel-session-split-tab-pane\"]').length < 2) throw new Error('split tab panes missing');"
    "splitTab.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 240, clientY: 120 }));"
    "await new Promise((resolve) => setTimeout(resolve, 50));"
    "if (!document.querySelector('[data-testid=\"channel-session-tab-menu\"]')) throw new Error('session tab context menu missing');"
    "window.dispatchEvent(new Event('pointerdown'));"
    "await new Promise((resolve) => setTimeout(resolve, 50));"
    "const singleSessionTab = tabs.find((tab) => !tab.querySelector('[data-testid=\"channel-session-split-tab\"]'));"
    "if (!singleSessionTab) throw new Error('single session tab missing');"
    "singleSessionTab.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 320, clientY: 120 }));"
    "await new Promise((resolve) => setTimeout(resolve, 50));"
    "const renameMenu = document.querySelector('[data-testid=\"channel-session-tab-menu\"]');"
    "if (!renameMenu || !/Rename session/.test(renameMenu.textContent || '')) throw new Error('session tab rename action missing');"
    "const renameButton = [...renameMenu.querySelectorAll('button')].find((button) => /Rename session/.test(button.textContent || ''));"
    "if (!renameButton) throw new Error('session tab rename button missing');"
    "renameButton.click();"
    "await new Promise((resolve) => setTimeout(resolve, 250));"
    "if (!document.querySelector('[data-testid=\"channel-session-tab-rename-input\"]')) throw new Error('session tab rename input missing');"
    "window.dispatchEvent(new Event('pointerdown'));"
    "await new Promise((resolve) => setTimeout(resolve, 50));"
    "const overflowButton = document.querySelector('[data-testid=\"channel-session-tab-overflow-button\"]');"
    "if (overflowButton) {"
    "  overflowButton.click();"
    "  await new Promise((resolve) => setTimeout(resolve, 50));"
    "  if (!document.querySelector('[data-testid=\"channel-session-tab-overflow-menu\"]')) throw new Error('session tab overflow menu missing');"
    "  window.dispatchEvent(new Event('pointerdown'));"
    "}"
)

_SESSION_FILE_TAB_PATH = "notes/session-tab-workflow.md"
_SESSION_FILE_TABS_READY = (
    "document.querySelectorAll('[data-testid=\"channel-session-tab\"]').length >= 3"
    f" && document.querySelector('[data-session-tab-key=\"file:{_SESSION_FILE_TAB_PATH}\"][data-active=\"true\"]')"
    " && document.querySelector('[data-testid=\"channel-session-tab-strip\"]')"
    " && document.querySelectorAll('[class*=\"bg-skeleton\"]').length === 0"
)

_ASSERT_AND_SPLIT_FILE_TAB_JS = (
    "const waitFor = async (predicate, label, timeout = 10000) => {"
    "  const started = Date.now();"
    "  while (Date.now() - started < timeout) {"
    "    if (predicate()) return;"
    "    await new Promise((resolve) => setTimeout(resolve, 120));"
    "  }"
    "  throw new Error(`timed out waiting for ${label}`);"
    "};"
    f"const fileTab = document.querySelector('[data-session-tab-key=\"file:{_SESSION_FILE_TAB_PATH}\"]');"
    "if (!fileTab) throw new Error('file tab missing');"
    "if (fileTab.getAttribute('data-active') !== 'true') throw new Error('file tab not active after route open');"
    f"if (document.querySelector('[data-testid=\"channel-session-tab\"]')?.getAttribute('data-session-tab-key') !== 'file:{_SESSION_FILE_TAB_PATH}') throw new Error('new file tab did not open at the front');"
    "fileTab.click();"
    "await new Promise((resolve) => setTimeout(resolve, 120));"
    "if (fileTab.getAttribute('data-loading') === 'true') throw new Error('active file tab showed loading on click');"
    "fileTab.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 360, clientY: 120 }));"
    "await new Promise((resolve) => setTimeout(resolve, 80));"
    "const menu = document.querySelector('[data-testid=\"channel-session-tab-menu\"]');"
    "if (!menu || !/Split right/.test(menu.textContent || '')) throw new Error('file tab split action missing');"
    "const splitButton = [...menu.querySelectorAll('button')].find((button) => /Split right/.test(button.textContent || ''));"
    "if (!splitButton) throw new Error('file tab split button missing');"
    "splitButton.click();"
    "await waitFor(() => /Split/.test(fileTab.textContent || ''), 'file split tab label');"
    "await waitFor(() => document.querySelectorAll('[class*=\"bg-skeleton\"]').length === 0, 'chat skeletons to clear');"
    "await waitFor(() => !document.querySelector('.animate-spin'), 'loading indicators to clear');"
)

_ASSERT_FILE_TABS_SETTLED_JS = (
    f"const fileTab = document.querySelector('[data-session-tab-key=\"file:{_SESSION_FILE_TAB_PATH}\"]');"
    "if (!fileTab) throw new Error('file tab missing after split');"
    "if (!/Split/.test(fileTab.textContent || '')) throw new Error('file split state missing from tab');"
    "if (document.querySelectorAll('[class*=\"bg-skeleton\"]').length > 0) throw new Error('skeletons still visible in file-tab capture');"
    "if (document.querySelector('.animate-spin')) throw new Error('loading indicator still visible in file-tab capture');"
)

_CLOSE_ALL_SESSION_TABS_JS = (
    "const waitFor = async (predicate, label) => {"
    "  const started = Date.now();"
    "  while (Date.now() - started < 8000) {"
    "    if (predicate()) return;"
    "    await new Promise((resolve) => setTimeout(resolve, 100));"
    "  }"
    "  throw new Error(`timed out waiting for ${label}`);"
    "};"
    "for (let i = 0; i < 8; i += 1) {"
    "  const tab = document.querySelector('[data-testid=\"channel-session-tab\"]');"
    "  if (!tab) break;"
    "  const close = tab.querySelector('button[aria-label^=\"Close\"]');"
    "  if (!close) throw new Error('tab close button missing');"
    "  close.click();"
    "  await new Promise((resolve) => setTimeout(resolve, 200));"
    "}"
    "await waitFor(() => !!document.querySelector('[data-testid=\"channel-session-inline-picker\"]'), 'inline picker');"
)

CHANNEL_SESSION_TAB_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="channel-session-tabs",
        route="/channels/{channel_session_tabs}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SESSION_TABS_READY,
        output="channel-session-tabs.png",
        color_scheme="dark",
        extra_init_scripts=["CHANNEL_SESSION_TABS_INIT"],
        assert_js=_ASSERT_SESSION_TABS_JS,
    ),
    ScreenshotSpec(
        name="channel-session-tabs-inline-picker",
        route="/channels/{channel_session_tabs}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SESSION_TABS_READY,
        output="channel-session-tabs-inline-picker.png",
        color_scheme="dark",
        extra_init_scripts=["CHANNEL_SESSION_TABS_INIT"],
        pre_capture_js=_CLOSE_ALL_SESSION_TABS_JS,
        assert_js=(
            "if (!document.querySelector('[data-testid=\"channel-session-inline-picker\"]')) throw new Error('inline picker missing after closing tabs');"
            "if (document.querySelector('[data-testid=\"channel-session-tab-strip\"]')) throw new Error('tab strip still visible after closing all tabs');"
        ),
    ),
    ScreenshotSpec(
        name="channel-session-file-tabs",
        route=f"/channels/{{channel_session_tabs}}?open_file=notes%2Fsession-tab-workflow.md",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_SESSION_FILE_TABS_READY,
        output="channel-session-file-tabs.png",
        color_scheme="dark",
        extra_init_scripts=["CHANNEL_SESSION_TABS_INIT"],
        pre_capture_js=_ASSERT_AND_SPLIT_FILE_TAB_JS,
        assert_js=_ASSERT_FILE_TABS_SETTLED_JS,
    ),
]


# ---------------------------------------------------------------------------
# Channel quick-automation checks — validates the lightweight presets surfaced
# inside Channel Settings > Automation > Tasks.
# ---------------------------------------------------------------------------

_QUICK_AUTOMATIONS_READY = (
    "!!document.querySelector('[data-testid=\"channel-quick-automations\"]')"
    " && document.body.innerText.includes('Widget Improvement Healthcheck')"
)

_QUICK_AUTOMATION_WAIT_JS = (
    "const waitFor = async (predicate, label, timeout = 10000) => {"
    "  const started = Date.now();"
    "  while (Date.now() - started < timeout) {"
    "    if (predicate()) return;"
    "    await new Promise((resolve) => setTimeout(resolve, 120));"
    "  }"
    "  throw new Error(`timed out waiting for ${label}`);"
    "};"
)

_SCROLL_TO_QUICK_AUTOMATIONS_JS = (
    _QUICK_AUTOMATION_WAIT_JS
    + "await waitFor(() => document.querySelector('[data-testid=\"channel-quick-automations\"]'), 'quick automations');"
    + "const section = document.querySelector('[data-testid=\"channel-quick-automations\"]');"
    + "section.scrollIntoView({ block: 'center', inline: 'nearest' });"
    + "await new Promise((resolve) => setTimeout(resolve, 180));"
)

_OPEN_QUICK_AUTOMATION_DRAWER_JS = (
    _SCROLL_TO_QUICK_AUTOMATIONS_JS
    + "const preset = document.querySelector('[data-testid=\"quick-automation-widget_improvement_healthcheck\"]');"
    + "if (!preset) throw new Error('widget improvement preset missing');"
    + "preset.click();"
    + "await waitFor(() => document.querySelector('[data-testid=\"quick-automation-review-drawer\"]'), 'quick automation drawer');"
)

_ASSERT_QUICK_AUTOMATIONS_JS = (
    "const section = document.querySelector('[data-testid=\"channel-quick-automations\"]');"
    "if (!section) throw new Error('quick automations section missing');"
    "const text = section.textContent || '';"
    "if (!/Quick automations/.test(text)) throw new Error('quick automations heading missing');"
    "if (!/Widget Improvement Healthcheck/.test(text)) throw new Error('widget improvement preset missing');"
    "if (!/Full customization lives in Automations/.test(text)) throw new Error('full customization hint missing');"
)

_ASSERT_QUICK_AUTOMATION_DRAWER_JS = (
    "const drawer = document.querySelector('[data-testid=\"quick-automation-review-drawer\"]');"
    "if (!drawer) throw new Error('quick automation drawer missing');"
    "const text = drawer.textContent || '';"
    "if (!/Widget Improvement Healthcheck/.test(text)) throw new Error('drawer preset title missing');"
    "if (!/Prompt/.test(text)) throw new Error('drawer prompt editor missing');"
    "if (!/Prefilled context/.test(text)) throw new Error('drawer context summary missing');"
    "if (!/Create & Customize/.test(text)) throw new Error('drawer customize action missing');"
)

_QUICK_AUTOMATION_PRESET_INIT = """
(() => {
  const originalFetch = window.fetch.bind(window);
  const presetResponse = {
    presets: [
      {
        id: "widget_improvement_healthcheck",
        title: "Widget Improvement Healthcheck",
        description: "Schedules a recurring review of this channel's dashboard widgets, including usefulness, health, stale widgets, and hidden layout issues.",
        surface: "channel_task",
        task_defaults: {
          title: "Widget Improvement Healthcheck",
          prompt: "Review this channel's dashboard widgets for usefulness, broken states, stale context, and practical improvements.",
          scheduled_at: "+1h",
          recurrence: "+1w",
          task_type: "scheduled",
          trigger_config: { type: "schedule" },
          skills: ["widgets", "widgets/errors", "widgets/channel_dashboards"],
          tools: ["describe_dashboard", "check_dashboard_widgets", "check_widget", "inspect_widget_pin"],
          post_final_to_channel: false,
          history_mode: "recent",
          history_recent_count: 30,
          skip_tool_approval: false
        }
      }
    ]
  };
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input?.url;
    if (raw) {
      const url = new URL(raw, window.location.origin);
      if (url.pathname === "/api/v1/admin/run-presets") {
        return new Response(JSON.stringify(presetResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (/\\/api\\/v1\\/admin\\/channels\\/[^/]+\\/tasks$/.test(url.pathname)) {
        return new Response(JSON.stringify({ tasks: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (/\\/api\\/v1\\/admin\\/channels\\/[^/]+\\/pipelines$/.test(url.pathname)) {
        return new Response(JSON.stringify({ subscriptions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (url.pathname === "/api/v1/admin/tasks" && url.searchParams.get("definitions_only") === "true") {
        return new Response(JSON.stringify({ tasks: [], total: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
    }
    return originalFetch(input, init);
  };
})();
"""

CHANNEL_QUICK_AUTOMATION_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="channel-quick-automations",
        route="/channels/{channel_quick_automations}/settings#automation",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_QUICK_AUTOMATIONS_READY,
        output="channel-quick-automations.png",
        color_scheme="dark",
        extra_init_scripts=[_QUICK_AUTOMATION_PRESET_INIT],
        pre_capture_js=_SCROLL_TO_QUICK_AUTOMATIONS_JS,
        assert_js=_ASSERT_QUICK_AUTOMATIONS_JS,
    ),
    ScreenshotSpec(
        name="channel-quick-automation-drawer",
        route="/channels/{channel_quick_automations}/settings#automation",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_QUICK_AUTOMATIONS_READY,
        output="channel-quick-automation-drawer.png",
        color_scheme="dark",
        extra_init_scripts=[_QUICK_AUTOMATION_PRESET_INIT],
        pre_capture_js=_OPEN_QUICK_AUTOMATION_DRAWER_JS,
        assert_js=_ASSERT_QUICK_AUTOMATION_DRAWER_JS,
    ),
    ScreenshotSpec(
        name="channel-quick-automation-drawer-mobile",
        route="/channels/{channel_quick_automations}/settings#automation",
        viewport={"width": 390, "height": 844},
        wait_kind="function",
        wait_arg=_QUICK_AUTOMATIONS_READY,
        output="channel-quick-automation-drawer-mobile.png",
        color_scheme="dark",
        extra_init_scripts=[_QUICK_AUTOMATION_PRESET_INIT],
        pre_capture_js=_OPEN_QUICK_AUTOMATION_DRAWER_JS,
        assert_js=_ASSERT_QUICK_AUTOMATION_DRAWER_JS,
    ),
]


# ---------------------------------------------------------------------------
# Channel widget-usefulness proposals — validates the human-facing usefulness
# proposal surface on channel dashboards and channel settings.
# ---------------------------------------------------------------------------

_WIDGET_USEFULNESS_READY = (
    "!!document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]') "
    "&& /proposal/i.test(document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]')?.textContent || '')"
)

_OPEN_WIDGET_USEFULNESS_DRAWER_JS = (
    "const waitFor = async (predicate, label, timeout = 10000) => {"
    "  const started = Date.now();"
    "  while (Date.now() - started < timeout) {"
    "    if (predicate()) return;"
    "    await new Promise((resolve) => setTimeout(resolve, 120));"
    "  }"
    "  throw new Error(`timed out waiting for ${label}`);"
    "};"
    "await waitFor(() => document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]'), 'proposal trigger');"
    "const button = document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]');"
    "if (!button) throw new Error('proposal button missing');"
    "button.click();"
    "await waitFor(() => document.querySelector('[data-testid=\"widget-usefulness-review-drawer\"]'), 'review drawer');"
)

_ASSERT_WIDGET_USEFULNESS_STRIP_JS = (
    "const trigger = document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]');"
    "if (!trigger) throw new Error('proposal trigger missing');"
    "const text = document.body.innerText || trigger.textContent || '';"
    "if (!/3 widget proposals|widget proposals/i.test(text)) throw new Error('widget proposal trigger count missing');"
    "if (document.querySelector('[data-testid=\"widget-usefulness-review-strip\"]')) throw new Error('persistent review strip should not render');"
)

_ASSERT_WIDGET_USEFULNESS_DRAWER_JS = (
    "const drawer = document.querySelector('[data-testid=\"widget-usefulness-review-drawer\"]');"
    "if (!drawer) throw new Error('review drawer missing');"
    "const text = drawer.textContent || '';"
    "if (!/Widget proposals/.test(text)) throw new Error('drawer title missing');"
    "if (!/Recent bot widget changes|bot widget change receipt/i.test(text)) throw new Error('bot widget change receipts missing');"
    "if (!/policy decision|Focus pin|Edit layout/.test(text)) throw new Error('actionable proposal controls missing');"
    "if (document.querySelectorAll('[data-testid=\"widget-usefulness-finding\"]').length < 1) throw new Error('proposals missing');"
)

_WIDGET_USEFULNESS_ENDPOINT_INIT = """
(() => {
  const originalFetch = window.fetch.bind(window);
  const assessment = {
    channel_id: "screenshot-channel",
    channel_name: "Widget usefulness review",
    dashboard_key: "channel:screenshot-channel",
    status: "needs_attention",
    summary: "3 widget usefulness proposal(s): 2 pinned widgets appear to overlap in purpose.",
    pin_count: 3,
    chat_visible_pin_count: 0,
    layout_mode: "rail-chat",
    widget_agency_mode: "propose_and_fix",
    project_scope_available: false,
    project: null,
    context_export: { exported_count: 0, export_enabled_count: 0 },
    recommendations: [
      {
        type: "duplicate",
        severity: "medium",
        surface: "dashboard",
        pin_id: "screenshot-pin-notes",
        label: "Usefulness notes",
        reason: "2 pinned widgets appear to overlap in purpose.",
        suggested_next_action: "Review these pins and consolidate, rename, or resize them if they serve the same job.",
        requires_policy_decision: true,
        evidence: { pin_ids: ["screenshot-pin-notes", "screenshot-pin-notes-copy"], labels: ["Usefulness notes", "Usefulness notes copy"] }
      },
      {
        type: "visibility",
        severity: "medium",
        surface: "chat",
        pin_id: "screenshot-pin-dock",
        label: "Usefulness dock panel",
        reason: "Pin is in the dock zone, but channel layout mode 'rail-chat' hides that zone in chat.",
        suggested_next_action: "Move the pin to a visible zone or change the channel presentation mode if this widget should be visible while chatting.",
        requires_policy_decision: true,
        evidence: { layout_mode: "rail-chat", zone: "dock", visible_zones: ["rail"] }
      },
      {
        type: "context",
        severity: "low",
        surface: "chat",
        pin_id: null,
        label: null,
        reason: "No pinned widgets currently export useful context into the channel prompt.",
        suggested_next_action: "Enable context_export on widgets whose state should guide future chat turns, or leave disabled for purely visual widgets.",
        requires_policy_decision: true,
        evidence: { export_enabled_count: 0, exported_count: 0 }
      }
    ]
  };
  const receipts = {
    receipts: [
      {
        id: "receipt-1",
        channel_id: "screenshot-channel",
        dashboard_key: "channel:screenshot-channel",
        action: "move_pins",
        summary: "Moved 2 widget pins into the rail so they stay visible while chatting.",
        reason: "The channel layout hides dock widgets, so the useful status widgets needed a chat-visible zone.",
        bot_id: "widget-health-bot",
        session_id: null,
        correlation_id: "00000000-0000-4000-8000-000000000001",
        task_id: null,
        affected_pin_ids: ["screenshot-pin-notes", "screenshot-pin-dock"],
        before_state: { pins: [{ id: "screenshot-pin-dock", label: "Usefulness dock panel", zone: "dock", grid_layout: { x: 0, y: 0, w: 1, h: 10 } }] },
        after_state: { pins: [{ id: "screenshot-pin-dock", label: "Usefulness dock panel", zone: "rail", grid_layout: { x: 0, y: 10, w: 1, h: 10 } }] },
        metadata: { moves: [{ pin_id: "screenshot-pin-dock", zone: "rail" }] },
        created_at: "2026-04-29T17:40:00Z"
      }
    ]
  };
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input?.url;
    if (raw) {
      const url = new URL(raw, window.location.origin);
      if (/\\/api\\/v1\\/admin\\/channels\\/[^/]+\\/widget-usefulness$/.test(url.pathname)) {
        return new Response(JSON.stringify(assessment), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (/\\/api\\/v1\\/admin\\/channels\\/[^/]+\\/widget-agency\\/receipts$/.test(url.pathname)) {
        return new Response(JSON.stringify(receipts), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (/\\/api\\/v1\\/admin\\/channels\\/[^/]+\\/settings$/.test(url.pathname) && (!init || !init.method || init.method === "GET")) {
        const response = await originalFetch(input, init);
        const body = await response.json();
        body.widget_agency_mode = "propose_and_fix";
        return new Response(JSON.stringify(body), {
          status: response.status,
          statusText: response.statusText,
          headers: { "Content-Type": "application/json" }
        });
      }
    }
    return originalFetch(input, init);
  };
})();
"""

CHANNEL_WIDGET_USEFULNESS_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="channel-widget-usefulness-dashboard",
        route="/widgets/channel/{channel_widget_usefulness}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_WIDGET_USEFULNESS_READY,
        output="channel-widget-usefulness-dashboard.png",
        color_scheme="dark",
        extra_init_scripts=[_WIDGET_USEFULNESS_ENDPOINT_INIT],
        assert_js=_ASSERT_WIDGET_USEFULNESS_STRIP_JS,
    ),
    ScreenshotSpec(
        name="channel-widget-usefulness-drawer",
        route="/widgets/channel/{channel_widget_usefulness}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=_WIDGET_USEFULNESS_READY,
        output="channel-widget-usefulness-drawer.png",
        color_scheme="dark",
        extra_init_scripts=[_WIDGET_USEFULNESS_ENDPOINT_INIT],
        pre_capture_js=_OPEN_WIDGET_USEFULNESS_DRAWER_JS,
        assert_js=_ASSERT_WIDGET_USEFULNESS_DRAWER_JS,
    ),
    ScreenshotSpec(
        name="channel-widget-usefulness-settings",
        route="/channels/{channel_widget_usefulness}/settings#dashboard",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"channel-widget-usefulness-settings-summary\"]') "
            "&& /Widget usefulness/.test(document.body.innerText)"
        ),
        output="channel-widget-usefulness-settings.png",
        color_scheme="dark",
        extra_init_scripts=[_WIDGET_USEFULNESS_ENDPOINT_INIT],
        pre_capture_js=(
            "const summary = document.querySelector('[data-testid=\"channel-widget-usefulness-settings-summary\"]');"
            "if (summary) summary.scrollIntoView({ block: 'center', inline: 'nearest' });"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
        ),
        assert_js=(
            "const summary = document.querySelector('[data-testid=\"channel-widget-usefulness-settings-summary\"]');"
            "if (!summary) throw new Error('settings summary missing');"
            "const text = document.body.innerText || summary.textContent || '';"
            "if (!/Widget usefulness/.test(text)) throw new Error('settings usefulness title missing');"
            "if (!/pins|widget proposals|layout|propose \\+ fix/.test(text)) throw new Error('settings usefulness metrics missing');"
            "if (!/bot widget change|Moved 2 widget pins/.test(text)) throw new Error('settings receipt summary missing');"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Dashboard pin config editor — schema-backed EditPinDrawer NUX.
# ---------------------------------------------------------------------------

_PIN_CONFIG_EDITOR_SCHEMA_INIT = """
(() => {
  const originalFetch = window.fetch.bind(window);
  const configSchema = {
    type: "object",
    required: ["entity_id"],
    properties: {
      entity_id: {
        type: "string",
        title: "Entity",
        description: "Widget data source used for this pinned status card.",
        default: "sensor.front_door"
      },
      units: {
        type: "string",
        title: "Units",
        description: "Display units for numeric values.",
        enum: ["imperial", "metric"],
        default: "imperial"
      },
      compact: {
        type: "boolean",
        title: "Compact layout",
        description: "Reduce padding and secondary metadata inside the widget.",
        default: false
      },
      refresh_interval: {
        type: "integer",
        title: "Refresh interval",
        description: "Polling cadence in seconds.",
        default: 60
      }
    }
  };
  const config = {
    entity_id: "sensor.front_door",
    units: "imperial",
    compact: false,
    refresh_interval: 60
  };
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input?.url;
    if (raw) {
      const url = new URL(raw, window.location.origin);
      if (/\\/api\\/v1\\/widgets\\/dashboard$/.test(url.pathname)) {
        const response = await originalFetch(input, init);
        const body = await response.json();
        body.pins = (body.pins || []).map((pin) => {
          if (pin.display_label !== "Configurable status") return pin;
          return {
            ...pin,
            widget_config: { ...config, ...(pin.widget_config || {}) },
            config_schema: configSchema
          };
        });
        return new Response(JSON.stringify(body), {
          status: response.status,
          statusText: response.statusText,
          headers: { "Content-Type": "application/json" }
        });
      }
    }
    return originalFetch(input, init);
  };
})();
"""

_ASSERT_PIN_CONFIG_EDITOR_JS = (
    "const drawer = document.querySelector('[data-testid=\"edit-pin-drawer\"]');"
    "if (!drawer) throw new Error('edit pin drawer missing');"
    "const settings = drawer.querySelector('[data-testid=\"widget-settings-section\"]');"
    "if (!settings) throw new Error('widget settings section missing');"
    "const text = drawer.textContent || '';"
    "if (!/Widget settings|Entity|Units|Compact layout|Refresh interval/.test(text)) throw new Error('schema settings controls missing');"
    "if (drawer.querySelector('[data-testid=\"advanced-widget-json-editor\"]')) throw new Error('advanced JSON should be collapsed by default');"
    "const toggle = drawer.querySelector('[data-testid=\"advanced-widget-json-toggle\"]');"
    "if (!toggle || toggle.getAttribute('aria-expanded') !== 'false') throw new Error('advanced JSON toggle not collapsed');"
)

PIN_CONFIG_EDITOR_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="dashboard-pin-config-editor",
        route="/widgets/channel/{dashboard_pin_config_channel}?edit_pin={dashboard_pin_config_pin}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg="!!document.querySelector('[data-testid=\"edit-pin-drawer\"]') && /Widget settings/.test(document.body.textContent || '')",
        output="dashboard-pin-config-editor.png",
        color_scheme="dark",
        extra_init_scripts=[_PIN_CONFIG_EDITOR_SCHEMA_INIT],
        assert_js=_ASSERT_PIN_CONFIG_EDITOR_JS,
    ),
    ScreenshotSpec(
        name="dashboard-pin-config-editor-mobile",
        route="/widgets/channel/{dashboard_pin_config_channel}?edit_pin={dashboard_pin_config_pin}",
        viewport={"width": 390, "height": 844},
        wait_kind="function",
        wait_arg="!!document.querySelector('[data-testid=\"edit-pin-drawer\"]') && /Widget settings/.test(document.body.textContent || '')",
        output="dashboard-pin-config-editor-mobile.png",
        color_scheme="dark",
        extra_init_scripts=[_PIN_CONFIG_EDITOR_SCHEMA_INIT],
        assert_js=_ASSERT_PIN_CONFIG_EDITOR_JS,
    ),
]


# ---------------------------------------------------------------------------
# Project workspace captures — validates the shared Project primitive across
# admin Projects, channel settings, Project-rooted files, and memory-tool
# transcript presentation. Staging creates one reusable Project and attaches a
# screenshot channel to it.
# ---------------------------------------------------------------------------
PROJECT_WORKSPACE_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="project-workspace-list",
        route="/admin/projects",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-list\"]') "
            "&& document.body.innerText.includes('Screenshot Project Workspace')"
        ),
        output="project-workspace-list.png",
        color_scheme="dark",
        assert_js=(
            "const rows = [...document.querySelectorAll('[data-testid=\"project-workspace-row\"]')];"
            "return { ok: rows.some((row) => row.textContent.includes('common/projects/spindrel-screenshot')), "
            "detail: 'Project row did not show the staged root path' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-detail",
        route="/admin/projects/{project_workspace_project}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-files\"]') "
            "&& document.body.innerText.includes('README.md')"
        ),
        output="project-workspace-detail.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('README.md') "
            "&& text.includes('common/projects/spindrel-screenshot'), "
            "detail: 'Project detail did not show the Project-rooted file browser' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-blueprints",
        route="/admin/projects/blueprints",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-blueprints-page\"]') "
            "&& document.body.innerText.includes('Screenshot Service Blueprint')"
        ),
        output="project-workspace-blueprints.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Screenshot Service Blueprint') "
            "&& text.includes('common/projects/{slug}') "
            "&& text.includes('2 files') "
            "&& text.includes('1 repos'), "
            "detail: 'Project Blueprint library did not show the seeded recipe declarations' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-blueprint-editor",
        route="/admin/projects/blueprints/{project_workspace_blueprint}",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-blueprint-editor\"]') "
            "&& document.body.innerText.includes('Screenshot Service Blueprint') "
            "&& document.body.innerText.includes('Repo Declarations')"
        ),
        output="project-workspace-blueprint-editor.png",
        color_scheme="dark",
        pre_capture_js=(
            "const editor = document.querySelector('[data-testid=\"project-blueprint-editor\"]');"
            "const scroller = editor && editor.parentElement;"
            "if (scroller) scroller.scrollTop = Math.floor(scroller.scrollHeight * 0.42);"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "const fieldValues = [...document.querySelectorAll('input, textarea')].map((el) => el.value || '').join('\\n');"
            "const combined = `${text}\\n${fieldValues}`;"
            "return { ok: combined.includes('README.md') "
            "&& combined.includes('overview.md') "
            "&& combined.includes('Verify Blueprint runtime') "
            "&& combined.includes('SCREENSHOT_PROJECT_GITHUB_TOKEN') "
            "&& combined.includes('spindrel'), "
            "detail: 'Project Blueprint editor did not expose files, knowledge, repos, setup commands, and secrets' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-settings-blueprint",
        route="/admin/projects/{project_workspace_blueprint_project}#Settings",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-blueprint-section\"]') "
            "&& !!document.querySelector('[data-testid=\"project-runtime-env-readiness\"]') "
            "&& document.body.innerText.includes('Screenshot Service Blueprint')"
        ),
        output="project-workspace-settings-blueprint.png",
        color_scheme="dark",
        full_page=True,
        assert_js=(
            "const text = document.body.innerText;"
            "const normalized = text.toLowerCase();"
            "return { ok: normalized.includes('secret bindings') "
            "&& text.includes('SCREENSHOT_PROJECT_GITHUB_TOKEN') "
            "&& text.includes('SCREENSHOT_PROJECT_NPM_TOKEN') "
            "&& normalized.includes('repo declarations') "
            "&& normalized.includes('env defaults') "
            "&& normalized.includes('runtime env available') "
            "&& text.includes('PROJECT_KIND') "
            "&& !text.includes('screenshot-token'), "
            "detail: 'Project settings did not expose runtime env readiness without leaking secret values' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-setup-ready",
        route="/admin/projects/{project_workspace_blueprint_project}#Setup",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-setup-ready\"]') "
            "&& document.body.innerText.includes('Ready to run setup') "
            "&& document.body.innerText.includes('https://github.com/mtotho/spindrel.git')"
        ),
        output="project-workspace-setup-ready.png",
        color_scheme="dark",
        full_page=True,
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Ready to run setup') "
            "&& text.includes('spindrel') "
            "&& text.includes('Verify Blueprint runtime') "
            "&& text.includes('SCREENSHOT_PROJECT_GITHUB_TOKEN') "
            "&& text.includes('SCREENSHOT_PROJECT_NPM_TOKEN'), "
            "detail: 'Project Setup tab did not show ready setup plan, command plan, and bound secret slots' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-setup-run-history",
        route="/admin/projects/{project_workspace_blueprint_project}#Setup",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-setup-run-history\"]') "
            "&& (document.body.innerText.includes('Latest run succeeded') "
            "|| document.body.innerText.includes('already_present') "
            "|| document.body.innerText.includes('cloned'))"
        ),
        output="project-workspace-setup-run-history.png",
        color_scheme="dark",
        full_page=True,
        pre_capture_js=(
            "const history = document.querySelector('[data-testid=\"project-workspace-setup-run-history\"]');"
            "if (history) history.scrollIntoView({ block: 'center' });"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Run History') "
            "&& (text.includes('cloned') || text.includes('already_present')) "
            "&& text.includes('Verify Blueprint runtime') "
            "&& !text.includes('screenshot-token'), "
            "detail: 'Project setup run history did not show redacted clone and command results' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-terminal",
        route="/admin/projects/{project_workspace_project}#Terminal",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-terminal\"]') "
            "&& document.body.innerText.includes('/common/projects/spindrel-screenshot') "
            "&& !!document.querySelector('.xterm') "
            "&& !document.body.innerText.includes('Starting shell')"
        ),
        output="project-workspace-terminal.png",
        color_scheme="dark",
        assert_js=(
            "return { ok: document.body.innerText.includes('Terminal') "
            "&& document.body.innerText.includes('/common/projects/spindrel-screenshot'), "
            "detail: 'Project terminal tab did not show Project cwd' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-channels",
        route="/admin/projects/{project_workspace_project}#Channels",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-attached-channels\"]') "
            "&& !!document.querySelector('[data-testid=\"project-workspace-channel-create\"]') "
            "&& !!document.querySelector('[data-testid=\"project-workspace-channel-attach\"]') "
            "&& document.body.innerText.includes('Project workspace demo')"
        ),
        output="project-workspace-channels.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Create Channel') "
            "&& text.includes('Attach Existing Channel') "
            "&& text.includes('Select channel') "
            "&& text.includes('Detach'), "
            "detail: 'Project Channels tab did not expose membership controls' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-channel-settings",
        route="/channels/{project_workspace}/settings#agent",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-channel-summary\"]') "
            "&& document.body.innerText.includes('/common/projects/spindrel-screenshot')"
        ),
        output="project-workspace-channel-settings.png",
        color_scheme="dark",
        assert_js=(
            "return { ok: document.body.innerText.includes('Bot memory uses the dedicated memory tool') "
            "&& document.body.innerText.includes('Open Project') "
            "&& document.body.innerText.includes('Open terminal'), "
            "detail: 'Channel settings did not expose Project binding actions' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-memory-tool",
        route="/channels/{project_workspace}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "document.body.innerText.includes('Replace Section memory/MEMORY.md') "
            "|| document.body.innerText.includes('Project workspace screenshot memory fact') "
            "|| document.body.innerText.toLowerCase().includes('memory was updated')"
        ),
        output="project-workspace-memory-tool.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Replace Section memory/MEMORY.md') "
            "|| text.includes('memory was updated') "
            "|| text.includes('Project workspace screenshot memory fact'), "
            "detail: 'Memory tool transcript was not visible' };"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Integration-chat captures — heroes that show the integration *delivering*,
# not the admin page. Each spec routes to a channel where the agent loop
# already ran (see ``stage_integration_chat``) and the persisted assistant
# message includes the rendered widget.
# ---------------------------------------------------------------------------
INTEGRATION_CHAT_SPECS: list[ScreenshotSpec] = [
    # chat-excalidraw — feeds `docs/guides/excalidraw.md`. seed_turn drives
    # the bot to call ``mermaid_to_excalidraw`` with a small graph; the
    # result widget shows the rendered diagram inline. Predicate gates on
    # the tool badge + at least one `<img>` (the rendered SVG/PNG).
    ScreenshotSpec(
        name="chat-excalidraw",
        route="/channels/{chat_excalidraw}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/MERMAID[ _]TO[ _]EXCALIDRAW|CREATE[ _]EXCALIDRAW/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        pre_capture_js=(
            "document.querySelectorAll('img[loading=\"lazy\"]').forEach(i => { i.loading = 'eager'; i.removeAttribute('loading'); });"
            " const imgs = Array.from(document.images);"
            " imgs.forEach(i => { try { i.scrollIntoView({block:'center'}); } catch(_){} });"
            " await Promise.race(["
            "   Promise.all(imgs.map(i => i.complete ? Promise.resolve() : new Promise(r => { i.addEventListener('load', r, {once:true}); i.addEventListener('error', r, {once:true}); }))),"
            "   new Promise(r => setTimeout(r, 4000))"
            " ]);"
            " await new Promise(r => setTimeout(r, 600));"
        ),
        output="chat-excalidraw.png",
    ),
    # chat-marp — feeds `docs/guides/marp-slides.md` (or a future slides guide).
    # The bot calls ``create_marp_slides`` (or legacy ``create_slides``) and
    # the result is delivered as a widget-backed attachment. Predicate gates
    # on the tool badge.
    ScreenshotSpec(
        name="chat-marp",
        route="/channels/{chat_marp}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/CREATE MARP SLIDES|CREATE SLIDES/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        output="chat-marp.png",
    ),
    # chat-browser-live — feeds `docs/guides/browser-live.md`. Requires a
    # paired browser (real extension OR the simulator at
    # ``scripts/screenshots/stage/browser_live_sim.py``). Predicate gates
    # on the BROWSER STATUS badge as a minimum and accepts BROWSER GOTO /
    # BROWSER SCREENSHOT badges that follow.
    ScreenshotSpec(
        name="chat-browser-live",
        route="/channels/{chat_browser_live}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Widget renders inside a same-origin iframe; we can't peek at its
        # <img> from the parent (sandboxed), so we settle for the badge text
        # and one extra second for the iframe to paint.
        wait_arg=(
            '/BROWSER[ _]SCREENSHOT/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        pre_capture_js="await new Promise(r => setTimeout(r, 1800));",
        output="chat-browser-live.png",
    ),
]


# ---------------------------------------------------------------------------
# Harness captures — admin pages around the agent harness flow:
#   - /admin/harnesses  (runtime card list, login state)
#   - /admin/bots/<id>  (bot editor with the Agent harness section bound)
#   - /admin/terminal   (in-browser shell used for `claude login`, etc.)
#
# These feed `docs/guides/agent-harnesses.md` and `docs/guides/admin-terminal.md`.
# ---------------------------------------------------------------------------
HARNESS_SPECS: list[ScreenshotSpec] = [
    # /admin/harnesses — list of registered runtimes and their auth status.
    # Predicate gates on either the Claude Code label rendering OR the
    # empty-state copy when no runtimes are registered (still photogenic).
    ScreenshotSpec(
        name="harness-overview",
        route="/admin/harnesses",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Claude Code|No harness runtimes|harness_runtime/.test(document.body.innerText)'
        ),
        output="harness-overview.png",
    ),
    # /admin/bots/<id> — the editor lands on the Identity group by default,
    # which contains both the Identity card and the Agent harness card.
    # Predicate waits for the harness section's stable copy + the runtime
    # dropdown's value being the staged `claude-code` runtime, then scrolls
    # the harness section into view before capture.
    ScreenshotSpec(
        name="harness-bot-editor",
        # `#identity` puts the editor on the Identity group, which contains
        # both the Identity card and the Agent harness card. Default landing
        # is the Overview group which does not show the harness section.
        route="/admin/bots/{harness_claude}#identity",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Agent harness|Delegate this bot/i.test(document.body.innerText)'
        ),
        pre_capture_js=(
            "const h = Array.from(document.querySelectorAll('h2,h3'))"
            "  .find(el => /Agent harness/i.test(el.textContent || ''));"
            " if (h) { h.scrollIntoView({block:'start'}); }"
            " await new Promise(r => setTimeout(r, 400));"
        ),
        output="harness-bot-editor.png",
    ),
    # /admin/terminal — in-browser PTY at rest (prompt visible, cursor blinking).
    # The TerminalPanel is lazy-loaded; predicate waits for the xterm root to
    # mount and for the page header to land.
    ScreenshotSpec(
        name="terminal-rest",
        route="/admin/terminal",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(".xterm, .xterm-viewport, [class*=\\"xterm\\"]")'
            ' && /Terminal/.test(document.body.innerText)'
        ),
        # Let the terminal echo its prompt before we shoot.
        pre_capture_js="await new Promise(r => setTimeout(r, 800));",
        output="terminal-rest.png",
    ),
    # /channels/{harness_chat} — a real harness turn rendered in a Spindrel
    # channel. The demo replay runtime drives the same TurnEvent bus the real
    # claude-code runtime does, so the capture shows native thinking blocks +
    # tool-call cards + the final reply, not a synthetic mock. Predicate
    # gates on a tool-call badge from the fixture (Read or Grep), the
    # delivered final answer text, and zero in-flight skeleton placeholders.
    ScreenshotSpec(
        name="harness-chat-result",
        route="/channels/{harness_chat}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/READ|GREP/i.test(document.body.innerText)'
            ' && /app\\/main\\.py/.test(document.body.innerText)'
            ' && document.querySelectorAll(\'[class*="bg-skeleton"]\').length === 0'
        ),
        output="harness-chat-result.png",
    ),
]


# ---------------------------------------------------------------------------
# Widget-pin fullscreen captures — `/widgets/pins/<pinId>` is the new
# whole-viewport widget surface and the default mobile path for opening a
# widget from anywhere (channel rail, spatial canvas, mobile hub).
#
# Both shots target the populated Notes pin from the demo dashboard so the
# body has rich markdown rather than a placeholder. Capture-time placeholder
# resolution looks up `screenshot:demo-dashboard`'s pins and grabs the one
# labeled "Notes".
# ---------------------------------------------------------------------------
WIDGET_PIN_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="widget-pin-fullscreen",
        route="/widgets/pins/{notes_pin}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Wait for both the page header ("Collapse to space" CTA appears at
        # ≥lg breakpoint) and the iframe-mounted widget body. The pin's
        # display_label "Notes" lands in the H1 once the pin query resolves.
        wait_arg=(
            '/Notes/.test(document.body.innerText)'
            ' && /Collapse to space|Refresh/i.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
        ),
        # Give the same-origin widget iframe ~1s to paint its markdown body
        # before we shoot — its <iframe> attaches synchronously but the
        # rendered content lands a tick later.
        pre_capture_js="await new Promise(r => setTimeout(r, 1000));",
        output="widget-pin-fullscreen.png",
    ),
    ScreenshotSpec(
        name="widget-pin-fullscreen-mobile",
        route="/widgets/pins/{notes_pin}",
        viewport={"width": 390, "height": 844},
        wait_kind="function",
        # Mobile header drops the "Collapse to space" label (hidden lg:inline)
        # and shows the burger menu instead. Title + back button are stable.
        wait_arg=(
            '/Notes/.test(document.body.innerText)'
            ' && !!document.querySelector(\'button[aria-label="Back"]\')'
        ),
        pre_capture_js="await new Promise(r => setTimeout(r, 1000));",
        output="widget-pin-fullscreen-mobile.png",
    ),
]


# ---------------------------------------------------------------------------
# Mobile hub capture — `/` at iPhone-12-Pro viewport (390x844) renders the
# `MobileHub` component (single-column branch in `useResponsiveColumns`).
# Sections render `null` when empty; staging flagship + attention provides
# Channels + Attention populated, the rest stay empty on the e2e instance.
# ---------------------------------------------------------------------------
MOBILE_HOME_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="mobile-home",
        route="/",
        viewport={"width": 390, "height": 844},
        wait_kind="function",
        # MobileHub renders a "+ New" channel-create CTA in the PageHeader
        # right slot, channel links once `useChannels` resolves, and category
        # group headers (Daily / Home / Work / Showcase) once the
        # ChannelsSection paints.
        wait_arg=(
            '/\\bNew\\b/.test(document.body.innerText)'
            ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
            ' && /Daily|Showcase|Work/i.test(document.body.innerText)'
        ),
        # Allow attention items + sections to settle.
        pre_capture_js="await new Promise(r => setTimeout(r, 800));",
        output="mobile-home.png",
    ),
]


# ---------------------------------------------------------------------------
# Starboard panel — the slide-in right rail on the spatial canvas. Starboard is
# the object inspector; decisions and run logs live in Mission Control Review.
# The panel is local component state, so the capture opens it with the toolbar.
# ---------------------------------------------------------------------------
STARBOARD_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="starboard-object-inspector",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(\'button[title="Open Starboard"]\')'
            ' && !!document.querySelector(\'[data-spatial-canvas="true"]\')'
        ),
        pre_capture_js=(
            "const btn = document.querySelector('button[title=\"Open Starboard\"]');"
            " if (btn) btn.click();"
            # Panel slide-in + object-inspector render.
            " const t0 = Date.now();"
            " while (Date.now() - t0 < 4000) {"
            "   if (document.querySelector('[data-starboard-panel=\"true\"]')"
            "       && document.querySelector('[data-testid=\"starboard-map-brief\"]')) break;"
            "   await new Promise(r => setTimeout(r, 100));"
            " }"
            " await new Promise(r => setTimeout(r, 600));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "if (!document.querySelector('[data-starboard-panel=\"true\"]')) throw new Error('Starboard panel did not open');"
            "if (!document.querySelector('[data-testid=\"starboard-map-brief\"]')) throw new Error('Starboard object inspector missing');"
            "if (!text.includes('Object inspector')) throw new Error('Starboard did not identify itself as an object inspector');"
            "if (text.includes('Mission Control') || text.includes('Daily Health') || text.includes('Context Bloat')) throw new Error('legacy Starboard station content is visible');"
        ),
        output="starboard-object-inspector.png",
        color_scheme="dark",
        extra_init_scripts=[
            "(() => { localStorage.setItem('spatial.starboard.width', '600'); })();",
            # Frame the camera the same as spatial-overview-1 so the
            # constellation reads in the background behind the panel.
            _spatial_camera_init({"x": 720, "y": 450, "scale": 0.7}),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Notifications captures — the admin-only ``/admin/notifications`` page is
# the in-use surface for this feature (there is no per-channel chat path).
# Pre-seed three channel targets + a group + a delivery-history row via the
# admin API before running this capture so the page shows populated state.
# ---------------------------------------------------------------------------
NOTIFICATIONS_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="notifications-overview",
        route="/admin/notifications",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '/Reusable targets|Create a notification target|Targets/.test(document.body.innerText)'
        ),
        # Let target rows + delivery-history fetch settle.
        pre_capture_js="await new Promise(r => setTimeout(r, 600));",
        output="notifications-overview.png",
    ),
]


# ---------------------------------------------------------------------------
# Attention Beacons captures — the spatial canvas with active beacons
# attached to channel tiles. Beacons are seeded via
# ``stage_attention`` (POSTs against ``/workspace/attention``) on top of the
# spatial scenario's existing channels.
# ---------------------------------------------------------------------------
ATTENTION_SPECS: list[ScreenshotSpec] = [
    # Canvas-level shot: zoom out enough that several channel tiles are in
    # frame, with the warning/error AlertTriangle badges visible at the
    # tile corners. Predicate gates on at least one badge + the canvas
    # being mounted.
    ScreenshotSpec(
        name="attention-canvas",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(\'[data-spatial-canvas="true"]\')'
            ' && document.querySelectorAll(\'[data-tile-kind="channel"]\').length >= 4'
        ),
        # Allow time for the 15s-interval attention items query to settle
        # AFTER the canvas mounts. Channels paint in <1s; attention items
        # land via React Query on first fetch, but the badge-stack render is
        # gated on `nodes` AND `attentionItems` both being populated.
        pre_capture_js="await new Promise(r => setTimeout(r, 2500));",
        output="attention-canvas.png",
        color_scheme="dark",
        extra_init_scripts=[
            # Mid-zoom (~0.55) panned upper-left, same framing as
            # spatial-zoom-out-01 — channels are large enough that beacon
            # badges read clearly in the corner.
            _spatial_camera_init({"x": 920, "y": 650, "scale": 0.55}),
        ],
    ),
    # Hub drawer: clicks the canvas-edge "Open Attention Hub" landmark button
    # (rendered at world (0, -650)) to open the drawer, then captures. Predicate
    # gates on the button being mounted; pre_capture_js does the click + waits.
    ScreenshotSpec(
        name="attention-hub",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(\'button[title="Open Attention Hub"]\')'
        ),
        pre_capture_js=(
            "const btn = document.querySelector('button[title=\"Open Attention Hub\"]');"
            " if (btn) btn.click();"
            " await new Promise(r => setTimeout(r, 1200));"
        ),
        output="attention-hub.png",
        color_scheme="dark",
        extra_init_scripts=[
            # Camera centered on world (0, -100) at scale 0.7 — keeps the
            # constellation visible in the background while the drawer slides
            # in from the right.
            _spatial_camera_init({"x": 720, "y": 380, "scale": 0.7}),
        ],
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
            elif js == "CHANNEL_SESSION_TABS_INIT":
                channel_id = staged.get("channel_session_tabs")
                latest_session_id = staged.get("session_tabs_latest")
                older_session_id = staged.get("session_tabs_older")
                if not channel_id or not latest_session_id or not older_session_id:
                    raise KeyError(
                        f"spec {s.name!r} needs channel_session_tabs/session_tabs_latest/session_tabs_older in staged state"
                    )
                init_scripts.append(
                    _channel_session_tabs_init_script(channel_id, latest_session_id, older_session_id)
                )
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
                assert_js=s.assert_js,
                extra_init_scripts=init_scripts,
                full_page=s.full_page,
                actions=list(s.actions),
            )
        )
    return out
