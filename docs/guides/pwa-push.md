# PWA & Web Push Notifications

![Spindrel running as a PWA on mobile](../images/omnipanel-mobile.png)

Spindrel installs as a Progressive Web App on desktop, Android, and iOS (16.4+). Once installed, bots can wake you with Web Push notifications — pipeline completions, approval requests, alerts, anything you explicitly asked to be buzzed about.

This guide covers installing the PWA, enabling push, using the `send_push_notification` bot tool, and the server-side `POST /api/v1/push/send` endpoint.

---

## Installing the PWA

The Spindrel UI ships a standard Web App Manifest (`ui/public/manifest.json`) plus a service worker (`ui/public/sw.js`). Every modern browser offers the install flow:

| Platform | Install path |
|---|---|
| Desktop Chrome / Edge | Install icon in the URL bar, or ⋮ menu → **Install Spindrel** |
| Desktop Safari 17+ | File → **Add to Dock** |
| Android Chrome | ⋮ menu → **Install app** |
| iOS 16.4+ Safari | Share → **Add to Home Screen** |

Installed mode runs standalone (no browser chrome), is pinned to the dock/home screen, and — critically for iOS — unlocks Web Push. **On iOS, Web Push only works inside the installed PWA** — Safari tabs cannot subscribe. On desktop and Android the browser tab is also a valid push target.

The app icons, theme color, and orientation all come from `manifest.json`. Theme color and background match the app's dark-default aesthetic.

---

## Server-side setup — VAPID keys

Web Push requires the server to sign outgoing payloads with a VAPID keypair. Generate one once and set three env vars:

```bash
# Generate the keypair
python -m app.tools.generate_vapid_keys

# Set in .env
VAPID_PUBLIC_KEY=BJt...
VAPID_PRIVATE_KEY=...
VAPID_SUBJECT=mailto:you@example.com
```

If VAPID is not configured, the server returns a 503 from `/api/v1/push/vapid-public-key` and push is silently disabled — the rest of the app still works. Regenerating the keypair invalidates every existing subscription, so do it once and leave it alone.

---

## Subscribing a device

Inside the installed PWA:

1. Go to **Settings → Notifications**.
2. Click **Enable browser push**.
3. Accept the browser's permission prompt.

Under the hood:

1. The UI fetches the server's VAPID public key from `GET /api/v1/push/vapid-public-key`.
2. The service worker calls `registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: <publicKey>})`.
3. The resulting `PushSubscription` (endpoint + p256dh + auth keys) is POSTed to `/api/v1/push/subscribe`, upserted on `endpoint`, and linked to your user row.

Re-subscribing from the same browser **replaces** the stored keys on the same endpoint — no duplicate rows build up. Unsubscribe with `POST /api/v1/push/unsubscribe` (also available in the Settings UI).

Multiple devices per user are supported: one subscription row per endpoint. When a push goes out, the server fans it out to every active subscription for that user.

---

## Sending from a bot — `send_push_notification`

The canonical pattern: bot decides something is important enough to interrupt you, calls `send_push_notification`. This is Spindrel's equivalent of Home Assistant's `notify.*` service.

```text
send_push_notification(
  user_email="me@example.com",
  title="Nightly ingest finished",
  body="5 new articles. 2 flagged for review.",
  url="/channels/abc-def?tab=digest",
  tag="nightly-ingest"
)
```

### Parameters

| Parameter | Notes |
|---|---|
| `user_email` | Recipient email — preferred, readable in bot configs |
| `user_id` | Alternative UUID if you already have it |
| `title` | Short headline, ~60 chars, shown as the notification title |
| `body` | Body text, ~180 chars, visible on the lock screen |
| `url` | Optional tap-target — relative URLs like `/channels/abc` are supported |
| `tag` | Optional — repeat sends with the same tag *replace* the prior notification rather than stacking |
| `only_if_inactive` | Default `true` — skip the send if you've been active in the app within ~2 minutes |

`title` and `body` are required. Either `user_email` or `user_id` identifies the target.

