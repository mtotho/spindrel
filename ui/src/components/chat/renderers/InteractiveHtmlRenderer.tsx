/**
 * Interactive HTML envelope renderer — for `emit_html_widget` output
 * (content_type = `application/vnd.spindrel.html+interactive`).
 *
 * Distinct from `SandboxedHtmlRenderer` (`text/html`): that one is
 * locked down with `sandbox=""` and `default-src 'none'` CSP for
 * previewing pinned workspace `.html` files. This renderer intentionally
 * permits scripts + same-origin network so bots can emit widgets that
 * read from the app's own `/api/v1/...` endpoints.
 *
 * Sandbox model:
 * - `sandbox="allow-scripts allow-same-origin"` — scripts run, and the
 *   iframe keeps the page's origin so fetch('/api/v1/...') carries the
 *   session cookie. No `allow-top-navigation`, no `allow-popups`, no
 *   `allow-forms`.
 * - CSP `default-src 'self'; script-src 'unsafe-inline' 'self'; style-src
 *   'unsafe-inline' 'self'; img-src data: blob: 'self'; connect-src
 *   'self'` — cross-origin network is blocked.
 *
 * Two input modes (mirrors the tool):
 * - **Inline**: `envelope.body` is the full assembled body content.
 * - **Path**: `envelope.source_path` + `envelope.source_channel_id` —
 *   renderer fetches the file, polls every 3s so edits to the file
 *   propagate to the widget without a page reload.
 *
 * The injected ``window.spindrel`` helper gives bot-written JS a small
 * API surface for common tasks (read/write workspace files, call any
 * /api/v1/... endpoint) without having to reconstruct channel_id or
 * auth headers. Scroll behavior: iframe height is measured via
 * ResizeObserver on the body so async-loaded content still sizes
 * correctly, capped at 800px where internal iframe scrolling takes over.
 *
 * Theme layer: every widget inherits the app's design language via a
 * `<style id="__spindrel_theme">` block and `window.spindrel.theme`
 * object (see `widgetTheme.ts`). Authors style with `sd-*` utility
 * classes and `var(--sd-*)` tokens so widgets stay consistent with the
 * rest of the app and pick up dark mode automatically.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot as BotIcon, RefreshCw } from "lucide-react";
import { apiFetch, ApiError } from "../../../api/client";
import type { ToolResultEnvelope } from "../../../types/api";
import type { ThemeTokens } from "../../../theme/tokens";
import { useThemeStore } from "../../../stores/theme";
import { buildWidgetThemeCss, buildWidgetThemeObject } from "./widgetTheme";

interface WidgetTokenResponse {
  token: string;
  expires_at: string;
  expires_in: number;
  bot_id: string;
  bot_name: string;
  bot_avatar_url: string | null;
  scopes: string[];
}

interface Props {
  envelope: ToolResultEnvelope;
  /** Channel the widget is rendering in. Used to build the injected
   *  `window.spindrel` helper so bot JS can call channel-scoped APIs.
   *  Falls back to `envelope.source_channel_id` when omitted. */
  channelId?: string;
  /** When true, the iframe fills its container's height (100%) instead of
   *  measuring the inner content. Used by dashboard grid tiles where the
   *  parent dictates the available height and the user expects the tile to
   *  fill the space they resized it to — not collapse to content size. */
  fillHeight?: boolean;
  /** Dashboard pin id when the widget is mounted as a pin. Exposed to the
   *  iframe as ``window.spindrel.dashboardPinId`` so widget JS can dispatch
   *  ``widget_config`` patches that persist against the pin (star-to-save,
   *  toggle state). Undefined for inline chat widgets. */
  dashboardPinId?: string;
  t: ThemeTokens;
}

// Default CSP directive → baseline source list. Kept as structured data
// (not a flat string) so envelope-declared `extra_csp` can append origins
// per directive without fragile string splicing.
const DEFAULT_CSP: Record<string, string[]> = {
  "default-src": ["'self'"],
  "script-src": ["'unsafe-inline'", "'self'"],
  "style-src": ["'unsafe-inline'", "'self'"],
  "img-src": ["data:", "blob:", "'self'"],
  "font-src": ["data:", "'self'"],
  "connect-src": ["'self'"],
};

// snake_case (backend / envelope wire format) → kebab-case (CSP directive).
const CSP_DIRECTIVE_MAP: Record<string, string> = {
  script_src: "script-src",
  connect_src: "connect-src",
  img_src: "img-src",
  style_src: "style-src",
  font_src: "font-src",
  media_src: "media-src",
  frame_src: "frame-src",
  worker_src: "worker-src",
};

// Origin guard — second line of defense (backend sanitize_extra_csp is first).
// Drops anything that isn't a bare https:// origin so a compromised envelope
// can't downgrade the policy by smuggling `'unsafe-eval'` or `*` through.
function isSafeCspOrigin(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const v = value.trim();
  if (!v.startsWith("https://")) return false;
  const host = v.slice("https://".length);
  if (!host) return false;
  if (host.includes("/") || host.includes("?") || host.includes("#")) return false;
  if (host.includes("*")) return false;
  return true;
}

