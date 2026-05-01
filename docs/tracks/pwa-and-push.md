---
tags: [spindrel, pwa, push-notifications, ux, mobile]
status: active
updated: 2026-04-19
---

# Track — PWA & Push Notifications

## North Star

Spindrel behaves like a first-class installable app — clean home-screen
icon, service worker, and a push-notification pathway bots can invoke
via tool call (HomeAssistant-notify style). No auto-push on every new
message; alerts are explicit and bot-driven.

## Status

| Phase | Summary | Status |
|---|---|---|
| A | Icons + manifest hygiene (favicon fix, maskable, theme-color) | ✅ shipped 2026-04-19 |
| B | Service worker + install prompt flow | ✅ shipped 2026-04-19 |
| C | Web Push end-to-end (VAPID, subscribe, tool, API) | ✅ shipped 2026-04-19 |
| D | Operator setup + docs (VAPID gen, `.env` wiring) | ⏳ docs pending |

## Phase A — Icons + manifest hygiene

- Replaced blurry/guide-covered PWA icons with clean renders of the
  Spindrel swirl SVG on a dark tile (`#111111`).
- `ui/public/favicon.ico` / `favicon-32.png` / `favicon.svg` — fixed
  prior 404 (only a non-existent path was referenced in index.html).
- Added maskable icon variants (`icon-{192,512}-maskable.png`) with
  ~28% safe-zone padding for Android adaptive-icon circular masks.
- `apple-touch-icon` at the iOS-standard 180×180.
- Light/dark `theme-color` pair in `index.html`.
- Manifest fields added: `id`, `scope`, `description`, `categories`,
  `purpose: "maskable"` entries.
- Reverted `viewport-fit=cover` + `env(safe-area-inset-*)` padding
  (Fix Log 2026-04-16 — breaks iOS standalone bottom).

## Phase B — Service worker + install

- Hand-rolled SW at `ui/public/sw.js` (vite-plugin-pwa@1.2.0 doesn't
  support vite 8 yet). Handles install/activate, a minimal network-first
  cache for `/assets/*`, `push` events, `notificationclick` (focuses
  existing Spindrel window or opens a URL).
- `ui/src/lib/registerSW.ts` — registers only in production; wires
  `updatefound` into the existing `toast()` as a sticky
  "New version available — Reload" toast.
- `ui/src/stores/installPrompt.ts` — captures the
  `beforeinstallprompt` event for later use; `main.tsx` captures on
  window load and clears on `appinstalled`.
- Settings → Global → `InstallAppSection` exposes the install CTA
  only when the browser offered a prompt.

## Phase C — Web Push end-to-end

**Backend** (6 files):

- `app/services/api_keys.py` — new `push:send` scope in `ALL_SCOPES`,
  `SCOPE_DESCRIPTIONS`, `SCOPE_GROUPS` under "Push Notifications".
- `app/config.py` — `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
  `VAPID_SUBJECT` settings; push disabled cleanly when unset.
- `app/db/models.py` + `migrations/versions/216_push_subscriptions.py`
  — `push_subscriptions` table (`user_id FK`, `endpoint UNIQUE`,
  `p256dh`, `auth`, `user_agent`, `created_at`, `last_used_at`).
- `app/services/presence.py` — in-memory last-seen map populated by a
  heartbeat endpoint; window is 120s. Used by `send_push` to skip a
  send when the user is actively in the app.
- `app/services/push.py` — single `send_push(user_id, title, body, ...)`
  entry point. Loops the user's subscriptions, calls `pywebpush` via
  `asyncio.to_thread`, prunes 404/410 endpoints, updates
  `last_used_at`. Respects `only_if_inactive`.
- `app/routers/api_v1_push.py` — `GET /vapid-public-key`,
  `POST /subscribe`, `POST /unsubscribe`, `POST /send` (requires
  `push:send` scope), `POST /presence/heartbeat`.
- `app/tools/local/send_push.py` — registered bot tool
  `send_push_notification(user_email|user_id, title, body, url?, tag?,
  only_if_inactive?)`. Gated by tool assignment, not a runtime scope
  check (matches how `send_file` and other outbound-action tools
  already work).
- `pyproject.toml` — `pywebpush>=2.0` added.
- `scripts/generate_vapid_keys.py` — one-shot CLI; prints the three
  `.env` lines to paste.

**Frontend** (7 files):

- `ui/public/sw.js` — already handles `push` events end-to-end (part
  of Phase B).
- `ui/src/lib/pushSubscription.ts` — `isPushSupported()`,
  `enablePush()`, `disablePush()`, `getExistingSubscription()`.
  iOS-gated: returns false in Safari tabs.
- `ui/src/hooks/usePresenceHeartbeat.ts` — 60s ping while
  `document.visibilityState === "visible"`; mounted in `AppShell`.
- `ui/app/(app)/settings.tsx` — new `NotificationsSection` in the
  Global tab with Enable/Disable toggle, iOS install hint, denied
  state.

## Key design decisions

1. **No automatic push on new messages.** User directive 2026-04-19
   — push is tool-driven only, like HomeAssistant's `notify` service.
   No `subscribe_all → NEW_MESSAGE` listener on the backend.
2. **Presence is in-memory, 120s window, frontend-pinged.** Simpler
   than DB heartbeat. Restart resets to "everyone inactive" briefly;
   acceptable.
3. **Tool assignment gates tool calls; scope gates API calls.** Same
   service underneath. This matches `send_file` / `send_slack_message`.
   Rejected the unified-permission approach as drift from existing
   Spindrel conventions.
4. **`only_if_inactive` defaults to true.** User explicitly wanted
   "don't buzz me when I'm already looking at it."
5. **Icon source = `spindrel-website/public/favicon.svg`** (indigo
   swirl on dark tile). Not the blue "A" that was previously rendered
   — that version always had construction-guide decorations baked in.

## Operator setup

```bash
# 1. Generate VAPID keys (one-shot)
python scripts/generate_vapid_keys.py

# 2. Paste the three printed lines into .env:
#      VAPID_PUBLIC_KEY=...
#      VAPID_PRIVATE_KEY=...
#      VAPID_SUBJECT=mailto:you@example.com

# 3. Restart the server. Push endpoints go live; the Settings →
#    Notifications toggle now does something.

# 4. Grant the `push:send` scope on the Bot Permissions page to any
#    bot/API key that should be able to call POST /api/v1/push/send.

# 5. For bot-agent use: assign the `send_push_notification` tool to
#    the bot in the Tools tab. The bot can then call it in the agent
#    loop with no additional scope grant.
```

## Open items / future

- [ ] **iOS install guide** — short doc on enabling push on iOS
  (must add to Home Screen first, then open the installed app and
  toggle Notifications).
- [ ] **Subscription list UI** — let users see / revoke their
  registered devices. Low priority; the Settings toggle covers
  single-device case today.
- [ ] **Notification history** — log sent pushes somewhere for
  debugging. Tie into existing trace system?
- [ ] **Topic-based subscriptions** — currently all pushes go to all
  of a user's devices. A per-subscription category filter (messages,
  alerts, pipelines) would be a nice v2.

## References

- Plan files: `~/.claude/plans/staged-frolicking-starfish.md` (mobile
  polish; partially superseded by this track's Phase A).
- Fix Log 2026-04-16 — iOS standalone viewport-fit lesson.
- Session log 2026-04-19-6 (this session).