### Gating

`send_push_notification` is in `app/tools/local/send_push.py` with `safety_tier="mutating"`. It's **not** in every bot's tool set by default — assign it explicitly via the bot's `local_tools` list. There's no additional runtime scope check: assigning the tool IS the grant, the same pattern used by `send_file`, `send_slack_message`, and other delivery tools.

The tool fails closed with a clear error if VAPID isn't configured, the user isn't found, or the user has no active subscriptions.

### Bot prompting pattern

The tool works best when the bot has a clear trigger criterion. Something like:

> When a pipeline run completes with `failed > 0`, send a push notification to the operator with a short summary. When all steps succeed, don't — the periodic digest handles that.

Over-notification is the enemy. The `only_if_inactive=true` default is a safety net, not a substitute for good judgment in the system prompt.

---

## Presence awareness — `only_if_inactive`

The UI pings `POST /api/v1/presence/heartbeat` every ~60 seconds while the tab is visible. The push service records the last heartbeat; when a push lands with `only_if_inactive=true`, the server checks: were you active in the last ~2 minutes? If yes, **skip** the send (`skippedActive=true` in the response). The UI will have delivered the content through the normal SSE channel, so waking the phone would be noise.

Set `only_if_inactive=false` for *must-see* pushes — approval prompts for dangerous tools, oncall alerts, anything the user explicitly wants even if they're at the keyboard.

---

## Sending from scripts — `POST /api/v1/push/send`

For scripts, webhooks, or external integrations, use the scoped endpoint directly:

```bash
curl -X POST https://agent.example.com/api/v1/push/send \
  -H "Authorization: Bearer $SPINDREL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "user_email": "me@example.com",
    "title": "Deploy finished",
    "body": "v1.42 is live on production.",
    "url": "/channels/deploys",
    "tag": "deploys"
  }'
```

Requires the `push:send` scope on the API key. The payload fields mirror the bot tool, plus optional `icon`, `badge`, and `data` for advanced notification chrome.

Response:

```json
{
  "sent": 2,
  "pruned": 0,
  "failed": 0,
  "skippedActive": false
}
```

- `sent` — how many subscriptions accepted the push.
- `pruned` — how many expired subscriptions were deleted during the send (410 Gone from the push service → we drop them).
- `failed` — transient failures; the subscription is retained.
- `skippedActive` — the `only_if_inactive` shortcut fired, no sends attempted.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `503` on `/vapid-public-key` | VAPID not configured | Run `python -m app.tools.generate_vapid_keys`, set the three env vars, restart |
| iOS "Enable browser push" does nothing | Safari tab, not installed PWA | Add to Home Screen, open from home-screen icon, retry |
| Android notifications arrive delayed | OS-level battery optimization | Exclude the browser from battery optimization; FCM delivery speeds up |
| Every send returns `skippedActive: true` | `only_if_inactive=true` + active tab | Set `only_if_inactive=false` for the pushes that must always deliver |
| Subscription shows in DB but never receives | Endpoint expired — push service returned 410 | The next send prunes it; re-subscribe in the app |
| `sent > 0` but nothing appears | OS notification permission revoked | Browser Settings → Notifications → re-grant |

---

## Reference

| What | Where |
|---|---|
| Tool — `send_push_notification` | `app/tools/local/send_push.py` |
| Send service | `app/services/push.py` |
| Routes — subscribe / unsubscribe / send / VAPID key / heartbeat | `app/routers/api_v1_push.py` |
| DB — `push_subscriptions` table | `app/db/models.py` (`PushSubscription`) |
| Service worker | `ui/public/sw.js` |
| Web App Manifest | `ui/public/manifest.json` |
| Subscribe UI | Settings → Notifications in the installed PWA |

## See also

- [API Reference](api.md) — the `/api/v1/push/*` endpoints and `push:send` scope.
- [Secrets & Redaction](secrets.md) — VAPID keys are secrets; store them via `.env` or the secrets store, not in the repo.
