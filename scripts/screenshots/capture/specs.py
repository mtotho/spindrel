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


# Wait predicate shared across all spatial specs: canvas mounted + at least
# four channel tiles painted (channels render as ``<a href="/channels/UUID">``
# both in the sidebar and as canvas tile labels). A higher floor than four
# would race against phyllotaxis seeding on the first run.
_SPATIAL_READY = (
    '!!document.querySelector(\'[data-spatial-canvas="true"]\')'
    ' && document.querySelectorAll(\'a[href^="/channels/"]\').length >= 4'
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
        wait_arg=_SPATIAL_READY,
        output="spatial-blackhole.png",
        color_scheme="dark",
        extra_init_scripts=[
            _spatial_camera_init({"x": 720, "y": -1420, "scale": 0.85}),
        ],
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
