---
tags: [agent-server, track, docs, screenshots, video, active]
status: active
updated: 2026-04-25 (A2.5-setup TUI: synthetic terminal-frame rig — PIL canvas + JetBrainsMono + AST-parsed PROVIDERS keep the wizard captures drift-resistant)
---

# Track - Quickstart Video

## North Star
A current, reproducible quickstart video regenerated weekly, backed by a living visual asset library that keeps pace with the product. The video stitches rendered documentation pages + product screenshots + (later) voice-overs + terminal recordings into a ~2-3 minute "how to use Spindrel" piece, one command away.

## Why this track exists
The screenshot pipeline shipped 2026-04-24 (`scripts/screenshots/`) with a flagship 8 — enough to prove staging + capture, nowhere near enough to tell the full product story. And screenshots alone aren't the end state: the user's vision is a regenerable video that walks a new user through setup → first channel → first widget → first pipeline, mixing product stills with rendered docs prose and eventually voiced narration.

Two parallel efforts advance in lockstep each week:

- **Track A — Visual Asset Library**: grow screenshot scope from 8 → 40+, add variants (dark, mobile, annotated), keep them current.
- **Track B — Video System**: grow the compositor from stills-only → doc-view + interaction recordings + TTS + publish pipeline.

Track A feeds Track B. Track B gives Track A a consumer that justifies the scope growth.

This track supersedes the **video-generation** scope of `Track - Docs Refresh.md` only. Docs Refresh keeps its prose/guides scope and closes on its own Phase F; the growing asset library and the video compositor live here as an evergreen scope.

## Status

