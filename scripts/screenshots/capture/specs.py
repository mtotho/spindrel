"""Flagship-8 capture specs.

Each spec carries its own readiness strategy; silent ``sleep`` is banned so
flake is visible. Routes use format-string substitution against a
``StagedState`` dict keyed on channel/task labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


WaitKind = Literal["selector", "function", "network_idle", "pin_count"]
ActionKind = Literal["click", "dblclick", "fill", "type", "press", "select", "wait", "wait_for"]


@dataclass
class Action:
    """A single pre-capture interaction. Runs after nav+ready, before screenshot.

    Shape per kind:
      - click:     selector required; clicks the first match
      - dblclick:  selector required; double-clicks the first match
      - fill:      selector + value; clears and types value into an input
      - type:      selector + value; sends keyboard text without clearing
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
            'document.querySelectorAll(\'[data-testid="home-recent-session-row"]\').length >= 4'
            ' && document.querySelectorAll(\'[data-testid="home-user-row"]\').length >= 2'
            ' && !!document.querySelector(\'[data-testid="home-users-section"]\')'
            ' && !!document.querySelector(\'[data-testid="home-unread-center"]\')'
            ' && !!document.querySelector(\'[data-testid="home-action-inbox"]\')'
            ' && /Action Inbox/i.test(document.body.innerText)'
        ),
        output="home.png",
        extra_init_scripts=[
            """
(() => {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input?.url;
    if (raw) {
      const url = new URL(raw, window.location.origin);
      if (url.pathname === "/api/v1/projects/review-inbox") {
        return new Response(JSON.stringify({
          generated_at: "2026-05-01T12:00:00Z",
          summary: {
            total: 3,
            needs_attention_count: 2,
            in_flight_count: 1,
            project_count: 1,
            ready_for_review: 1,
            changes_requested: 1,
            follow_up_running: 1,
            follow_up_created: 0,
            missing_evidence: 0,
            reviewing: 0,
            reviewed: 0,
            blocked: 0
          },
          items: [{
            id: "home-project-run-review",
            project_id: "home-project",
            project_name: "Spindrel",
            project_slug: "spindrel",
            task_id: "home-project-run-review",
            title: "Review overnight Project Factory PR",
            branch: "factory/overnight-review",
            state: "ready_for_review",
            status: "completed",
            review_status: "ready_for_review",
            updated_at: "2026-05-01T11:45:00Z",
            evidence: { tests_count: 3, screenshots_count: 2, changed_files_count: 5, dev_targets_count: 1 },
            next_action: "Review the PR, tests, screenshots, and receipt.",
            links: {
              project_url: "/admin/projects/home-project",
              project_runs_url: "/admin/projects/home-project#Runs",
              run_url: "/admin/projects/home-project/runs/home-project-run-review"
            }
          }, {
            id: "home-project-run-changes",
            project_id: "home-project",
            project_name: "Spindrel",
            project_slug: "spindrel",
            task_id: "home-project-run-changes",
            title: "Follow up on intake triage screenshots",
            branch: "factory/intake-follow-up",
            state: "changes_requested",
            status: "completed",
            review_status: "changes_requested",
            updated_at: "2026-05-01T11:30:00Z",
            evidence: { tests_count: 1, screenshots_count: 0, changed_files_count: 2, dev_targets_count: 1 },
            next_action: "Start a follow-up run from reviewer feedback.",
            links: {
              project_url: "/admin/projects/home-project",
              project_runs_url: "/admin/projects/home-project#Runs",
              run_url: "/admin/projects/home-project/runs/home-project-run-changes"
            }
          }]
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.pathname === "/api/v1/workspace/attention/issue-work-packs") {
        return new Response(JSON.stringify({
          work_packs: [{
            id: "home-work-pack-intake-ui",
            title: "Mission Control Review tabs do not switch the list",
            summary: "Review the issue intake navigation and make tab switching reliable.",
            category: "code_bug",
            confidence: "high",
            status: "proposed",
            source_item_ids: ["home-issue-intake-tabs"],
            launch_prompt: "Fix Mission Control Review tab switching and verify with screenshots.",
            project_id: "home-project",
            project_name: "Spindrel",
            channel_id: "home-channel",
            channel_name: "Project factory dogfood",
            launchable: true,
            created_at: "2026-05-01T11:50:00Z",
            updated_at: "2026-05-01T11:50:00Z"
          }]
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
    }
    return originalFetch(input, init);
  };
})();
            """,
        ],
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: /Action Inbox/i.test(text) "
            "&& text.includes('items need a look') "
            "&& text.includes('Issue intake') "
            "&& text.includes('Project reviews'), "
            "detail: 'Home did not surface actionable review inbox attention' };"
        ),
    ),
    ScreenshotSpec(
        name="home-inbox",
        route="/",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            '!!document.querySelector(\'[data-testid="home-action-inbox"]\')'
            ' && /Action Inbox/i.test(document.body.innerText)'
        ),
        output="home-inbox.png",
        color_scheme="dark",
        actions=[
            Action(kind="click", selector='button[title="Inbox"]'),
            Action(kind="wait_for", selector='[data-testid="home-rail-inbox-panel"]'),
        ],
        extra_init_scripts=[
            """
(() => {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input?.url;
    if (raw) {
      const url = new URL(raw, window.location.origin);
      if (url.pathname === "/api/v1/projects/review-inbox") {
        return new Response(JSON.stringify({
          generated_at: "2026-05-01T12:00:00Z",
          summary: {
            total: 3,
            needs_attention_count: 2,
            in_flight_count: 1,
            project_count: 1,
            ready_for_review: 1,
            changes_requested: 1,
            follow_up_running: 1,
            follow_up_created: 0,
            missing_evidence: 0,
            reviewing: 0,
            reviewed: 0,
            blocked: 0
          },
          items: [{
            id: "home-project-run-review",
            project_id: "home-project",
            project_name: "Spindrel",
            project_slug: "spindrel",
            task_id: "home-project-run-review",
            title: "Review overnight Project Factory PR",
            branch: "factory/overnight-review",
            state: "ready_for_review",
            status: "completed",
            review_status: "ready_for_review",
            updated_at: "2026-05-01T11:45:00Z",
            evidence: { tests_count: 3, screenshots_count: 2, changed_files_count: 5, dev_targets_count: 1 },
            next_action: "Review the PR, tests, screenshots, and receipt.",
            links: {
              project_url: "/admin/projects/home-project",
              project_runs_url: "/admin/projects/home-project#Runs",
              run_url: "/admin/projects/home-project/runs/home-project-run-review"
            }
          }, {
            id: "home-project-run-changes",
            project_id: "home-project",
            project_name: "Spindrel",
            project_slug: "spindrel",
            task_id: "home-project-run-changes",
            title: "Follow up on intake triage screenshots",
            branch: "factory/intake-follow-up",
            state: "changes_requested",
            status: "completed",
            review_status: "changes_requested",
            updated_at: "2026-05-01T11:30:00Z",
            evidence: { tests_count: 1, screenshots_count: 0, changed_files_count: 2, dev_targets_count: 1 },
            next_action: "Start a follow-up run from reviewer feedback.",
            links: {
              project_url: "/admin/projects/home-project",
              project_runs_url: "/admin/projects/home-project#Runs",
              run_url: "/admin/projects/home-project/runs/home-project-changes"
            }
          }]
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.pathname === "/api/v1/workspace/attention/issue-work-packs") {
        return new Response(JSON.stringify({
          work_packs: [{
            id: "home-work-pack-intake-ui",
            title: "Mission Control Review tabs do not switch the list",
            summary: "Review the issue intake navigation and make tab switching reliable.",
            category: "code_bug",
            confidence: "high",
            status: "proposed",
            source_item_ids: ["home-issue-intake-tabs"],
            launch_prompt: "Fix Mission Control Review tab switching and verify with screenshots.",
            project_id: "home-project",
            project_name: "Spindrel",
            channel_id: "home-channel",
            channel_name: "Project factory dogfood",
            launchable: true,
            created_at: "2026-05-01T11:50:00Z",
            updated_at: "2026-05-01T11:50:00Z"
          }]
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
    }
    return originalFetch(input, init);
  };
})();
            """,
        ],
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: !!document.querySelector('[data-testid=\"home-rail-inbox-panel\"]') "
            "&& /Ready for review/i.test(text) "
            "&& text.includes('Project reviews') "
            "&& text.includes('Issue intake') "
            "&& /Unread replies/i.test(text), "
            "detail: 'Home Inbox panel did not group review-ready work and unread replies' };"
        ),
    ),
    ScreenshotSpec(
        name="chat-main",
        route="/channels/{chat_main}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        # Chat widgets now live behind the left workbench, so the main chat
        # capture gates on the transcript/header, not mounted pin count.
        wait_arg=(
            'document.querySelectorAll(\'[class*="bg-skeleton"]\').length === 0 '
            '&& document.body.innerText.includes("Evening check-in") '
            '&& document.body.innerText.length > 600'
        ),
        output="chat-main.png",
        assert_js=(
            "if (!document.querySelector('[aria-label=\"More actions\"]')) throw new Error('channel header overflow menu missing');"
            "if (document.querySelector('[aria-label=\"Beam to spatial canvas\"]')) throw new Error('spatial action should live in overflow, not header chrome');"
            "if (document.querySelector('[aria-label=\"Switch to dashboard view\"]')) throw new Error('dashboard action should live in overflow, not header chrome');"
            "if (document.querySelector('[aria-label=\"Open right dock\"]')) throw new Error('right widget dock should not surface in chat');"
        ),
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
        assert_js=(
            "const text = document.body.innerText;"
            "if (!text.includes('Pinned widgets')) throw new Error('mobile workbench did not show unified widget section');"
            "if (/\\bRail\\b|\\bDock\\b|Chips shown above the chat/.test(text)) throw new Error('mobile drawer leaked desktop widget-zone language');"
        ),
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
    "if (!/(Review finding|Review item|Review signal)/.test(selected.textContent || '')) throw new Error('selected brief does not expose the review action');"
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

_ATTENTION_REVIEW_DECK_ENDPOINT_INIT = """
(() => {
  const originalFetch = window.fetch.bind(window);
  const now = "2026-04-29T14:14:00Z";
  const baseItem = (id, title, message, status, evidence, severity = "critical", target = "Gardening With Sprout") => ({
    id,
    source_type: evidence?.report_issue ? "bot" : "system",
    source_id: evidence?.report_issue ? "Sprout" : "system",
    channel_id: "00000000-0000-0000-0000-0000000000aa",
    channel_name: target,
    target_kind: "channel",
    target_id: "00000000-0000-0000-0000-0000000000aa",
    target_node_id: "channel:qa",
    dedupe_key: `screenshot:${id}`,
    severity,
    title,
    message,
    next_steps: [],
    requires_response: true,
    status,
    occurrence_count: title === "view_spatial_canvas failed" ? 7 : 1,
    evidence: evidence || {},
    latest_correlation_id: null,
    response_message_id: null,
    assigned_bot_id: null,
    assignment_mode: null,
    assignment_status: evidence?.operator_triage?.state === "running" ? "running" : null,
    assignment_instructions: null,
    assigned_by: null,
    assigned_at: null,
    assignment_task_id: evidence?.operator_triage?.task_id || null,
    assignment_report: evidence?.operator_triage?.summary || null,
    assignment_reported_by: evidence?.operator_triage?.reported_by || null,
    assignment_reported_at: evidence?.operator_triage?.reported_at || null,
    first_seen_at: "2026-04-29T12:01:00Z",
    last_seen_at: now,
    responded_at: status === "responded" ? now : null,
    resolved_at: null
  });
  const reviewOne = baseItem("00000000-0000-0000-0000-000000000101", "view_spatial_canvas failed", "Invalid focus_token.", "responded", {
    kind: "tool_call",
    classification: "platform_contract",
    error_kind: "internal",
    operator_triage: {
      state: "ready_for_review",
      classification: "likely_spindrel_code_issue",
      confidence: "high",
      summary: "Repeated heartbeat failures hit view_spatial_canvas with invalid focus_token across seven occurrences.",
      suggested_action: "Open a code fix to review focus-token lifecycle and add a safe fallback when tokens expire.",
      route: "code_fix",
      review_required: true,
      reported_by: "operator",
      reported_at: now
    }
  });
  const reviewTwo = baseItem("00000000-0000-0000-0000-000000000102", "pin_spatial_widget failed", "Bot has no API permissions for interactive widgets.", "responded", {
    kind: "tool_call",
    classification: "permission_contract",
    operator_triage: {
      state: "ready_for_review",
      classification: "user_decision",
      confidence: "high",
      summary: "Sprout tried to pin an interactive widget, but the bot lacks API permissions.",
      suggested_action: "Decide whether this bot should receive scoped widget permissions.",
      route: "owner_follow_up",
      review_required: true,
      reported_by: "operator",
      reported_at: now
    }
  });
  const inboxOne = baseItem("00000000-0000-0000-0000-000000000201", "search_memory failed", "Decimal is not JSON serializable.", "open", {
    kind: "tool_call",
    classification: "platform_contract",
    error_kind: "internal"
  }, "error", "Codex - E2E");
  const inboxTwo = baseItem("00000000-0000-0000-0000-000000000202", "Heartbeat failed", "Recovered: stuck running for 1203s.", "open", {
    kind: "heartbeat",
    classification: "retryable_contract"
  }, "warning");
  const issueOne = baseItem("00000000-0000-0000-0000-000000000203", "Project Runs hides merge evidence", "When a review session launches, the run row does not frame the merge receipt clearly.", "open", {
    issue_intake: {
      reported_by: "codex",
      reported_at: now,
      category_hint: "quality",
      project_hint: "Spindrel",
      tags: ["project-runs", "review"],
      observed_behavior: "Merge receipt is below the visible row.",
      expected_behavior: "The cockpit should frame launch and merge evidence.",
      steps: ["Open Mission Control Review", "Launch a review work pack"],
      source: "conversation"
    }
  }, "warning", "Spindrel Development");
  const issueTwo = baseItem("00000000-0000-0000-0000-000000000204", "Codex task could not run e2e screenshots", "The task reported missing e2e target access.", "open", {
    report_issue: {
      category: "blocked",
      suggested_action: "Grant a task-scoped e2e target before launching.",
      reported_by: "codex",
      reported_at: now,
      task_id: "00000000-0000-0000-0000-000000000901",
      origin: "project_coding_run"
    }
  }, "error", "Spindrel Development");
  const runningOne = baseItem("00000000-0000-0000-0000-000000000301", "radarr_releases failed", "Operator is classifying repeated HTTP 500s.", "responded", {
    kind: "tool_call",
    operator_triage: {
      state: "running",
      task_id: "00000000-0000-0000-0000-000000000501",
      session_id: "00000000-0000-0000-0000-000000000601",
      parent_channel_id: "00000000-0000-0000-0000-000000000701",
      operator_bot_id: "operator",
      reported_by: "operator"
    }
  }, "critical", "jellyfin-support");
  const clearedOne = baseItem("00000000-0000-0000-0000-000000000401", "get_tool_info failed", "Duplicate setup probe; no human action needed.", "acknowledged", {
    kind: "tool_call",
    operator_triage: {
      state: "processed",
      classification: "duplicate_or_noise",
      confidence: "high",
      summary: "Duplicate setup probe already covered by the primary finding.",
      suggested_action: "No action needed.",
      route: "can_ignore",
      review_required: false,
      reported_by: "operator",
      reported_at: now
    }
  }, "warning", "Baking With Crumb");
  const clearedTwo = baseItem("00000000-0000-0000-0000-000000000402", "Trace error", "Expected transient trace while staging the screenshot scenario.", "acknowledged", {
    kind: "trace",
    operator_triage: {
      state: "processed",
      classification: "expected_test_noise",
      confidence: "medium",
      summary: "Expected transient trace from the screenshot fixture.",
      suggested_action: "No action needed.",
      route: "can_ignore",
      review_required: false,
      reported_by: "operator",
      reported_at: now
    }
  }, "info", "Evening check-in");
  const items = [reviewOne, reviewTwo, issueOne, issueTwo, inboxOne, inboxTwo, runningOne, clearedOne, clearedTwo];
  const workPacks = [
    {
      id: "00000000-0000-0000-0000-000000000801",
      title: "Improve Project review evidence framing",
      summary: "Conversational intake and agent blocker reports both point to the Project review cockpit needing clearer launch and merge evidence.",
      category: "code_bug",
      confidence: "high",
      status: "proposed",
      source_item_ids: [issueOne.id, issueTwo.id],
      launch_prompt: "Fix the Project review cockpit evidence framing and verify with screenshots.",
      triage_task_id: "00000000-0000-0000-0000-000000000501",
      project_id: null,
      project_name: null,
      channel_id: null,
      channel_name: null,
      launched_task_id: null,
      launched_task_status: null,
      source_items: [
        {
          id: issueOne.id,
          title: issueOne.title,
          message: issueOne.message,
          severity: issueOne.severity,
          status: issueOne.status,
          channel_id: issueOne.channel_id,
          channel_name: issueOne.channel_name,
          evidence: issueOne.evidence
        },
        {
          id: issueTwo.id,
          title: issueTwo.title,
          message: issueTwo.message,
          severity: issueTwo.severity,
          status: issueTwo.status,
          channel_id: issueTwo.channel_id,
          channel_name: issueTwo.channel_name,
          evidence: issueTwo.evidence
        }
      ],
      metadata: {
        triage_receipt_id: "issue-triage-receipt:screenshot",
        triage_receipt: {
          id: "issue-triage-receipt:screenshot",
          source: "scheduled_triage",
          summary: "Grouped review evidence issues into launch-ready Project work packs.",
          grouping_rationale: "The selected notes all concern Project Factory review evidence and can be verified together.",
          launch_readiness: "Two packs are launchable after operator review; planning-only items stay out of launch.",
          follow_up_questions: ["Confirm whether the evidence copy should mention screenshots explicitly."],
          excluded_items: ["Future scheduling controls were left for a later track slice."],
          created_at: now
        },
        target_project_hint: "Spindrel",
        target_channel_hint: "Spindrel Development",
        review_actions: [{ action: "edited", actor: "user:operator", at: now, prior_status: "proposed", status: "proposed" }]
      },
      triage_receipt_id: "issue-triage-receipt:screenshot",
      triage_receipt: {
        id: "issue-triage-receipt:screenshot",
        source: "scheduled_triage",
        summary: "Grouped review evidence issues into launch-ready Project work packs.",
        grouping_rationale: "The selected notes all concern Project Factory review evidence and can be verified together.",
        launch_readiness: "Two packs are launchable after operator review; planning-only items stay out of launch.",
        follow_up_questions: ["Confirm whether the evidence copy should mention screenshots explicitly."],
        excluded_items: ["Future scheduling controls were left for a later track slice."],
        created_at: now
      },
      latest_review_action: { action: "edited", actor: "user:operator", at: now, prior_status: "proposed", status: "proposed" },
      created_at: now,
      updated_at: now
    },
    {
      id: "00000000-0000-0000-0000-000000000802",
      title: "Add batch launch proof for overnight packs",
      summary: "A second reviewed code pack is ready so the operator can launch multiple Project runs together.",
      category: "code_bug",
      confidence: "medium",
      status: "proposed",
      source_item_ids: [issueOne.id],
      launch_prompt: "Add batch launch proof for overnight work packs and verify with screenshots.",
      triage_task_id: "00000000-0000-0000-0000-000000000501",
      project_id: null,
      project_name: null,
      channel_id: null,
      channel_name: null,
      launched_task_id: null,
      launched_task_status: null,
      source_items: [{
        id: issueOne.id,
        title: issueOne.title,
        message: issueOne.message,
        severity: issueOne.severity,
        status: issueOne.status,
        channel_id: issueOne.channel_id,
        channel_name: issueOne.channel_name,
        evidence: issueOne.evidence
      }],
      metadata: {
        triage_receipt_id: "issue-triage-receipt:screenshot",
        triage_receipt: {
          id: "issue-triage-receipt:screenshot",
          source: "scheduled_triage",
          summary: "Grouped review evidence issues into launch-ready Project work packs.",
          grouping_rationale: "The selected notes all concern Project Factory review evidence and can be verified together.",
          launch_readiness: "Two packs are launchable after operator review; planning-only items stay out of launch.",
          follow_up_questions: ["Confirm whether the evidence copy should mention screenshots explicitly."],
          excluded_items: ["Future scheduling controls were left for a later track slice."],
          created_at: now
        },
        target_project_hint: "Spindrel",
        target_channel_hint: "Spindrel Development",
        review_actions: [{ action: "edited", actor: "user:operator", at: now, prior_status: "proposed", status: "proposed" }]
      },
      triage_receipt_id: "issue-triage-receipt:screenshot",
      triage_receipt: {
        id: "issue-triage-receipt:screenshot",
        source: "scheduled_triage",
        summary: "Grouped review evidence issues into launch-ready Project work packs.",
        grouping_rationale: "The selected notes all concern Project Factory review evidence and can be verified together.",
        launch_readiness: "Two packs are launchable after operator review; planning-only items stay out of launch.",
        follow_up_questions: ["Confirm whether the evidence copy should mention screenshots explicitly."],
        excluded_items: ["Future scheduling controls were left for a later track slice."],
        created_at: now
      },
      latest_review_action: { action: "edited", actor: "user:operator", at: now, prior_status: "proposed", status: "proposed" },
      created_at: now,
      updated_at: now
    }
  ];
  const runs = [{
    task_id: "00000000-0000-0000-0000-000000000501",
    run_kind: "attention_triage",
    session_id: null,
    parent_channel_id: null,
    bot_id: "operator",
    status: "complete",
    task_status: "completed",
    item_count: items.length,
    counts: { total: items.length, running: 1, processed: 2, ready_for_review: 2, failed: 0, unreported: 2 },
    items,
    model_override: null,
    model_provider_id_override: null,
    effective_model: "gpt-5.4",
    created_at: now,
    completed_at: now,
    error: null
  }];
  const issueTriageRuns = [{
    task_id: "00000000-0000-0000-0000-000000000601",
    run_kind: "issue_intake_triage",
    session_id: "00000000-0000-0000-0000-000000000602",
    parent_channel_id: "channel-ops",
    bot_id: "operator",
    status: "complete",
    task_status: "complete",
    item_count: 2,
    counts: { total: 2, running: 0, processed: 2, ready_for_review: 0, failed: 0, unreported: 0 },
    items: [issueOne, issueTwo],
    work_pack_count: 2,
    work_packs: workPacks,
    model_override: null,
    model_provider_id_override: null,
    effective_model: "gpt-5.4",
    created_at: now,
    completed_at: now,
    error: null
  }];
  const brief = {
    generated_at: now,
    summary: { autofix: 0, blockers: 0, fix_packs: 1, decisions: 1, quiet: 2, running: 1, cleared: 2, total: items.length },
    next_action: {
      kind: "open_item",
      title: "Review the spatial canvas finding",
      description: "Operator grouped repeated focus-token failures into one code-fix decision.",
      action_label: "Open finding",
      item_id: reviewOne.id,
      fix_pack_id: null
    },
    blockers: [],
    fix_packs: [{
      id: "fix-spatial-focus-token",
      title: "Fix focus-token recovery",
      summary: "Repeated map reads are failing after stale focus tokens.",
      count: 1,
      severity: "critical",
      target_summary: "Gardening With Sprout",
      item_ids: [reviewOne.id],
      prompt: "Fix stale focus-token handling in the spatial canvas flow.",
      action_label: "Open evidence",
      action: { type: "open_item", item_id: reviewOne.id }
    }],
    decisions: [{
      id: "decision-widget-permissions",
      kind: "decision",
      title: "Widget permission decision",
      summary: "Sprout needs explicit scoped API permission before it can pin interactive widgets.",
      severity: "warning",
      target_label: "Gardening With Sprout",
      item_ids: [reviewTwo.id],
      action_label: "Make decision",
      action: { type: "open_item", item_id: reviewTwo.id }
    }],
    autofix_queue: [],
    quiet_digest: { count: 2, groups: [{ label: "Duplicate setup probes", count: 2 }] },
    running: [runningOne],
    cleared: [clearedOne, clearedTwo]
  };
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input?.url;
    if (raw) {
      const url = new URL(raw, window.location.origin);
      if (url.pathname === "/api/v1/workspace/attention/triage-runs") {
        return new Response(JSON.stringify({ runs }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.pathname === "/api/v1/workspace/attention/issue-triage-runs") {
        return new Response(JSON.stringify({ runs: issueTriageRuns }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.pathname === "/api/v1/workspace/attention/brief") {
        return new Response(JSON.stringify(brief), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.pathname === "/api/v1/workspace/attention/issue-work-packs") {
        return new Response(JSON.stringify({ work_packs: workPacks }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.pathname === "/api/v1/projects") {
        return new Response(JSON.stringify([{ id: "project-1", name: "Spindrel", slug: "spindrel", root_path: "common/projects/spindrel", workspace_id: "workspace-1", created_at: now, updated_at: now }]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.pathname === "/api/v1/projects/project-1/channels") {
        return new Response(JSON.stringify([{ id: "channel-dev", name: "Spindrel Development", bot_id: "codex" }]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.pathname === "/api/v1/workspace/attention") {
        return new Response(JSON.stringify({ items }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
    }
    return originalFetch(input, init);
  };
})();
"""


SPATIAL_CHECK_SPECS: list[ScreenshotSpec] = [
    ScreenshotSpec(
        name="spatial-check-map-brief-selection",
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
        route="/hub/attention?mode=review&item=00000000-0000-0000-0000-000000000101",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "document.body.innerText.includes('Mission Control Review')"
            " && document.body.innerText.includes('Open a code fix')"
            " && document.body.innerText.includes('view_spatial_canvas failed')"
        ),
        output="spatial-check-attention-review-deck.png",
        color_scheme="dark",
        extra_init_scripts=[_ATTENTION_REVIEW_DECK_ENDPOINT_INIT],
        assert_js=(
            "const text = document.body.innerText;"
            "const lower = `${document.body.innerText} ${document.body.textContent || ''}`.toLowerCase();"
            "if (!text.includes('Findings') || !text.includes('Unreviewed') || !text.includes('Sweeps') || !text.includes('Cleared')) throw new Error('review deck queue chips missing');"
            "if (document.querySelector('[data-testid=\"attention-command-deck-what-now\"]')) throw new Error('selected review item should own focus without global what-now lane');"
            "if (!text.includes('view_spatial_canvas failed') || !text.includes('pin_spatial_widget failed')) throw new Error('review deck did not render seeded operator findings');"
            "if (!lower.includes('operator finding') || !lower.includes('open a code fix')) throw new Error('selected finding detail missing useful action language');"
            "if (lower.includes('watch the active sweep')) throw new Error('active sweep prompt competes with selected finding');"
            "if (text.includes('Reviewing now')) throw new Error('stale reviewing-now copy is visible');"
            "if (text.includes('Open in Attention') || text.includes('Open deck')) throw new Error('legacy attention launcher copy is visible');"
            "if (text.includes('Raw signal') || text.includes('raw signal') || text.includes('Next best click')) throw new Error('legacy review language is visible');"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-issue-intake-work-packs",
        route="/hub/attention?mode=issues",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "(() => {"
            "const text = document.body.innerText;"
            "const lower = text.toLowerCase();"
            "return !!document.querySelector('[data-testid=\"issue-intake-workspace\"]')"
            " && !!document.querySelector('[data-testid=\"issue-triage-runs-panel\"]')"
            " && text.includes('Improve Project review evidence framing')"
            " && lower.includes('triage receipt')"
            " && text.includes('Grouped review evidence issues')"
            " && text.includes('Spindrel Development');"
            "})()"
        ),
        output="spatial-check-issue-intake-work-packs.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[_ATTENTION_REVIEW_DECK_ENDPOINT_INIT],
        pre_capture_js=(
            "const selectLaunchable = [...document.querySelectorAll('button')].find((button) => button.textContent?.includes('Select launchable'));"
            "if (!selectLaunchable) throw new Error('Select launchable button missing before issue work-pack capture');"
            "selectLaunchable.click();"
            "await new Promise((resolve) => setTimeout(resolve, 200));"
            "const review = [...document.querySelectorAll('button')].find((button) => button.textContent?.includes('Review'));"
            "if (!review) throw new Error('Review button missing before issue work-pack capture');"
            "review.click();"
            "await new Promise((resolve) => setTimeout(resolve, 200));"
            "const dismiss = [...document.querySelectorAll('button')].find((button) => button.textContent?.includes('Dismiss'));"
            "if (!dismiss) throw new Error('Dismiss button missing after opening issue work-pack review');"
            "await new Promise((resolve) => setTimeout(resolve, 400));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "const lower = text.toLowerCase();"
            "if (!lower.includes('issue intake') || !text.includes('Start issue triage')) throw new Error('issue intake lane missing');"
            "if (!text.includes('Project Runs hides merge evidence') || !text.includes('Codex task could not run e2e screenshots')) throw new Error('raw issue intake missing');"
            "if (!text.includes('Improve Project review evidence framing')) throw new Error('work pack missing');"
            "if (!text.includes('Add batch launch proof for overnight packs') || !text.includes('Launch selected (2)')) throw new Error('batch work-pack launch controls missing');"
            "if (!text.includes('Spindrel Development') || !text.includes('Launch')) throw new Error('Project launch target controls missing');"
            "if (!text.includes('Review work pack') || !text.includes('Needs info') || !text.includes('Dismiss')) throw new Error('work-pack review controls missing');"
            "if (!lower.includes('last review: edited')) throw new Error('work-pack review provenance missing');"
            "if (text.includes('No work packs yet')) throw new Error('work pack empty state rendered with seeded pack');"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-attention-run-log",
        route="/hub/attention?mode=runs",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"attention-run-workspace\"]')"
            " && document.body.innerText.toLowerCase().includes('sweep history')"
            " && document.body.innerText.toLowerCase().includes('sweep receipt')"
        ),
        output="spatial-check-attention-run-log.png",
        color_scheme="dark",
        extra_init_scripts=[_ATTENTION_REVIEW_DECK_ENDPOINT_INIT],
        assert_js=(
            "const text = document.body.innerText;"
            "const lower = text.toLowerCase();"
            "if (document.querySelector('[data-testid=\"attention-command-deck-what-now\"]')) throw new Error('run mode should not show the global what-now lane');"
            "if (!lower.includes('sweep history')) throw new Error('sweep history rail missing');"
            "if (!lower.includes('sweep receipt')) throw new Error('selected sweep receipt is not the primary detail');"
            "if (!lower.includes('operator sweep') || !lower.includes('ready for review') || !lower.includes('cleared by operator')) throw new Error('run receipt did not render seeded review/cleared groups');"
            "if (lower.includes('no operator sweeps yet') || lower.includes('start a sweep to create a receipt')) throw new Error('run log rendered empty state with seeded run data');"
            "if (lower.includes('check cleared receipts')) throw new Error('run mode is competing with cleared-receipt CTA');"
            "if (text.includes('Transcript') && !text.includes('Transcript evidence')) throw new Error('transcript disclosure does not use evidence copy');"
        ),
    ),
    ScreenshotSpec(
        name="spatial-check-density-smoke",
        route="/spatial",
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
# Channel widget-usefulness fixes — validates the human-facing usefulness
# fix surface on channel dashboards and channel settings.
# ---------------------------------------------------------------------------

_WIDGET_USEFULNESS_READY = (
    "!!document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]') "
    "&& /fix/i.test(document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]')?.textContent || '')"
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
    "await waitFor(() => document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]'), 'widget fix trigger');"
    "const button = document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]');"
    "if (!button) throw new Error('widget fix button missing');"
    "button.click();"
    "await waitFor(() => document.querySelector('[data-testid=\"widget-usefulness-review-drawer\"]'), 'review drawer');"
)

_ASSERT_WIDGET_USEFULNESS_STRIP_JS = (
    "const trigger = document.querySelector('[data-testid=\"widget-usefulness-review-trigger\"]');"
    "if (!trigger) throw new Error('widget fix trigger missing');"
    "const text = document.body.innerText || trigger.textContent || '';"
    "if (!/2 widget fixes|widget fixes/i.test(text)) throw new Error('widget fix trigger count missing');"
    "if (document.querySelector('[data-testid=\"widget-usefulness-review-strip\"]')) throw new Error('persistent review strip should not render');"
)

_ASSERT_WIDGET_USEFULNESS_DRAWER_JS = (
    "const drawer = document.querySelector('[data-testid=\"widget-usefulness-review-drawer\"]');"
    "if (!drawer) throw new Error('review drawer missing');"
    "const text = drawer.textContent || '';"
    "if (!/Widget fixes/.test(text)) throw new Error('drawer title missing');"
    "if (!/Recent bot widget activity|widget authoring/i.test(text)) throw new Error('bot widget activity receipts missing');"
    "if (!/Remove 1 duplicate|Move to rail|Focus pin|Edit layout/.test(text)) throw new Error('one-click fix controls missing');"
    "if (document.querySelectorAll('[data-testid=\"widget-usefulness-finding\"]').length < 1) throw new Error('widget fixes missing');"
)

_WIDGET_USEFULNESS_ENDPOINT_INIT = """
(() => {
  const originalFetch = window.fetch.bind(window);
  const assessment = {
    channel_id: "screenshot-channel",
    channel_name: "Widget usefulness review",
    dashboard_key: "channel:screenshot-channel",
    status: "needs_attention",
    summary: "2 one-click widget fix(es): 2 pinned widgets appear to overlap in purpose.",
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
        suggested_next_action: "Keep Usefulness notes and remove duplicate pins: Usefulness notes copy.",
        requires_policy_decision: false,
        proposal_id: "remove_duplicate_pins:screenshot-pin-notes-screenshot-pin-notes-copy",
        apply: {
          id: "remove_duplicate_pins:screenshot-pin-notes-screenshot-pin-notes-copy",
          action: "remove_duplicate_pins",
          label: "Remove 1 duplicate",
          description: "Keep Usefulness notes and remove duplicate pins: Usefulness notes copy.",
          impact: "Removes duplicate dashboard pins only; widget bundle/source files are left untouched.",
          keep_pin_id: "screenshot-pin-notes",
          remove_pin_ids: ["screenshot-pin-notes-copy"]
        },
        evidence: { pin_ids: ["screenshot-pin-notes", "screenshot-pin-notes-copy"], labels: ["Usefulness notes", "Usefulness notes copy"], keep_pin_id: "screenshot-pin-notes", remove_pin_ids: ["screenshot-pin-notes-copy"] }
      },
      {
        type: "visibility",
        severity: "medium",
        surface: "chat",
        pin_id: "screenshot-pin-dock",
        label: "Usefulness dock panel",
        reason: "Pin is in the dock zone, but channel layout mode 'rail-chat' hides that zone in chat.",
        suggested_next_action: "Move Usefulness dock panel from dock to rail so it appears in chat.",
        requires_policy_decision: false,
        proposal_id: "move_pin_to_visible_zone:screenshot-pin-dock-rail",
        apply: {
          id: "move_pin_to_visible_zone:screenshot-pin-dock-rail",
          action: "move_pin_to_visible_zone",
          label: "Move to rail",
          description: "Move Usefulness dock panel from dock to rail so it appears in chat.",
          impact: "Changes this pin's dashboard zone and keeps its existing size where possible.",
          pin_id: "screenshot-pin-dock",
          from_zone: "dock",
          to_zone: "rail"
        },
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
    ],
    findings: []
  };
  const receipts = {
    receipts: [
      {
        id: "receipt-authoring-1",
        kind: "authoring",
        channel_id: "screenshot-channel",
        dashboard_key: "channel:screenshot-channel",
        action: "authoring_checked",
        summary: "Checked the project status widget in the runtime host and kept the existing pin.",
        reason: "The widget was recently edited, so the bot verified it before relying on the dashboard.",
        bot_id: "widget-health-bot",
        session_id: null,
        correlation_id: "00000000-0000-4000-8000-000000000002",
        task_id: null,
        affected_pin_ids: ["screenshot-pin-notes"],
        before_state: {},
        after_state: {},
        metadata: {
          kind: "authoring",
          library_ref: "workspace/project_status",
          touched_files: ["widget://workspace/project_status/index.html"],
          health_status: "healthy",
          health_summary: "Runtime smoke check rendered the widget with no browser errors.",
          check_phases: [{ name: "runtime", ok: true }]
        },
        created_at: "2026-04-29T17:44:00Z"
      },
      {
        id: "receipt-1",
        kind: "agency",
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

_AGENT_WIDGET_AUTHORING_ENDPOINT_INIT = """
(() => {
  const originalFetch = window.fetch.bind(window);
  const manifest = {
    schema_version: "2026-04-29",
    context: {
      bot_id: "widget-health-bot",
      bot_name: "Widget Health Bot",
      channel_id: "screenshot-channel",
      channel_name: "Widget usefulness proposals"
    },
    api: { scopes: ["read:channels", "read:widgets", "write:widgets"], endpoint_count: 142 },
    tools: {
      catalog_count: 96,
      working_set_count: 18,
      configured: ["prepare_widget_authoring", "file", "check_html_widget_authoring", "preview_widget", "emit_html_widget", "pin_widget", "check_widget", "publish_widget_authoring_receipt"],
      pinned: [],
      enrolled: [],
      profiles: {},
      safety_tiers: {},
      recommended_core: ["prepare_widget_authoring", "file", "check_html_widget_authoring", "preview_widget", "emit_html_widget", "pin_widget", "check_widget", "publish_widget_authoring_receipt"],
      details: [],
      details_truncated: false
    },
    skills: {
      working_set_count: 3,
      bot_enrolled: [{ id: "widgets", name: "Widgets", source: "file", scope: "bot" }],
      channel_enrolled: [
        { id: "widgets/html", name: "HTML widgets", source: "file", scope: "channel" },
        { id: "widgets/authoring_runs", name: "Widget Authoring Runs", source: "file", scope: "channel" }
      ]
    },
    project: {
      attached: true,
      id: "widget-authoring-project",
      name: "Widget Authoring",
      root_path: "/workspace/widgets",
      runtime_env: { ready: true, missing_secrets: [], invalid_env_keys: [], reserved_env_keys: [] }
    },
    harness: { runtime: "codex", workdir: "/workspace/widgets", bridge_status: "connected" },
    widgets: {
      authoring_tools: ["prepare_widget_authoring", "file", "check_html_widget_authoring", "check_widget_authoring", "preview_widget", "emit_html_widget", "pin_widget", "check_widget", "publish_widget_authoring_receipt"],
      required_authoring_tools: ["prepare_widget_authoring", "file", "check_html_widget_authoring", "check_widget_authoring", "preview_widget", "emit_html_widget", "pin_widget", "check_widget", "publish_widget_authoring_receipt"],
      missing_authoring_tools: [],
      recommended_skills: ["widgets", "widgets/html", "widgets/sdk", "widgets/authoring_runs"],
      available_skills: ["widgets", "widgets/html", "widgets/sdk", "widgets/authoring_runs"],
      missing_skills: [],
      health_loop: "available",
      html_authoring_check: "available",
      tool_widget_authoring_check: "available",
      authoring_flow: ["prepare_widget_authoring", "preview_widget", "check_html_widget_authoring", "emit_html_widget", "pin_widget", "check_widget", "publish_widget_authoring_receipt"],
      readiness: "ready",
      findings: []
    },
    doctor: { status: "ok", findings: [] }
  };
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input?.url;
    if (raw) {
      const url = new URL(raw, window.location.origin);
      if (url.pathname === "/api/v1/agent-capabilities") {
        return new Response(JSON.stringify(manifest), {
          status: 200,
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
            "if (!/pins|one-click fixes|layout|propose \\+ fix/.test(text)) throw new Error('settings usefulness metrics missing');"
            "if (!/widget authoring|Checked the project status widget/.test(text)) throw new Error('settings receipt summary missing');"
        ),
    ),
    ScreenshotSpec(
        name="channel-widget-authoring-readiness",
        route="/channels/{channel_widget_usefulness}/settings#agent",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"agent-readiness-widget-authoring\"]') "
            "&& /Widget authoring ready/.test(document.body.innerText)"
        ),
        output="channel-widget-authoring-readiness.png",
        color_scheme="dark",
        extra_init_scripts=[_AGENT_WIDGET_AUTHORING_ENDPOINT_INIT],
        pre_capture_js=(
            "const row = document.querySelector('[data-testid=\"agent-readiness-widget-authoring\"]');"
            "if (row) row.scrollIntoView({ block: 'center', inline: 'nearest' });"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
        ),
        assert_js=(
            "const row = document.querySelector('[data-testid=\"agent-readiness-widget-authoring\"]');"
            "if (!row) throw new Error('widget authoring readiness row missing');"
            "const text = document.body.innerText || row.textContent || '';"
            "if (!/Widget authoring ready/.test(text)) throw new Error('widget authoring ready label missing');"
            "if (!/HTML full check/i.test(text)) throw new Error('HTML authoring check badge missing');"
            "if (!/authoring tools available/.test(text)) throw new Error('authoring tool count missing');"
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
# admin Projects, channel settings, Project-rooted files, memory-tool transcript
# presentation, fresh Project instances, and coding-run receipts.
# ---------------------------------------------------------------------------
_PROJECT_CODING_RUN_ENDPOINT_INIT = """
(() => {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input?.url;
    const method = String(init?.method || (typeof input === "object" && input?.method) || "GET").toUpperCase();
    if (raw && method === "POST") {
      const url = new URL(raw, window.location.origin);
      const scheduleCreateMatch = url.pathname.match(/\\/api\\/v1\\/projects\\/([^/]+)\\/coding-run-schedules$/);
      if (scheduleCreateMatch) {
        return new Response(JSON.stringify({
          id: "screenshot-project-coding-run-schedule",
          project_id: scheduleCreateMatch[1],
          channel_id: null,
          title: "Weekly Project review",
          request: "Review the Project for regressions, stale PRs, missing tests, and architecture issues.",
          status: "active",
          enabled: true,
          scheduled_at: "2026-05-01T13:00:00Z",
          recurrence: "+1w",
          run_count: 3,
          last_run: {
            id: "screenshot-project-coding-run-task",
            task_id: "screenshot-project-coding-run-task",
            status: "complete",
            created_at: "2026-04-30T15:28:00Z",
            branch: "screenshot/project-coding-run"
          },
          recent_runs: [{
            id: "screenshot-project-coding-run-task",
            task_id: "screenshot-project-coding-run-task",
            status: "complete",
            created_at: "2026-04-30T15:28:00Z",
            branch: "screenshot/project-coding-run"
          }],
          created_at: "2026-04-30T15:20:00Z",
          machine_target_grant: {
            provider_id: "ssh",
            target_id: "e2e-8000",
            capabilities: ["inspect", "exec"],
            allow_agent_tools: true,
            provider_label: "E2E Codex Target",
            target_label: "Spindrel e2e target",
            diagnostics: []
          }
        }), {
          status: 201,
          headers: { "Content-Type": "application/json" }
        });
      }
      const reviewMatch = url.pathname.match(/\\/api\\/v1\\/projects\\/([^/]+)\\/coding-runs\\/review-sessions$/);
      if (reviewMatch) {
        return new Response(JSON.stringify({
          id: "screenshot-review-task",
          status: "pending",
          title: "Review Project coding runs",
          bot_id: "screenshot-projects",
          channel_id: null,
          session_id: "screenshot-review-session",
          project_instance_id: null,
          correlation_id: null,
          created_at: "2026-04-30T15:28:00Z",
          scheduled_at: null,
          run_at: null,
          completed_at: null,
          error: null
        }), {
          status: 201,
          headers: { "Content-Type": "application/json" }
        });
      }
      const continueMatch = url.pathname.match(/\\/api\\/v1\\/projects\\/([^/]+)\\/coding-runs\\/([^/]+)\\/continue$/);
      if (continueMatch) {
        window.__PROJECT_FOLLOW_UP_CREATED__ = true;
        const projectId = continueMatch[1];
        const parentTaskId = continueMatch[2];
        const followUpTaskId = "screenshot-project-coding-run-follow-up-task";
        return new Response(JSON.stringify({
          id: followUpTaskId,
          project_id: projectId,
          status: "pending",
          request: "Follow up on Project run review feedback.",
          branch: "screenshot/project-coding-run",
          base_branch: "development",
          repo: { name: "spindrel", path: "spindrel", url: "https://github.com/mtotho/spindrel.git" },
          parent_task_id: parentTaskId,
          root_task_id: parentTaskId,
          continuation_index: 1,
          continuation_feedback: "Tighten the receipt copy and recapture the Project Runs screenshot.",
          continuation_count: 0,
          latest_continuation: null,
          continuations: [],
          task: {
            id: followUpTaskId,
            status: "pending",
            title: "Project coding run follow-up 1",
            bot_id: "screenshot-projects",
            channel_id: "channel-1",
            session_id: null,
            project_instance_id: "screenshot-project-instance",
            correlation_id: "screenshot-follow-up-correlation",
            created_at: "2026-04-30T15:40:00Z",
            scheduled_at: null,
            run_at: null,
            completed_at: null,
            error: null
          },
          receipt: null,
          activity: [],
          review: {
            status: "pending",
            blocker: null,
            reviewed: false,
            reviewed_at: null,
            recovery: { can_continue: false, blocker: "Run is still active.", suggested_feedback: "", latest_continuation_id: null },
            actions: { can_refresh: true, can_mark_reviewed: false, can_cleanup_instance: false, can_request_changes: false, can_continue: false }
          },
          created_at: "2026-04-30T15:40:00Z",
          updated_at: "2026-04-30T15:40:00Z"
        }), {
          status: 201,
          headers: { "Content-Type": "application/json" }
        });
      }
    }
    if (raw && method === "GET") {
      const url = new URL(raw, window.location.origin);
      if (url.pathname === "/api/v1/admin/tasks/machine-automation-options") {
        return new Response(JSON.stringify({
          providers: [{
            provider_id: "ssh",
            provider_label: "E2E Codex Target",
            driver: "ssh",
            label: "E2E Codex Target",
            target_label: "SSH target",
            description: "Task-scoped access to the deployed e2e and main-server test surfaces.",
            capabilities: ["inspect", "exec"],
            target_count: 1,
            ready_target_count: 1,
            targets: [{
              provider_id: "ssh",
              provider_label: "E2E Codex Target",
              target_id: "e2e-8000",
              driver: "ssh",
              label: "Spindrel e2e target",
              hostname: "10.10.30.208",
              platform: "linux",
              ready: true,
              status: "ready",
              status_label: "Ready",
              reason: null,
              checked_at: "2026-04-30T15:28:00Z",
              handle_id: "screenshot-e2e-8000",
              capabilities: ["inspect", "exec"]
            }]
          }],
          step_types: [
            { type: "machine_inspect", label: "Machine inspect", capability: "inspect" },
            { type: "machine_exec", label: "Machine exec", capability: "exec" }
          ]
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      const scheduleMatch = url.pathname.match(/\\/api\\/v1\\/projects\\/([^/]+)\\/coding-run-schedules$/);
      if (scheduleMatch) {
        return new Response(JSON.stringify([{
          id: "screenshot-project-coding-run-schedule",
          project_id: scheduleMatch[1],
          channel_id: null,
          title: "Weekly Project review",
          request: "Review the Project for regressions, stale PRs, missing tests, and architecture issues.",
          status: "active",
          enabled: true,
          scheduled_at: "2026-05-01T13:00:00Z",
          recurrence: "+1w",
          run_count: 3,
          last_run: {
            id: "screenshot-project-coding-run-task",
            task_id: "screenshot-project-coding-run-task",
            status: "complete",
            created_at: "2026-04-30T15:28:00Z",
            branch: "screenshot/project-coding-run"
          },
          recent_runs: [{
            id: "screenshot-project-coding-run-task",
            task_id: "screenshot-project-coding-run-task",
            status: "complete",
            created_at: "2026-04-30T15:28:00Z",
            branch: "screenshot/project-coding-run"
          }, {
            id: "screenshot-project-coding-run-task-previous",
            task_id: "screenshot-project-coding-run-task-previous",
            status: "reviewed",
            created_at: "2026-04-23T15:28:00Z",
            branch: "screenshot/project-coding-run-previous"
          }],
          created_at: "2026-04-30T15:20:00Z",
          machine_target_grant: {
            provider_id: "ssh",
            target_id: "e2e-8000",
            capabilities: ["inspect", "exec"],
            allow_agent_tools: true,
            provider_label: "E2E Codex Target",
            target_label: "Spindrel e2e target",
            diagnostics: []
          }
        }, {
          id: "screenshot-project-coding-run-schedule-paused",
          project_id: scheduleMatch[1],
          channel_id: null,
          title: "Paused dependency sweep",
          request: "Check dependency drift and publish a receipt.",
          status: "cancelled",
          enabled: false,
          scheduled_at: "2026-05-02T13:00:00Z",
          recurrence: "+1d",
          run_count: 1,
          last_run: {
            id: "screenshot-project-coding-run-task-paused",
            task_id: "screenshot-project-coding-run-task-paused",
            status: "blocked",
            created_at: "2026-04-29T15:28:00Z",
            branch: "screenshot/dependency-sweep"
          },
          recent_runs: [{
            id: "screenshot-project-coding-run-task-paused",
            task_id: "screenshot-project-coding-run-task-paused",
            status: "blocked",
            created_at: "2026-04-29T15:28:00Z",
            branch: "screenshot/dependency-sweep"
          }],
          created_at: "2026-04-29T15:20:00Z",
          machine_target_grant: null
        }]), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      const reviewBatchMatch = url.pathname.match(/\\/api\\/v1\\/projects\\/([^/]+)\\/coding-runs\\/review-batches$/);
      if (reviewBatchMatch) {
        const finalizedReview = window.__PROJECT_REVIEW_FINALIZED__ === true;
        return new Response(JSON.stringify([{
          id: "issue-work-pack-batch:screenshot",
          project_id: reviewBatchMatch[1],
          status: finalizedReview ? "reviewed" : "ready_for_review",
          run_count: 2,
          status_counts: finalizedReview ? { reviewed: 2 } : { ready_for_review: 2 },
          evidence: { tests_count: 4, screenshots_count: 2, changed_files_count: 4, dev_targets_count: 4 },
          run_ids: ["screenshot-project-coding-run", "screenshot-project-coding-run-batch-peer"],
          task_ids: ["screenshot-project-coding-run-task", "screenshot-project-coding-run-batch-peer-task"],
          ready_run_ids: finalizedReview ? [] : ["screenshot-project-coding-run", "screenshot-project-coding-run-batch-peer"],
          unreviewed_run_ids: finalizedReview ? [] : ["screenshot-project-coding-run", "screenshot-project-coding-run-batch-peer"],
          source_work_packs: [
            { id: "screenshot-work-pack-main", title: "Prepare the Project workspace screenshot receipt", status: "launched", category: "code_bug", confidence: "high" },
            { id: "screenshot-work-pack-batch-peer", title: "Add batch launch proof for overnight packs", status: "launched", category: "code_bug", confidence: "medium" }
          ],
          review_sessions: finalizedReview ? [{
            task_id: "screenshot-review-task",
            status: "complete",
            title: "Review Project coding runs",
            session_id: "screenshot-review-session",
            created_at: "2026-04-30T15:28:00Z",
            completed_at: "2026-04-30T15:32:00Z",
            active: false
          }] : [],
          active_review_task: null,
          latest_review_task: finalizedReview ? { task_id: "screenshot-review-task", status: "complete", title: "Review Project coding runs", active: false } : null,
          latest_activity_at: "2026-04-30T15:32:00Z",
          summary: { title: "Prepare the Project workspace screenshot receipt", source_work_pack_count: 2, ready_count: finalizedReview ? 0 : 2, unreviewed_count: finalizedReview ? 0 : 2 },
          actions: { can_select: true, can_start_review: !finalizedReview, can_resume_review: false, can_mark_reviewed: !finalizedReview }
        }]), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      const reviewSessionMatch = url.pathname.match(/\\/api\\/v1\\/projects\\/([^/]+)\\/coding-runs\\/review-sessions$/);
      if (reviewSessionMatch) {
        const finalizedReview = window.__PROJECT_REVIEW_FINALIZED__ === true;
        return new Response(JSON.stringify([{
          id: "screenshot-review-task",
          task_id: "screenshot-review-task",
          project_id: reviewSessionMatch[1],
          status: finalizedReview ? "finalized" : "active",
          task_status: finalizedReview ? "complete" : "running",
          title: "Review Project coding runs",
          session_id: "screenshot-review-session",
          channel_id: "channel-1",
          created_at: "2026-04-30T15:28:00Z",
          completed_at: finalizedReview ? "2026-04-30T15:32:00Z" : null,
          latest_activity_at: finalizedReview ? "2026-04-30T15:32:00Z" : "2026-04-30T15:28:00Z",
          selected_task_ids: ["screenshot-project-coding-run-task", "screenshot-project-coding-run-batch-peer-task"],
          selected_run_ids: ["screenshot-project-coding-run", "screenshot-project-coding-run-batch-peer"],
          run_count: 2,
          launch_batch_ids: ["issue-work-pack-batch:screenshot"],
          outcome_counts: finalizedReview ? { accepted: 2 } : {},
          evidence: { tests_count: 4, screenshots_count: 2, changed_files_count: 4, dev_targets_count: 4 },
          source_work_packs: [
            { id: "screenshot-work-pack-main", title: "Prepare the Project workspace screenshot receipt", status: "launched", category: "code_bug", confidence: "high" },
            { id: "screenshot-work-pack-batch-peer", title: "Add batch launch proof for overnight packs", status: "launched", category: "code_bug", confidence: "medium" }
          ],
          selected_runs: [
            { id: "screenshot-project-coding-run", task_id: "screenshot-project-coding-run-task", review_status: finalizedReview ? "reviewed" : "ready_for_review", branch: "screenshot/project-coding-run", handoff_url: "https://example.invalid/spindrel/project-run" },
            { id: "screenshot-project-coding-run-batch-peer", task_id: "screenshot-project-coding-run-batch-peer-task", review_status: finalizedReview ? "reviewed" : "ready_for_review", branch: "screenshot/project-coding-run-batch-proof", handoff_url: "https://example.invalid/spindrel/project-run-peer" }
          ],
          summaries: finalizedReview ? [
            { id: "screenshot-review-receipt-1", task_id: "screenshot-project-coding-run-task", status: "succeeded", outcome: "accepted", summary: "Accepted after review context preflight and merged to development.", merge: true, merge_method: "squash", created_at: "2026-04-30T15:32:00Z" },
            { id: "screenshot-review-receipt-2", task_id: "screenshot-project-coding-run-batch-peer-task", status: "succeeded", outcome: "accepted", summary: "Accepted batch peer with screenshot evidence.", merge: true, merge_method: "squash", created_at: "2026-04-30T15:31:00Z" }
          ] : [],
          latest_summary: finalizedReview ? "Accepted after review context preflight and merged to development." : null,
          merge: { method: "squash", requested_count: finalizedReview ? 2 : 0, completed_count: finalizedReview ? 2 : 0 },
          actions: { can_open_task: true, can_select_runs: true, active: !finalizedReview, finalized: finalizedReview }
        }]), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      const detailMatch = url.pathname.match(/\\/api\\/v1\\/projects\\/([^/]+)\\/coding-runs\\/([^/]+)$/);
      if (detailMatch) {
        const projectId = detailMatch[1];
        const taskId = detailMatch[2];
        const followUpProof = taskId === "screenshot-project-coding-run-needs-follow-up-task";
        const followUpTaskId = "screenshot-project-coding-run-follow-up-task";
        const followUpCreated = window.__PROJECT_FOLLOW_UP_CREATED__ === true;
        const latestFollowUp = followUpProof && followUpCreated ? {
          id: "screenshot-project-coding-run-follow-up",
          task_id: followUpTaskId,
          status: "pending",
          review_status: "pending",
          continuation_index: 1,
          feedback: "Tighten the receipt copy and recapture the Project Runs screenshot."
        } : null;
        const reviewPayload = followUpProof ? {
          status: "changes_requested",
          blocker: "Receipt copy is too vague and the Project Runs screenshot was not recaptured.",
          reviewed: false,
          reviewed_at: null,
          reviewed_by: null,
          review_task_id: "screenshot-review-task",
          review_session_id: "screenshot-review-session",
          review_summary: "Needs a targeted follow-up before acceptance.",
          review_details: { outcome: "rejected", notes: "Tighten the receipt copy and recapture the Project Runs screenshot." },
          merge_method: null,
          merged_at: null,
          merge_commit_sha: null,
          handoff_url: "https://example.invalid/spindrel/project-run",
          pr: { url: "https://example.invalid/spindrel/project-run", state: "OPEN", draft: true, checks_status: "passed" },
          steps: {
            branch: { status: "succeeded", summary: "Branch ready." },
            pr: { status: "succeeded", summary: "Pull request ready." },
            status: { status: "succeeded", summary: "Repository state inspected." },
            review: { status: "needs_review", summary: "Reviewer requested a follow-up." }
          },
          evidence: { changed_files_count: 2, tests_count: 2, screenshots_count: 1, dev_targets_count: 2, has_tests: true, has_screenshots: true, has_dev_targets: true },
          instance: { id: "screenshot-project-instance", status: "ready", root_path: "common/project-instances/screenshot/project-run" },
          recovery: {
            can_continue: true,
            blocker: null,
            suggested_feedback: "Tighten the receipt copy and recapture the Project Runs screenshot.",
            latest_continuation_id: followUpCreated ? followUpTaskId : null
          },
          actions: { can_refresh: true, can_mark_reviewed: true, can_cleanup_instance: true, can_request_changes: true, can_continue: true }
        } : {
          status: "reviewed",
          blocker: null,
          reviewed: true,
          reviewed_at: "2026-04-30T15:30:00Z",
          reviewed_by: "agent",
          review_task_id: "screenshot-review-task",
          review_session_id: "screenshot-review-session",
          review_summary: "Accepted after reviewing tests, screenshots, and PR handoff evidence.",
          review_details: { outcome: "accepted", checks: "passed", screenshots: "reviewed", notes: "Stored evidence is sufficient for the screenshot scenario." },
          merge_method: "squash",
          merged_at: "2026-04-30T15:32:00Z",
          merge_commit_sha: "abc1234def5678",
          handoff_url: "https://example.invalid/spindrel/project-run",
          pr: { url: "https://example.invalid/spindrel/project-run", state: "MERGED", draft: false, checks_status: "passed" },
          steps: {
            branch: { status: "succeeded", summary: "Branch ready." },
            pr: { status: "succeeded", summary: "Pull request ready." },
            status: { status: "succeeded", summary: "Repository state inspected." },
            merge: { status: "succeeded", summary: "Merged with squash." },
            review: { status: "succeeded", summary: "Finalized accepted review." }
          },
          evidence: { changed_files_count: 2, tests_count: 2, screenshots_count: 2, dev_targets_count: 2, has_tests: true, has_screenshots: true, has_dev_targets: true },
          instance: { id: "screenshot-project-instance", status: "ready", root_path: "common/project-instances/screenshot/project-run" },
          recovery: {
            can_continue: false,
            blocker: "Run is already reviewed.",
            suggested_feedback: "Accepted after reviewing tests, screenshots, and PR handoff evidence.",
            latest_continuation_id: "screenshot-project-coding-run-follow-up-task"
          },
          actions: { can_refresh: true, can_mark_reviewed: false, can_cleanup_instance: true, can_request_changes: false, can_continue: false }
        };
        return new Response(JSON.stringify({
          id: taskId,
          project_id: projectId,
          status: "completed",
          request: followUpProof ? "Follow up on Project run review feedback." : "Prepare the Project workspace screenshot receipt and handoff evidence.",
          branch: "screenshot/project-coding-run",
          base_branch: "development",
          repo: { name: "spindrel", path: "spindrel", url: "https://github.com/mtotho/spindrel.git" },
          runtime_target: { ready: true, configured_keys: ["SPINDREL_E2E_URL", "GITHUB_TOKEN"], missing_secrets: [] },
          dev_targets: [
            { key: "api", label: "API", port: 31100, port_env: "SPINDREL_DEV_API_PORT", url: "http://127.0.0.1:31100", url_env: "SPINDREL_DEV_API_URL", status: "running" },
            { key: "ui", label: "UI", port: 31200, port_env: "SPINDREL_DEV_UI_PORT", url: "http://127.0.0.1:31200", url_env: "SPINDREL_DEV_UI_URL", status: "running" }
          ],
          dependency_stack: {
            configured: true,
            instance: {
              id: "screenshot-dependency-stack",
              status: "running",
              source_path: ".spindrel/docker-compose.yml",
              env: { DATABASE_URL: "postgres://redacted", REDIS_URL: "redis://redacted" }
            }
          },
          dependency_stack_preflight: { status: "ready", env_keys: ["DATABASE_URL", "REDIS_URL"] },
          readiness: { status: "ready", blockers: [], required_evidence: ["tests", "screenshots", "handoff"] },
          work_surface: {
            kind: "project_instance",
            isolation: "isolated",
            expected: "fresh_project_instance",
            active: true,
            status: "ready",
            display_path: "/workspace/common/project-instances/screenshot-project/screenshot-project-instance",
            root_path: "common/project-instances/screenshot-project/screenshot-project-instance",
            project_id: projectId,
            project_instance_id: "screenshot-project-instance",
            owner_kind: "task",
            owner_id: taskId,
            blocker: null
          },
          source_artifact: { path: ".spindrel/audits/screenshot-sweep.md", section: "Proposed Run Packs" },
          launch_batch_id: "run-pack-batch:screenshot",
          parent_task_id: null,
          root_task_id: taskId,
          continuation_index: 0,
          continuation_feedback: null,
          continuation_count: latestFollowUp ? 1 : 0,
          latest_continuation: latestFollowUp,
          continuations: latestFollowUp ? [latestFollowUp] : [],
          task: {
            id: taskId,
            status: "complete",
            title: "Project coding run",
            bot_id: "screenshot-projects",
            channel_id: "channel-1",
            session_id: "screenshot-project-session",
            project_instance_id: "screenshot-project-instance",
            correlation_id: "screenshot-project-correlation",
            created_at: "2026-04-30T15:20:00Z",
            scheduled_at: null,
            run_at: "2026-04-30T15:21:00Z",
            completed_at: "2026-04-30T15:28:00Z",
            error: null
          },
          receipt: {
            id: "screenshot-project-coding-run-receipt",
            project_id: projectId,
            project_instance_id: "screenshot-project-instance",
            task_id: taskId,
            session_id: "screenshot-project-session",
            bot_id: "screenshot-projects",
            idempotency_key: "screenshot:project-coding-run",
            status: "completed",
            summary: "Screenshot Project coding run receipt with review-ready evidence.",
            handoff_type: "pull_request",
            handoff_url: "https://example.invalid/spindrel/project-run",
            branch: "screenshot/project-coding-run",
            base_branch: "development",
            commit_sha: "def5678abc1234",
            changed_files: [
              { path: "app/services/projects.py", status: "modified", summary: "Centralized Project work-surface policy." },
              { path: "ui/app/(app)/admin/projects/[projectId]/ProjectRunsSection.tsx", status: "modified", summary: "Added Project Factory review controls." }
            ],
            tests: [
              { command: "pytest tests/unit/test_projects_service.py", status: "passed", exit_code: 0, summary: "Project work-surface policy passed." },
              { command: "cd ui && npx tsc --noEmit", status: "passed", exit_code: 0, summary: "Frontend typecheck passed." }
            ],
            screenshots: [
              { path: "docs/images/project-workspace-runs.png", label: "Project Runs cockpit", viewport: "1440x1000", status: "captured" },
              { path: "docs/images/project-workspace-run-detail.png", label: "Project Run detail", viewport: "1440x1000", status: "captured" }
            ],
            dev_targets: [
              { key: "api", label: "API", url: "http://127.0.0.1:31100", port: 31100, status: "running" },
              { key: "ui", label: "UI", url: "http://127.0.0.1:31200", port: 31200, status: "running" }
            ],
            metadata: {
              risks: ["No live PR provider fetch in v1; stored evidence is canonical."],
              follow_ups: ["Enrich receipts from PR bodies when provider integration is available."],
              dependency_health: "postgres and redis healthy",
              implementation_notes: "Receipt includes structured files, tests, screenshots, dev targets, and review notes."
            },
            created_at: "2026-04-30T15:28:00Z"
          },
          activity: [
            { id: "screenshot-project-coding-run-progress-branch", kind: "execution_receipt", status: "succeeded", summary: "Screenshot Project run branch ready.", source: { scope: "project_coding_run", action_type: "handoff.prepare_branch", result: { current_branch: "screenshot/project-coding-run" } }, created_at: "2026-04-30T15:21:00Z" },
            { id: "screenshot-project-coding-run-progress-pr", kind: "execution_receipt", status: "succeeded", summary: "Screenshot Project run draft PR ready.", source: { scope: "project_coding_run", action_type: "handoff.open_pr", result: { pr_url: "https://example.invalid/spindrel/project-run" } }, created_at: "2026-04-30T15:27:00Z" },
            { id: "screenshot-project-coding-run-activity", kind: "project_receipt", status: "succeeded", summary: "Published screenshot handoff receipt", created_at: "2026-04-30T15:28:00Z" }
          ],
          review: reviewPayload,
          created_at: "2026-04-30T15:20:00Z",
          updated_at: "2026-04-30T15:32:00Z"
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      const match = url.pathname.match(/\\/api\\/v1\\/projects\\/([^/]+)\\/coding-runs$/);
      if (match) {
        const response = await originalFetch(input, init);
        const finalizedReview = window.__PROJECT_REVIEW_FINALIZED__ === true;
        const enrichRun = (run, projectId) => {
          const latestContinuation = run.latest_continuation || null;
          const queueState = finalizedReview ? "reviewed" : (
            latestContinuation ? "follow_up_running" : run.review?.status === "changes_requested" ? "changes_requested" : "ready_for_review"
          );
          const queuePriority = finalizedReview ? 90 : queueState === "changes_requested" ? 10 : queueState === "follow_up_running" ? 50 : 30;
          const queueAction = finalizedReview ? "No operator action needed." : (
            queueState === "follow_up_running" ? "Wait for the follow-up run to publish updated evidence." :
            queueState === "changes_requested" ? "Start a follow-up run from reviewer feedback." :
            "Review the PR, tests, screenshots, and receipt."
          );
          return {
          ...run,
          launch_batch_id: run.launch_batch_id || "issue-work-pack-batch:screenshot",
          review_queue_state: queueState,
          review_queue_priority: queuePriority,
          review_next_action: queueAction,
          dev_targets: run.dev_targets || [
            { key: "api", label: "API", port: 31100, port_env: "SPINDREL_DEV_API_PORT", url: "http://127.0.0.1:31100", url_env: "SPINDREL_DEV_API_URL" },
            { key: "ui", label: "UI", port: 31200, port_env: "SPINDREL_DEV_UI_PORT", url: "http://127.0.0.1:31200", url_env: "SPINDREL_DEV_UI_URL" }
          ],
          root_task_id: run.root_task_id || run.task?.id || run.id,
          parent_task_id: run.parent_task_id || null,
          continuation_index: run.continuation_index || 0,
          continuation_feedback: run.continuation_feedback || null,
          continuation_count: run.continuation_count ?? (latestContinuation ? 1 : 0),
          latest_continuation: latestContinuation,
          continuations: run.continuations || (latestContinuation ? [latestContinuation] : []),
          review: finalizedReview ? {
            status: "reviewed",
            blocker: null,
            reviewed: true,
            reviewed_at: "2026-04-30T15:30:00Z",
            reviewed_by: "agent",
            review_task_id: "screenshot-review-task",
            review_session_id: "screenshot-review-session",
            review_summary: "Accepted after review context preflight and merged to development.",
            review_details: { outcome: "accepted", checks: "passed", screenshots: "reviewed" },
            merge_method: "squash",
            merged_at: "2026-04-30T15:32:00Z",
            merge_commit_sha: "abc1234def5678",
            handoff_url: run.receipt?.handoff_url || "https://example.invalid/spindrel/project-run",
            pr: { url: run.receipt?.handoff_url || "https://example.invalid/spindrel/project-run", state: "MERGED", draft: false, checks_status: "passed" },
            steps: {
              branch: { status: "succeeded", summary: "Screenshot Project run branch ready." },
              push: { status: "succeeded", summary: "Changes pushed for review." },
              pr: { status: "succeeded", summary: "Pull request ready." },
              status: { status: "succeeded", summary: "Project run repository state inspected." },
              merge: { status: "succeeded", summary: "Merged with squash." },
              review: { status: "succeeded", summary: "Finalized accepted review." },
              cleanup: { status: "missing", summary: null }
            },
            evidence: {
              changed_files_count: run.receipt?.changed_files?.length || 2,
              tests_count: run.receipt?.tests?.length || 2,
              screenshots_count: run.receipt?.screenshots?.length || 1,
              dev_targets_count: run.receipt?.dev_targets?.length || 2,
              has_tests: true,
              has_screenshots: true,
              has_dev_targets: true
            },
            instance: { id: "screenshot-project-instance", status: "ready", root_path: "common/project-instances/screenshot/project-run" },
            actions: { can_refresh: true, can_mark_reviewed: false, can_cleanup_instance: true, can_request_changes: false }
          } : run.review ? {
            ...run.review,
            status: "ready_for_review",
            blocker: null,
            reviewed: false,
            reviewed_at: null,
            actions: {
              ...(run.review.actions || {}),
              can_mark_reviewed: true,
              can_request_changes: true
            }
          } : {
            status: "ready_for_review",
            blocker: null,
            reviewed: false,
            reviewed_at: null,
            handoff_url: run.receipt?.handoff_url || "https://example.invalid/spindrel/project-run",
            pr: { url: run.receipt?.handoff_url || "https://example.invalid/spindrel/project-run", state: "OPEN", draft: true, checks_status: "passed" },
            steps: {
              branch: { status: "succeeded", summary: "Screenshot Project run branch ready." },
              push: { status: "missing", summary: null },
              pr: { status: "succeeded", summary: "Screenshot Project run draft PR ready." },
              status: { status: "succeeded", summary: "Project run repository state inspected." },
              cleanup: { status: "missing", summary: null }
            },
            evidence: {
              changed_files_count: run.receipt?.changed_files?.length || 2,
              tests_count: run.receipt?.tests?.length || 2,
              screenshots_count: run.receipt?.screenshots?.length || 1,
              dev_targets_count: run.receipt?.dev_targets?.length || 2,
              has_tests: true,
              has_screenshots: true,
              has_dev_targets: true
            },
            instance: { id: "screenshot-project-instance", status: "ready", root_path: "common/project-instances/screenshot/project-run" },
            actions: { can_refresh: true, can_mark_reviewed: true, can_cleanup_instance: true, can_request_changes: true }
          }
        };
        };
        const ensureBatchRows = (rows, projectId) => {
          const enriched = rows.map((run) => enrichRun(run, projectId));
          if (enriched.length === 0) return enriched;
          const hasReviewBatch = enriched.some((run) => enriched.filter((other) => other.launch_batch_id === run.launch_batch_id).length > 1);
          if (hasReviewBatch) return enriched;
          const first = { ...enriched[0], launch_batch_id: "issue-work-pack-batch:screenshot" };
          const peerTaskId = "screenshot-project-coding-run-batch-peer-task";
          const peer = {
            ...first,
            id: "screenshot-project-coding-run-batch-peer",
            request: "Add batch launch proof for overnight packs.",
            branch: "screenshot/project-coding-run-batch-proof",
            source_artifact: { path: ".spindrel/audits/screenshot-sweep.md", section: "Proposed Run Packs" },
            task: { ...(first.task || {}), id: peerTaskId, title: "Project coding run batch peer" },
            receipt: first.receipt ? {
              ...first.receipt,
              id: "screenshot-project-coding-run-batch-peer-receipt",
              task_id: peerTaskId,
              summary: "Batch peer Project coding run receipt",
              branch: "screenshot/project-coding-run-batch-proof"
            } : first.receipt
          };
          return [first, peer, ...enriched.slice(1)];
        };
        if (response.ok) {
          try {
            const rows = await response.clone().json();
            if (Array.isArray(rows) && rows.length > 0) {
              return new Response(JSON.stringify(ensureBatchRows(rows, match[1])), {
                status: response.status,
                headers: { "Content-Type": "application/json" }
              });
            }
          } catch {}
          return response;
        }
        if (response.status !== 404) return response;
        const projectId = match[1];
        const bodySeed = [{
          id: "screenshot-project-coding-run",
          project_id: projectId,
          status: "completed",
          request: "Prepare the Project workspace screenshot receipt and handoff evidence.",
          branch: "screenshot/project-coding-run",
          base_branch: "development",
          repo: { name: "spindrel", path: "spindrel", url: "https://github.com/mtotho/spindrel.git" },
          runtime_target: { ready: true, configured_keys: ["SPINDREL_E2E_URL", "GITHUB_TOKEN"], missing_secrets: [] },
          dev_targets: [
            { key: "api", label: "API", port: 31100, port_env: "SPINDREL_DEV_API_PORT", url: "http://127.0.0.1:31100", url_env: "SPINDREL_DEV_API_URL" },
            { key: "ui", label: "UI", port: 31200, port_env: "SPINDREL_DEV_UI_PORT", url: "http://127.0.0.1:31200", url_env: "SPINDREL_DEV_UI_URL" }
          ],
          parent_task_id: null,
          root_task_id: "screenshot-project-coding-run-task",
          continuation_index: 0,
          continuation_feedback: null,
          continuation_count: 1,
          latest_continuation: {
            id: "screenshot-project-coding-run-follow-up",
            task_id: "screenshot-project-coding-run-follow-up-task",
            status: "pending",
            review_status: "pending",
            continuation_index: 1,
            feedback: "Tighten the receipt copy and recapture the Project Runs screenshot."
          },
          continuations: [{
            id: "screenshot-project-coding-run-follow-up",
            task_id: "screenshot-project-coding-run-follow-up-task",
            status: "pending",
            review_status: "pending",
            continuation_index: 1,
            feedback: "Tighten the receipt copy and recapture the Project Runs screenshot."
          }],
          task: {
            id: "screenshot-project-coding-run-task",
            status: "complete",
            title: "Project coding run",
            bot_id: "screenshot-projects",
            channel_id: null,
            session_id: null,
            project_instance_id: null,
            correlation_id: null,
            created_at: new Date().toISOString(),
            scheduled_at: null,
            run_at: null,
            completed_at: new Date().toISOString(),
            error: null,
            machine_target_grant: {
              provider_id: "ssh",
              target_id: "e2e-8000",
              grant_id: "screenshot-machine-grant",
              grant_source_task_id: "screenshot-project-coding-run-task",
              granted_by_user_id: null,
              capabilities: ["inspect", "exec"],
              allow_agent_tools: true,
              expires_at: null,
              created_at: "2026-04-30T15:28:00Z",
              provider_label: "E2E Codex Target",
              target_label: "spindrel-bot :8000 / :18000",
              diagnostics: []
            }
          },
          receipt: {
            id: "screenshot-project-coding-run-receipt",
            project_id: projectId,
            project_instance_id: null,
            task_id: "screenshot-project-coding-run-task",
            session_id: null,
            bot_id: "screenshot-projects",
            idempotency_key: "screenshot:project-coding-run",
            status: "completed",
            summary: "Screenshot Project coding run receipt",
            handoff_type: "branch",
            handoff_url: "https://example.invalid/spindrel/project-run",
            branch: "screenshot/project-coding-run",
            base_branch: "development",
            commit_sha: null,
            changed_files: ["app/services/projects.py", "ui/app/(app)/admin/projects/[projectId]/ProjectRunsSection.tsx"],
            tests: [
              { command: "pytest tests/unit/test_projects_service.py", status: "passed" },
              { command: "cd ui && npx tsc --noEmit", status: "passed" }
            ],
            screenshots: [{ path: "docs/images/project-workspace-runs.png", status: "captured" }],
            dev_targets: [
              { key: "api", label: "API", url: "http://127.0.0.1:31100", port: 31100, status: "running" },
              { key: "ui", label: "UI", url: "http://127.0.0.1:31200", port: 31200, status: "running" }
            ],
            metadata: {
              dev_targets: [
                { key: "api", label: "API", url: "http://127.0.0.1:31100", port: 31100, status: "running" },
                { key: "ui", label: "UI", url: "http://127.0.0.1:31200", port: 31200, status: "running" }
              ]
            },
            created_at: new Date().toISOString()
          },
          activity: [
            {
              id: "screenshot-project-coding-run-progress-branch",
              kind: "execution_receipt",
              status: "succeeded",
              summary: "Screenshot Project run branch ready.",
              source: { scope: "project_coding_run", action_type: "handoff.prepare_branch", result: { current_branch: "screenshot/project-coding-run" } },
              created_at: new Date().toISOString()
            },
            {
              id: "screenshot-project-coding-run-progress-pr",
              kind: "execution_receipt",
              status: "succeeded",
              summary: "Screenshot Project run draft PR ready.",
              source: { scope: "project_coding_run", action_type: "handoff.open_pr", result: { pr_url: "https://example.invalid/spindrel/project-run" } },
              created_at: new Date().toISOString()
            },
            {
              id: "screenshot-project-coding-run-activity",
              kind: "project_receipt",
              status: "succeeded",
              summary: "Published screenshot handoff receipt",
              created_at: new Date().toISOString()
            }
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString()
        }];
        const body = ensureBatchRows(bodySeed, projectId);
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
    }
    return originalFetch(input, init);
  };
})();
"""

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
            "!!document.querySelector('[data-testid=\"project-overview-home\"]') "
            "&& document.body.innerText.toLowerCase().includes('project factory') "
            "&& document.body.innerText.toLowerCase().includes('review work is waiting') "
            "&& document.body.innerText.toLowerCase().includes('recent coding runs') "
            "&& document.body.innerText.toLowerCase().includes('needs human review')"
        ),
        output="project-workspace-detail.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Needs human review') "
            "&& text.includes('Running now') "
            "&& text.includes('Issue intake') "
            "&& text.includes('Attached channels') "
            "&& text.includes('Runtime env') "
            "&& text.includes('Work surface') "
            "&& text.includes('common/projects/spindrel-screenshot'), "
            "detail: 'Project detail did not show the Project work hub overview' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-files",
        route="/admin/projects/{project_workspace_project}#files",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-files\"]') "
            "&& document.body.innerText.includes('README.md')"
        ),
        output="project-workspace-files.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('README.md') "
            "&& text.includes('common/projects/spindrel-screenshot'), "
            "detail: 'Project Files tab did not show the Project-rooted file browser' };"
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
            "&& !!document.querySelector('[data-testid=\"project-workspace-basics\"]') "
            "&& !!document.querySelector('[data-testid=\"project-runtime-env-readiness\"]') "
            "&& document.body.innerText.includes('Screenshot Service Blueprint') "
            "&& (document.body.innerText.toLowerCase().includes('runtime env available') "
            "|| document.body.innerText.toLowerCase().includes('runtime keys are ready'))"
        ),
        output="project-workspace-settings-blueprint.png",
        color_scheme="dark",
        full_page=True,
        pre_capture_js=(
            "const basics = document.querySelector('[data-testid=\"project-workspace-basics\"]');"
            "if (basics) basics.scrollIntoView({ block: 'start' });"
            "await new Promise((resolve) => setTimeout(resolve, 250));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "const normalized = text.toLowerCase();"
            "return { ok: normalized.includes('secret bindings') "
            "&& normalized.includes('work surface') "
            "&& normalized.includes('attached channels') "
            "&& text.includes('SCREENSHOT_PROJECT_GITHUB_TOKEN') "
            "&& text.includes('SCREENSHOT_PROJECT_NPM_TOKEN') "
            "&& normalized.includes('repo declarations') "
            "&& normalized.includes('env defaults') "
            "&& (normalized.includes('runtime env available') || normalized.includes('runtime keys are ready')) "
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
        name="project-workspace-setup-blueprint-cta",
        route="/admin/projects/{project_workspace_project}#Setup",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-setup-ready\"]') "
            "&& document.body.innerText.includes('No Blueprint recipe applied') "
            "&& document.body.innerText.includes('Create Blueprint')"
        ),
        output="project-workspace-setup-blueprint-cta.png",
        color_scheme="dark",
        full_page=True,
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('No Blueprint recipe applied') "
            "&& text.includes('Create Blueprint') "
            "&& text.includes('fresh instances') "
            "&& text.includes('isolated factory runs'), "
            "detail: 'Direct Project setup tab did not show the Blueprint creation CTA' };"
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
        name="project-workspace-instances",
        route="/admin/projects/{project_workspace_blueprint_project}#Instances",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-instances\"]') "
            "&& document.body.innerText.includes('Fresh Instances') "
            "&& document.body.innerText.includes('common/project-instances')"
        ),
        output="project-workspace-instances.png",
        color_scheme="dark",
        full_page=True,
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Fresh Instances') "
            "&& text.includes('Instance History') "
            "&& text.includes('common/project-instances') "
            "&& text.includes('ready'), "
            "detail: 'Project Instances tab did not show a ready fresh instance and its root path' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-runs",
        route="/admin/projects/{project_workspace_project}#Runs",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-runs\"]') "
            "&& document.body.innerText.includes('Start new work') "
            "&& document.body.innerText.includes('Prepare the Project workspace screenshot receipt') "
            "&& document.body.innerText.includes('Screenshot Project coding run receipt')"
        ),
        output="project-workspace-runs.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[_PROJECT_CODING_RUN_ENDPOINT_INIT],
        pre_capture_js="window.scrollTo(0, 0); await new Promise((resolve) => setTimeout(resolve, 120));",
        assert_js=(
            "const text = document.body.innerText.toLowerCase();"
            "return { ok: text.includes('needs your review') "
            "&& text.includes('batch review shortcuts') "
            "&& text.includes('ask agent to review batch') "
            "&& text.includes('prepare the project workspace screenshot receipt') "
            "&& text.includes('add batch launch proof for overnight packs') "
            "&& text.includes('sources: prepare the project workspace screenshot receipt') "
            "&& text.includes('work surface:') "
            "&& text.includes('launch batch:') "
            "&& text.includes('run receipts'), "
            "detail: 'Project Runs tab did not expose human-review queue, launch-batch context, and receipt evidence' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-review-inbox",
        route="/admin/projects/{project_workspace_project}#Runs",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-runs\"]') "
            "&& document.body.innerText.includes('Needs your review') "
            "&& document.body.innerText.includes('Sources: Prepare the Project workspace screenshot receipt')"
        ),
        output="project-workspace-review-inbox.png",
        color_scheme="dark",
        full_page=False,
        extra_init_scripts=[_PROJECT_CODING_RUN_ENDPOINT_INIT],
        pre_capture_js=(
            "const root = document.querySelector('[data-testid=\"project-workspace-runs\"]');"
            "const inbox = [...root.querySelectorAll('*')].find((el) => /^Needs your review$/.test((el.textContent || '').trim()));"
            "if (inbox) inbox.scrollIntoView({ block: 'start' });"
            "await new Promise((resolve) => setTimeout(resolve, 160));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Needs your review') "
            "&& text.includes('Open the review page first') "
            "&& text.includes('Sources: Prepare the Project workspace screenshot receipt') "
            "&& text.includes('Evidence: 4 tests') "
            "&& text.includes('Select batch') "
            "&& text.includes('Ask agent to review batch'), "
            "detail: 'Project Runs tab did not show the human-review queue and batch context' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-run-detail",
        route="/admin/projects/{project_workspace_project}/runs/screenshot-project-coding-run-task",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-run-detail\"]') "
            "&& document.body.innerText.includes('Review Decision') "
            "&& document.body.innerText.includes('Changed Files') "
            "&& document.body.innerText.includes('Activity Timeline')"
        ),
        output="project-workspace-run-detail.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[_PROJECT_CODING_RUN_ENDPOINT_INIT],
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Screenshot Project coding run receipt with review-ready evidence') "
            "&& text.includes('Accepted after reviewing tests') "
            "&& text.includes('Recovery') "
            "&& text.includes('Latest follow-up') "
            "&& text.includes('app/services/projects.py') "
            "&& text.includes('pytest tests/unit/test_projects_service.py') "
            "&& text.includes('docs/images/project-workspace-run-detail.png') "
            "&& text.includes('Fresh Project instance') "
            "&& text.includes('Dependency stack running') "
            "&& text.includes('Published screenshot handoff receipt'), "
            "detail: 'Project Run detail page did not expose receipt, review, evidence, dependency, and activity data' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-run-follow-up",
        route="/admin/projects/{project_workspace_project}/runs/screenshot-project-coding-run-needs-follow-up-task",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-run-detail\"]') "
            "&& document.body.innerText.includes('Follow-up run available') "
            "&& document.body.innerText.includes('Start follow-up')"
        ),
        output="project-workspace-run-follow-up.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[_PROJECT_CODING_RUN_ENDPOINT_INIT],
        pre_capture_js=(
            "const recovery = [...document.querySelectorAll('*')].find((el) => /^Recovery$/.test((el.textContent || '').trim()));"
            "if (recovery) recovery.scrollIntoView({ block: 'start' });"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
            "const button = [...document.querySelectorAll('button')].find((item) => /Start follow-up/.test(item.textContent || ''));"
            "if (button) button.click();"
            "await new Promise((resolve) => setTimeout(resolve, 350));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Follow-up run created') "
            "&& text.includes('Open follow-up') "
            "&& text.includes('A follow-up run has already been created from this run.') "
            "&& text.includes('CHANGES_REQUESTED') "
            "&& text.includes('Needs a targeted follow-up before acceptance') "
            "&& !text.includes('Start follow-up') "
            "&& !text.includes('Uses the existing Project coding-run continuation path.'), "
            "detail: 'Project Run detail page did not create a follow-up run from recovery controls' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-review-ledger",
        route="/admin/projects/{project_workspace_project}#Runs",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-review-ledger\"]') "
            "&& document.body.innerText.includes('Agent Review Sessions') "
            "&& document.body.innerText.includes('Review Project coding runs')"
        ),
        output="project-workspace-review-ledger.png",
        color_scheme="dark",
        full_page=False,
        extra_init_scripts=["window.__PROJECT_REVIEW_FINALIZED__ = true;", _PROJECT_CODING_RUN_ENDPOINT_INIT],
        pre_capture_js=(
            "const root = document.querySelector('[data-testid=\"project-workspace-runs\"]');"
            "const ledger = [...root.querySelectorAll('*')].find((el) => /^Agent Review Sessions$/.test((el.textContent || '').trim()));"
            "if (ledger) ledger.scrollIntoView({ block: 'start' });"
            "await new Promise((resolve) => setTimeout(resolve, 180));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Agent Review Sessions') "
            "&& text.includes('Review Project coding runs') "
            "&& text.includes('2 accepted') "
            "&& text.includes('squash merge 2/2') "
            "&& text.includes('Sources: Prepare the Project workspace screenshot receipt') "
            "&& text.includes('View summary'), "
            "detail: 'Project Runs tab did not show the review-session ledger' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-scheduled-reviews",
        route="/admin/projects/{project_workspace_project}#Runs",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-runs\"]') "
            "&& document.body.innerText.includes('Scheduled Reviews') "
            "&& document.body.innerText.includes('Weekly Project review') "
            "&& document.body.innerText.includes('Run now')"
        ),
        output="project-workspace-scheduled-reviews.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[_PROJECT_CODING_RUN_ENDPOINT_INIT],
        pre_capture_js=(
            "const root = document.querySelector('[data-testid=\"project-workspace-runs\"]');"
            "const scheduled = [...root.querySelectorAll('*')].find((el) => /^Scheduled Reviews$/.test((el.textContent || '').trim()));"
            "if (scheduled) scheduled.scrollIntoView({ block: 'start' });"
            "await new Promise((resolve) => setTimeout(resolve, 160));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Scheduled Reviews') "
            "&& text.includes('Recurring Project coding runs') "
            "&& text.includes('Weekly Project review') "
            "&& text.includes('+1w') "
            "&& text.includes('3 runs') "
            "&& text.includes('Last run: complete') "
            "&& text.includes('RECENT RUNS') "
            "&& text.includes('Paused dependency sweep') "
            "&& text.includes('Resume') "
            "&& text.includes('Edit') "
            "&& text.includes('Execution access: E2E Codex Target') "
            "&& text.includes('Run now') "
            "&& text.includes('Disable'), "
            "detail: 'Project Runs tab did not expose scheduled review controls and provenance' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-execution-access",
        route="/admin/projects/{project_workspace_project}#Runs",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-runs\"]') "
            "&& document.body.innerText.includes('Start new work') "
            "&& document.body.innerText.includes('New run')"
        ),
        output="project-workspace-execution-access.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[_PROJECT_CODING_RUN_ENDPOINT_INIT],
        pre_capture_js=(
            "const pageRoot = document.querySelector('[data-testid=\"project-workspace-runs\"]');"
            "const newRun = pageRoot && [...pageRoot.querySelectorAll('button')].find((button) => /^New run$/.test((button.textContent || '').trim()));"
            "if (newRun) newRun.click();"
            "await new Promise((resolve) => setTimeout(resolve, 180));"
            "const root = document.querySelector('[data-testid=\"project-run-execution-access\"]');"
            "const trigger = root && root.querySelector('button[aria-haspopup=\"listbox\"]');"
            "if (trigger) trigger.click();"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
            "const option = [...document.querySelectorAll('[role=\"option\"]')].find((item) => /Spindrel e2e target/.test(item.textContent || ''));"
            "if (option) option.click();"
            "await new Promise((resolve) => setTimeout(resolve, 160));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Execution access') "
            "&& text.includes('Spindrel e2e target') "
            "&& text.includes('inspect') "
            "&& text.includes('exec') "
            "&& text.includes('Agent tools') "
            "&& text.includes('Grant is attached only to the task being launched.'), "
            "detail: 'Project coding-run launch did not expose task-scoped e2e machine access' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-review-launched",
        route="/admin/projects/{project_workspace_project}#Runs",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-runs\"]') "
            "&& document.body.innerText.includes('Prepare the Project workspace screenshot receipt') "
            "&& document.body.innerText.includes('Ask agent to review')"
        ),
        output="project-workspace-review-launched.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[_PROJECT_CODING_RUN_ENDPOINT_INIT],
        pre_capture_js=(
            "const root = document.querySelector('[data-testid=\"project-workspace-runs\"]');"
            "const box = [...root.querySelectorAll('input[type=\"checkbox\"]')].find((input) => input.getAttribute('aria-label'));"
            "if (box && !box.checked) { box.scrollIntoView({ block: 'center' }); await new Promise((resolve) => setTimeout(resolve, 80)); box.click(); }"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
            "const start = [...root.querySelectorAll('button')].find((button) => /Ask agent to review/.test(button.textContent || ''));"
            "if (start) start.click();"
            "await new Promise((resolve) => setTimeout(resolve, 350));"
            "const launched = [...root.querySelectorAll('*')].find((el) => /Review agent started/.test(el.textContent || ''));"
            "if (launched) launched.scrollIntoView({ block: 'center' });"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: /\\d+ selected/.test(text) "
            "&& text.includes('Review agent started') "
            "&& text.includes('Review agent task created') "
            "&& text.includes('screenshot') "
            "&& text.includes('Ask agent to review') "
            "&& text.includes('Close on our side'), "
            "detail: 'Project Runs tab did not show a launched agent review session' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-review-execution-access",
        route="/admin/projects/{project_workspace_project}#Runs",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-runs\"]') "
            "&& document.body.innerText.includes('Prepare the Project workspace screenshot receipt')"
        ),
        output="project-workspace-review-execution-access.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[_PROJECT_CODING_RUN_ENDPOINT_INIT],
        pre_capture_js=(
            "const root = document.querySelector('[data-testid=\"project-workspace-runs\"]');"
            "window.scrollTo(0, document.body.scrollHeight);"
            "await new Promise((resolve) => setTimeout(resolve, 160));"
            "const batchTools = [...root.querySelectorAll('button')].find((button) => /^Batch tools$/.test((button.textContent || '').trim()));"
            "if (batchTools) { batchTools.click(); await new Promise((resolve) => setTimeout(resolve, 160)); }"
            "const box = [...root.querySelectorAll('input[type=\"checkbox\"]')].find((input) => input.getAttribute('aria-label'));"
            "if (box && !box.checked) { box.scrollIntoView({ block: 'center' }); await new Promise((resolve) => setTimeout(resolve, 80)); box.click(); }"
            "await new Promise((resolve) => setTimeout(resolve, 220));"
            "const access = document.querySelector('[data-testid=\"project-review-execution-access\"]');"
            "const trigger = access && access.querySelector('button[aria-haspopup=\"listbox\"]');"
            "if (trigger) trigger.click();"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
            "const option = [...document.querySelectorAll('[role=\"option\"]')].find((item) => /Spindrel e2e target/.test(item.textContent || ''));"
            "if (option) option.click();"
            "if (access) access.scrollIntoView({ block: 'center' });"
            "await new Promise((resolve) => setTimeout(resolve, 160));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('1 selected') "
            "&& text.includes('Agent review prompt') "
            "&& text.includes('Execution access') "
            "&& text.includes('Spindrel e2e target') "
            "&& text.includes('Task-scoped existing target grant') "
            "&& text.includes('Ask agent to review'), "
            "detail: 'Project review launch did not expose task-scoped e2e machine access' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-review-finalized",
        route="/admin/projects/{project_workspace_project}#Runs",
        viewport={"width": 1440, "height": 1000},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"project-workspace-runs\"]') "
            "&& document.body.innerText.includes('Prepare the Project workspace screenshot receipt') "
            "&& document.body.innerText.includes('PR merged')"
        ),
        output="project-workspace-review-finalized.png",
        color_scheme="dark",
        full_page=True,
        extra_init_scripts=[
            "window.__PROJECT_REVIEW_FINALIZED__ = true;",
            _PROJECT_CODING_RUN_ENDPOINT_INIT,
        ],
        pre_capture_js=(
            "const root = document.querySelector('[data-testid=\"project-workspace-runs\"]');"
            "const runRow = root && [...root.querySelectorAll('*')].reverse().find((el) => /Prepare the Project workspace screenshot receipt/.test(el.textContent || '') && /PR merged/.test(el.textContent || ''));"
            "if (runRow) runRow.scrollIntoView({ block: 'center' });"
            "await new Promise((resolve) => setTimeout(resolve, 120));"
        ),
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Review: reviewed') "
            "&& text.includes('PR merged') "
            "&& text.includes('checks passed') "
            "&& text.includes('merge squash') "
            "&& text.includes('commit abc1234') "
            "&& text.includes('review task screensh') "
            "&& text.includes('Progress: PR: ready') "
            "&& text.includes('PR / handoff'), "
            "detail: 'Project Runs tab did not expose finalized review and merge provenance' };"
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
            "const text = document.body.innerText.toLowerCase();"
            "return { ok: text.includes('create channel') "
            "&& text.includes('attach existing channel') "
            "&& text.includes('channel') "
            "&& text.includes('detach'), "
            "detail: 'Project Channels tab did not expose membership controls' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-channel-settings",
        route="/channels/{project_workspace}/settings#agent",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "document.body.innerText.includes('Primary Project') "
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
            "(document.body.innerText.includes('Replace Section memory/MEMORY.md') "
            "|| document.body.innerText.includes('Project workspace screenshot memory fact') "
            "|| document.body.innerText.toLowerCase().includes('memory was updated'))"
        ),
        output="project-workspace-memory-tool.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('Project') "
            "&& (text.includes('Replace Section memory/MEMORY.md') "
            "|| text.includes('memory was updated') "
            "|| text.includes('Project workspace screenshot memory fact')), "
            "detail: 'Memory tool transcript was not visible' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-channel-header",
        route="/channels/{project_workspace}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"channel-header-title-region\"]') "
            "&& !!document.querySelector('button[title^=\"Open Project: Screenshot Project Workspace\"]') "
            "&& (document.body.innerText.includes('Project workspace screenshot memory fact') "
            "|| document.body.innerText.includes('The memory was updated.'))"
        ),
        output="project-workspace-channel-header.png",
        color_scheme="dark",
        assert_js=(
            "const badge = document.querySelector('button[title^=\"Open Project: Screenshot Project Workspace\"]');"
            "return { ok: !!badge "
            "&& (badge.textContent || '').includes('Screenshot Project Workspace'), "
            "detail: 'Channel header did not expose the subtle Project badge link' };"
        ),
    ),
    ScreenshotSpec(
        name="project-workspace-context-mentions",
        route="/channels/{project_workspace}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "!!document.querySelector('[data-testid=\"chat-composer-drop-zone\"]') "
            "&& document.body.innerText.includes('Project workspace demo')"
        ),
        output="project-workspace-context-mentions.png",
        color_scheme="dark",
        actions=[
            Action(kind="wait", value="700"),
            Action(kind="click", selector=".tiptap-chat-input [contenteditable=\"true\"]"),
            Action(kind="type", selector=".tiptap-chat-input [contenteditable=\"true\"]", value="@README"),
            Action(kind="wait", value="1200"),
        ],
        assert_js=(
            "const rows = [...document.querySelectorAll('[data-testid=\"llm-prompt-autocomplete-row\"]')];"
            "const text = document.body.innerText;"
            "return { ok: rows.some((row) => row.getAttribute('data-completion-value') === 'file:README.md') "
            "&& text.includes('Project file'), "
            "detail: 'Project file context completion did not appear in the composer @ picker' };"
        ),
    ),
    ScreenshotSpec(
        name="project-factory-dogfood-planning",
        route="/channels/{project_factory_dogfood}",
        viewport={"width": 1440, "height": 900},
        wait_kind="function",
        wait_arg=(
            "document.body.innerText.includes('Project factory dogfood planning') "
            "&& document.body.innerText.includes('Created 2 proposed Work Packs') "
            "&& document.body.innerText.includes('Dogfood code pack')"
        ),
        output="project-factory-dogfood-planning.png",
        color_scheme="dark",
        assert_js=(
            "const text = document.body.innerText;"
            "return { ok: text.includes('@file:.spindrel/factory-plan.md') "
            "&& text.includes('@project:dependencies') "
            "&& text.includes('Triage receipt') "
            "&& text.includes('needs-info'), "
            "detail: 'Dogfood planning transcript did not show explicit context and Work Pack creation' };"
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
            ' && document.querySelectorAll(\'[data-testid="home-recent-session-row"]\').length >= 3'
            ' && document.querySelectorAll(\'[data-testid="home-user-row"]\').length >= 2'
            ' && !!document.querySelector(\'[data-testid="home-users-section"]\')'
            ' && !!document.querySelector(\'[data-testid="home-unread-center"]\')'
            ' && /Recent sessions|Unread center|Users/i.test(document.body.innerText)'
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
        route="/spatial",
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
        route="/spatial",
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
        route="/spatial",
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