function buildCsp(extra: Record<string, unknown> | null | undefined): string {
  const merged: Record<string, string[]> = {};
  for (const [directive, sources] of Object.entries(DEFAULT_CSP)) {
    merged[directive] = [...sources];
  }
  if (extra && typeof extra === "object") {
    for (const [key, value] of Object.entries(extra)) {
      const directive = CSP_DIRECTIVE_MAP[key];
      if (!directive) continue;
      const list = Array.isArray(value) ? value : [value];
      const clean = list.filter(isSafeCspOrigin) as string[];
      if (!clean.length) continue;
      // Lazy-initialize directives not in the baseline (media-src, frame-src,
      // worker-src) — CSP falls back to default-src 'self' otherwise, which
      // would block the very third-party the widget just declared.
      if (!merged[directive]) merged[directive] = ["'self'"];
      const seen = new Set(merged[directive]);
      for (const origin of clean) {
        if (seen.has(origin)) continue;
        seen.add(origin);
        merged[directive].push(origin);
      }
    }
  }
  return Object.entries(merged)
    .map(([directive, sources]) => `${directive} ${sources.join(" ")}`)
    .join("; ");
}

const MAX_IFRAME_HEIGHT = 800;

/** JSON-escape a value for injection into a <script> string. */
function jsonForScript(value: string | null | undefined): string {
  return JSON.stringify(value ?? null).replace(/</g, "\\u003c");
}

/** Build the host-page helper script that gets injected into every widget.
 *  Exposes `window.spindrel` with channel_id + small conveniences so bot
 *  JS doesn't have to reconstruct URLs or JSON headers.
 *
 *  ``widgetToken`` authenticates every ``api()`` call as the bot that
 *  emitted the widget (``envelope.source_bot_id``). The host re-mints
 *  before expiry and overwrites ``window.spindrel.__token`` in-place so
 *  long-lived widgets keep a fresh bearer without reloading.
 *
 *  For declarative HTML widgets the tool's raw JSON result is baked into
 *  the body preamble as ``window.spindrel.toolResult``. The host can push
 *  fresh data after a state_poll refresh via ``__setToolResult`` without
 *  reassigning srcDoc (which would destroy the widget's in-iframe state).
 *  Widget JS observes refreshes via the ``spindrel:toolresult`` CustomEvent
 *  or by re-reading ``window.spindrel.toolResult`` on demand.
 */