| Phase | Track | Area | Status |
|---|---|---|---|
| A1 | A | Flagship 8 (screenshot pipeline baseline) | **done** — shipped 2026-04-24 |
| A-cap | A | Interaction-aware capture specs (`actions:` hook + `check` drift gate) | **done** — shipped 2026-04-24; 9 `DOCS_REPAIR_SPECS` ready, scaffolding landed in `capture/specs.py` + `capture/runner.py` + `check_drift.py` |
| A2.5 | A | Unbreak 9 broken docs image links | **done** — shipped 2026-04-24; 9/9 captures landed in `docs/images/` after three iteration passes (route fixes, tab-selector fixes, wait-on-skeleton fixes). Drift check clean for `docs/guides/*`. |
| A2 | A | Integration hero shots (admin-detail pass) | **done** — shipped 2026-04-24; reworked from 8 templated captures (all looked identical in the "Available - not adopted" zero-state) down to 5 differentiated heroes: `integrations-library.png` (17-card Library catalog), `integrations-active.png` (4 adopted, grouped Needs Setup/Ready), `integration-github.png` (ENABLED + 9 events + missing-secrets banner), `integration-homeassistant.png` (ENABLED + 6 tool widgets), `integration-frigate.png` (NEEDS SETUP + webhook + 8 tools + 1 skill). Now uses real adoption: `stage_integrations` enables 4 curated integrations via `PUT /api/v1/admin/integrations/{id}/status`. Hash-routed list views (`#library`, `#active`) bypass tab-click stale styling. Cleanup: deleted 86 stale `chat:e2e:*` channels so the channel sidebar shows a real DAILY/HOME/SHOWCASE/WORK product environment. |
| A2-channel | A | In-channel widget heroes (frigate cameras grid, HA dashboard tiles, github PR card) | later — requires seeding persisted tool-result messages with widget envelopes; admin-detail pass covers the docs-guide need for now |
| A2.5-setup | A | 8 missing `docs/setup.md` images | **partially shipped 2026-04-25** — 5 of 8 done. (1) `providers-screen-v1.png` resolved by retargeting setup.md to existing `providers-settings.png`. (4) TUI-walkthrough captures (`setup-1`, `setup-3-modelname`, `setup-4-websearch-select`, `setup-5-start`) shipped via new synthetic terminal-frame rig (`scripts/screenshots/capture/tui_render.py` + `tui_frames.py`, `--only setup-tui`). Remaining 3 are onboarding-flow UI shots (`setup-6-login-screen`, `setup-7-first-channel`, `setup-10-first-chat`) — need fresh-instance staging since the test instance is already onboarded. |
| A3-docs | A | Docs-gap-ordered feature deep-dives (10 captures) replacing prior A3 list | **in-progress** — 5 of 8 shipped 2026-04-24: `providers-settings.png`, `pipeline-library.png`, `approvals-queue.png` (admin slice, zero-staging); `workspace-files.png` (Default Workspace explorer with `bots/channels/common/integrations/users` tree); `skill-detail.png` (`/admin/skills/widgets%2Fhtml` — emit_html_widget, full markdown + frontmatter + triggers). Remaining: `knowledge-base` (deferred — orchestrator KB empty, needs content seeding), `pipeline-run-detail` (needs completed sub-session card), `setup-wizard` (terminal frame / manual capture). `usage-and-budgets` already covered by `usage-and-forecast.png` from A2.5. `dev-panel-widget` already covered by `dev-panel-tools.png` from A1. |
| A3-core | A | Core-feature heroes — admin sub-pass 1 (2 captures) | **done** — shipped 2026-04-24; `webhooks-list.png` (3 seeded webhooks with varied event-filter chips) + `tools-library.png` (Local section with full tool catalog, type badges, dates) wired into `webhooks.md` + `custom-tools.md`. New scenario `stage_core_features` seeds + tears down webhook rows by exact-name dedupe. |
| A3-core-2a | A | Core-feature heroes — KB inventory hero | **done** — shipped 2026-04-24; `kb-detail.png` (Memory & Knowledge → Knowledge tab, filtered to seeded "Orion" row showing "4 files / 8 chunks / 12m ago" + path prefix `bots/screenshot-orchestrator/knowledge-base`) wired into `knowledge-bases.md`. Two new server helpers (`seed_bot_knowledge_chunks.py` + `clear_bot_knowledge_chunks.py`) insert/delete `FilesystemChunk` rows directly — embeddings are NULL because the inventory page only counts. Helpers call `load_bots()` first because the registry is server-startup-populated and the helper subprocess is fresh. Prefix is computed via `workspace_service.get_bot_knowledge_base_index_prefix(bot)` so shared-workspace bots (Orion is one) get `bots/<id>/knowledge-base` and standalone bots get `knowledge-base` — same source the inventory route queries. |
| A3-core-2b | A | Core-feature heroes — chat-content sub-pass (4 captures) | **done** — shipped 2026-04-24 via the live agent loop (path (1) — user reversed the synthetic-injection recommendation, "I dont mind incurring some llm cost if it will help get faster/better results"). New `client.seed_turn(channel_id, message, expected_tool, ...)` primitive resets the channel session, posts the prompt via `/chat`, polls `/channels/{id}/state` for primary `active_turns` to drain, then asserts the latest assistant message's `tool_calls[]` includes the named tool. Four dedicated channels (`screenshot:chat-{delegation,cmd-exec,plan,subagents}`) so reruns don't pollute each other or flagship's `chat-main`. All run on `gemini-2.5-flash` (LiteLLM-routed, since the e2e instance has no Anthropic provider — the bot's default `claude-sonnet-4-6` 404s); Vega the delegate uses `gemini-2.5-flash-lite`. Captures: `chat-delegation` (DelegationCard "Delegated to vega"), `chat-command-execution` (EXEC COMMAND badge + raw stdout in fenced block), `chat-plan-card` (SessionPlanCard with PLANNING pill + 4-step checklist + "Approve & Execute" CTA — published into `/docs/planning/session-plan-mode.md` since `/docs/guides/plan-mode.md` is a stub redirect), `chat-subagents` (SPAWN SUBAGENTS badge + synthesis above an inline subagent WEB SEARCH row). Wired into `delegation.md` / `command-execution.md` / `subagents.md` / `session-plan-mode.md`. All four double as B-roll for the quickstart video. |
| A4 | A | UI archetype variants (dark + mobile) | later |
| A5 | A | Admin / ops captures (6–8) | later |
| A6 | A | Callout-annotated variants + `capture/annotate.py` | later |
| B1 | B | Still-kind proof video (first shippable) | **done** — shipped 2026-04-24; 24.6s mp4 at `docs/videos/quickstart.mp4` |
| B2 | B | Doc-view scenes via mkdocs (doc_hero, doc_callout) | **done** — shipped 2026-04-24; `scripts/screenshots/video/mkdocs_server.py` runs one `mkdocs serve --no-livereload` for the lifetime of the build, `_doc_capture.py` drives Playwright sync (DPR=1 viewport) for full-page hero captures and viewport-clipped callout captures with an injected indigo box-shadow ring, `clips/doc_hero.py` pans top→bottom over a tall page via a new `fit="width"` mode in `still._ken_burns_clip`, `clips/doc_callout.py` zooms into the highlight bbox using cx/cy resolved from the live page. Scenes promoted into `quickstart.yml`: `doc_widget_system` (callout on `guides/widget-system.md` h1) + `doc_index_hero` (full-page pan over `guides/index.md`). Total runtime grew 24.6s → ~40s. Per-scene `color_scheme: light\|dark` switches mkdocs-material's palette via `data-md-color-scheme` set in an `add_init_script` so the very first paint is correct (cookie-priming wasn't reliable). Cache lives at `scripts/screenshots/.cache/doc_views/<scene>-<scheme>.png`. |
| B3 | B | Playwright interaction recordings + manual slots | later |
| B4 | B | TTS voice-over | later |
| B5 | B | Publish pipeline + weekly regen automation | later |

## Known follow-ups

