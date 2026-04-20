# browser_live — sketch

Drives the user's real browser via a paired MV3 extension. Bot calls
`browser_goto / browser_act / browser_eval / browser_screenshot`; the
server RPCs the extension over WebSocket; the extension dispatches onto
`chrome.tabs / chrome.scripting / chrome.tabs.captureVisibleTab`.

## Status: skeleton

Wired enough to smoke-test end-to-end but several TODOs before ship:

- `router._resolve_user_for_token` accepts any token as the user_id —
  replace with a real lookup against per-user `IntegrationSettings`
  (`BROWSER_LIVE_PAIRING_TOKEN`). Add admin-UI button to (re)generate.
- `tools/browser._user_id_for_call` routes by `current_bot_id` for the
  sketch — switch to the real `current_user_id` ContextVar once the
  pairing-token table exists.
- Navigation completion in `background.js` is a 500ms sleep — replace
  with `chrome.webNavigation.onCompleted` keyed by tab+frame.
- No widget for `browser_screenshot` yet (`widgets/screenshot.html`).
- No tests. Lift the bridge into a fake-WebSocket test harness; the
  per-tool integration tests can use that fake.
- Firefox support: MV3 service-worker semantics differ — port to a
  background script if needed. The WS protocol is identical.

## Try it locally

1. `docker compose up` (or `uvicorn`) — integration auto-discovers.
2. Open Chrome → `chrome://extensions` → Developer mode → Load unpacked
   → pick `integrations/browser_live/extension/`.
3. Open Options. Server URL = `http://localhost:8000`. Token = anything
   (sketch accepts any). Save.
4. Watch the server log for `browser_live: connected`.
5. From any bot with `browser_live` enabled in its tool policy, ask it
   to `browser_goto("https://example.com")` and then
   `browser_screenshot()`.

## Safety

- The extension can do anything the user can do in any tab. Treat the
  pairing token like a password.
- Bot tool policy gates exposure — `browser_eval` is `exec_capable`,
  `browser_act` / `browser_goto` are `mutating`, `browser_screenshot` /
  `browser_status` are `readonly`.
- No secret scrubbing in `browser_eval` results — assume returned values
  may end up in chat / traces / memory.