function spindrelBootstrap(
  channelId: string | null,
  botId: string | null,
  botName: string | null,
  widgetToken: string | null,
  initialToolResultJson: string | null,
  themeJson: string,
  dashboardPinId: string | null,
  widgetPath: string | null,
): string {
  return `<script>
(function () {
  const channelId = ${jsonForScript(channelId)};
  const botId = ${jsonForScript(botId)};
  const botName = ${jsonForScript(botName)};
  const dashboardPinId = ${jsonForScript(dashboardPinId)};
  const widgetPath = ${jsonForScript(widgetPath)};
  // Normalise a workspace-relative path. Strips "./" segments, collapses
  // "a/b/../c" to "a/c", rejects escapes above the bundle root when the
  // input started with "../". Backend also re-validates; this is just
  // cosmetic + fail-fast for obvious mistakes.
  function normalizePath(p) {
    const parts = p.split("/");
    const out = [];
    for (const seg of parts) {
      if (seg === "" || seg === ".") continue;
      if (seg === "..") {
        if (out.length === 0) {
          throw new Error("spindrel: path escapes widget root: " + p);
        }
        out.pop();
      } else {
        out.push(seg);
      }
    }
    return out.join("/");
  }
  // Resolve a user-facing path string for a workspace API call.
  //  - "./foo" / "../foo" → resolved against the directory of widgetPath
  //    (the bundle root). Only works for path-mode widgets; throws otherwise.
  //  - "foo/bar" / "data/x.json" → treated as a channel-workspace-relative
  //    path as-is (current default). No magic.
  //  - Leading "/" → hard error for now; reserved for future absolute
  //    /workspace/channels/<id>/... and /workspace/widgets/<slug>/... grammar
  //    (DX-5b, not shipped).
  function resolvePath(input) {
    if (typeof input !== "string" || !input) {
      throw new Error("spindrel: path must be a non-empty string");
    }
    if (input.startsWith("/")) {
      throw new Error(
        "spindrel: absolute /workspace/... paths not yet supported — " +
        "pass a channel-workspace-relative path (e.g. 'data/widgets/x/foo.json') " +
        "or './foo.json' / '../x/foo.json' to resolve against the widget bundle"
      );
    }
    if (input.startsWith("./") || input.startsWith("../") || input === "." || input === "..") {
      if (!widgetPath) {
        throw new Error(
          "spindrel: relative paths require path-mode (widgetPath is null; inline widgets can't use ./ or ../)"
        );
      }
      const dir = widgetPath.includes("/")
        ? widgetPath.slice(0, widgetPath.lastIndexOf("/"))
        : "";
      return normalizePath((dir ? dir + "/" : "") + input);
    }
    return normalizePath(input);
  }
  // Token mutated in-place by the host on re-mint — read fresh per call.
  const state = { token: ${jsonForScript(widgetToken)} };
  const initialToolResult = ${initialToolResultJson ?? "null"};
  const initialTheme = ${themeJson};
  // Token-ready promise — resolves as soon as a non-null token lands in
  // state.token (either baked into srcDoc or pushed later via __setToken).
  // apiFetch awaits this when no token is present yet, so the widget's
  // initial-paint fetches (fired synchronously from iframe load) don't go
  // out unauthenticated and 422 before the mint query completes. React-
  // query's mint is async; the iframe's srcDoc bootstraps first.
  let __tokenReadyResolve = null;
  const tokenReady = state.token
    ? Promise.resolve()
    : new Promise(function (r) { __tokenReadyResolve = r; });
  // Like fetch() but bearer-attached. Returns the raw Response so callers
  // can choose how to consume the body (.blob() for images, .json(), .text(),
  // streaming, whatever). Use this for anything non-JSON (image/video blobs,
  // file downloads). For JSON endpoints, api() below is the convenience
  // wrapper that throws on !ok and parses the body for you.
  async function apiFetch(path, options) {
    // Wait for the bot's widget token before firing. Only blocks when
    // the srcDoc hadn't baked a token in yet — once the first mint lands
    // the promise is resolved forever and subsequent calls are sync.
    if (!state.token) await tokenReady;
    const opts = options || {};
    const baseHeaders = opts.body !== undefined && !opts.headers
      ? { "Content-Type": "application/json" }
      : {};
    const headers = Object.assign(
      baseHeaders,
      state.token ? { "Authorization": "Bearer " + state.token } : {},
      opts.headers || {}
    );
    return fetch(path, Object.assign({}, opts, { headers }));
  }
  async function api(path, options) {
    const resp = await apiFetch(path, options);
    const ct = resp.headers.get("content-type") || "";
    const data = ct.includes("application/json") ? await resp.json() : await resp.text();
    if (!resp.ok) {
      const msg = typeof data === "string" ? data : (data && data.detail) || resp.statusText;
      throw new Error("API " + resp.status + ": " + msg);
    }
    return data;
  }
  function requireChannel() {
    if (!channelId) throw new Error("spindrel.channelId is not set for this widget");
    return channelId;
  }
  async function readWorkspaceFile(path) {
    const cid = requireChannel();
    const resolved = resolvePath(path);
    const url = "/api/v1/channels/" + encodeURIComponent(cid) +
      "/workspace/files/content?path=" + encodeURIComponent(resolved);
    const data = await api(url);
    return data.content;
  }
  async function writeWorkspaceFile(path, content) {
    const cid = requireChannel();
    const resolved = resolvePath(path);
    const url = "/api/v1/channels/" + encodeURIComponent(cid) +
      "/workspace/files/content?path=" + encodeURIComponent(resolved);
    return api(url, { method: "PUT", body: JSON.stringify({ content: content }) });
  }
  async function listWorkspaceFiles(opts) {
    const cid = requireChannel();
    const o = opts || {};
    const qs = new URLSearchParams();
    if (o.include_archive) qs.set("include_archive", "true");
    if (o.include_data) qs.set("include_data", "true");
    if (o.data_prefix) qs.set("data_prefix", o.data_prefix);
    const url = "/api/v1/channels/" + encodeURIComponent(cid) +
      "/workspace/files" + (qs.toString() ? "?" + qs.toString() : "");
    return api(url);
  }
  // Minimal CommonMark-ish renderer. Supports headings (#, ##, ###, ####),
  // bold (**x**), italic (*x*), inline code (\`x\`), fenced code blocks
  // (\`\`\`lang\\n...\\n\`\`\`), unordered + ordered lists (- / 1.),
  // blockquotes (>), links, and paragraphs. HTML-escapes all source first,
  // then applies inline transformations — safe to \`innerHTML\` bot-authored
  // prose. Not a full CommonMark parser; no tables, footnotes, HTML
  // passthrough. If a widget needs more than this, inline marked.js into
  // the bundle. Keep in sync with the skill's Markdown Rendering section.
  function renderMarkdown(src) {
    if (src == null) return "";
    const text = String(src);
    function escapeHtml(s) {
      return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }
    // Pull fenced code blocks out first so their contents aren't mangled
    // by inline rules. Replace with sentinels, restore at the end.
    const fences = [];
    let buf = text.replace(/\`\`\`([^\\n\`]*)\\n([\\s\\S]*?)\`\`\`/g, function (_m, lang, code) {
      const i = fences.push({ lang: lang.trim(), code: code }) - 1;
      return "\\x00FENCE" + i + "\\x00";
    });
    buf = escapeHtml(buf);
    // Block-level, line-oriented.
    const lines = buf.split(/\\n/);
    const out = [];
    let para = [];
    let list = null; // {type: 'ul'|'ol', items: [[...lines]]}
    let quote = [];
    function flushPara() {
      if (para.length) { out.push("<p>" + inline(para.join(" ")) + "</p>"); para = []; }
    }
    function flushList() {
      if (!list) return;
      const tag = list.type;
      out.push("<" + tag + ">" +
        list.items.map(function (item) {
          return "<li>" + inline(item.join(" ")) + "</li>";
        }).join("") +
        "</" + tag + ">");
      list = null;
    }
    function flushQuote() {
      if (!quote.length) return;
      out.push("<blockquote>" + inline(quote.join(" ")) + "</blockquote>");
      quote = [];
    }
    function flushAll() { flushPara(); flushList(); flushQuote(); }
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      let m;
      if (!line.trim()) { flushAll(); continue; }
      if ((m = /^(#{1,4})\\s+(.*)$/.exec(line))) {
        flushAll();
        out.push("<h" + m[1].length + ">" + inline(m[2]) + "</h" + m[1].length + ">");
        continue;
      }
      if ((m = /^\\s*[-*+]\\s+(.*)$/.exec(line))) {
        flushPara(); flushQuote();
        if (!list || list.type !== "ul") { flushList(); list = { type: "ul", items: [] }; }
        list.items.push([m[1]]);
        continue;
      }
      if ((m = /^\\s*\\d+\\.\\s+(.*)$/.exec(line))) {
        flushPara(); flushQuote();
        if (!list || list.type !== "ol") { flushList(); list = { type: "ol", items: [] }; }
        list.items.push([m[1]]);
        continue;
      }
      if ((m = /^&gt;\\s?(.*)$/.exec(line))) {
        flushPara(); flushList();
        quote.push(m[1]);
        continue;
      }
      // Continuation of previous block: if we're in a list, append to last
      // item; otherwise accumulate into the current paragraph.
      if (list) { list.items[list.items.length - 1].push(line.replace(/^\\s+/, "")); continue; }
      if (quote.length) { quote.push(line); continue; }
      para.push(line);
    }
    flushAll();
    function inline(s) {
      return s
        .replace(/\`([^\`]+?)\`/g, "<code>$1</code>")
        .replace(/\\*\\*([^*]+?)\\*\\*/g, "<strong>$1</strong>")
        .replace(/(^|[^*])\\*([^*\\n]+?)\\*(?!\\*)/g, "$1<em>$2</em>")
        .replace(/\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g, function (_m, txt, href) {
          // href already HTML-escaped; further strip quotes defensively.
          return '<a href="' + href.replace(/"/g, "") + '" target="_blank" rel="noopener noreferrer">' + txt + "</a>";
        });
    }
    let html = out.join("");
    html = html.replace(/\\x00FENCE(\\d+)\\x00/g, function (_m, i) {
      const f = fences[Number(i)];
      const cls = f.lang ? ' class="language-' + escapeHtml(f.lang) + '"' : "";
      return "<pre><code" + cls + ">" + escapeHtml(f.code) + "</code></pre>";
    });
    return html;
  }
  // Fetch a workspace file as an object URL — for <img src> / <video src> /
  // <a href download>. Bridges the Authorization-header gap: <img> elements
  // can't carry a bearer, so we fetch-with-auth, blob it, URL.createObjectURL
  // the result, and hand back a same-origin URL the browser will load without
  // a second round-trip. Supports the same relative-path grammar as the
  // workspace-file helpers. The object URL lives until revokeAsset(url) is
  // called or the iframe is torn down — fine to ignore for short-lived
  // widgets; revoke explicitly if you're loading many large assets.
  const __assetRegistry = new Set();
  async function loadAsset(path) {
    const cid = requireChannel();
    const resolved = resolvePath(path);
    const url = "/api/v1/channels/" + encodeURIComponent(cid) +
      "/workspace/files/raw?path=" + encodeURIComponent(resolved);
    const resp = await apiFetch(url);
    if (!resp.ok) {
      throw new Error("loadAsset '" + path + "': HTTP " + resp.status);
    }
    const blob = await resp.blob();
    const objectUrl = URL.createObjectURL(blob);
    __assetRegistry.add(objectUrl);
    return objectUrl;
  }
  function revokeAsset(url) {
    if (__assetRegistry.has(url)) {
      URL.revokeObjectURL(url);
      __assetRegistry.delete(url);
    }
  }
  // Event subscription sugar — returns an unsubscribe function so widgets
  // don't have to hold a reference to the bound handler just to remove it.
  function subscribe(eventName, cb) {
    if (typeof cb !== "function") throw new Error("subscribe: callback required");
    const handler = function (e) { cb(e.detail, e); };
    window.addEventListener(eventName, handler);
    return function () { window.removeEventListener(eventName, handler); };
  }
  function onToolResult(cb) { return subscribe("spindrel:toolresult", cb); }
  function onTheme(cb) { return subscribe("spindrel:theme", cb); }
  // onConfig is sugar: widget_config now rides in toolResult.config, so we
  // subscribe to toolresult and only fire when config actually changes.
  function onConfig(cb) {
    if (typeof cb !== "function") throw new Error("onConfig: callback required");
    let last = (window.spindrel && window.spindrel.toolResult && window.spindrel.toolResult.config) || null;
    let lastJson;
    try { lastJson = JSON.stringify(last); } catch (_) { lastJson = null; }
    const handler = function (e) {
      const cfg = (e.detail && e.detail.config) || null;
      let cfgJson;
      try { cfgJson = JSON.stringify(cfg); } catch (_) { cfgJson = null; }
      if (cfgJson !== lastJson) {
        lastJson = cfgJson;
        last = cfg;
        cb(cfg, e);
      }
    };
    window.addEventListener("spindrel:toolresult", handler);
    return function () { window.removeEventListener("spindrel:toolresult", handler); };
  }
  // JSON state helper — load / patch / save over workspace files with
  // deep-merge RMW semantics. Collapses the status-dashboard boilerplate
  // (read → JSON.parse → merge defaults → JSON.stringify → write) into
  // three methods. Arrays are replaced, not concatenated — if you want
  // append semantics, spread the old array in your patch.
  function isPlainObject(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v);
  }
  function deepMerge(a, b) {
    if (!isPlainObject(a) || !isPlainObject(b)) return b === undefined ? a : b;
    const out = Object.assign({}, a);
    for (const k of Object.keys(b)) {
      out[k] = isPlainObject(a[k]) && isPlainObject(b[k])
        ? deepMerge(a[k], b[k])
        : b[k];
    }
    return out;
  }
  function deepClone(v) {
    if (v == null || typeof v !== "object") return v;
    try { return JSON.parse(JSON.stringify(v)); } catch (_) { return v; }
  }
  async function dataLoad(path, defaults) {
    const base = defaults !== undefined ? deepClone(defaults) : {};
    let raw;
    try {
      raw = await readWorkspaceFile(path);
    } catch (_) {
      return base; // file doesn't exist yet
    }
    if (!raw || !raw.trim()) return base;
    let parsed;
    try { parsed = JSON.parse(raw); } catch (e) {
      throw new Error("spindrel.data.load: invalid JSON in " + path + ": " + e.message);
    }
    if (defaults === undefined) return parsed;
    return isPlainObject(parsed) ? deepMerge(base, parsed) : parsed;
  }
  async function dataSave(path, object) {
    await writeWorkspaceFile(path, JSON.stringify(object, null, 2));
    return object;
  }
  async function dataPatch(path, patch, defaults) {
    const current = await dataLoad(path, defaults);
    const next = isPlainObject(current) && isPlainObject(patch)
      ? deepMerge(current, patch)
      : (patch !== undefined ? patch : current);
    await dataSave(path, next);
    return next;
  }
  // One-line tool-dispatch helper. Wraps POST /api/v1/widget-actions so bots
  // don't re-write the same 15-line dance in every widget. Fills bot_id +
  // channel_id from the helper context; extras (display_label, widget_config,
  // source_record_id, dashboard_pin_id) flow through via opts.extra. Returns
  // the fresh envelope on success, throws with the server error on failure.
  async function callTool(name, args, opts) {
    if (!name) throw new Error("callTool: tool name is required");
    const o = opts || {};
    const body = Object.assign(
      {
        dispatch: "tool",
        tool: name,
        args: args || {},
        bot_id: botId,
        channel_id: channelId,
      },
      o.extra || {}
    );
    const resp = await api("/api/v1/widget-actions", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (!resp || resp.ok !== true) {
      throw new Error((resp && resp.error) || "callTool '" + name + "' failed");
    }
    return resp.envelope || null;
  }
  window.spindrel = {
    channelId: channelId,
    botId: botId,
    botName: botName,
    dashboardPinId: dashboardPinId,
    widgetPath: widgetPath,
    resolvePath: resolvePath,
    api: api,
    apiFetch: apiFetch,
    readWorkspaceFile: readWorkspaceFile,
    writeWorkspaceFile: writeWorkspaceFile,
    listWorkspaceFiles: listWorkspaceFiles,
    loadAsset: loadAsset,
    revokeAsset: revokeAsset,
    renderMarkdown: renderMarkdown,
    callTool: callTool,
    data: {
      load: dataLoad,
      save: dataSave,
      patch: dataPatch,
    },
    onToolResult: onToolResult,
    onConfig: onConfig,
    onTheme: onTheme,
    toolResult: initialToolResult,
    theme: initialTheme,
    __setToken: function (t) {
      state.token = t || null;
      // Unblock any apiFetch calls queued while the mint was in flight.
      if (state.token && __tokenReadyResolve) {
        __tokenReadyResolve();
        __tokenReadyResolve = null;
      }
    },
    __setToolResult: function (obj) {
      window.spindrel.toolResult = obj;
      try {
        window.dispatchEvent(new CustomEvent("spindrel:toolresult", { detail: obj }));
      } catch (_) { /* CustomEvent unavailable — ignore */ }
    },
    __setTheme: function (t) {
      window.spindrel.theme = t;
      try {
        window.dispatchEvent(new CustomEvent("spindrel:theme", { detail: t }));
      } catch (_) { /* ignore */ }
    }
  };
})();
</script>`;
}