- **Preview render perf**: at 1920×1080 the per-frame PIL crop+resize runs ~3 fps render speed, so a 6s scene takes ~60s to preview. Acceptable for B1 proof; a `--fast` flag dropping preview to 720p@15 would cut the feedback loop to <15s. Defer until the cadence proves it matters.
- **A2 Gmail replacement → `bluebubbles-thread`** (decided 2026-04-24). BlueBubbles binding + HUD is already required for A2.5's `channel-bluebubbles-hud.png`, so the staging amortizes across both phases.
- **`bot_skills` seed helper** (surfaces in `bot-skills-learning-1.png` as an empty "Bot-Authored Skills" section). The `/admin/skills` POST populates the catalog but not the per-bot surfacing-counts table `bot_skills` that drives the learning analytics view. A thin `server_helpers/seed_bot_skills.py` writing N rows with fake `surfacing_count`, `last_surfaced_at`, and `health_score` values would fill that panel. Parked — ship the structural frame now, iterate when the guide rewrite rolls through.
- **CLI argparse bug fixed 2026-04-24**: `--only` was being swallowed by the `rest` REMAINDER arg for the video subcommand. Switched to `parse_known_args()`; `video` still gets its tail via `unknown`, and top-level flags like `--only` now reach their parser.
- **Lessons from the first live run** (recorded so the next batch doesn't repeat them):
  - Channel settings are at `/channels/{id}/settings#<tab>` (hash-based), not `?tab=`. Tab keys are `channel|agent|presentation|dashboard|knowledge|memory|automation|context|logs`. Heartbeat lives inside **automation**; history-mode inside **memory**.
  - Secrets route is `/admin/secret-values` (plural "values"), not `/admin/secrets`.
  - `/admin/learning` tab keys are CamelCase (`#Skills`, `#Dreaming`, `#History`).
  - Integration detail pages are at `/admin/integrations/<slug>` (e.g. `.../ingestion`) — no drawer click needed.
  - Playwright `page.wait_for_selector` does NOT support mixing `text=` syntax into a CSS comma-union. Use either plain CSS or a JS function wait.
  - Skeleton/loading states use Tailwind `.animate-pulse`, not `.animate-spin`. Wait on both to disappear for clean captures.
  - **A2 admin-detail captures need no staging** — `/admin/integrations/<slug>` renders from the registry populated at server startup. `_run_stage`/`_run_teardown` short-circuit when `only="integrations"`; `_run_capture` skips the channel placeholder lookups. Pattern reusable for any future "admin route + manifest-driven content" capture.
  - **HomeAssistant manifest name** displays as `Homeassistant` (single word) in the page header — minor copy issue in the integration's `name:` field, not a screenshot bug. Out of scope here; fix in `integrations/homeassistant/integration.yaml` when guides start citing this image.
  - **`Activity & Debug` "Loading tasks..." persists** on the HA capture; the section lazy-fetches after the visible viewport. Acceptable since hero content (Overview, Manifest, Detected Assets) renders cleanly above. If a future caption pulls in the Activity section, extend the wait predicate to require absence of "Loading tasks..." text.
  - **A2 rework lesson — adopt before you capture.** The first 8 admin-detail captures all looked templated because every integration was in the universal "Available - not adopted" zero-state, with capability badges styled by manifest (not lifecycle). Reduced scope to 5 differentiated heroes after adopting 4 curated integrations (`github`, `homeassistant`, `frigate`, `web_search`). Hash-routed list views (`/admin/integrations#library` and `#active`) avoid stale tab styling that `page.click("text=Library")` produces.
  - **Channel sidebar hygiene matters for hero shots.** First A2 captures leaked 22+ `chat:e2e:*` rows + dbg-/e2e-/default residue into the sidebar — looked like an unmaintained dev box. Cleanup script: `client.list_channels()` → keep only `screenshot:*` + `orchestrator:home`, `DELETE /api/v1/channels/{id}` on the rest. Bring this in as a `--purge-test-channels` helper if reruns get flaky from new e2e cron ticks.
  - **`full_page=True` doesn't reach inner-scroll containers.** Detail-page screenshots truncate the Configuration / Env vars sections because `RefreshableScrollView` uses `overflow-hidden flex-1`. Workarounds: taller viewport (1100→1600), patch runner to scroll inner container, or accept the truncation. Parked — none of the A2 captions need below-fold content.
  - **A3-docs admin slice gotcha — heavy list endpoints stick the spinner.** `/admin/approvals` defaults to `status=all` which returns hundreds of historical e2e-test rows on this instance; the `Spinner` component stayed mounted past the 15s wait timeout. Workaround: `Action(kind="click", selector="button:has-text('Pending')")` to switch to a lighter query (Pending is empty on a quiet instance, renders the empty-state copy fast). Same trick will apply to any future capture that hits a high-cardinality endpoint — switch to a filtered tab via action before the screenshot.
  - **Tab-state gotcha on segmented controls.** After click-action selects a new tab, the `useApprovals` re-query resolves and the empty-state renders, but the segmented-control visual doesn't always paint the new tab as the highlighted pill before screenshot. Acceptable for a docs hero (the empty-state copy itself reads "No approvals with status \"pending\"." which makes the active filter unambiguous). If a future capture needs the visual pill highlighted, add an extra `wait_for` on `[data-state="active"]` or equivalent attribute.
  - **Slashy skill IDs need URL-encoding.** Routes like `/admin/skills/widgets/html` resolve `widgets` as an entity and 404 inside it. Use `widgets%2Fhtml` in the spec route. The CLI's `resolve_specs` doesn't auto-encode placeholders — bake the encoding into the spec literal.
  - **Workspace ID resolution at capture time.** `/admin/workspaces/<uuid>/files` needs the Default Workspace UUID, which differs per instance. `_run_capture` calls `client.list_workspaces()` and substitutes `{default_workspace}` from the first row. Use `/api/v1/workspaces` (no admin prefix — `/api/v1/admin/workspaces` returns 404).
  - **Skeletons aren't always `animate-pulse`.** `bot-skills-learning-1`'s wait predicate gated on `.animate-pulse` and `.animate-spin` being absent — both never present, so it captured the loading state every time. The actual skeletons are `h-14 rounded-md bg-surface-raised/35` divs. Fix: gate on resolved-state markers (StatGrid labels "Surfacings"/"Auto-injects"/"Unused", catalog rows showing "N uses"), not the absence of skeleton classes. Whenever a wait predicate ships, verify it captures the loaded state — never just "no spinner".
  - **Auto-purge on every capture run.** `client.purge_test_channels()` runs at the start of `_run_capture` for every scenario; allow-list keeps `screenshot:*` + `orchestrator:*` + `default`, deletes the rest (covers `chat:e2e:*`, `e2e-test:*`, `dbg-*`, `frag-*`, `smoke-*`, etc.). Idempotent — clean instances are a no-op. Without this, the channel sidebar in any chrome-rendered capture leaks test-runner debris from overnight cron ticks.
  - **`text-transform: uppercase` and `innerText`.** Chromium's `innerText` reflects rendered text-transform, so a label rendered as "SURFACINGS" comes back as "SURFACINGS" — case-insensitive regex (`/Surfacings/i`) is required. `textContent` would still return the source case but doesn't reflect render order; stick with `innerText` + `i` flag.
  - **The drift gate doesn't catch missing heroes.** `python -m scripts.screenshots check` only verifies *referenced* images exist — it can't tell you that 40 guides ship with zero images. Fixed 2026-04-24 by walking every `docs/guides/*.md` and wiring shipped captures into 17 of them: `providers`, `pipelines`, `tool-policies`, `homeassistant`, `widget-dashboards`, `widget-system`, `dev-panel`, `discovery-and-enrollment`, `task-sub-sessions`, `templates-and-activation`, `how-spindrel-works`, `integrations`, `integration-status`, `index`, `html-widgets`, `chat-state-rehydration`, `pwa-push`. After: 24 guides still image-less, all needing NEW captures (mostly per-integration heroes for `slack`, `discord`, `excalidraw`, `browser-live`, `local-machine-control`, plus reference guides where a hero may not even fit). Future drift-gate enhancement: surface guides with zero `![...](...)` references so this gap is visible from CI, not from a manual sweep.
  - **Drift gate gained `--require-hero` (2026-04-24).** `python -m scripts.screenshots check --require-hero` walks `docs/guides/*.md`, skips a small allow-list of intentionally text-only reference docs (`api`, `clients`, `feature-status`, `ubiquitous-language`, `ui-design`, `ui-components`, `context-management`, `development-process`, `e2e-testing`, `plan-mode`, `programmatic-tool-calling`, `workflows`), and exits non-zero on any other guide with zero `![...]` references. Today reports 10 still image-less: 6 integration guides (slack/discord/excalidraw/browser-live/gmail/local-machine-control — deferred per the user's "core features first" framing) + 4 core-feature guides (`command-execution`, `delegation`, `knowledge-bases`, `subagents` — the chat-content sub-pass A3-core-2 covers these). The allow-list is the single editing surface — adding/removing a guide from text-only status is a one-line change.
  - **Webhook seed dedupe via exact-name match.** The webhook model has no `client_id` and the admin API doesn't enforce name-uniqueness, so reruns must dedupe client-side. `ensure_webhook` greps `list_webhooks()` by exact `name` before inserting; teardown matches the same names. First pass shipped with names prefixed `screenshot:` for namespace clarity, but the prefix bled into the docs hero — re-shot with prefixless names. Lesson: when a model lacks a stable namespace marker, prefer descriptive product names + an internal allow-list, not synthetic prefixes that show up in captures.
  - **Tools-library count chip "0 tools" matches `\d+ tools` while loading.** Same trap as bot-skills-learning, different surface: the count chip renders "0 tools" before `useTools` resolves, so a `\d+\s+tools?` regex passes during the loading state. Fix: require the integer match to be > 0 — `/(?:^|\s)([1-9]\d*)\s+tools?\b/i` — and additionally gate on a section header being rendered (`\bLocal\b/i`). The `i` flag is non-negotiable because `text-transform: uppercase` makes the section header render as "LOCAL" in `innerText`.
  - **Knowledge Library inventory only counts FilesystemChunk rows, no embeddings needed.** `/admin/learning/knowledge-library` aggregates `(COUNT(DISTINCT file_path), COUNT(*), MAX(indexed_at))` filtered by `bot_id` + `file_path LIKE prefix/%`. The screenshot helper inserts rows directly with `embedding=NULL` and a hashed `content_hash` per chunk — no embedder dependency, no reindex step. The catch: prefix differs per bot (`knowledge-base` for standalone, `bots/<id>/knowledge-base` for shared-workspace). Compute it via `workspace_service.get_bot_knowledge_base_index_prefix(bot)` so the seeder stays in lockstep with the inventory route. Two-step debugging on first run: (1) helper bot lookup failed because the registry is hydrated only at server startup — fix is `await load_bots()` in the helper before `get_bot()`; (2) seeded chunks didn't show because Orion is shared-workspace and my hardcoded `knowledge-base/` prefix doesn't match its `bots/<id>/knowledge-base/` index prefix — fix is to compute via the same workspace_service call.
  - **Default sort + viewport crop hides the seeded row.** `/admin/learning#Knowledge` sorts alphabetically by `owner_name`, so on a shared instance with `Dbg`/`Default`/`E2E*`/`EOD*` bots seeded by other suites, the screenshot bot ("Orion", `O...`) renders below the 1440x900 fold. Fix: drive the existing search input via `Action(kind="fill", ...)` to filter to the seeded row. The same pattern (use the page's own search/filter UI to surface the screenshot subject) generalizes to any high-cardinality inventory route — admin/skills, admin/tools, admin/bots — where alphabetical defaults bury the demo bot.
  - **Live agent loop > synthetic message injection for chat-content captures (A3-core-2b).** Reversal of the prior recommendation. Synthetic injection requires hand-rolling `assistant_turn_body` items + `tool_calls[]` ids + `tool_results[]` envelopes per capture, and any drift in the modern OrderedTranscript renderer silently breaks the hero. Driving `/chat` with a tightly-prompted user message and asserting the named tool fires is more robust: real persisted shapes, no spelunking, and re-runs naturally adapt to renderer changes. Cost is ~1¢ per Flash-tier run × 4 captures = trivial. Two model gotchas burned an hour: (1) the e2e instance has no Anthropic provider, so any bot defaulting to `claude-sonnet-4-6` 404s — explicitly pin `model="gemini-2.5-flash"` + `model_provider_id="gemini"` on every chat-content stager; (2) Gemini Flash silently fails (returns "I had trouble generating a response") on plan-mode publish-plan calls when the prompt is open-ended, because plan-mode's heavy system prompt + the publish_plan schema together overflow what Flash can compose without hand-holding — pre-fill the exact title/summary/scope/steps in the user prompt and tell it "do not ask any clarifying questions".
  - **Subagent ephemeral child turns leak typing cursors into the parent capture.** `spawn_subagents` schedules `_subagent_*` sub-sessions whose turn entries land in the parent channel's `active_turns` with `is_primary=False`, AND whose WEB SEARCH / READ rows render inline on the parent channel while still in flight. Naive "wait for active_turns to drain" timed out at 240s because subagents can take 90+ seconds each; if you only filter by `is_primary=True` the parent message is finalized but the inline subagent row still shows a typing cursor at capture time. Fix: a two-phase wait — first drain primary turns (so the parent's tool_calls assertion can run), then optionally drain ALL turns with a separate `subagent_timeout_s` budget so the subagent's body paints fully before screenshot. Best-effort second phase: timeout exits silently (partial render is the worst case, not a broken capture).
  - **`sessions.router` is mounted at `/sessions` not `/api/v1/sessions`.** Bit me when wiring `start_session_plan_mode` for the chat-plan-card capture. Plan-mode start endpoint is `POST /sessions/{sid}/plan/start`. The session list/messages endpoints under `/api/v1/sessions/{sid}/messages` are a SEPARATE router. Two-router split is intentional — the plan-mode router predates the API versioning convention.
  - **B2 lesson — full-page captures dwarf PIL's bomb threshold.** Long mkdocs guides like `widget-system.md` render at 1920×46k at DPR=2, which is 177M pixels — past PIL's default `MAX_IMAGE_PIXELS` (89M) and past the point where Ken Burns at 30fps stays interactive. Two fixes: drop `device_scale_factor` to 1 in the doc-view Playwright context (output is 1080p anyway, supersampling adds nothing for video) and set `Image.MAX_IMAGE_PIXELS = None` in `still.py` since these are first-party renders, never untrusted input. The 1920×23k cache PNG is fine.
  - **B2 lesson — `_ken_burns_clip` needed a `fit` mode for tall sources.** The original `_center_fit` always crops to output aspect, which is right for a 1920×1200 hero still but squashes a 1920×23000 full-page capture into 1080p, destroying readability. Added `fit="width"` that scales source to output width and lets height grow; the per-frame crop window then derives `crop_h` from `out_h` rather than `src_h` so each rendered frame stays at output aspect regardless of source height. doc_hero passes `fit="width"`; still continues to use the default `fit="cover"`.
  - **B2 lesson — mkdocs livereload injects scripts into the captured HTML.** Without `--no-livereload`, every page mkdocs serves wires up a websocket-reload `<script>` tag that doesn't render visually but slows `wait_until="networkidle"` since the socket never closes. The `mkdocs_serve` context manager passes `--no-livereload` and the screenshots come back faster + cleaner.
  - **B2 lesson — color scheme via `add_init_script`, not cookie priming.** mkdocs-material persists scheme via the `__palette` cookie, but Playwright contexts start with an empty cookie jar — so the first paint is always the default (slate, in our config). Setting `data-md-color-scheme` on `<html>` and `<body>` via `context.add_init_script(...)` makes the first paint correct without a redirect/reload dance.
  - **B2 lesson — port reuse for an already-running mkdocs.** A common dev workflow has `mkdocs serve` running in a separate shell. `mkdocs_server.py` checks `bind` on the configured port; if it's already taken, it probes `/` for a 200 and reuses the URL rather than failing. The reuse path skips the subprocess teardown — leaving the user's dev server alone is the correct behavior.

## Interleaved weekly cadence

Each week is a small dose of both tracks — neither stands alone.

- **Week 0 (this week)**: A1 done, ship B1 (4-scene still proof, ~22s).
- **Week +1**: A2 (integration hero shots) + start B2.
- **Week +2**: finish B2 (doc-view scenes working) + A3 (feature deep-dives).
- **Week +3**: A6 (annotated variants — needed for doc_callout polish) + A4 (dark-mode pairs).
- **Week +4**: B3 (interaction recordings + manual slots) + A5 (admin/ops).
- **Week +5**: B4 (TTS).
- **Week +6**: B5 (publish pipeline) — first fully-automated weekly regen.

After Week +6 the loop is additive: each week adds ~3 new captures (new integrations, new archetypes, polished areas) and maybe one storyboard edit.

## Phase detail

### Phase A1 — Flagship 8 (done)
`home`, `chat-main`, `widget-dashboard`, `chat-pipeline-live`, `html-widget-hero`, `dev-panel-tools`, `omnipanel-mobile`, `admin-bots-list`. Baseline — staged via HTTP stagers, captured via Playwright, idempotent + teardown-clean.

### Phase A-cap — Interaction-aware specs + drift gate (done 2026-04-24)

Three capture-capability additions landed same session as A2.5 scaffolding:

- `Action` dataclass + `actions: list[Action]` field on `ScreenshotSpec` (`scripts/screenshots/capture/specs.py`). Five primitives: `click`, `fill`, `press`, `select`, `wait_for`.
- `_run_actions()` executor in `scripts/screenshots/capture/runner.py`, invoked after `wait_for` and before `page.screenshot`. Fails loud — no sleeps, no silent skips. Capture failures surface as `wait-timeout` results with the offending action in `detail`.
- `scripts/screenshots/check_drift.py` + `python -m scripts.screenshots check` — scans `docs/**/*.md` for `![](...png)` refs, verifies each exists, exits non-zero on miss. Immediately surfaced 17 broken refs (9 in guides → A2.5; 8 in `docs/setup.md` → A2.5-setup).

Unblocks modal/drawer/tab captures without taking on B3's video-clip scope. Reusable by B3's `playwright_action` clip — same `Action` dataclass.

### Phase A2.5-setup — Setup walkthrough captures (TUI shipped 2026-04-25)

5 of 8 missing `docs/setup.md` heroes shipped; 3 remain.

**Shipped (5):**

| File | Approach | Notes |
|---|---|---|
| `providers-screen-v1.png` | Reuse | `docs/setup.md` retargeted to existing `providers-settings.png` (same admin route). |
| `setup-1.png` | Synthetic TUI | Banner + prereq check + LLM Provider select with 7 providers (OpenAI highlighted). |
| `setup-3-modelname.png` | Synthetic TUI | Default model select after picking OpenAI (gpt-4.1 highlighted). |
| `setup-4-websearch-select.png` | Synthetic TUI | Web search backend select (SearXNG built-in highlighted). |
| `setup-5-start.png` | Synthetic TUI | Final confirm + service-up output (provider-seed.yaml notice + green ✓ http://localhost:8000 / 8081 + spindrel CLI install). |

Code shipped: `scripts/screenshots/capture/tui_render.py` (PIL canvas + JetBrainsMono font + ANSI palette + window-chrome title bar), `tui_frames.py` (Frame builders, AST-parses `PROVIDERS` from `scripts/setup.py` so model menus stay current), `--only setup-tui` in `cli.py` (no API, no Playwright — straight PIL render).

Live run: `python -m scripts.screenshots all --only setup-tui` → 4/4 captures land in `docs/images/` in <1s. No staging, no teardown, no test instance required.

**Remaining (3) — onboarding-flow UI:**

| File | Blocker |
|---|---|
| `setup-6-login-screen.png` | Browser screenshot of `/login` — straightforward but the test instance has the auth page, just needs a Playwright nav without auth context (existing rig assumes a logged-in `AuthBundle`). |
| `setup-7-first-channel.png` | Onboarding modal / "create your first channel" UX. The test instance is already onboarded, so capturing this requires either (a) ephemeral fresh-DB instance, (b) destructive stage that clears all channels + re-runs the welcome flow, or (c) reusing an existing `New Channel` dialog as a stand-in. |
| `setup-10-first-chat.png` | Same as above — needs a "first time chatting" framing (empty channel + onboarding cue). Could share infrastructure with `setup-7` if we go fresh-instance. |

Recommendation when these come up next: split into a `--only setup-flow` bundle that stands up an ephemeral container (separate compose project, isolated volume) with `SPINDREL_HEADLESS=1` first-boot, captures the three frames, then tears down. Heavier than the TUI rig but isolates onboarding-flow staging from the live test instance.

### Phase A2.5 — Unbreak 9 broken docs image links (scaffolding done 2026-04-24)

| File | Guide | Route / interaction |
|---|---|---|
| `channel-heartbeat.png` | `heartbeats.md` | channel Settings → Heartbeat tab (action: click tab) |
| `channel_history_mode.png` | `chat-history.md` | channel Settings → History tab (action: click tab) |
| `mcp-list.png` | `mcp-servers.md` | `/admin/mcp-servers` with 2 seeded servers |
| `secret-store.png` | `secrets.md` | `/admin/secrets` with 3 seeded secrets |
| `usage-and-forecast.png` | `usage-and-billing.md` | `/admin/usage` |
| `integration-edit-v2.png` | `ingestion.md` | `/admin/integrations` → click "ingestion" (action: click) |
| `bot-skills-learning-1.png` | `bot-skills.md` | `/admin/learning` with seeded skills |
| `bot-skills-learning-2.png` | `bot-skills.md` | same view, Health / Analytics tab (action: click tab) |
| `channel-bluebubbles-hud.png` | `bluebubbles.md` | channel with BlueBubbles binding pinned |

Code shipped: `scripts/screenshots/stage/scenarios/docs_repair.py`, `DOCS_REPAIR_SPECS` in `capture/specs.py`, `--only docs-repair` in `cli.py`, five new admin-API helpers on `SpindrelClient` (secrets, MCP servers, skills, heartbeat toggle, channel bindings).

Live run command: `python -m scripts.screenshots all --only docs-repair`. `teardown --only docs-repair` is symmetric and only removes docs-repair records (flagship's chat-main is left alone so `stage_flagship` can re-toggle heartbeat on reruns).

### Phase A2 — Integration hero shots (8–10)
One representative screenshot per shipped integration, in situ:
- `slack-app-home.png` — Slack App Home tab with buttons
- `github-pr-card.png` — channel with GitHub PR card widget
- `homeassistant-dashboard.png` — HA device widgets
- `frigate-cameras.png` — Frigate cameras grid widget
- `excalidraw-canvas.png` — Excalidraw embedded canvas
- `browser-live-preview.png` — Browser Live session thumbnail
- `discord-thread.png` — Discord message exchange
- `web-search-results.png` — web_search tool result card
- **TBD (replaces Gmail — being removed)**: candidates are `bluebubbles-thread.png` (iMessage visually distinct), `claude-code.png` (developer chat), `arr-library.png` (media stack), `firecrawl-result.png` (crawl card). Pick at A2 kickoff.

Each needs a staged channel with integration bound + a realistic envelope pinned or a real tool call persisted. Reuses `screenshot:*` client_id prefix pattern.

### Phase A3 — Feature deep-dives (8–10)
One screenshot per major feature area the quickstart should explain:
`approvals-queue`, `heartbeats-view`, `skill-learning-tab`, `tool-policies`, `providers-settings`, `usage-and-budgets`, `knowledge-base`, `workspace-files`, `pipeline-library`, `memory-viewer`. Some need new `data-testid` / `data-status` attributes (budget: one per element, zero logic changes).

### Phase A4 — UI archetype variants
- Dark-mode pairs for Flagship 8 — `home-dark.png` etc. Playwright context already supports `color_scheme="dark"`.
- Mobile (375×812) variants for `chat-main`, `widget-dashboard`, `home`.
- Tablet (820×1180) variant for `widget-dashboard` only — shows grid responsive breakpoint.

### Phase A5 — Admin / ops captures (6–8)
`admin-integrations-list`, `admin-tasks-list`, `admin-cron-schedules`, `admin-audit-log`, `admin-api-keys`, `admin-rate-limits`, `admin-e2e-runs`.

### Phase A6 — Callout-annotated variants
Post-process, not re-capture:
- `scripts/screenshots/capture/annotate.py` reads a base PNG + annotation spec (selector or explicit bbox + label + arrow position), produces `docs/images/annotated/<name>.png`.
- Annotation specs in `docs/images/annotated/*.yml`.
- Used by video `doc_callout` scenes AND by docs prose.

First Track-A phase that *both* improves the asset library and feeds Track B.

### Phase B1 — Still-kind proof (active)
Full architecture skeleton (storyboard YAML, dataclasses, clip dispatch, compositor, CLI) but ships only `kind: still`. Other kinds stubbed with `NotImplementedError("phase Bn")`.

Storyboard lives at `scripts/screenshots/storyboards/quickstart.yml`. CLI surface:
```
python -m scripts.screenshots video build   [--storyboard ...] [--skip-capture]
python -m scripts.screenshots video preview --scene <id> [--storyboard ...]
python -m scripts.screenshots video plan    [--storyboard ...]
```

Scene schema includes all phase-B* fields (sections, kinds, audio slot) even though only `still` renders. No storyboard migrations when B2+ land.

Deliverable: `docs/videos/quickstart.mp4`, ~22s, 4 still scenes from A1, captions + Ken Burns + crossfades + watermark, no audio.

### Phase B2 — Doc-view scenes
- `scripts/screenshots/video/mkdocs_server.py` — subprocess context manager for `mkdocs serve --dev-addr 127.0.0.1:8765`; waits for `/` 200, guarantees cleanup. One instance per build.
- `clips/doc_hero.py` — full-page screenshot Ken Burns top→bottom (or smooth-scroll recording via `record_video_dir`).
- `clips/doc_callout.py` — navigate with anchor, inject highlight-box CSS overlay around the `highlight` selector, Ken Burns zoom into the callout.
- Per-scene `color_scheme: light|dark` via mkdocs-material's `__palette` cookie.

After B2 the quickstart grows to ~60–90s with 6–8 scenes mixing product stills and rendered docs prose.

### Phase B3 — Interaction recordings + manual slots
- `clips/playwright_action.py` — scene YAML grows an `actions: [{type: click|type|scroll, ...}]` list; context uses `record_video_dir`; result MP4 trimmed to `duration`.
- `clips/manual.py` — pass-through for user-supplied MP4s/PNGs under `scripts/screenshots/assets/manual/`. Canonical path for asciinema-exported terminal recordings.

### Phase B4 — TTS
- Scene schema gains `audio: { text?, voice?, file? }` (already reserved in B1 — no migration).
- Pluggable provider env: `SPINDREL_VIDEO_TTS=openai|elevenlabs|piper`.
- Scene duration becomes `max(visual, audio) + padding`.
- `meta.captions_mode: burned|sidecar|both` — sidecar writes `.vtt`.

### Phase B5 — Publish pipeline + weekly regen
- `video publish` versions output as `quickstart-YYYY-MM-DD.mp4` + updates `latest.mp4` symlink.
- Copies to `spindrel-website/public/videos/`.
- Optional upload to Cloudflare R2 / S3 via provider interface.
- Optional cron on e2e host for fully-hands-off weekly regen (default stays: user triggers manually).

## Capture-pipeline lessons (TUI rig — A2.5-setup, 2026-04-25)

- **Synthetic > real recording for wizard heroes.** termtosvg / asciinema can record `setup.sh` but the recording is non-deterministic (depends on timing, terminal width, prompt animations, venv install delays) and re-running setup.sh requires git clone + venv create. A PIL canvas with a monospace font driven by `Frame(lines=[Line(spans=[Span(text, color, bold)])])` renders four heroes in <1s, every byte deterministic.
- **Drift-resistance comes from sourcing data, not output.** The frame builders import `PROVIDERS` from `scripts/setup.py` (via `ast.literal_eval` on the source — see below) so when the wizard adds Mistral, the model menu hero auto-inherits it. Synthetic ≠ frozen if the data is sourced from the live module.
- **AST-parse > module-import for source-of-truth modules with heavy top-level deps.** `scripts/setup.py` does `Style([...])` at top level which imports `questionary`. Even `SPINDREL_HEADLESS=1` doesn't dodge it — `STYLE = Style([...])` is unconditional. Reading the file as text and pulling the `PROVIDERS` Assign node out via `ast.parse` + `ast.literal_eval` gets the same data without the import-time side effects.
- **The TUI rig is fully outside the existing capture path.** No Playwright, no `capture_batch`, no `AuthBundle` — `_run_capture_setup_tui` branches early on `only == "setup-tui"` and calls the renderer directly. Stage and teardown are no-ops. This keeps the TUI rig orthogonal to the browser-automation path; it doesn't even need a running test instance.
- **Window-chrome title bar reads as "this is a terminal".** Three colored circles (red/yellow/green dots) + a dim title string at the top of the canvas frames the screenshot as a desktop terminal window without faking an actual window manager. Uses ~56px of vertical space — well worth it for context.

## Key invariants

- **Two tracks, one cadence.** Track A grows the asset library; Track B grows the compositor. Each week advances both.
- **The storyboard YAML is the only hand-edited artifact.** No per-scene Python scripts.
- **Scene kinds are closed at plan time, open for new implementations.** Adding a kind is a new file in `clips/`, not a refactor.
- **mkdocs is the single source for doc visuals.** No parallel markdown renderer; the video shows exactly what the docs site shows.
- **Assets are an input contract.** `video build` may re-run `capture` but never mutates staging semantics.
- **Silent now, compositable later.** B1 MP4 has no audio track; B4's TTS is purely additive (audio track muxed onto existing video stream).
- **Fail loudly.** Missing assets, bad selectors, unknown scene ids, mkdocs-not-running — all error with a clear next step. No black frames, no silent skips.
- **No auto-publish.** A human plays the MP4 before anything leaves the repo.
- **This track is evergreen.** Phases land, their row in the status table ticks to `done`, the Track stays `active`. Per the living-tracks-never-close rule.

## References

- `scripts/screenshots/` — shared pipeline for stagers/captures/video
- `scripts/screenshots/storyboards/quickstart.yml` — the storyboard (hand-edited each week)
- `docs/images/` — asset library (PNG output)
- `docs/videos/` — video output (gitignored)
- `mkdocs.yml` — docs site config; B2 doc scenes resolve `guide:` values against `nav:`
- `Track - Docs Refresh.md` — closes on Phase F; does not absorb video scope
- Plan file: `~/.claude/plans/i-need-help-going-frolicking-clover.md`
