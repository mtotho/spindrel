// Service worker — keeps the WS to Spindrel open and dispatches RPCs
// onto chrome.* APIs. Survives MV3 service-worker idle by re-opening
// on demand from any chrome.runtime event.

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

let ws = null;
let backoff = RECONNECT_BASE_MS;
let attaching = false;

async function getConfig() {
  const { server_url, token } = await chrome.storage.local.get([
    "server_url",
    "token",
  ]);
  return { server_url, token };
}

async function connect() {
  if (attaching || (ws && ws.readyState <= 1)) return;
  const { server_url, token } = await getConfig();
  if (!server_url || !token) {
    console.warn("[spindrel] not configured — open Options");
    return;
  }
  attaching = true;
  const url = `${server_url.replace(/^http/, "ws")}/integrations/browser_live/ws?token=${encodeURIComponent(token)}`;
  ws = new WebSocket(url);

  ws.addEventListener("open", () => {
    console.log("[spindrel] connected");
    backoff = RECONNECT_BASE_MS;
  });

  ws.addEventListener("message", async (ev) => {
    let frame;
    try {
      frame = JSON.parse(ev.data);
    } catch (e) {
      return;
    }
    if (frame.type === "hello") return;
    if (!frame.request_id) return;
    try {
      const result = await dispatch(frame.op, frame.args || {});
      ws.send(JSON.stringify({ request_id: frame.request_id, result }));
    } catch (e) {
      ws.send(
        JSON.stringify({ request_id: frame.request_id, error: String(e?.message || e) }),
      );
    }
  });

  ws.addEventListener("close", () => {
    attaching = false;
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, RECONNECT_MAX_MS);
  });

  ws.addEventListener("error", () => {
    try { ws.close(); } catch {}
  });

  attaching = false;
}

// Resolve when the top-level frame of `tabId` finishes loading. Falls back
// to a timer if the navigation event never fires (e.g. SPA route change
// where the URL was already resolved synchronously).
function waitForNav(tabId, timeoutMs) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      chrome.webNavigation.onCompleted.removeListener(onDone);
      resolve();
    };
    const onDone = (details) => {
      if (details.tabId === tabId && details.frameId === 0) finish();
    };
    chrome.webNavigation.onCompleted.addListener(onDone);
    setTimeout(finish, timeoutMs);
  });
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("no active tab");
  return tab;
}

async function dispatch(op, args) {
  switch (op) {
    case "goto": {
      const tab = args.new_tab
        ? await chrome.tabs.create({ url: args.url })
        : await chrome.tabs.update((await activeTab()).id, { url: args.url });
      await waitForNav(tab.id, 25000);
      const fresh = await chrome.tabs.get(tab.id);
      return { final_url: fresh.url, tab_id: fresh.id, title: fresh.title };
    }
    case "act": {
      const tab = await activeTab();
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        args: [args],
        func: ({ selector, action, value }) => {
          const el = document.querySelector(selector);
          if (!el) return { ok: false, error: `selector not found: ${selector}` };
          switch (action) {
            case "click": el.click(); break;
            case "focus": el.focus(); break;
            case "hover":
              el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
              break;
            case "scroll_into_view":
              el.scrollIntoView({ block: "center", behavior: "instant" });
              break;
            case "type": {
              el.focus();
              const proto = Object.getPrototypeOf(el);
              const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
              setter ? setter.call(el, value) : (el.value = value);
              el.dispatchEvent(new Event("input", { bubbles: true }));
              el.dispatchEvent(new Event("change", { bubbles: true }));
              break;
            }
            default: return { ok: false, error: `unknown action: ${action}` };
          }
          return { ok: true };
        },
      });
      return result;
    }
    case "eval": {
      const tab = await activeTab();
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        world: "MAIN",
        args: [args.expression],
        func: (expr) => {
          try {
            // eslint-disable-next-line no-new-func
            const v = (0, eval)(expr);
            return { value: v === undefined ? null : JSON.parse(JSON.stringify(v)) };
          } catch (e) {
            return { error: String(e?.message || e) };
          }
        },
      });
      if (result?.error) throw new Error(result.error);
      return result;
    }
    case "screenshot": {
      const tab = await activeTab();
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
        format: "png",
      });
      return {
        image_data_url: dataUrl,
        url: tab.url,
        title: tab.title,
        width: tab.width,
        height: tab.height,
      };
    }
    default:
      throw new Error(`unknown op: ${op}`);
  }
}

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.storage.onChanged.addListener(() => {
  try { ws?.close(); } catch {}
  connect();
});
connect();
