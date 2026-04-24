---
tags: [agent-server, track, docs, screenshots, video, active]
status: active
updated: 2026-04-24 (A2 admin-detail integration heroes shipped 8/8)
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
| A2 | A | Integration hero shots (admin-detail pass) | **done** — shipped 2026-04-24; 8/8 captures (`integration-{slack,discord,github,homeassistant,frigate,excalidraw,browser-live,web-search}.png`) via `--only integrations`. Registry-driven (no staging). Each shows Overview + capability badges + Manifest editor + Events + Detected Assets — usable hero for the matching `docs/guides/*.md`. |
| A2-channel | A | In-channel widget heroes (frigate cameras grid, HA dashboard tiles, github PR card) | later — requires seeding persisted tool-result messages with widget envelopes; admin-detail pass covers the docs-guide need for now |
| A2.5-setup | A | 8 missing `docs/setup.md` images (`setup-1.png` … `setup-10-first-chat.png`, `providers-screen-v1.png`) | later — surfaced by the new drift check; these are the manual setup-wizard walkthrough, likely need a dedicated scenario or user-captured frames |
| A3-docs | A | Docs-gap-ordered feature deep-dives (10 captures) replacing prior A3 list | later |
| A4 | A | UI archetype variants (dark + mobile) | later |
| A5 | A | Admin / ops captures (6–8) | later |
| A6 | A | Callout-annotated variants + `capture/annotate.py` | later |
| B1 | B | Still-kind proof video (first shippable) | **done** — shipped 2026-04-24; 24.6s mp4 at `docs/videos/quickstart.mp4` |
| B2 | B | Doc-view scenes via mkdocs (doc_hero, doc_callout) | next |
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
