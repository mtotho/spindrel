# browser_live

Drives the user's real browser via a paired MV3 extension. Bot calls
`browser_goto / browser_act / browser_eval / browser_screenshot /
browser_status`; the server RPCs the extension over WebSocket; the
extension dispatches onto `chrome.tabs / chrome.scripting /
chrome.tabs.captureVisibleTab` against your *actual logged-in tabs*.

## Architecture

```
  Bot tool call ──▶ bridge.request(op, args)
                      │   (in-memory, per-process)
                      ▼
                   conn.send(JSON-RPC frame) ──ws──▶ extension/background.js
                                                              │
                   Future awaits matching request_id          │
                      ▲                                       ▼
                      └──────────── reply frame ──────── chrome.tabs / scripting / captureVisibleTab
```

- **Pairing token** — single global token stored as integration setting
  `BROWSER_LIVE_PAIRING_TOKEN`. Generate via
  `POST /integrations/browser_live/admin/token/rotate` (admin-auth).
  Rotating disconnects any currently-paired browser; pair again to
  resume.
- **Multi-browser** — multiple extensions (e.g. desktop + laptop) can
  pair concurrently. Default routing = most-recently-connected. Pass
  `connection_id` to a tool to target a specific browser; discover IDs
  via `browser_status`.
- **Single-process only** — bridge state is in-memory. Multi-worker
  deployments need an external broker keyed by `connection_id`.

## Try it

1. **Generate a token**

       curl -X POST -H "Authorization: Bearer $ADMIN_KEY" \
            http://localhost:8000/integrations/browser_live/admin/token/rotate

2. **Load the extension** — Chrome → `chrome://extensions` → Developer
   mode → Load unpacked → pick `integrations/browser_live/extension/`.

3. **Pair** — click the extension icon → Options → paste the server URL
   and the token → Save.

4. **Verify** — server log shows `browser_live: connected …`. Then
   `GET /integrations/browser_live/admin/status` lists the connection.

5. **Drive it** — from any bot with `browser_live` in its tool policy:

       browser_goto("https://example.com")
       browser_screenshot()
       browser_act("a", "click")

## Safety

- The extension can do anything you can do in any tab. Treat the
  pairing token like a password.
- Tool tier gates exposure: `browser_eval` is `exec_capable`,
  `browser_goto` / `browser_act` are `mutating`, `browser_screenshot` /
  `browser_status` are `readonly`.
- No secret scrubbing on `browser_eval` results — assume returned
  values may end up in chat / traces / memory.

## Future

- Forward extension-initiated events (`tabs.onUpdated`,
  `webNavigation.onErrorOccurred`, console errors) onto
  `channel_events` so widgets can subscribe via `spindrel.stream`.
- Live-tab widget (mirror `captureVisibleTab` frames + take-over /
  hand-back buttons).
- Per-user pairing tokens once the user-management track lands a
  `current_user_id` ContextVar.
- Firefox port (background script instead of MV3 service worker).