// Widgets that never call the app's API (pure data render off
// `window.spindrel.toolResult`) don't need a bot-scoped bearer. Skipping
// the mint for them avoids a pointless 400 when the emitting bot has no
// API key configured — and, more importantly, avoids surfacing a red
// "no API permissions" banner on a widget that wouldn't have used the
// permissions anyway. Heuristic: look for the three signatures bot
// widgets use to hit our backend. False positives are fine (mint runs,
// banner only shows if bot has no key AND widget mentions one of these).
const WIDGET_NEEDS_AUTH_RE = /\.api(?:Fetch)?\(|\/api\/v1\//;
function bodyNeedsAuth(body: string | null | undefined): boolean {
  if (!body) return false;
  return WIDGET_NEEDS_AUTH_RE.test(body);
}

// Matches the server-side preamble written in
// `_build_html_widget_body`. We snapshot-extract the JSON so refreshes can
// postMessage-equivalent push fresh data into a live iframe without
// rebuilding srcDoc.
//
// The regex must match the FULL preamble script tag (opening through
// closing), not just the `window.spindrel.toolResult = ...` assignment.
// Earlier we only matched from the assignment, which left an orphan
// `<script>window.spindrel = window.spindrel || {};` in the body — the
// browser saw an unclosed script and parsed the following HTML as JS,
// blowing up with "Unexpected token '<'" at line 2:1.
const TOOL_RESULT_PREAMBLE_RE =
  /<script>\s*window\.spindrel\s*=\s*window\.spindrel\s*\|\|\s*\{\};\s*window\.spindrel\.toolResult\s*=\s*([\s\S]+?);\s*<\/script>/;

function extractToolResultFromBody(body: string): unknown | undefined {
  const match = TOOL_RESULT_PREAMBLE_RE.exec(body);
  if (!match) return undefined;
  try {
    // Reverse the `</` escape the backend applies to keep the script tag
    // from closing early mid-JSON literal.
    const json = match[1].replace(/<\\\//g, "</");
    return JSON.parse(json);
  } catch {
    return undefined;
  }
}

function wrapHtml(
  body: string,
  channelId: string | null,
  botId: string | null,
  botName: string | null,
  widgetToken: string | null,
  initialToolResultJson: string | null,
  themeCss: string,
  themeJson: string,
  isDark: boolean,
  dashboardPinId: string | null,
  widgetPath: string | null,
  csp: string,
): string {
  return `<!doctype html>
<html${isDark ? ' class="dark"' : ""}>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<style id="__spindrel_theme">${themeCss}</style>
${spindrelBootstrap(channelId, botId, botName, widgetToken, initialToolResultJson, themeJson, dashboardPinId, widgetPath)}
</head>
<body>
<div id="__sd_root">
${body}
</div>
</body>
</html>`;
}

function formatRelative(ts: number | null): string {
  if (!ts) return "";
  const secs = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ago`;
}

export function InteractiveHtmlRenderer({ envelope, channelId, fillHeight, dashboardPinId, t }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(200);
  const themeMode = useThemeStore((s) => s.mode);
  const isDark = themeMode === "dark";

  const sourcePath = envelope.source_path || null;
  const sourceChannelId = envelope.source_channel_id || null;
  const sourceBotId = envelope.source_bot_id || null;
  const pathMode = !!sourcePath && !!sourceChannelId;
  const effectiveChannelId = channelId ?? sourceChannelId;

  // For inline widgets we know the body at mount time and can skip minting
  // when the widget won't use it. PathMode widgets fetch their body later,
  // so we can't pre-check — mint unconditionally and let the banner surface
  // if the bot turns out to have no key. Inline is the common case (every
  // tool-emitted widget template), so the weather-widget false-positive
  // banner is solved.
  const inlineNeedsAuth = !pathMode && bodyNeedsAuth(envelope.body);
  const shouldMint = !!sourceBotId && (pathMode || inlineNeedsAuth);

  const themeCss = useMemo(
    () => buildWidgetThemeCss({ tokens: t, isDark }),
    [t, isDark],
  );
  const themeJson = useMemo(
    () => JSON.stringify(buildWidgetThemeObject({ tokens: t, isDark })),
    [t, isDark],
  );
  // CSP is derived per-envelope — widgets declare their third-party origin
  // needs via ``extra_csp`` (Maps, Mapbox, etc.). ``buildCsp`` merges onto
  // the locked-down baseline and drops anything that isn't a concrete
  // ``https://`` origin.
  const cspString = useMemo(
    () => buildCsp(envelope.extra_csp),
    [envelope.extra_csp],
  );

  // Mint a bot-scoped bearer token so widget JS authenticates as the
  // emitting bot — not as the viewing user. We re-mint before expiry and
  // push the new value into the iframe via `window.spindrel.__setToken`
  // so the srcDoc doesn't reload (which would reset the widget's state).
  const tokenQuery = useQuery({
    queryKey: ["widget-auth-mint", sourceBotId],
    queryFn: () =>
      apiFetch<WidgetTokenResponse>("/api/v1/widget-auth/mint", {
        method: "POST",
        body: JSON.stringify({ source_bot_id: sourceBotId }),
      }),
    enabled: shouldMint,
    // 15-minute server TTL; re-mint at 12 min so the widget never sees a
    // 401 mid-call. Short TTL = short screenshot exposure.
    refetchInterval: 12 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
  const widgetToken = tokenQuery.data?.token ?? null;
  const botName = tokenQuery.data?.bot_name ?? null;

  // Push fresh tokens into the live iframe without reloading srcDoc.
  useEffect(() => {
    if (!widgetToken) return;
    try {
      const w = iframeRef.current?.contentWindow as
        | (Window & { spindrel?: { __setToken?: (t: string) => void } })
        | null
        | undefined;
      w?.spindrel?.__setToken?.(widgetToken);
    } catch {
      // Cross-origin edge case — srcDoc should be same-origin under
      // allow-same-origin, but if the iframe is mid-navigation the access
      // throws. The next mint tick picks it up.
    }
  }, [widgetToken]);

  const fileQuery = useQuery({
    queryKey: [
      "interactive-html-widget-content",
      sourceChannelId,
      sourcePath,
    ],
    queryFn: () =>
      apiFetch<{ path: string; content: string }>(
        `/api/v1/channels/${sourceChannelId}/workspace/files/content?path=${encodeURIComponent(
          sourcePath!,
        )}`,
      ),
    enabled: pathMode,
    refetchInterval: 3000,
    refetchOnWindowFocus: true,
  });

  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  useEffect(() => {
    if (fileQuery.data?.content != null) {
      setLastUpdated(Date.now());
    }
  }, [fileQuery.data?.content]);

  // Keep the "updated Xs ago" chip ticking even without new data.
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!pathMode) return;
    const id = setInterval(() => setTick((n) => n + 1), 10_000);
    return () => clearInterval(id);
  }, [pathMode]);

  const rawBody = useMemo(() => {
    if (pathMode) return fileQuery.data?.content ?? "";
    return envelope.body ?? "";
  }, [pathMode, fileQuery.data?.content, envelope.body]);

  // Declarative HTML widgets ship the tool's JSON result baked into a
  // `window.spindrel.toolResult = {...}` preamble. Splitting it off lets
  // srcDoc depend only on the (stable) HTML fragment while tool-result
  // refreshes are pushed into the live iframe via `__setToolResult`.
  // That preserves scroll / focus / animation state across polls.
  const { bodyWithoutPreamble, initialToolResultJson } = useMemo(() => {
    const match = TOOL_RESULT_PREAMBLE_RE.exec(rawBody);
    if (!match) {
      return { bodyWithoutPreamble: rawBody, initialToolResultJson: null as string | null };
    }
    const stripped = rawBody.replace(TOOL_RESULT_PREAMBLE_RE, "");
    const restored = match[1].replace(/<\\\//g, "</");
    return {
      bodyWithoutPreamble: stripped.replace(/^\s*<script>\s*<\/script>\s*/i, ""),
      initialToolResultJson: restored as string | null,
    };
  }, [rawBody]);

  // Freeze the JSON that flowed into srcDoc at mount so subsequent poll
  // refreshes flow through `__setToolResult` rather than rebuilding srcDoc.
  const frozenInitialToolResultRef = useRef<string | null>(null);
  if (frozenInitialToolResultRef.current === null && initialToolResultJson != null) {
    frozenInitialToolResultRef.current = initialToolResultJson;
  }

  const lastInjectedToolResultRef = useRef<string | null>(null);
  useEffect(() => {
    if (pathMode) return;
    if (initialToolResultJson == null) return;
    // Same JSON as last push? No-op (first mount is handled by srcDoc seed).
    if (initialToolResultJson === lastInjectedToolResultRef.current) return;
    if (initialToolResultJson === frozenInitialToolResultRef.current
        && lastInjectedToolResultRef.current === null) {
      lastInjectedToolResultRef.current = initialToolResultJson;
      return;
    }
    try {
      const w = iframeRef.current?.contentWindow as
        | (Window & {
            spindrel?: { __setToolResult?: (v: unknown) => void };
          })
        | null
        | undefined;
      if (w?.spindrel?.__setToolResult) {
        const parsed = JSON.parse(initialToolResultJson);
        w.spindrel.__setToolResult(parsed);
        lastInjectedToolResultRef.current = initialToolResultJson;
      }
    } catch {
      // Iframe mid-navigation or malformed JSON — next body update retries.
    }
  }, [initialToolResultJson, pathMode]);

  // Measure iframe content height via ResizeObserver on the body so
  // async-loaded content (fetch + render, setInterval updates) still
  // triggers iframe resizing — not just the initial `load` event.
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const updateHeight = () => {
      try {
        const doc = iframe.contentDocument;
        if (!doc?.body) return;
        // Measure the intrinsic content wrapper, not body. body may be
        // sized to viewport (min-height:100vh from bot CSS) which would
        // feedback-loop against the iframe's own height.
        const root = doc.getElementById("__sd_root") ?? doc.body;
        const h = Math.min(root.scrollHeight + 24, MAX_IFRAME_HEIGHT);
        setHeight(Math.max(80, h));
      } catch {
        // Edge case: contentDocument not accessible. Stay at last height.
      }
    };

    let observer: ResizeObserver | null = null;
    const onLoad = () => {
      updateHeight();
      try {
        const doc = iframe.contentDocument;
        if (!doc?.body || observer) return;
        const root = doc.getElementById("__sd_root") ?? doc.body;
        observer = new ResizeObserver(updateHeight);
        observer.observe(root);
      } catch {
        // ignored
      }
    };
    iframe.addEventListener("load", onLoad);
    return () => {
      iframe.removeEventListener("load", onLoad);
      if (observer) observer.disconnect();
    };
  }, [bodyWithoutPreamble]);

  const errorOverlay =
    pathMode && fileQuery.error ? (
      <div
        style={{
          padding: "6px 10px",
          fontSize: 11,
          color: t.danger,
          borderBottom: `1px solid ${t.surfaceBorder}`,
        }}
      >
        Failed to load {sourcePath}:{" "}
        {fileQuery.error instanceof Error
          ? fileQuery.error.message
          : "unknown error"}
      </div>
    ) : null;

  // Widget auth error — surface so the user understands why fetches fail.
  // Common cause: bot has no API key configured. We prefer the backend's
  // `detail` field (FastAPI's user-facing message) over the generic "API
  // error 400: Bad Request" so the user sees actionable guidance (where
  // to provision scopes) directly in the widget chrome.
  const authError = (() => {
    if (!shouldMint || !tokenQuery.error) return null;
    const err = tokenQuery.error;
    if (err instanceof ApiError && err.detail) return err.detail;
    if (err instanceof Error) return err.message;
    return "unknown error";
  })();

  return (
    <div
      style={{
        borderRadius: 8,
        overflow: "hidden",
        position: "relative",
        // Dashboard grid tiles set an explicit height on their children;
        // flex-column + h-full lets the iframe grow to fill the tile.
        ...(fillHeight
          ? { height: "100%", display: "flex", flexDirection: "column" as const }
          : null),
      }}
    >
      {errorOverlay}
      {authError && (
        <div
          style={{
            padding: "6px 10px",
            fontSize: 11,
            color: t.danger,
            background: t.dangerSubtle,
            borderBottom: `1px solid ${t.surfaceBorder}`,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span style={{ flex: 1 }}>{authError}</span>
          <button
            type="button"
            onClick={() => tokenQuery.refetch()}
            disabled={tokenQuery.isFetching}
            style={{
              appearance: "none",
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "2px 8px",
              fontSize: 11,
              color: t.text,
              background: t.surfaceOverlay,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4,
              cursor: tokenQuery.isFetching ? "wait" : "pointer",
              fontFamily: "inherit",
            }}
          >
            <RefreshCw size={10} />
            {tokenQuery.isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}
      {/* Subtle bot-origin chip — bottom-left so it doesn't collide with
          the "updated Xm ago" indicator (top-right). Signals to the user
          that whatever this widget's JS does, it runs with THIS bot's
          permissions, not theirs. */}
      {botName && (
        <div
          style={{
            position: "absolute",
            bottom: 6,
            left: 8,
            fontSize: 10,
            padding: "2px 6px",
            borderRadius: 4,
            background: t.overlayLight,
            color: t.textMuted,
            pointerEvents: "none",
            display: "flex",
            alignItems: "center",
            gap: 4,
            opacity: 0.75,
            zIndex: 1,
          }}
          title={`Widget runs as @${botName}. API calls use this bot's permissions, not yours.`}
        >
          <BotIcon size={10} />
          <span>@{botName}</span>
        </div>
      )}
      {pathMode && lastUpdated && (
        <div
          aria-hidden
          style={{
            position: "absolute",
            top: 6,
            right: 8,
            fontSize: 10,
            padding: "2px 6px",
            borderRadius: 4,
            background: t.overlayLight,
            color: t.textMuted,
            pointerEvents: "none",
          }}
          title={`Refreshed ${formatRelative(lastUpdated)} (polling every 3s). tick=${tick}`}
        >
          {formatRelative(lastUpdated)}
        </div>
      )}
      <iframe
        ref={iframeRef}
        srcDoc={wrapHtml(
          bodyWithoutPreamble,
          effectiveChannelId,
          sourceBotId,
          botName,
          widgetToken,
          frozenInitialToolResultRef.current,
          themeCss,
          themeJson,
          isDark,
          dashboardPinId ?? null,
          sourcePath,
          cspString,
        )}
        sandbox="allow-scripts allow-same-origin"
        title={envelope.display_label || "Interactive HTML widget"}
        style={{
          width: "100%",
          // Dashboard tiles: fill parent height (resize-aware). Chat messages:
          // content-measured height capped at MAX_IFRAME_HEIGHT.
          height: fillHeight ? "100%" : height,
          flex: fillHeight ? 1 : undefined,
          border: "none",
          display: "block",
        }}
      />
    </div>
  );
}
