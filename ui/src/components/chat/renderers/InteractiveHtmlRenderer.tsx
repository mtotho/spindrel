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
 * - `sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"` — scripts run,
 *   the iframe keeps the page's origin so fetch('/api/v1/...') carries the
 *   session cookie, and native `<form>` elements submit without the
 *   "Blocked form submission" warning (widgets still call preventDefault
 *   and dispatch through `sp.callHandler`; allow-forms just silences the
 *   browser's default-action probe). External `_blank` links can open in
 *   a new tab, but there is still no `allow-top-navigation`.
 * - CSP `default-src 'self'; script-src 'unsafe-inline' 'self'; style-src
 *   'unsafe-inline' 'self'; img-src data: blob: 'self'; connect-src
 *   'self'` — cross-origin network is blocked.
 *
 * Two input modes (mirrors the tool):
 * - **Inline**: `envelope.body` is the full assembled body content.
 * - **Path**: `envelope.source_path` + `envelope.source_channel_id` —
 *   renderer fetches the file, keeps it cached across remounts, and
 *   revalidates mutable sources on a relaxed cadence.
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
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bot as BotIcon, RefreshCw } from "lucide-react";
import { apiFetch, ApiError } from "../../../api/client";
import type { ResolvedWidgetThemeResponse, ToolResultEnvelope } from "../../../types/api";
import type { ThemeTokens } from "../../../theme/tokens";
import { useThemeStore } from "../../../stores/theme";
import { getAuthToken, useAuthStore } from "../../../stores/auth";
import { useIsAdmin } from "../../../hooks/useScope";
import { toast } from "../../../stores/toast";
import { useDashboardPinsStore } from "../../../stores/dashboardPins";
import {
  buildWidgetThemeCss,
  buildWidgetThemeObject,
  resolveWidgetThemeTokens,
} from "./widgetTheme";
import { WIDGET_ICON_SPRITE, WIDGET_ICON_NAMES } from "./widgetIcons";
import type { PresentationFamily } from "@/src/lib/widgetHostPolicy";

// Dedupes missing-file toasts across renderer re-mounts and periodic polls.
// Key: dashboard pin id when pinned, else `${channelId}|${path}` for chat
// envelopes. Lives at module scope so remount / HMR doesn't reset it.
const MISSING_WIDGET_TOAST_KEYS = new Set<string>();
const WIDGET_AUTH_STALE_MS = 11 * 60 * 1000;
const WIDGET_AUTH_GC_MS = 20 * 60 * 1000;
const MUTABLE_WIDGET_SOURCE_STALE_MS = 60 * 1000;
const MUTABLE_WIDGET_SOURCE_GC_MS = 10 * 60 * 1000;
const IMMUTABLE_WIDGET_SOURCE_GC_MS = 30 * 60 * 1000;
const PINNED_WIDGET_IFRAME_IDLE_TTL_MS = 5 * 60 * 1000;
const MAX_PINNED_WIDGET_IFRAMES = 12;
type PooledPinnedWidgetIframe = {
  iframe: HTMLIFrameElement;
  srcDoc: string;
  parkedAt: number | null;
  cleanupTimer: number | null;
};
const PINNED_WIDGET_IFRAME_POOL = new Map<string, PooledPinnedWidgetIframe>();
let pinnedWidgetIframeParkingLot: HTMLDivElement | null = null;

export function hasPinnedWidgetIframeEntry(key: string | null | undefined): boolean {
  if (!key) return false;
  return PINNED_WIDGET_IFRAME_POOL.has(key);
}

function getPinnedWidgetIframeParkingLot(): HTMLDivElement | null {
  if (typeof document === "undefined") return null;
  if (pinnedWidgetIframeParkingLot?.isConnected) return pinnedWidgetIframeParkingLot;
  const lot = document.createElement("div");
  lot.setAttribute("data-spindrel-widget-iframe-lot", "1");
  lot.style.position = "fixed";
  lot.style.left = "-10000px";
  lot.style.top = "0";
  lot.style.width = "1px";
  lot.style.height = "1px";
  lot.style.overflow = "hidden";
  lot.style.opacity = "0";
  lot.style.pointerEvents = "none";
  lot.style.zIndex = "-1";
  document.body.appendChild(lot);
  pinnedWidgetIframeParkingLot = lot;
  return lot;
}

function evictPinnedWidgetIframe(key: string): void {
  const entry = PINNED_WIDGET_IFRAME_POOL.get(key);
  if (!entry) return;
  if (entry.cleanupTimer != null) {
    window.clearTimeout(entry.cleanupTimer);
  }
  PINNED_WIDGET_IFRAME_POOL.delete(key);
  if (entry.iframe.parentElement) {
    entry.iframe.parentElement.removeChild(entry.iframe);
  }
  entry.iframe.srcdoc = "";
}

function schedulePinnedWidgetIframeEviction(key: string): void {
  const entry = PINNED_WIDGET_IFRAME_POOL.get(key);
  if (!entry) return;
  if (entry.cleanupTimer != null) {
    window.clearTimeout(entry.cleanupTimer);
  }
  entry.parkedAt = Date.now();
  entry.cleanupTimer = window.setTimeout(() => {
    evictPinnedWidgetIframe(key);
  }, PINNED_WIDGET_IFRAME_IDLE_TTL_MS);
}

function touchPinnedWidgetIframeEntry(key: string): PooledPinnedWidgetIframe | undefined {
  const entry = PINNED_WIDGET_IFRAME_POOL.get(key);
  if (!entry) return undefined;
  if (entry.cleanupTimer != null) {
    window.clearTimeout(entry.cleanupTimer);
    entry.cleanupTimer = null;
  }
  entry.parkedAt = null;
  PINNED_WIDGET_IFRAME_POOL.delete(key);
  PINNED_WIDGET_IFRAME_POOL.set(key, entry);
  return entry;
}

function trimPinnedWidgetIframePool(): void {
  if (PINNED_WIDGET_IFRAME_POOL.size <= MAX_PINNED_WIDGET_IFRAMES) return;
  for (const [key, entry] of PINNED_WIDGET_IFRAME_POOL) {
    if (entry.parkedAt != null) {
      evictPinnedWidgetIframe(key);
      if (PINNED_WIDGET_IFRAME_POOL.size <= MAX_PINNED_WIDGET_IFRAMES) return;
    }
  }
}

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
  /** Current viewed session when the widget is rendered inside a session-
   *  scoped surface (scratch/session page, mini chat, etc.). */
  sessionId?: string;
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
  /** Pre-measured tile size from the enclosing grid cell. When present, the
   *  iframe's initial ``height`` state starts at ``gridDimensions.height``
   *  instead of the default 200 so the tile doesn't visibly pop from 200px
   *  to its final size on mount/remount. Also exposed to widget JS as
   *  ``window.spindrel.gridSize`` for widgets that want to render to the
   *  exact cell size (e.g. aspect-ratio-aware images). */
  gridDimensions?: { width: number; height: number };
  /** Host-side callback fired once the iframe has loaded and the preamble
   *  has posted a ``spindrel:ready`` handshake. Used by ``PinnedToolWidget``
   *  to drop its pre-load skeleton so dashboard↔chat switches stay visually
   *  stable instead of popping through the 200px default. */
  onIframeReady?: () => void;
  /** Dashboard chrome flag — when true, host flips
   *  ``documentElement.dataset.hoverScrollbars`` on the iframe once it's
   *  loaded so the widget's own scrollbar hides at rest and reveals on
   *  hover (mirrors the `.scroll-subtle` class applied to the outer tile
   *  body in `PinnedToolWidget`). CSS for this is injected by the widget
   *  preamble (see `app/services/widget_templates.py::_build_html_widget_body`). */
  hoverScrollbars?: boolean;
  /** Host-zone classification, exposed to widget JS as
 *  ``window.spindrel.layout``. One of ``"chip" | "header" | "rail" | "dock" | "grid"``;
   *  undefined falls through to ``"grid"`` so widgets can branch on layout
   *  without null-checks. Chip-authored widgets read this to render the 180×32
   *  compact variant; grid widgets render full-size. */
  layout?: WidgetLayout;
  /** Host wrapper shell mode. Exposed to widget JS as
   *  ``window.spindrel.hostSurface`` and mirrored onto the iframe document as
   *  ``data-spindrel-host-surface`` so HTML widgets can choose whether to draw
   *  their own inner background/card or rely on the host shell. */
  hostSurface?: HostSurface;
  presentationFamily?: PresentationFamily;
  t: ThemeTokens;
}

export type WidgetLayout = "chip" | "header" | "rail" | "dock" | "grid";
export type HostSurface = "surface" | "plain" | "translucent";

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
// Accept only bare http(s) origins. This intentionally rejects paths,
// queries, fragments, wildcards, and non-network schemes so a compromised
// envelope can't downgrade the policy by smuggling `'unsafe-eval'` or `*`
// through. `serverUrl` in local-ui → remote-api dev is often `http://...`,
// so CSP cannot be https-only here.
function normalizeSafeCspOrigin(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const v = value.trim();
  if (!v || v.includes("*")) return null;
  try {
    const url = new URL(v);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    if (url.username || url.password) return null;
    if (url.pathname !== "/" || url.search || url.hash) return null;
    return url.origin;
  } catch {
    return null;
  }
}

function appendCspOrigins(
  merged: Record<string, string[]>,
  directive: string,
  origins: string[],
): void {
  if (!origins.length) return;
  if (!merged[directive]) merged[directive] = ["'self'"];
  const seen = new Set(merged[directive]);
  for (const origin of origins) {
    if (seen.has(origin)) continue;
    seen.add(origin);
    merged[directive].push(origin);
  }
}

function buildCsp(
  extra: Record<string, unknown> | null | undefined,
  appOrigin: string | null,
  options?: { allowAppScripts?: boolean },
): string {
  const merged: Record<string, string[]> = {};
  for (const [directive, sources] of Object.entries(DEFAULT_CSP)) {
    merged[directive] = [...sources];
  }
  const runtimeOrigin = normalizeSafeCspOrigin(appOrigin);
  if (runtimeOrigin) {
    // Central app/backend origin allowance. Covers the common "UI on localhost,
    // API on remote agent-server" dev setup without requiring per-widget
    // extra_csp declarations. Keep it narrowly scoped to the resource classes
    // widgets legitimately load from the app backend.
    for (const directive of ["connect-src", "img-src", "media-src", "frame-src"]) {
      appendCspOrigins(merged, directive, [runtimeOrigin]);
    }
    if (options?.allowAppScripts) {
      // `runtime: react` widgets load vendored React + Babel from the
      // agent-server static mount. In same-origin prod the relative
      // `/widget-runtime/...` path is already covered by `'self'`; in dev
      // (Vite UI on a different origin from the API) the absolute URL
      // needs an explicit script-src allowance.
      appendCspOrigins(merged, "script-src", [runtimeOrigin]);
    }
  }
  if (options?.allowAppScripts) {
    // Babel.transform + `new Function(compiled)` in the React runtime shim
    // both count as "evaluating a string as JavaScript" — without
    // 'unsafe-eval' the iframe blocks JSX compilation entirely. This is
    // scoped to the `runtime: react` path; HTML widgets stay locked down.
    if (!merged["script-src"].includes("'unsafe-eval'")) {
      merged["script-src"].push("'unsafe-eval'");
    }
  }
  if (extra && typeof extra === "object") {
    for (const [key, value] of Object.entries(extra)) {
      const directive = CSP_DIRECTIVE_MAP[key];
      if (!directive) continue;
      const list = Array.isArray(value) ? value : [value];
      const clean = list
        .map(normalizeSafeCspOrigin)
        .filter((origin): origin is string => !!origin);
      if (!clean.length) continue;
      // Lazy-initialize directives not in the baseline (media-src, frame-src,
      // worker-src) — CSP falls back to default-src 'self' otherwise, which
      // would block the very third-party the widget just declared.
      appendCspOrigins(merged, directive, clean);
    }
  }
  return Object.entries(merged)
    .map(([directive, sources]) => `${directive} ${sources.join(" ")}`)
    .join("; ");
}

const MAX_IFRAME_HEIGHT = 800;

/** JSON-escape a value for injection into a <script> string. */
function jsonForScript(value: string | null | undefined): string {
  return JSON.stringify(value ?? null)
    .replace(/</g, "\\u003c")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

// Defense-in-depth for pre-stringified JSON that gets inlined directly as a
// JS expression (initialToolResultJson, themeJson). U+2028 and U+2029 are
// valid JSON characters but JS parses them as line terminators inside
// string literals, breaking the bootstrap `<script>` and leaving
// `window.spindrel` undefined for every widget on the page. The backend
// also escapes these in `_build_html_widget_body`; this catches anything
// that bypasses that path (pre-baked JSON re-extracted by the renderer,
// theme tokens, future inline payloads).
function escapeInlineJsonForScript(jsonText: string): string {
  return jsonText
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
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
 *  the body preamble as ``window.spindrel.result`` with
 *  ``window.spindrel.widgetConfig`` alongside it. ``toolResult`` remains a
 *  compatibility object. The host can push fresh data after a state_poll
 *  refresh via ``__setToolResult`` without reassigning srcDoc (which would
 *  destroy the widget's in-iframe state). Widget JS observes refreshes via
 *  the ``spindrel:toolresult`` CustomEvent or by re-reading
 *  ``window.spindrel.result`` / ``window.spindrel.widgetConfig`` on demand.
 */
function spindrelBootstrap(
  channelId: string | null,
  sessionId: string | null,
  botId: string | null,
  botName: string | null,
  serverUrl: string | null,
  widgetToken: string | null,
  initialToolResultJson: string | null,
  themeJson: string,
  dashboardPinId: string | null,
  widgetPath: string | null,
  gridDimensions: { width: number; height: number } | null,
  layout: WidgetLayout,
  hostSurface: HostSurface,
  presentationFamily: PresentationFamily,
): string {
  const gridDimensionsJson = gridDimensions
    ? JSON.stringify(gridDimensions)
    : "null";
  return `<script>
(function () {
  const channelId = ${jsonForScript(channelId)};
  const sessionId = ${jsonForScript(sessionId)};
  const botId = ${jsonForScript(botId)};
  const botName = ${jsonForScript(botName)};
  const serverUrl = ${jsonForScript(serverUrl)};
  const dashboardPinId = ${jsonForScript(dashboardPinId)};
  const widgetPath = ${jsonForScript(widgetPath)};
  // Tile size the iframe was spawned into (null for inline chat renders).
  // Widget JS can read window.spindrel.gridSize to pre-size image/video
  // placeholders at the right aspect ratio instead of computing from CSS.
  const gridSize = ${gridDimensionsJson};
  // Host-zone classification. One of "chip" | "rail" | "dock" | "grid".
  // Chip widgets render a 180×32 compact variant; other zones render full.
  const layout = ${jsonForScript(layout)};
  // Host shell mode. "surface" means the dashboard wrapper draws the outer
  // card; "plain" means widget content sits flush against the dashboard.
  const hostSurface = ${jsonForScript(hostSurface)};
  const presentationFamily = ${jsonForScript(presentationFamily)};
  try {
    document.documentElement.setAttribute("data-spindrel-host-surface", hostSurface);
  } catch (_) {}
  function resolveApiUrl(path) {
    if (typeof path !== "string" || !path) return path;
    if (/^[a-zA-Z][a-zA-Z\\d+.-]*:/.test(path) || path.startsWith("//")) {
      return path;
    }
    if (!serverUrl) return path;
    const base = serverUrl.replace(/\\/+$/, "");
    if (path.startsWith("/")) return base + path;
    return new URL(path, base + "/").toString();
  }
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
  const initialToolResult = ${initialToolResultJson ? escapeInlineJsonForScript(initialToolResultJson) : "null"};
  function __deriveResult(obj) {
    if (!obj || typeof obj !== "object") return obj;
    if (Object.prototype.hasOwnProperty.call(obj, "result")) return obj.result;
    return obj;
  }
  function __deriveWidgetConfig(obj) {
    if (!obj || typeof obj !== "object") return null;
    if (Object.prototype.hasOwnProperty.call(obj, "widget_config")) return obj.widget_config || {};
    if (Object.prototype.hasOwnProperty.call(obj, "config")) return obj.config || {};
    return null;
  }
  const initialResult = __deriveResult(initialToolResult);
  const initialWidgetConfig = __deriveWidgetConfig(initialToolResult);
  const initialTheme = ${escapeInlineJsonForScript(themeJson)};
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
    return fetch(resolveApiUrl(path), Object.assign({}, opts, { headers }));
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
    const __t0 = Date.now();
    const resp = await apiFetch(url);
    if (!resp.ok) {
      __sendDebugEvent("load-asset", {
        path: path, resolved: resolved, ok: false, status: resp.status,
        error: "HTTP " + resp.status, durationMs: Date.now() - __t0,
      });
      throw new Error("loadAsset '" + path + "': HTTP " + resp.status);
    }
    const blob = await resp.blob();
    const objectUrl = URL.createObjectURL(blob);
    __assetRegistry.add(objectUrl);
    __sendDebugEvent("load-asset", {
      path: path, resolved: resolved, ok: true, status: resp.status,
      sizeBytes: blob && blob.size || 0, durationMs: Date.now() - __t0,
    });
    return objectUrl;
  }
  function revokeAsset(url) {
    if (__assetRegistry.has(url)) {
      URL.revokeObjectURL(url);
      __assetRegistry.delete(url);
    }
  }
  // Fetch an attachment and return a same-origin blob URL for use as
  // <img src>, <video src>, or <a href download>. Attachment display can't
  // use a static src= URL because the /file endpoint requires auth and
  // <img> elements don't carry Authorization headers. This helper fetches
  // the raw bytes with the bearer token and vends a same-origin object URL.
  // The object URL lives for the widget's lifetime unless you call
  // URL.revokeObjectURL(url) manually. Usage:
  //   const url = await window.spindrel.loadAttachment(attachmentId);
  //   document.querySelector('img').src = url;
  const __attachmentRegistry = new Set();
  async function loadAttachment(id) {
    if (!id) throw new Error("loadAttachment: id is required");
    const __t0 = Date.now();
    try {
      const resp = await apiFetch("/api/v1/attachments/" + encodeURIComponent(id) + "/file");
      if (!resp.ok) {
        __sendDebugEvent("load-attachment", {
          id: id, ok: false, status: resp.status,
          error: "HTTP " + resp.status, durationMs: Date.now() - __t0,
        });
        throw new Error("loadAttachment '" + id + "': HTTP " + resp.status);
      }
      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);
      __attachmentRegistry.add(objectUrl);
      __sendDebugEvent("load-attachment", {
        id: id, ok: true, status: resp.status,
        sizeBytes: blob && blob.size || 0, durationMs: Date.now() - __t0,
      });
      return objectUrl;
    } catch (e) {
      // If we already emitted above (HTTP failure path), this just rethrows.
      throw e;
    }
  }
  function revokeAttachment(url) {
    if (__attachmentRegistry.has(url)) {
      URL.revokeObjectURL(url);
      __attachmentRegistry.delete(url);
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
  // onConfig is sugar over the canonical widgetConfig channel. We still fall
  // back to toolResult.config for older preambles.
  function onConfig(cb) {
    if (typeof cb !== "function") throw new Error("onConfig: callback required");
    let last = (window.spindrel && (window.spindrel.widgetConfig || (window.spindrel.toolResult && window.spindrel.toolResult.config))) || null;
    let lastJson;
    try { lastJson = JSON.stringify(last); } catch (_) { lastJson = null; }
    const handler = function (e) {
      const cfg = (window.spindrel && (window.spindrel.widgetConfig || (e.detail && e.detail.config))) || null;
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
  // --- state: versioned data.load with forward migrations.
  //   spec: { schema_version: N, migrations?: [{from, to, apply}], defaults? }
  // On load: read file, read its __schema_version__ (default 1 if missing),
  // run ordered migrations up to N, persist, return the upgraded object.
  // Throws on downgrade (file version > declared) — widgets should refuse
  // to touch data written by a newer bundle. Per-path mutex serialises
  // concurrent state.load calls inside this window; cross-iframe coordination
  // relies on the same RMW limitation as data.patch (documented in the skill).
  const __stateLocks = {};
  async function __withStateLock(path, fn) {
    const prev = __stateLocks[path] || Promise.resolve();
    let release;
    const gate = new Promise(function (r) { release = r; });
    __stateLocks[path] = prev.then(function () { return gate; });
    try { await prev; } catch (_) { /* ignore prior errors */ }
    try { return await fn(); } finally { release(); }
  }
  async function stateLoad(path, spec) {
    const s = spec || {};
    const declared = typeof s.schema_version === "number" ? s.schema_version : 1;
    if (!Number.isFinite(declared) || declared < 1) {
      throw new Error("spindrel.state: schema_version must be a positive integer");
    }
    const migrations = Array.isArray(s.migrations) ? s.migrations.slice() : [];
    const defaults = s.defaults;
    return __withStateLock(path, async function () {
      const initial = await dataLoad(path, undefined);
      let obj;
      let fileVersion;
      const hasInitial = initial !== undefined
        && (typeof initial !== "object" || initial !== null);
      if (!hasInitial || !isPlainObject(initial)) {
        obj = defaults !== undefined ? deepClone(defaults) : {};
        fileVersion = 0; // treat brand-new bundle as pre-v1
      } else {
        obj = deepClone(initial);
        const v = obj.__schema_version__;
        fileVersion = typeof v === "number" && v >= 1 ? v : 1;
      }
      if (fileVersion > declared) {
        throw new Error(
          "spindrel.state: " + path + " was written by schema v" + fileVersion +
          " but the bundle declares v" + declared + " — refusing to downgrade"
        );
      }
      let changed = fileVersion === 0; // brand-new file always persists version
      let v = Math.max(1, fileVersion);
      while (v < declared) {
        const step = migrations.find(function (m) { return m && m.from === v; });
        if (!step || typeof step.apply !== "function" || step.to !== v + 1) {
          throw new Error(
            "spindrel.state: missing migration from v" + v + " to v" + (v + 1) +
            " for " + path
          );
        }
        const result = await step.apply(obj);
        if (isPlainObject(result)) obj = result;
        v = step.to;
        changed = true;
      }
      obj.__schema_version__ = declared;
      if (changed) await dataSave(path, obj);
      return obj;
    });
  }
  async function stateSave(path, object) {
    return __withStateLock(path, async function () {
      const out = isPlainObject(object) ? Object.assign({}, object) : object;
      // Preserve the caller's declared version if they supplied one; otherwise
      // leave the existing field intact (rehydrate from disk if absent).
      if (isPlainObject(out) && typeof out.__schema_version__ !== "number") {
        try {
          const disk = await dataLoad(path, undefined);
          if (isPlainObject(disk) && typeof disk.__schema_version__ === "number") {
            out.__schema_version__ = disk.__schema_version__;
          }
        } catch (_) { /* first save */ }
      }
      await dataSave(path, out);
      return out;
    });
  }
  async function statePatch(path, patch, spec) {
    return __withStateLock(path, async function () {
      const current = await stateLoadInner(path, spec);
      const next = isPlainObject(current) && isPlainObject(patch)
        ? deepMerge(current, patch)
        : (patch !== undefined ? patch : current);
      if (isPlainObject(next) && spec && typeof spec.schema_version === "number") {
        next.__schema_version__ = spec.schema_version;
      }
      await dataSave(path, next);
      return next;
    });
  }
  // Internal variant used by statePatch so the outer patch lock isn't
  // re-entered by the nested load. Shares migration semantics with
  // stateLoad but does not acquire __stateLocks again.
  async function stateLoadInner(path, spec) {
    const s = spec || {};
    const declared = typeof s.schema_version === "number" ? s.schema_version : 1;
    const migrations = Array.isArray(s.migrations) ? s.migrations.slice() : [];
    const defaults = s.defaults;
    const initial = await dataLoad(path, undefined);
    let obj;
    let fileVersion;
    if (!isPlainObject(initial)) {
      obj = defaults !== undefined ? deepClone(defaults) : {};
      fileVersion = 0;
    } else {
      obj = deepClone(initial);
      const v = obj.__schema_version__;
      fileVersion = typeof v === "number" && v >= 1 ? v : 1;
    }
    if (fileVersion > declared) {
      throw new Error(
        "spindrel.state: " + path + " was written by schema v" + fileVersion +
        " but the bundle declares v" + declared + " — refusing to downgrade"
      );
    }
    let v = Math.max(1, fileVersion);
    while (v < declared) {
      const step = migrations.find(function (m) { return m && m.from === v; });
      if (!step || typeof step.apply !== "function" || step.to !== v + 1) {
        throw new Error(
          "spindrel.state: missing migration from v" + v + " to v" + (v + 1) +
          " for " + path
        );
      }
      const result = await step.apply(obj);
      if (isPlainObject(result)) obj = result;
      v = step.to;
    }
    obj.__schema_version__ = declared;
    return obj;
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
    const __t0 = Date.now();
    const __argsClone = __safeJsonClone(args || {});
    try {
      const resp = await api("/api/v1/widget-actions", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (!resp || resp.ok !== true) {
        const errMsg = (resp && resp.error) || "callTool '" + name + "' failed";
        __sendDebugEvent("tool-call", {
          tool: name, args: __argsClone, ok: false,
          error: errMsg, durationMs: Date.now() - __t0,
        });
        throw new Error(errMsg);
      }
      const env = resp.envelope || null;
      __sendDebugEvent("tool-call", {
        tool: name, args: __argsClone, ok: true,
        response: __safeJsonClone(env), durationMs: Date.now() - __t0,
      });
      return env;
    } catch (e) {
      // Rethrow after trace (the try/catch above already emits on !ok
      // responses; this catches transport errors from api()).
      if (!(e && e.__spindrel_traced)) {
        __sendDebugEvent("tool-call", {
          tool: name, args: __argsClone, ok: false,
          error: (e && e.message) || String(e), durationMs: Date.now() - __t0,
        });
      }
      throw e;
    }
  }
  // Fetch a tool's input + (optional) return schema so widget authors
  // can look up the expected envelope shape before coding extraction.
  // Local tools with a registered 'returns=' schema get a concrete
  // 'returns_schema'; MCP tools return 'returns_schema: null' (the MCP
  // spec doesn't carry return shapes — fall back to ambient trace via
  // inspect_widget_pin). Throws on 404 / unknown tool.
  async function toolSchema(name) {
    if (!name || typeof name !== "string") {
      throw new Error("toolSchema: name is required");
    }
    return api("/api/v1/tools/" + encodeURIComponent(name) + "/signature");
  }

  // ───────────────────────────────────────────────────────────────────────
  // Phase B.1 SDK helper: spindrel.db — server-side SQLite per bundle.
  // Routes through POST /api/v1/widget-actions (dispatch:"db_query"|"db_exec").
  // dashboard_pin_id identifies which pin's bundle DB to target.
  // ───────────────────────────────────────────────────────────────────────

  async function dbQuery(sql, params) {
    if (!dashboardPinId) throw new Error("spindrel.db requires a pinned widget (dashboardPinId is null)");
    if (typeof sql !== "string" || !sql.trim()) throw new Error("spindrel.db.query: sql must be a non-empty string");
    const resp = await api("/api/v1/widget-actions", {
      method: "POST",
      body: JSON.stringify({
        dispatch: "db_query",
        sql: sql,
        params: params || [],
        dashboard_pin_id: dashboardPinId,
      }),
    });
    if (!resp || resp.ok !== true) throw new Error((resp && resp.error) || "spindrel.db.query failed");
    return (resp.db_result && resp.db_result.rows) || [];
  }
  async function dbExec(sql, params) {
    if (!dashboardPinId) throw new Error("spindrel.db requires a pinned widget (dashboardPinId is null)");
    if (typeof sql !== "string" || !sql.trim()) throw new Error("spindrel.db.exec: sql must be a non-empty string");
    const resp = await api("/api/v1/widget-actions", {
      method: "POST",
      body: JSON.stringify({
        dispatch: "db_exec",
        sql: sql,
        params: params || [],
        dashboard_pin_id: dashboardPinId,
      }),
    });
    if (!resp || resp.ok !== true) throw new Error((resp && resp.error) || "spindrel.db.exec failed");
    return resp.db_result || { lastInsertRowid: null, rowsAffected: 0 };
  }
  async function dbTx(callback) {
    if (!dashboardPinId) throw new Error("spindrel.db requires a pinned widget (dashboardPinId is null)");
    if (typeof callback !== "function") throw new Error("spindrel.db.tx: callback must be a function");
    // Lightweight client-side tx wrapper: runs callback with a tx-like object
    // whose exec/query methods share the same pin-id context. For true server-
    // side atomicity, use raw SQL with BEGIN/COMMIT in a single db_exec call.
    const tx = { exec: dbExec, query: dbQuery };
    return callback(tx);
  }

  // ───────────────────────────────────────────────────────────────────────
  // Phase B.2 SDK helper: spindrel.callHandler — invoke a @on_action Python
  // handler declared in the pin's widget.py. Routes through
  // POST /api/v1/widget-actions (dispatch:"widget_handler"). The handler
  // runs in-process under the pin's bot scope.
  // ───────────────────────────────────────────────────────────────────────

  async function callHandler(name, args) {
    if (!dashboardPinId) {
      throw new Error("spindrel.callHandler requires a pinned widget (dashboardPinId is null)");
    }
    if (typeof name !== "string" || !name.trim()) {
      throw new Error("spindrel.callHandler: name must be a non-empty string");
    }
    const resp = await api("/api/v1/widget-actions", {
      method: "POST",
      body: JSON.stringify({
        dispatch: "widget_handler",
        handler: name,
        args: args || {},
        dashboard_pin_id: dashboardPinId,
      }),
    });
    if (!resp || resp.ok !== true) {
      throw new Error((resp && resp.error) || "spindrel.callHandler '" + name + "' failed");
    }
    return resp.result;
  }

  // ───────────────────────────────────────────────────────────────────────
  // Phase A SDK helpers (2026-04-19). See Track - Widget SDK in the vault
  // for the full plan. These are pure client-side — no new backend infra.
  // Scope: widget↔widget bus, TTL cache with dedup, host-chrome toasts,
  // log ring buffer, minimal UI helpers (table, status), declarative form,
  // uncaught-error forwarding to host chrome.
  // ───────────────────────────────────────────────────────────────────────

  // --- Bus: widget↔widget pubsub via BroadcastChannel, scoped per channel.
  // User-dashboard cross-widget comms land when dashboard slug threads
  // through the iframe props (Phase B). For now: channel-scoped only;
  // falls back to a "global" scope if channelId is null.
  const __busName = "spindrel:bus:" + (channelId || "global");
  let __busChannel = null;
  try {
    __busChannel = typeof BroadcastChannel !== "undefined"
      ? new BroadcastChannel(__busName)
      : null;
  } catch (_) { __busChannel = null; }
  const __busSubs = new Map();
  function __busEnsureWired() {
    if (!__busChannel || __busChannel.__wired) return __busChannel;
    __busChannel.__wired = true;
    __busChannel.addEventListener("message", function (e) {
      const msg = e.data || {};
      const subs = __busSubs.get(msg.topic);
      if (!subs) return;
      for (const cb of subs) {
        try { cb(msg.data, msg.topic); } catch (err) { console.error("spindrel.bus handler threw:", err); }
      }
    });
    return __busChannel;
  }
  function busPublish(topic, data) {
    if (typeof topic !== "string" || !topic) throw new Error("spindrel.bus.publish: topic required");
    const ch = __busEnsureWired();
    if (!ch) return;
    try { ch.postMessage({ topic: topic, data: data }); } catch (_) { /* serialization error */ }
  }
  function busSubscribe(topic, cb) {
    if (typeof topic !== "string" || !topic) throw new Error("spindrel.bus.subscribe: topic required");
    if (typeof cb !== "function") throw new Error("spindrel.bus.subscribe: callback required");
    __busEnsureWired();
    let set = __busSubs.get(topic);
    if (!set) { set = new Set(); __busSubs.set(topic, set); }
    set.add(cb);
    return function () {
      const s = __busSubs.get(topic);
      if (!s) return;
      s.delete(cb);
      if (s.size === 0) __busSubs.delete(topic);
    };
  }

  // --- Stream: SSE multiplexer over the channel-events bus. Widgets
  // subscribe to one or more ChannelEventKind values and receive typed
  // events as they arrive. Uses fetch() + ReadableStream (not EventSource)
  // so the widget bearer token rides in the Authorization header rather
  // than leaking into a query string. Auto-reconnects on network drop
  // with exponential backoff + since=lastSeq so the ring buffer fills the gap.
  const __STREAM_KIND_WHITELIST = new Set([
    "new_message","message_updated","turn_started","turn_stream_token",
    "turn_stream_thinking","turn_stream_tool_start","turn_stream_tool_result",
    "turn_ended","approval_requested","approval_resolved","attachment_deleted",
    "delivery_failed","workflow_progress","heartbeat_tick","tool_activity",
    "shutdown","replay_lapsed","context_budget","memory_scheme_bootstrap",
    "pinned_file_updated","skill_auto_inject","llm_status","ephemeral_message",
    "modal_submitted","widget_reload",
  ]);
  function __streamNormalizeArgs(a, b, c) {
    // Overloaded:
    //   stream(kind|kinds, cb)
    //   stream(kind|kinds, filter, cb)
    //   stream(optsObject, cb)
    //   stream(optsObject, filter, cb)
    let opts, filter, cb;
    const firstIsOpts = a && typeof a === "object" && !Array.isArray(a);
    if (firstIsOpts) { opts = a; }
    else { opts = { kinds: a }; }
    if (typeof b === "function" && c === undefined) { cb = b; }
    else { filter = b; cb = c; }
    if (typeof cb !== "function") throw new Error("spindrel.stream: callback required");
    if (filter !== undefined && filter !== null && typeof filter !== "function") {
      throw new Error("spindrel.stream: filter must be a function or omitted");
    }
    let kinds = opts.kinds;
    if (typeof kinds === "string") kinds = [kinds];
    if (kinds && !Array.isArray(kinds)) {
      throw new Error("spindrel.stream: kinds must be a string, array of strings, or omitted");
    }
    if (kinds) {
      for (const k of kinds) {
        if (!__STREAM_KIND_WHITELIST.has(k)) {
          throw new Error("spindrel.stream: unknown event kind '" + k + "'");
        }
      }
    }
    const cid = opts.channelId || channelId;
    if (!cid) {
      throw new Error("spindrel.stream: channelId required (widget has no host channel; pass opts.channelId)");
    }
    return { kinds: kinds || null, channelId: cid, since: typeof opts.since === "number" ? opts.since : null, filter: filter || null, cb: cb };
  }
  // --- Broker probe/ack. If the host mounts WidgetStreamBroker on this page
  // it answers stream_ready_probe with stream_ready_ack, letting us piggyback
  // on the host's channel SSE instead of opening our own fetch. See
  // ui/src/api/hooks/useWidgetStreamBroker.ts.
  const __STREAM_BROKER_SETTLE_MS = 75;
  let __streamBrokerReady = false;
  let __streamBrokerChannelId = null;
  let __directStreamCount = 0;
  function __streamPerfDebugEnabled() {
    try {
      return window.localStorage.getItem("spindrelPerfDebug") === "1" ||
        new URLSearchParams(window.location.search).get("perf") === "1";
    } catch (_) {
      return false;
    }
  }
  function __streamPerfLog(message, extra) {
    if (!__streamPerfDebugEnabled()) return;
    try {
      console.debug("[spindrel:perf] widget stream", Object.assign({
        message: message,
        channelId: channelId,
        directStreams: __directStreamCount,
        brokerReady: __streamBrokerReady,
        brokerChannelId: __streamBrokerChannelId,
      }, extra || {}));
    } catch (_) {}
  }
  window.addEventListener("message", function (e) {
    const msg = e && e.data;
    if (!msg || typeof msg !== "object" || msg.__spindrel !== true) return;
    if (msg.type === "stream_ready_ack") {
      __streamBrokerReady = true;
      __streamBrokerChannelId = msg.channelId || null;
      __streamPerfLog("broker ack");
    }
  });
  if (channelId) {
    try {
      window.parent.postMessage(
        { __spindrel: true, type: "stream_ready_probe" },
        "*"
      );
    } catch (_) { /* cross-origin edge — falls back to direct SSE */ }
  }
  let __streamSubCounter = 0;
  function __newStreamSubId() {
    __streamSubCounter += 1;
    return "sub-" + Date.now().toString(36) + "-" + __streamSubCounter;
  }
  function stream(a, b, c) {
    const args = __streamNormalizeArgs(a, b, c);
    let stopped = false;
    let activeUnsub = null;
    let settleTimer = null;

    function startBroker() {
      const subId = __newStreamSubId();
      function onBrokerMsg(e) {
        const msg = e && e.data;
        if (stopped || !msg || typeof msg !== "object") return;
        if (msg.__spindrel !== true || msg.type !== "stream_event") return;
        if (msg.subId !== subId) return;
        const event = msg.event;
        if (!event) return;
        if (args.filter) {
          let keep = true;
          try { keep = !!args.filter(event); }
          catch (err) {
            console.error("spindrel.stream filter threw:", err);
            keep = false;
          }
          if (!keep) return;
        }
        try { args.cb(event); }
        catch (err) { console.error("spindrel.stream handler threw:", err); }
      }
      window.addEventListener("message", onBrokerMsg);
      try {
        window.parent.postMessage({
          __spindrel: true,
          type: "stream_subscribe",
          subId: subId,
          kinds: args.kinds,
          channelId: args.channelId,
        }, "*");
        __streamPerfLog("broker subscribe", { subId: subId, kinds: args.kinds });
      } catch (_) { /* host unreachable — unsubscribe still cleans up */ }
      return function unsubscribe() {
        window.removeEventListener("message", onBrokerMsg);
        try {
          window.parent.postMessage({
            __spindrel: true,
            type: "stream_unsubscribe",
            subId: subId,
          }, "*");
        } catch (_) {}
      };
    }

    function startDirect() {
      const controller = new AbortController();
      let retry = 0;
      let lastSeq = args.since;
      let reconnectTimer = null;
      let counted = true;
      __directStreamCount += 1;
      __streamPerfLog("direct subscribe", { kinds: args.kinds });
      function closeDirect() {
        if (counted) {
          counted = false;
          __directStreamCount = Math.max(0, __directStreamCount - 1);
          __streamPerfLog("direct unsubscribe", { kinds: args.kinds });
        }
        if (reconnectTimer != null) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
        try { controller.abort(); } catch (_) {}
      }
      async function connect() {
        if (stopped) return;
        const params = new URLSearchParams();
        params.set("channel_id", args.channelId);
        if (args.kinds && args.kinds.length) params.set("kinds", args.kinds.join(","));
        if (typeof lastSeq === "number") params.set("since", String(lastSeq));
        const url = "/api/v1/widget-actions/stream?" + params.toString();
        let resp;
        try {
          resp = await apiFetch(url, { signal: controller.signal, headers: { Accept: "text/event-stream" } });
        } catch (err) {
          if (stopped || controller.signal.aborted) return;
          scheduleReconnect();
          return;
        }
        if (!resp.ok || !resp.body) {
          if (stopped) return;
          scheduleReconnect();
          return;
        }
        retry = 0;
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        try {
          while (true) {
            const chunk = await reader.read();
            if (chunk.done || stopped) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            const lines = buffer.split("\\n");
            buffer = lines.pop() || "";
            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              let event;
              try { event = JSON.parse(line.slice(6)); }
              catch (_) { continue; }
              if (typeof event.seq === "number") lastSeq = event.seq;
              if (event.kind === "shutdown") { stopped = true; closeDirect(); return; }
              if (event.kind === "replay_lapsed") {
                try { notify("warn", "Stream replay lapsed — some events may be missing."); } catch (_) {}
                // Fall through — the widget also sees it via cb so it can refetch.
              }
              if (args.filter) {
                let keep = true;
                try { keep = !!args.filter(event); }
                catch (err) { console.error("spindrel.stream filter threw:", err); keep = false; }
                if (!keep) continue;
              }
              try { args.cb(event); }
              catch (err) { console.error("spindrel.stream handler threw:", err); }
            }
          }
        } catch (_) { /* reader error — fall through to reconnect */ }
        if (!stopped) scheduleReconnect();
      }
      function scheduleReconnect() {
        if (stopped || reconnectTimer != null) return;
        const delay = Math.min(1000 * Math.pow(2, retry), 30000);
        retry = Math.min(retry + 1, 10);
        reconnectTimer = setTimeout(function () {
          reconnectTimer = null;
          if (!stopped) connect();
        }, delay);
      }
      connect();
      return closeDirect;
    }

    function brokerMatches() {
      return __streamBrokerReady && args.channelId === __streamBrokerChannelId;
    }

    function startBestAvailable() {
      if (stopped || activeUnsub) return;
      activeUnsub = brokerMatches() ? startBroker() : startDirect();
    }

    if (brokerMatches()) {
      startBestAvailable();
    } else if (channelId && args.channelId === channelId && !__streamBrokerReady) {
      settleTimer = setTimeout(startBestAvailable, __STREAM_BROKER_SETTLE_MS);
    } else {
      startBestAvailable();
    }

    return function unsubscribe() {
      if (stopped) return;
      stopped = true;
      if (settleTimer != null) {
        clearTimeout(settleTimer);
        settleTimer = null;
      }
      if (activeUnsub) {
        try { activeUnsub(); } catch (_) {}
        activeUnsub = null;
      }
    };
  }

  // --- onReload / autoReload: the lazy-author DX layer over widget_reload.
  //
  //   Widget author pattern:
  //     spindrel.autoReload(async () => {
  //       const rows = await spindrel.db.query("select ...");
  //       render(rows);
  //     });
  //
  //   Behind the scenes the preamble starts a single SSE subscription filtered
  //   by kind=widget_reload and pin_id===self.dashboardPinId. Every registered
  //   callback fires when a reload arrives. autoReload additionally runs the
  //   render function once at registration time so "mount" and "reload" share
  //   a single code path.
  //
  //   No-op (but returns a callable unsubscribe) when the widget is not pin-
  //   scoped (dashboardPinId === null) or has no channelId — there's no bus
  //   to subscribe to. Widget authors don't need to guard.
  const __reloadHandlers = new Set();
  let __reloadStreamUnsub = null;
  function __ensureReloadStream() {
    if (__reloadStreamUnsub || !dashboardPinId || !channelId) return;
    try {
      __reloadStreamUnsub = stream(
        { kinds: ["widget_reload"], channelId: channelId },
        function (event) {
          const payload = event && event.payload;
          return !!payload && payload.pin_id === dashboardPinId;
        },
        function (event) {
          for (const cb of Array.from(__reloadHandlers)) {
            try {
              const r = cb(event);
              if (r && typeof r.then === "function") {
                r.catch(function (err) {
                  console.error("spindrel.onReload handler rejected:", err);
                });
              }
            } catch (err) {
              console.error("spindrel.onReload handler threw:", err);
            }
          }
        }
      );
    } catch (err) {
      // Stream setup failed (e.g. channelId absent). Don't block the widget;
      // next onReload() call retries.
      console.error("spindrel.onReload: could not subscribe:", err);
    }
  }
  function onReload(cb) {
    if (typeof cb !== "function") throw new Error("spindrel.onReload: callback required");
    __reloadHandlers.add(cb);
    __ensureReloadStream();
    return function unsubscribe() {
      __reloadHandlers.delete(cb);
      if (__reloadHandlers.size === 0 && __reloadStreamUnsub) {
        try { __reloadStreamUnsub(); } catch (_) {}
        __reloadStreamUnsub = null;
      }
    };
  }
  function autoReload(renderFn) {
    if (typeof renderFn !== "function") {
      throw new Error("spindrel.autoReload: render function required");
    }
    try {
      const r = renderFn();
      if (r && typeof r.then === "function") {
        r.catch(function (err) {
          console.error("spindrel.autoReload initial render rejected:", err);
        });
      }
    } catch (err) {
      console.error("spindrel.autoReload initial render threw:", err);
    }
    return onReload(function () { return renderFn(); });
  }

  // --- Cache: TTL'd Map with inflight dedup so concurrent get() for the
  // same key share a single fetcher invocation.
  const __cacheStore = new Map();
  function cacheGet(key, ttlMs, fetcher) {
    if (typeof key !== "string" || !key) throw new Error("spindrel.cache.get: key required");
    const now = Date.now();
    const hit = __cacheStore.get(key);
    if (hit && hit.expires > now && hit.value !== undefined) return Promise.resolve(hit.value);
    if (hit && hit.inflight) return hit.inflight;
    if (typeof fetcher !== "function") {
      return Promise.resolve(hit && hit.value !== undefined ? hit.value : undefined);
    }
    const ttl = typeof ttlMs === "number" && ttlMs > 0 ? ttlMs : 30000;
    const p = Promise.resolve().then(fetcher).then(function (val) {
      __cacheStore.set(key, { expires: Date.now() + ttl, value: val });
      return val;
    }).catch(function (err) {
      __cacheStore.delete(key);
      throw err;
    });
    __cacheStore.set(key, { inflight: p });
    return p;
  }
  function cacheSet(key, value, ttlMs) {
    const ttl = typeof ttlMs === "number" && ttlMs > 0 ? ttlMs : 30000;
    __cacheStore.set(key, { expires: Date.now() + ttl, value: value });
  }
  function cacheClear(key) {
    if (key === undefined) __cacheStore.clear();
    else __cacheStore.delete(key);
  }

  // --- Notify: surface a status message to the host chrome as a toast
  // rendered above the iframe. Levels: info / success / warn / error.
  // Use for auth failures, submit confirmations, non-fatal errors the
  // widget would otherwise swallow silently.
  function notify(level, message) {
    const lvl = (level === "warn" || level === "error" || level === "success") ? level : "info";
    const msg = typeof message === "string"
      ? message
      : String(message == null ? "" : message);
    try {
      window.parent.postMessage(
        { __spindrel: true, type: "notify", level: lvl, message: msg, ts: Date.now() },
        "*"
      );
    } catch (_) { /* cross-origin or detached */ }
  }

  // --- Log: in-iframe ring buffer (cap 200) + forward to host for the
  // future Dev Panel "Widget log" subtab. Not wired to the panel yet;
  // the messages flow through postMessage so the receiver can pick them
  // up without another iframe change.
  const __logBuffer = [];
  const __LOG_CAP = 200;
  function __logPush(level, args) {
    const entry = {
      ts: Date.now(),
      level: level,
      message: Array.prototype.slice.call(args).map(function (a) {
        if (typeof a === "string") return a;
        try { return JSON.stringify(a); } catch (_) { return String(a); }
      }).join(" "),
    };
    __logBuffer.push(entry);
    if (__logBuffer.length > __LOG_CAP) __logBuffer.shift();
    // Forward to the ambient debug-event ring so the Inspector panel +
    // inspect_widget_pin tool can read author-level logs alongside tool
    // traffic + errors. __sendDebugEvent is a no-op when pinId is null.
    if (typeof __sendDebugEvent === "function") {
      __sendDebugEvent("log", { level: level, message: entry.message });
    }
  }
  const log = {
    info:  function () { __logPush("info",  arguments); },
    warn:  function () { __logPush("warn",  arguments); },
    error: function () { __logPush("error", arguments); },
    buffer: function () { return __logBuffer.slice(); },
    clear:  function () { __logBuffer.length = 0; },
  };

  // ───────────────────────────────────────────────────────────────────────
  // Debug-event ring (POST /api/v1/widget-debug/events). Ambient trace of
  // every callTool / loadAttachment / loadAsset request-response pair, plus
  // uncaught JS errors, unhandled promise rejections, console.log/warn/error
  // output, and explicit spindrel.log.* entries. The authoring bot reads
  // these via the inspect_widget_pin tool; the user reads them via the
  // Inspector side-panel on the pin. Fire-and-forget: failures never bubble
  // into widget runtime. No events emitted when dashboardPinId is null
  // (inline chat renders don't have a pin to attach to).
  // ───────────────────────────────────────────────────────────────────────
  function __safeJsonClone(v) {
    if (v == null) return v;
    try { return JSON.parse(JSON.stringify(v)); } catch (_) {
      try { return String(v); } catch (__) { return null; }
    }
  }
  async function __sendDebugEvent(kind, payload) {
    if (!dashboardPinId) return;
    try {
      await apiFetch("/api/v1/widget-debug/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pin_id: dashboardPinId,
          kind: kind,
          ts: Date.now(),
          payload: payload || {},
        }),
      });
    } catch (_) { /* debug telemetry — must never break the widget */ }
  }
  // console shim — tees through to the real console so native devtools
  // still show the output, AND forwards to the event ring so the bot /
  // Inspector can read it without the user opening devtools.
  (function () {
    const levels = ["log", "info", "warn", "error"];
    levels.forEach(function (lvl) {
      const orig = console[lvl] ? console[lvl].bind(console) : function () {};
      console[lvl] = function () {
        try { orig.apply(null, arguments); } catch (_) {}
        try {
          const args = Array.prototype.slice.call(arguments).map(__safeJsonClone);
          __sendDebugEvent("console", { level: lvl === "log" ? "log" : lvl, args: args });
        } catch (_) {}
      };
    });
  })();

  // --- UI helpers: minimal DOM-fragment builders using sd-* utility classes.
  // No framework — ui.status replaces innerHTML; ui.table returns an HTML
  // string so widgets can either set innerHTML or inject into a template.
  function __coerceEl(elOrSelector) {
    if (elOrSelector == null) throw new Error("spindrel.ui: element required");
    if (typeof elOrSelector === "string") {
      const el = document.querySelector(elOrSelector);
      if (!el) throw new Error("spindrel.ui: selector '" + elOrSelector + "' matched nothing");
      return el;
    }
    return elOrSelector;
  }
  function __esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function uiStatus(elOrSelector, state, opts) {
    const el = __coerceEl(elOrSelector);
    const o = opts || {};
    if (state === "ready") { el.innerHTML = ""; return; }
    if (state === "loading") {
      const h = typeof o.height === "number" ? o.height : 60;
      el.innerHTML = '<div class="sd-skeleton" style="height:' + h + 'px"></div>';
      return;
    }
    if (state === "empty") {
      el.innerHTML = '<div class="sd-empty">' + __esc(o.message || "Nothing to show") + '</div>';
      return;
    }
    if (state === "error") {
      el.innerHTML = '<div class="sd-error">' + __esc(o.message || "Something went wrong") + '</div>';
      return;
    }
    throw new Error("spindrel.ui.status: unknown state '" + state + "'");
  }
  function uiTable(rows, columns, opts) {
    const o = opts || {};
    if (!Array.isArray(rows) || rows.length === 0) {
      return '<div class="sd-empty">' + __esc(o.emptyMessage || "No rows") + '</div>';
    }
    const cols = Array.isArray(columns) && columns.length > 0
      ? columns
      : Object.keys(rows[0] || {}).map(function (k) { return { key: k, label: k }; });
    const thead = cols.map(function (c) {
      return '<th style="text-align:' + (c.align || "left") + '">' +
        __esc(c.label != null ? c.label : c.key) + '</th>';
    }).join("");
    const tbody = rows.map(function (row) {
      const tds = cols.map(function (c) {
        let v = row[c.key];
        if (typeof c.format === "function") {
          try { v = c.format(v, row); } catch (_) { /* fall back to raw */ }
        }
        const isHtml = c.html === true;
        return '<td style="text-align:' + (c.align || "left") + '">' +
          (isHtml ? (v == null ? "" : String(v)) : __esc(v)) + '</td>';
      }).join("");
      return '<tr>' + tds + '</tr>';
    }).join("");
    return '<table class="sd-table"><thead><tr>' + thead +
      '</tr></thead><tbody>' + tbody + '</tbody></table>';
  }

  // --- ui.chart: minimal inline SVG line/bar/area helper. Sparkline-first:
  // no axis, fills container width, theme.accent stroke. Data accepts a
  // flat number[] or an array of {x?, y} points; x is i when omitted.
  // Opts: { type?: "line"|"bar"|"area", height?, color?, min?, max?,
  //   showAxis?, strokeWidth?, format?(v), emptyMessage?, label? }.
  function uiChart(elOrSelector, data, opts) {
    const el = __coerceEl(elOrSelector);
    const o = opts || {};
    const type = o.type || "line";
    const height = typeof o.height === "number" ? o.height : 40;
    const vbWidth = 200; // fixed viewBox; SVG scales to container width
    const strokeWidth = typeof o.strokeWidth === "number" ? o.strokeWidth : 1.5;
    const accent = (window.spindrel && window.spindrel.theme && window.spindrel.theme.accent) || "#3b82f6";
    const color = o.color || accent;
    const showAxis = o.showAxis === true;
    const fmt = typeof o.format === "function" ? o.format : function (v) { return String(v); };

    const arr = Array.isArray(data) ? data : [];
    if (arr.length === 0) {
      el.innerHTML = '<div class="sd-empty">' + __esc(o.emptyMessage || "No data") + '</div>';
      return;
    }
    const points = arr.map(function (d, i) {
      if (typeof d === "number") return { x: i, y: d };
      if (d && typeof d === "object") {
        const yn = typeof d.y === "number" ? d.y : Number(d.y);
        const xn = typeof d.x === "number" ? d.x : (d.x != null ? Number(d.x) : i);
        return { x: isFinite(xn) ? xn : i, y: isFinite(yn) ? yn : 0 };
      }
      return { x: i, y: 0 };
    });

    let minY = typeof o.min === "number" ? o.min : Infinity;
    let maxY = typeof o.max === "number" ? o.max : -Infinity;
    for (const p of points) {
      if (typeof o.min !== "number" && p.y < minY) minY = p.y;
      if (typeof o.max !== "number" && p.y > maxY) maxY = p.y;
    }
    if (!isFinite(minY)) minY = 0;
    if (!isFinite(maxY)) maxY = 0;
    if (minY === maxY) maxY = minY + 1; // flat line: pad so stroke sits mid-band

    const padY = 2;
    const innerH = Math.max(1, height - padY * 2);
    const axisW = showAxis ? 28 : 0;
    const innerW = Math.max(1, vbWidth - axisW - 2);

    function sx(i) {
      if (points.length === 1) return axisW + innerW / 2;
      return axisW + (i / (points.length - 1)) * innerW;
    }
    function sy(y) {
      const t = (y - minY) / (maxY - minY);
      return padY + (1 - t) * innerH;
    }

    let body = "";
    if (type === "bar") {
      const step = innerW / points.length;
      const barW = Math.max(0.5, step - 1);
      for (let i = 0; i < points.length; i++) {
        const x = axisW + i * step;
        const y = sy(points[i].y);
        const h = (padY + innerH) - y;
        body += '<rect x="' + x.toFixed(2) + '" y="' + y.toFixed(2) +
          '" width="' + barW.toFixed(2) + '" height="' + Math.max(0, h).toFixed(2) +
          '" fill="' + __esc(color) + '" vector-effect="non-scaling-stroke" />';
      }
    } else {
      const d = points.map(function (p, i) {
        return (i === 0 ? "M" : "L") + sx(i).toFixed(2) + "," + sy(p.y).toFixed(2);
      }).join(" ");
      if (type === "area") {
        const fill = d +
          " L" + sx(points.length - 1).toFixed(2) + "," + (padY + innerH).toFixed(2) +
          " L" + sx(0).toFixed(2) + "," + (padY + innerH).toFixed(2) + " Z";
        body += '<path d="' + fill + '" fill="' + __esc(color) +
          '" fill-opacity="0.18" stroke="none" vector-effect="non-scaling-stroke" />';
      }
      body += '<path d="' + d + '" fill="none" stroke="' + __esc(color) +
        '" stroke-width="' + strokeWidth + '" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" />';
    }

    let axis = "";
    if (showAxis) {
      const tickStyle = 'font-size="9" fill="currentColor" font-family="inherit" opacity="0.55"';
      axis =
        '<text x="' + (axisW - 2) + '" y="' + (padY + 6) + '" text-anchor="end" ' + tickStyle + '>' + __esc(fmt(maxY)) + '</text>' +
        '<text x="' + (axisW - 2) + '" y="' + (padY + innerH) + '" text-anchor="end" ' + tickStyle + '>' + __esc(fmt(minY)) + '</text>';
    }

    const title = o.label ? '<title>' + __esc(o.label) + '</title>' : '';
    el.innerHTML =
      '<svg viewBox="0 0 ' + vbWidth + ' ' + height + '" ' +
      'width="100%" height="' + height + '" preserveAspectRatio="none" ' +
      'style="display:block;overflow:visible">' +
      title + axis + body +
      '</svg>';
  }

  // --- ui.icon: render an icon from the sprite injected at body top.
  // Returns an SVG string suitable for innerHTML or template concatenation.
  // Static usage (no JS): <svg class="sd-icon"><use href="#sd-icon-check"/></svg>
  const __SD_ICON_NAMES = ${JSON.stringify(WIDGET_ICON_NAMES)};
  function uiIcon(name, opts) {
    const o = opts || {};
    const cls = "sd-icon" + (o.size ? " sd-icon--" + o.size : "") +
      (o.tone ? " sd-icon--" + o.tone : "") +
      (o.className ? " " + o.className : "");
    const safeName = String(name || "");
    // Best-effort validation — unknown names produce an invisible <svg>.
    // Known names render via sprite <use>.
    if (!__SD_ICON_NAMES.includes(safeName)) {
      if (window.spindrel && window.spindrel.log && window.spindrel.log.warn) {
        window.spindrel.log.warn("spindrel.ui.icon: unknown name '" + safeName + "'");
      }
    }
    return '<svg class="' + __esc(cls) + '" aria-hidden="true" focusable="false">' +
      '<use href="#sd-icon-' + __esc(safeName) + '"></use></svg>';
  }

  // --- ui.autogrow: resize a textarea to fit its content on input.
  // Returns a teardown function. Caps at opts.maxHeight (default 240px).
  function uiAutogrow(elOrSelector, opts) {
    const ta = __coerceEl(elOrSelector);
    const o = opts || {};
    const maxH = typeof o.maxHeight === "number" ? o.maxHeight : 240;
    ta.setAttribute("data-autogrow", "true");
    function resize() {
      ta.style.height = "auto";
      const next = Math.min(maxH, ta.scrollHeight);
      ta.style.height = next + "px";
      ta.style.overflowY = ta.scrollHeight > maxH ? "auto" : "hidden";
    }
    ta.addEventListener("input", resize);
    // Run once on next frame so initial value sizes correctly.
    Promise.resolve().then(resize);
    return function teardown() {
      ta.removeEventListener("input", resize);
      ta.style.height = "";
      ta.style.overflowY = "";
      ta.removeAttribute("data-autogrow");
    };
  }

  // --- ui.menu: popover menu anchored to an element.
  //   const menu = spindrel.ui.menu(anchor, [
  //     { label: "Edit", icon: "pencil", onSelect: () => … },
  //     { label: "Delete", icon: "trash", danger: true, onSelect: () => … },
  //     { divider: true },
  //     { label: "Help",  onSelect: () => … },
  //   ]);
  //   // menu.close() to dismiss programmatically.
  // Handles outside-click + Escape + ArrowUp/Down/Enter.
  function uiMenu(anchorEl, items, opts) {
    const anchor = __coerceEl(anchorEl);
    const o = opts || {};
    const list = Array.isArray(items) ? items : [];
    const menu = document.createElement("div");
    menu.className = "sd-menu";
    menu.setAttribute("role", "menu");

    const itemEls = [];
    list.forEach(function (it, i) {
      if (it && it.divider) {
        const d = document.createElement("div");
        d.className = "sd-menu-divider";
        menu.appendChild(d);
        return;
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sd-menu-item" + (it.danger ? " sd-menu-item--danger" : "");
      btn.setAttribute("role", "menuitem");
      btn.tabIndex = -1;
      const iconHtml = it.icon ? uiIcon(it.icon, { size: "sm" }) : '';
      const kbdHtml = it.kbd ? '<span class="sd-spacer"></span><span class="sd-kbd">' + __esc(it.kbd) + '</span>' : '';
      btn.innerHTML = iconHtml + '<span>' + __esc(it.label || "") + '</span>' + kbdHtml;
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        close();
        if (typeof it.onSelect === "function") it.onSelect();
      });
      btn.addEventListener("mouseenter", function () { setActive(i); });
      menu.appendChild(btn);
      itemEls.push({ el: btn, index: i });
    });

    let activeIdx = -1;
    function setActive(i) {
      if (activeIdx >= 0 && itemEls[activeIdx]) {
        itemEls[activeIdx].el.removeAttribute("data-active");
      }
      activeIdx = i;
      if (itemEls[i]) {
        itemEls[i].el.setAttribute("data-active", "true");
        itemEls[i].el.focus();
      }
    }
    function move(step) {
      if (itemEls.length === 0) return;
      let n = activeIdx < 0 ? (step > 0 ? 0 : itemEls.length - 1) : activeIdx + step;
      if (n < 0) n = itemEls.length - 1;
      if (n >= itemEls.length) n = 0;
      setActive(n);
    }
    function onKey(ev) {
      if (ev.key === "Escape") { close(); ev.preventDefault(); return; }
      if (ev.key === "ArrowDown") { move(1); ev.preventDefault(); return; }
      if (ev.key === "ArrowUp") { move(-1); ev.preventDefault(); return; }
      if (ev.key === "Enter" && activeIdx >= 0 && itemEls[activeIdx]) {
        itemEls[activeIdx].el.click();
        ev.preventDefault();
      }
    }
    function onDocClick(ev) {
      if (!menu.contains(ev.target) && ev.target !== anchor) close();
    }
    let closed = false;
    function close() {
      if (closed) return;
      closed = true;
      document.removeEventListener("click", onDocClick, true);
      document.removeEventListener("keydown", onKey, true);
      if (menu.parentNode) menu.parentNode.removeChild(menu);
    }

    document.body.appendChild(menu);
    // Position below-right of anchor. Menu shrinks against viewport edges.
    const rect = anchor.getBoundingClientRect();
    const mh = menu.offsetHeight || 120;
    const mw = menu.offsetWidth || 140;
    const gap = 4;
    let top = rect.bottom + window.scrollY + gap;
    let left = rect.left + window.scrollX;
    const vh = window.innerHeight, vw = window.innerWidth;
    if (rect.bottom + mh + gap > vh && rect.top - mh - gap > 0) {
      top = rect.top + window.scrollY - mh - gap;
    }
    if (left + mw > vw - 4) left = Math.max(4, vw - mw - 4);
    menu.style.top = top + "px";
    menu.style.left = left + "px";
    if (o.minWidth === "anchor") menu.style.minWidth = rect.width + "px";
    menu.classList.add("sd-anim-pop");

    setTimeout(function () {
      document.addEventListener("click", onDocClick, true);
      document.addEventListener("keydown", onKey, true);
    }, 0);

    return { close: close };
  }

  // --- ui.tooltip: attach a hover/focus tooltip to an element.
  // Returns a teardown function.
  function uiTooltip(elOrSelector, text, opts) {
    const target = __coerceEl(elOrSelector);
    const o = opts || {};
    const delay = typeof o.delay === "number" ? o.delay : 200;
    let tip = null;
    let showT = 0;
    function show() {
      if (tip) return;
      tip = document.createElement("div");
      tip.className = "sd-tooltip";
      tip.textContent = String(text);
      document.body.appendChild(tip);
      const rect = target.getBoundingClientRect();
      const th = tip.offsetHeight, tw = tip.offsetWidth;
      let top = rect.top + window.scrollY - th - 6;
      if (top < window.scrollY + 4) top = rect.bottom + window.scrollY + 6;
      let left = rect.left + window.scrollX + rect.width / 2 - tw / 2;
      const vw = window.innerWidth;
      if (left < 4) left = 4;
      if (left + tw > vw - 4) left = vw - tw - 4;
      tip.style.top = top + "px";
      tip.style.left = left + "px";
      tip.classList.add("sd-anim-fade-in");
    }
    function hide() {
      if (showT) { clearTimeout(showT); showT = 0; }
      if (tip && tip.parentNode) tip.parentNode.removeChild(tip);
      tip = null;
    }
    function enter() { if (!showT) showT = setTimeout(show, delay); }
    function leave() { hide(); }
    target.addEventListener("mouseenter", enter);
    target.addEventListener("mouseleave", leave);
    target.addEventListener("focus", enter);
    target.addEventListener("blur", leave);
    return function teardown() {
      hide();
      target.removeEventListener("mouseenter", enter);
      target.removeEventListener("mouseleave", leave);
      target.removeEventListener("focus", enter);
      target.removeEventListener("blur", leave);
    };
  }

  // --- ui.confirm: promise-based confirm modal.
  //   const ok = await spindrel.ui.confirm({
  //     title: "Delete todo?",
  //     body: "This can't be undone.",
  //     confirmLabel: "Delete",
  //     danger: true,
  //   });
  function uiConfirm(opts) {
    const o = opts || {};
    return new Promise(function (resolve) {
      const backdrop = document.createElement("div");
      backdrop.className = "sd-modal-backdrop";
      const modal = document.createElement("div");
      modal.className = "sd-modal sd-anim-pop";
      const titleHtml = o.title ? '<h3 class="sd-modal__title">' + __esc(o.title) + '</h3>' : '';
      const bodyHtml = o.body ? '<div class="sd-modal__body">' + __esc(o.body) + '</div>' : '';
      const cancelLabel = o.cancelLabel || "Cancel";
      const confirmLabel = o.confirmLabel || "Confirm";
      const confirmCls = o.danger ? "sd-btn-danger" : "sd-btn-primary";
      modal.innerHTML = titleHtml + bodyHtml +
        '<div class="sd-modal__actions">' +
        '<button type="button" class="sd-btn" data-act="cancel">' + __esc(cancelLabel) + '</button>' +
        '<button type="button" class="sd-btn ' + confirmCls + '" data-act="confirm">' + __esc(confirmLabel) + '</button>' +
        '</div>';
      backdrop.appendChild(modal);
      document.body.appendChild(backdrop);
      function finish(result) {
        document.removeEventListener("keydown", onKey, true);
        if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
        resolve(result);
      }
      function onKey(ev) {
        if (ev.key === "Escape") { ev.preventDefault(); finish(false); }
        if (ev.key === "Enter") { ev.preventDefault(); finish(true); }
      }
      modal.querySelector('[data-act="cancel"]').addEventListener("click", function () { finish(false); });
      modal.querySelector('[data-act="confirm"]').addEventListener("click", function () { finish(true); });
      backdrop.addEventListener("click", function (ev) {
        if (ev.target === backdrop) finish(false);
      });
      document.addEventListener("keydown", onKey, true);
      const focusBtn = modal.querySelector(o.danger ? '[data-act="cancel"]' : '[data-act="confirm"]');
      if (focusBtn) focusBtn.focus();
    });
  }

  // --- Image: auth-aware image loader with a skeleton placeholder.
  //
  //   const tile = spindrel.image(url, { aspectRatio: "16/9", alt: "..." });
  //   container.appendChild(tile);
  //   // later (optional): tile.update(nextUrl) to swap the source without
  //   // tearing down the node (useful for rotating snapshot refreshes).
  //
  // Kills the "broken-image chrome chip" flash that shows up when a widget
  // appends an <img> with no src and fills src in later via an async
  // apiFetch → blob → createObjectURL dance. The returned wrapper renders
  // an sd-skeleton box at the declared aspect ratio immediately, then fades
  // in the <img> once the blob arrives. Revokes the previous object URL on
  // each .update() so rotating feeds don't leak.
  function image(url, opts) {
    const o = opts || {};
    const wrap = document.createElement("div");
    wrap.className = "sd-image";
    // Aspect ratio: accept "16/9" | "4/3" | 1.78 | number. Default to 16/9
    // so a zero-config call still sizes nicely inside a tile; callers can
    // pass a number to match an exact source aspect.
    let ar = o.aspectRatio;
    if (typeof ar === "number" && isFinite(ar) && ar > 0) {
      ar = String(ar);
    } else if (typeof ar !== "string" || !ar.trim()) {
      ar = "16 / 9";
    }
    wrap.style.cssText =
      "position:relative;width:100%;aspect-ratio:" + ar +
      ";border-radius:6px;overflow:hidden;background:var(--sd-surface-overlay,rgba(255,255,255,0.04))";

    // Skeleton shimmer fills the wrap until the blob lands.
    const skel = document.createElement("div");
    skel.className = "sd-skeleton";
    skel.style.cssText = "position:absolute;inset:0";
    wrap.appendChild(skel);

    // Error banner (hidden by default) — reuses sd-error styling.
    const err = document.createElement("div");
    err.className = "sd-error";
    err.style.cssText = "position:absolute;inset:0;display:none;align-items:center;justify-content:center;padding:8px;text-align:center;font-size:11px";
    wrap.appendChild(err);

    // The <img> stays hidden (opacity 0) until the blob resolves; then we
    // fade it in. Absolute-positioned so the skeleton can continue to fill
    // the wrap without a reflow when the image swaps in.
    const img = document.createElement("img");
    img.alt = typeof o.alt === "string" ? o.alt : "";
    img.style.cssText =
      "position:absolute;inset:0;width:100%;height:100%;" +
      "object-fit:cover;display:block;opacity:0;transition:opacity .2s ease";
    wrap.appendChild(img);

    let currentObjectUrl = null;
    let inflight = 0;
    function setError(msg) {
      err.textContent = msg || "Image failed to load";
      err.style.display = "flex";
      skel.style.display = "none";
    }
    function clearError() {
      err.style.display = "none";
      err.textContent = "";
    }
    async function load(nextUrl) {
      if (typeof nextUrl !== "string" || !nextUrl) {
        throw new Error("spindrel.image.update: url is required");
      }
      const ticket = ++inflight;
      clearError();
      skel.style.display = "block";
      img.style.opacity = "0";
      let resp;
      try {
        resp = await apiFetch(nextUrl, { headers: { Accept: "image/*" } });
      } catch (e) {
        if (ticket !== inflight) return;
        setError("Image fetch failed" + (e && e.message ? ": " + e.message : ""));
        return;
      }
      if (ticket !== inflight) return;
      if (!resp || !resp.ok) {
        setError("Image fetch failed: HTTP " + (resp && resp.status));
        return;
      }
      let blob;
      try { blob = await resp.blob(); }
      catch (_) {
        if (ticket !== inflight) return;
        setError("Image payload not readable");
        return;
      }
      if (ticket !== inflight) return;
      if (currentObjectUrl) {
        try { URL.revokeObjectURL(currentObjectUrl); } catch (_) {}
      }
      currentObjectUrl = URL.createObjectURL(blob);
      img.onload = function () {
        skel.style.display = "none";
        img.style.opacity = "1";
      };
      img.onerror = function () {
        setError("Image data invalid");
      };
      img.src = currentObjectUrl;
    }
    wrap.update = function (nextUrl) { return load(nextUrl); };
    wrap.revoke = function () {
      inflight++;
      if (currentObjectUrl) {
        try { URL.revokeObjectURL(currentObjectUrl); } catch (_) {}
        currentObjectUrl = null;
      }
    };
    if (typeof url === "string" && url) {
      load(url).catch(function (e) {
        // load() handles its own UI state — swallow the promise rejection
        // so the call site doesn't have to .catch() everywhere.
        console.error("spindrel.image:", e);
      });
    }
    return wrap;
  }

  // --- Form: declarative form renderer with sd-* styling + validation.
  // spec: { fields: [{name, label, type, required, options, placeholder,
  //   validate?(value, values) → string|undefined}],
  //   initial?, onSubmit(values, api), submitLabel?, submittingLabel?,
  //   resetOnSubmit? }
  // Returns { values, set(patch), reset(), submit() }.
  function form(elOrSelector, spec) {
    const el = __coerceEl(elOrSelector);
    const fields = (spec && spec.fields) || [];
    if (!Array.isArray(fields)) throw new Error("spindrel.form: spec.fields must be an array");
    const initial = (spec && spec.initial) || {};
    const state = { values: Object.assign({}, initial), submitting: false, errors: {} };

    function renderField(f) {
      const val = state.values[f.name] != null ? state.values[f.name] : "";
      const err = state.errors[f.name];
      const required = f.required ? " required" : "";
      const fid = "__sdf_" + __esc(f.name);
      const label = '<label class="sd-label" for="' + fid + '">' +
        __esc(f.label != null ? f.label : f.name) +
        (f.required ? ' <span class="sd-required">*</span>' : '') + '</label>';
      let input;
      if (f.type === "textarea") {
        input = '<textarea class="sd-textarea" id="' + fid + '" name="' + __esc(f.name) + '"' +
          required + (f.placeholder ? ' placeholder="' + __esc(f.placeholder) + '"' : '') +
          '>' + __esc(val) + '</textarea>';
      } else if (f.type === "select") {
        const opts = (f.options || []).map(function (opt) {
          const o = typeof opt === "string" ? { value: opt, label: opt } : opt;
          const selected = String(val) === String(o.value) ? " selected" : "";
          return '<option value="' + __esc(o.value) + '"' + selected + '>' +
            __esc(o.label != null ? o.label : o.value) + '</option>';
        }).join("");
        input = '<select class="sd-select" id="' + fid + '" name="' + __esc(f.name) + '"' +
          required + '>' + opts + '</select>';
      } else if (f.type === "checkbox") {
        const checked = val ? " checked" : "";
        input = '<input type="checkbox" class="sd-checkbox" id="' + fid +
          '" name="' + __esc(f.name) + '"' + checked + ' />';
      } else {
        input = '<input type="' + __esc(f.type || "text") + '" class="sd-input" id="' + fid +
          '" name="' + __esc(f.name) + '"' + required +
          ' value="' + __esc(val) + '"' +
          (f.placeholder ? ' placeholder="' + __esc(f.placeholder) + '"' : '') + ' />';
      }
      const errHtml = err ? '<div class="sd-error" style="font-size:12px;margin-top:4px">' +
        __esc(err) + '</div>' : '';
      return '<div class="sd-stack-sm" data-field="' + __esc(f.name) + '">' +
        label + input + errHtml + '</div>';
    }

    function render() {
      const submitLabel = (spec && spec.submitLabel) || "Submit";
      el.innerHTML =
        '<form class="sd-stack" novalidate>' +
        fields.map(renderField).join("") +
        '<div class="sd-hstack sd-hstack-between">' +
        '<div class="sd-meta" data-form-status></div>' +
        '<button type="submit" class="sd-btn sd-btn-primary" data-form-submit' +
        (state.submitting ? ' disabled' : '') + '>' +
        __esc(state.submitting ? (spec.submittingLabel || "Working…") : submitLabel) +
        '</button></div></form>';
      const formEl = el.querySelector("form");
      formEl.addEventListener("input", function (e) {
        const t = e.target;
        if (!t || !t.name) return;
        state.values[t.name] = t.type === "checkbox" ? t.checked : t.value;
      });
      formEl.addEventListener("submit", function (e) {
        e.preventDefault();
        handleSubmit();
      });
    }

    async function handleSubmit() {
      if (state.submitting) return;
      state.errors = {};
      for (const f of fields) {
        const v = state.values[f.name];
        if (f.required && (v == null || v === "" || v === false)) {
          state.errors[f.name] = "Required";
        } else if (typeof f.validate === "function") {
          try {
            const r = await f.validate(v, state.values);
            if (typeof r === "string" && r) state.errors[f.name] = r;
          } catch (err) {
            state.errors[f.name] = (err && err.message) || "Invalid";
          }
        }
      }
      if (Object.keys(state.errors).length > 0) { render(); return; }
      if (typeof (spec && spec.onSubmit) !== "function") { render(); return; }
      state.submitting = true;
      render();
      try {
        await spec.onSubmit(Object.assign({}, state.values), { api: api, apiFetch: apiFetch });
        if (spec.resetOnSubmit) state.values = Object.assign({}, initial);
      } catch (err) {
        const status = el.querySelector("[data-form-status]");
        const msg = (err && err.message) || "Submit failed";
        if (status) status.innerHTML = '<span class="sd-error">' + __esc(msg) + '</span>';
        notify("error", msg);
      } finally {
        state.submitting = false;
        render();
      }
    }

    render();
    return {
      get values() { return Object.assign({}, state.values); },
      set: function (patch) { Object.assign(state.values, patch || {}); render(); },
      reset: function () { state.values = Object.assign({}, initial); state.errors = {}; render(); },
      submit: handleSubmit,
    };
  }

  // --- Error boundary: forward uncaught errors to host chrome so the
  // widget card surfaces a banner instead of the widget going silently
  // dead. Host chrome re-renders with a Reload action.
  window.addEventListener("error", function (e) {
    const msg = (e.error && e.error.message) || e.message || "Uncaught error";
    const stack = (e.error && e.error.stack) || null;
    try {
      window.parent.postMessage({
        __spindrel: true, type: "error",
        message: msg, source: e.filename || null, lineno: e.lineno || null,
      }, "*");
    } catch (_) {}
    __sendDebugEvent("error", {
      message: msg, src: e.filename || null,
      line: e.lineno || null, col: e.colno || null, stack: stack,
    });
  });
  window.addEventListener("unhandledrejection", function (e) {
    const reason = e.reason;
    const msg = (reason && reason.message) || String(reason == null ? "Promise rejected" : reason);
    const stack = (reason && reason.stack) || null;
    try {
      window.parent.postMessage({
        __spindrel: true, type: "error",
        message: msg, source: "unhandledrejection", lineno: null,
      }, "*");
    } catch (_) {}
    __sendDebugEvent("rejection", { reason: msg, stack: stack });
  });

  window.spindrel = {
    channelId: channelId,
    sessionId: sessionId,
    botId: botId,
    botName: botName,
    serverUrl: serverUrl,
    dashboardPinId: dashboardPinId,
    widgetPath: widgetPath,
    gridSize: gridSize,
    layout: layout,
    hostSurface: hostSurface,
    presentationFamily: presentationFamily,
    image: image,
    resolvePath: resolvePath,
    api: api,
    apiFetch: apiFetch,
    readWorkspaceFile: readWorkspaceFile,
    writeWorkspaceFile: writeWorkspaceFile,
    listWorkspaceFiles: listWorkspaceFiles,
    loadAsset: loadAsset,
    revokeAsset: revokeAsset,
    loadAttachment: loadAttachment,
    revokeAttachment: revokeAttachment,
    renderMarkdown: renderMarkdown,
    callTool: callTool,
    callHandler: callHandler,
    toolSchema: toolSchema,
    data: {
      load: dataLoad,
      save: dataSave,
      patch: dataPatch,
    },
    state: {
      load: stateLoad,
      save: stateSave,
      patch: statePatch,
    },
    bus: {
      publish: busPublish,
      subscribe: busSubscribe,
    },
    stream: stream,
    onReload: onReload,
    autoReload: autoReload,
    cache: {
      get: cacheGet,
      set: cacheSet,
      clear: cacheClear,
    },
    notify: notify,
    log: log,
    ui: {
      status: uiStatus,
      table: uiTable,
      chart: uiChart,
      icon: uiIcon,
      autogrow: uiAutogrow,
      menu: uiMenu,
      tooltip: uiTooltip,
      confirm: uiConfirm,
    },
    form: form,
    db: {
      query: dbQuery,
      exec: dbExec,
      tx: dbTx,
    },
    onToolResult: onToolResult,
    onConfig: onConfig,
    onTheme: onTheme,
    toolResult: initialToolResult,
    result: initialResult,
    widgetConfig: initialWidgetConfig,
    widgetContext: {
      result: initialResult,
      widgetConfig: initialWidgetConfig,
    },
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
      window.spindrel.result = __deriveResult(obj);
      window.spindrel.widgetConfig = __deriveWidgetConfig(obj);
      window.spindrel.widgetContext = {
        result: window.spindrel.result,
        widgetConfig: window.spindrel.widgetConfig,
      };
      try {
        window.dispatchEvent(new CustomEvent("spindrel:toolresult", { detail: obj }));
      } catch (_) { /* CustomEvent unavailable — ignore */ }
    },
    __setTheme: function (t) {
      window.spindrel.theme = t;
      try {
        window.dispatchEvent(new CustomEvent("spindrel:theme", { detail: t }));
      } catch (_) { /* ignore */ }
    },
    __setHostSurface: function (nextSurface) {
      const normalized = nextSurface === "plain" ? "plain" : "surface";
      window.spindrel.hostSurface = normalized;
      try {
        document.documentElement.setAttribute("data-spindrel-host-surface", normalized);
      } catch (_) { /* ignore */ }
    }
  };

  // Let the host chrome drop its pre-load skeleton. Fires once per iframe
  // boot after window.spindrel has been fully populated and widget code
  // has had its first microtask pass. Paired with onIframeReady() on the
  // React side — see PinnedToolWidget's iframeReady gate.
  function __postReady() {
    try {
      window.parent.postMessage({ __spindrel: true, type: "ready" }, "*");
    } catch (_) { /* detached / cross-origin */ }
  }
  if (document.readyState === "complete" || document.readyState === "interactive") {
    // Push to the end of the microtask queue so any synchronous render
    // kicked off by inline widget code lands before the host drops the
    // skeleton (avoids a one-frame empty-iframe flash between skeleton
    // hide and first widget paint).
    Promise.resolve().then(__postReady);
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      Promise.resolve().then(__postReady);
    });
  }
})();
</script>`;
}

// Widgets that never call the app's API (pure data render off
// `window.spindrel.result`) don't need a bot-scoped bearer. Skipping
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
  /<script>\s*window\.spindrel\s*=\s*window\.spindrel\s*\|\|\s*\{\};\s*window\.spindrel\.toolResult\s*=\s*([\s\S]+?);\s*(?:window\.spindrel\.[\s\S]*?)?<\/script>/;

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

// Minimal frontmatter reader — pulls just the `runtime:` line out of a
// leading HTML-comment YAML block. Mirrors the server-side scanner regex
// but only extracts the one field we need at render time. We intentionally
// do not bring in a full YAML parser: misformed frontmatter degrades to
// `runtime: html` instead of breaking the renderer.
const FRONTMATTER_RE = /^\s*<!--\s*\n?---\s*\n([\s\S]*?)\n---\s*\n?\s*-->/;
const FRONTMATTER_RUNTIME_LINE_RE = /^\s*runtime\s*:\s*(['"]?)(\w+)\1\s*$/m;

function parseFrontmatterRuntime(body: string): "html" | "react" | null {
  const block = FRONTMATTER_RE.exec(body);
  if (!block) return null;
  const line = FRONTMATTER_RUNTIME_LINE_RE.exec(block[1]);
  if (!line) return null;
  const v = line[2].toLowerCase();
  if (v === "react") return "react";
  if (v === "html") return "html";
  return null;
}

function buildReactRuntimePreamble(serverUrl: string | null): string {
  // `serverUrl` is the absolute origin of the agent-server backend. In
  // same-origin prod it's empty/null, so relative `/widget-runtime/...`
  // resolves against the host page. In dev with separate Vite + FastAPI
  // origins, we need the absolute URL so the iframe can fetch the vendored
  // bundles from the API host. CSP `script-src` is widened in `buildCsp`
  // when `allowAppScripts: true` is set.
  const prefix = serverUrl ? serverUrl.replace(/\/$/, "") : "";
  const reactSrc = `${prefix}/widget-runtime/react.production.min.js`;
  const reactDomSrc = `${prefix}/widget-runtime/react-dom.production.min.js`;
  const babelSrc = `${prefix}/widget-runtime/babel.standalone.min.js`;
  // The mount shim is intentionally tiny + dependency-free. It scans for
  // `<script type="text/spindrel-react">` blocks (a custom MIME so
  // babel-standalone's auto-runner doesn't fight us), compiles each one
  // through Babel with the `react` + `typescript` presets (TS types
  // stripped, never checked), and executes inside a closure where
  // `React`, `ReactDOM`, and `spindrel` are in scope. Compile errors
  // render a host-styled error card so a broken JSX block degrades
  // visibly instead of silently producing a blank iframe.
  const shim = `
(function(){
  function showErr(msg){
    var el=document.createElement('pre');
    el.id='__spindrel_react_error';
    el.textContent='[runtime: react] '+msg;
    el.style.cssText='color:var(--sd-danger,#c00);background:var(--sd-bg-surface,#fff);padding:12px;font:12px/1.45 ui-monospace,Menlo,monospace;white-space:pre-wrap;border:1px solid var(--sd-border,#ddd);border-radius:6px;margin:12px;';
    (document.getElementById('__sd_root')||document.body).appendChild(el);
    // Mirror to the SDK debug ring so the authoring bot can call
    // inspect_widget_pin(pin_id) and see the compile error with the same
    // shape as a runtime JS error. Try/caught so a missing log helper
    // never masks the visible error card.
    try {
      if (window.spindrel && window.spindrel.log && window.spindrel.log.error) {
        window.spindrel.log.error('[runtime: react] ' + msg);
      }
    } catch (_) { /* ignore */ }
  }
  // Surface async runtime errors. React 18's createRoot schedules render —
  // an exception inside a component (undefined hook, bad data access, etc.)
  // is captured by React and reported via window.onerror / unhandledrejection
  // rather than our sync try/catch. Without this trap the iframe goes blank
  // with only a "Minified React error #..." in the iframe console.
  window.addEventListener('error',function(ev){
    var msg=(ev&&ev.error&&(ev.error.stack||ev.error.message))||(ev&&ev.message)||'unknown error';
    showErr(String(msg));
  });
  window.addEventListener('unhandledrejection',function(ev){
    var r=ev&&ev.reason;
    var msg=(r&&(r.stack||r.message))||String(r||'unhandled rejection');
    showErr(msg);
  });
  if (typeof Babel==='undefined'||typeof React==='undefined'||typeof ReactDOM==='undefined'){
    showErr('Failed to load React runtime from /widget-runtime/. Verify the agent-server static mount is reachable.');
    return;
  }
  window.spindrel=window.spindrel||{};
  window.spindrel.React=React;
  window.spindrel.ReactDOM=ReactDOM;
  window.spindrel.useApi=function(){return window.spindrel.api;};
  window.spindrel.useTheme=function(){
    var s=React.useState(window.spindrel.theme);
    React.useEffect(function(){
      var h=function(){s[1](window.spindrel.theme);};
      window.addEventListener('spindrel:theme',h);
      return function(){window.removeEventListener('spindrel:theme',h);};
    },[]);
    return s[0];
  };
  function run(node,idx){
    var src=node.textContent||'';
    try {
      var compiled=Babel.transform(src,{presets:['react','typescript'],filename:(node.dataset.spindrelFile||('widget-'+idx+'.tsx'))}).code;
      (new Function('React','ReactDOM','spindrel',compiled))(React,ReactDOM,window.spindrel);
    } catch(e){
      showErr((e&&e.message)||String(e));
    }
  }
  function start(){
    var blocks=document.querySelectorAll('script[type="text/spindrel-react"]');
    for (var i=0;i<blocks.length;i++) run(blocks[i],i);
  }
  if (document.readyState==='loading') {
    document.addEventListener('DOMContentLoaded',start,{once:true});
  } else {
    start();
  }
})();`;
  return [
    `<script src="${reactSrc}"></script>`,
    `<script src="${reactDomSrc}"></script>`,
    `<script src="${babelSrc}"></script>`,
    `<script>${shim}</script>`,
  ].join("\n");
}

function wrapHtml(
  body: string,
  channelId: string | null,
  sessionId: string | null,
  botId: string | null,
  botName: string | null,
  serverUrl: string | null,
  widgetToken: string | null,
  initialToolResultJson: string | null,
  themeCss: string,
  themeJson: string,
  isDark: boolean,
  dashboardPinId: string | null,
  widgetPath: string | null,
  csp: string,
  gridDimensions: { width: number; height: number } | null,
  layout: WidgetLayout,
  hostSurface: HostSurface,
  presentationFamily: PresentationFamily,
  hoverScrollbars: boolean,
  runtime: "html" | "react",
): string {
  const hostKind = dashboardPinId ? "pinned" : "inline";
  const hoverScrollbarAttr = hoverScrollbars ? ' data-hover-scrollbars="1"' : "";
  const reactRuntimePreamble =
    runtime === "react" ? buildReactRuntimePreamble(serverUrl) : "";
  return `<!doctype html>
<html${isDark ? ' class="dark"' : ""} data-sd-host="${hostKind}" data-sd-layout="${layout}" data-sd-host-surface="${hostSurface}" data-spindrel-host-surface="${hostSurface}" data-spindrel-runtime="${runtime}"${hoverScrollbarAttr}>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<style id="__spindrel_theme">${themeCss}</style>
${spindrelBootstrap(channelId, sessionId, botId, botName, serverUrl, widgetToken, initialToolResultJson, themeJson, dashboardPinId, widgetPath, gridDimensions, layout, hostSurface, presentationFamily)}
${reactRuntimePreamble}
</head>
<body data-sd-host="${hostKind}" data-sd-layout="${layout}" data-sd-host-surface="${hostSurface}">
${WIDGET_ICON_SPRITE}
<div id="__sd_root" data-sd-host="${hostKind}" data-sd-layout="${layout}" data-sd-host-surface="${hostSurface}">
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

export function InteractiveHtmlRenderer({
  envelope,
  sessionId,
  channelId,
  fillHeight,
  dashboardPinId,
  gridDimensions,
  onIframeReady,
  hoverScrollbars,
  layout,
  hostSurface = "surface",
  presentationFamily = "card",
  t,
}: Props) {
  const serverUrl = useAuthStore((s) => s.serverUrl || null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const iframeHostRef = useRef<HTMLDivElement | null>(null);
  // Start from the measured grid height when the caller knows it — otherwise
  // fall back to the legacy 200px default for inline chat rendering. Chips are
  // fixed-height; seeding them at 200 then shrinking to ~32 flashes visibly.
  const [height, setHeight] = useState(() => {
    if (gridDimensions?.height && gridDimensions.height > 0) return gridDimensions.height;
    return layout === "chip" ? 32 : 200;
  });
  const themeMode = useThemeStore((s) => s.mode);
  const isDark = themeMode === "dark";

  // Freeze the gridDimensions that flowed into srcDoc at mount so re-renders
  // triggered by parent ResizeObserver ticks don't force a srcDoc rebuild
  // (which would reload the iframe and discard widget state). Widgets that
  // care about live size should read ResizeObserver in-iframe.
  const frozenGridDimensionsRef = useRef(gridDimensions ?? null);
  if (frozenGridDimensionsRef.current === null && gridDimensions) {
    frozenGridDimensionsRef.current = gridDimensions;
  }

  const sourcePath = envelope.source_path || null;
  const sourceChannelId = envelope.source_channel_id || null;
  const sourceIntegrationId = envelope.source_integration_id || null;
  const sourceLibraryRef = envelope.source_library_ref || null;
  const sourceBotId = envelope.source_bot_id || null;
  // Default to "channel" when omitted so pre-catalog envelopes keep working.
  // Library envelopes always carry an explicit source_kind.
  const sourceKind = envelope.source_kind
    ?? (sourceLibraryRef
      ? "library"
      : sourceIntegrationId ? "integration" : "channel");
  const pathMode =
    (sourceKind === "library" && !!sourceLibraryRef)
    || (
      !!sourcePath
      && (
        (sourceKind === "channel" && !!sourceChannelId)
        || sourceKind === "builtin"
        || (sourceKind === "integration" && !!sourceIntegrationId)
      )
    );
  // The `channelId` prop is the authoritative source — set by every render
  // surface that knows which channel the widget lives on (chat view, channel
  // dashboards via `ChannelDashboardMultiCanvas`). We deliberately do NOT
  // fall back to `envelope.source_channel_id` here: that field points at the
  // channel the widget was *emitted from*, which is not always the channel
  // the widget is *being viewed in*, and relying on it previously masked a
  // genuine plumbing gap in `WidgetScope` for channel dashboards.
  const effectiveChannelId = channelId ?? null;

  // For inline widgets we know the body at mount time and can skip minting
  // when the widget won't use it. PathMode widgets fetch their body later,
  // so we can't pre-check — mint unconditionally and let the banner surface
  // if the bot turns out to have no key. Inline is the common case (every
  // tool-emitted widget template), so the weather-widget false-positive
  // banner is solved.
  const inlineBody = typeof envelope.body === "string" ? envelope.body : null;
  const inlineNeedsAuth = !pathMode && bodyNeedsAuth(inlineBody);
  const needsAuth = pathMode || inlineNeedsAuth;
  // Two auth scopes: bot-scoped (mint via /widget-auth/mint) or user-scoped
  // (inject the viewer's bearer directly; endpoints accept both via
  // `verify_auth_or_user`). Pins with `source_bot_id` opted into the bot's
  // ceiling; pins without it fall back to the viewer's own credentials so
  // user-pinned suites work without a bot indirection.
  const shouldMint = !!sourceBotId && needsAuth;
  const userScopedToken = useMemo(
    () => (!sourceBotId && needsAuth ? getAuthToken() || null : null),
    [sourceBotId, needsAuth],
  );

  const widgetThemeQuery = useQuery({
    queryKey: ["resolved-widget-theme", effectiveChannelId ?? null],
    queryFn: () => apiFetch<ResolvedWidgetThemeResponse>(
      `/api/v1/widgets/themes/resolve${effectiveChannelId ? `?channel_id=${encodeURIComponent(effectiveChannelId)}` : ""}`,
    ),
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });

  const resolvedWidgetTokens = useMemo<ThemeTokens>(
    () => resolveWidgetThemeTokens(widgetThemeQuery.data?.theme ?? null, t, isDark),
    [widgetThemeQuery.data?.theme, t, isDark],
  );

  const themeCss = useMemo(
    () => buildWidgetThemeCss({
      tokens: resolvedWidgetTokens,
      isDark,
      theme: widgetThemeQuery.data?.theme,
    }),
    [resolvedWidgetTokens, isDark, widgetThemeQuery.data?.theme],
  );
  const themeJson = useMemo(
    () => JSON.stringify(buildWidgetThemeObject({
      tokens: resolvedWidgetTokens,
      isDark,
      theme: widgetThemeQuery.data?.theme,
    })),
    [resolvedWidgetTokens, isDark, widgetThemeQuery.data?.theme],
  );

  // Mint a bot-scoped bearer token so widget JS authenticates as the
  // emitting bot — not as the viewing user. We re-mint before expiry and
  // push the new value into the iframe via `window.spindrel.__setToken`
  // so the srcDoc doesn't reload (which would reset the widget's state).
  const tokenQuery = useQuery({
    // Keyed on both bot and pin — the pin_id is baked into the minted JWT
    // so endpoints can grant channel-scoped access implicitly based on the
    // pin's dashboard. Different pins mean different tokens.
    queryKey: ["widget-auth-mint", sourceBotId, dashboardPinId],
    queryFn: () =>
      apiFetch<WidgetTokenResponse>("/api/v1/widget-auth/mint", {
        method: "POST",
        body: JSON.stringify({
          source_bot_id: sourceBotId,
          ...(dashboardPinId ? { pin_id: dashboardPinId } : {}),
        }),
      }),
    enabled: shouldMint,
    staleTime: WIDGET_AUTH_STALE_MS,
    gcTime: WIDGET_AUTH_GC_MS,
    // 15-minute server TTL; re-mint at 12 min so the widget never sees a
    // 401 mid-call. Short TTL = short screenshot exposure.
    refetchInterval: 12 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 1,
  });
  // Effective bearer: minted bot token when available, else the viewer's
  // token for user-scoped pins. Widget calls await this via `tokenReady`
  // so initial-paint fetches don't race.
  const widgetToken = tokenQuery.data?.token ?? userScopedToken ?? null;
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

  // Source-specific content endpoint. All four return ``{path, content}``
  // so the downstream body-building code stays uniform.
  const contentEndpoint = useMemo(() => {
    if (!pathMode) return null;
    if (sourceKind === "library" && sourceLibraryRef) {
      const botParam = sourceBotId
        ? `&bot_id=${encodeURIComponent(sourceBotId)}`
        : "";
      return `/api/v1/widgets/html-widget-content/library?ref=${encodeURIComponent(sourceLibraryRef)}${botParam}`;
    }
    if (!sourcePath) return null;
    if (sourceKind === "builtin") {
      return `/api/v1/widgets/html-widget-content/builtin?path=${encodeURIComponent(sourcePath)}`;
    }
    if (sourceKind === "integration" && sourceIntegrationId) {
      return `/api/v1/widgets/html-widget-content/integrations/${encodeURIComponent(sourceIntegrationId)}?path=${encodeURIComponent(sourcePath)}`;
    }
    if (sourceChannelId) {
      return `/api/v1/channels/${sourceChannelId}/workspace/files/content?path=${encodeURIComponent(sourcePath)}`;
    }
    return null;
  }, [pathMode, sourcePath, sourceKind, sourceIntegrationId, sourceChannelId, sourceLibraryRef, sourceBotId]);

  // Sources that ship with the deploy can't change at runtime — fetch once
  // and stop. Author-editable sources (workspace files, bot/workspace library
  // bundles) poll at a relaxed cadence; the `widget_reload` event bus already
  // covers "I just edited the HTML, show me now" without needing tight
  // polling. 3s across every pinned widget was saturating the network tab
  // and stalling the dashboard.
  const isMutableSource =
    (sourceKind === "library"
      && !!sourceLibraryRef
      && !sourceLibraryRef.startsWith("core/"))
    || (sourceKind === "channel" && !!sourceChannelId && !!sourcePath);
  const fileQuery = useQuery({
    queryKey: [
      "interactive-html-widget-content",
      sourceKind,
      sourceChannelId,
      sourceIntegrationId,
      sourceLibraryRef,
      sourceBotId,
      sourcePath,
    ],
    queryFn: () =>
      apiFetch<{ path: string; content: string }>(contentEndpoint!),
    enabled: pathMode && !!contentEndpoint,
    staleTime: isMutableSource ? MUTABLE_WIDGET_SOURCE_STALE_MS : Infinity,
    gcTime: isMutableSource ? MUTABLE_WIDGET_SOURCE_GC_MS : IMMUTABLE_WIDGET_SOURCE_GC_MS,
    // Immutable sources: no polling. Mutable sources: 30s. 404 → stop
    // regardless so a deleted file doesn't keep firing.
    refetchInterval: (query) => {
      const err = query.state.error;
      if (err instanceof ApiError && err.status === 404) return false;
      if (!isMutableSource) return false;
      return 30_000;
    },
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return failureCount < 3;
    },
    refetchOnMount: false,
    refetchOnWindowFocus: isMutableSource,
    refetchOnReconnect: false,
  });

  // Fire a sticky toast when a path-mode widget's source file is missing.
  // Deduped at module scope so glitched/offscreen widgets don't stack
  // duplicate toasts on every remount. Pinned widgets get a "Remove pin"
  // action; chat envelopes auto-dismiss after ~6s since there's nothing
  // to delete (the envelope lives in message history).
  useEffect(() => {
    const err = fileQuery.error;
    const is404 = err instanceof ApiError && err.status === 404;
    if (!is404 || !sourcePath) return;
    const key = dashboardPinId ?? `${sourceChannelId ?? "-"}|${sourcePath}`;
    if (MISSING_WIDGET_TOAST_KEYS.has(key)) return;
    MISSING_WIDGET_TOAST_KEYS.add(key);
    if (dashboardPinId) {
      toast({
        kind: "error",
        message: `Widget HTML missing: ${sourcePath}`,
        durationMs: 0,
        action: {
          label: "Remove pin",
          onClick: () => {
            useDashboardPinsStore
              .getState()
              .unpinWidget(dashboardPinId)
              .catch(() => {
                toast({
                  kind: "error",
                  message: `Failed to remove pin for ${sourcePath}`,
                });
              });
          },
        },
      });
    } else {
      toast({
        kind: "error",
        message: `Widget HTML missing: ${sourcePath}`,
        durationMs: 6000,
      });
    }
  }, [fileQuery.error, sourcePath, sourceChannelId, dashboardPinId]);

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

  // Host-side receiver for `spindrel.notify` / `spindrel.log` / uncaught
  // iframe errors. Iframes postMessage up to the parent window; we filter
  // by `event.source === iframeRef.current.contentWindow` so widgets in
  // other iframes don't bleed their toasts into this card.
  // Phase A SDK — extended in Phase B to feed the Dev Panel widget log subtab.
  type Toast = { id: number; level: "info" | "success" | "warn" | "error"; message: string };
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [widgetError, setWidgetError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const iframe = iframeRef.current;
      if (!iframe) return;
      if (event.source !== iframe.contentWindow) return;
      const data = event.data as
        | {
            __spindrel?: true;
            type?: string;
            level?: string;
            message?: string;
            entry?: { ts?: number; level?: string; message?: string };
          }
        | null
        | undefined;
      if (!data || data.__spindrel !== true) return;
      if (data.type === "notify") {
        const id = Date.now() + Math.random();
        const lvl = (data.level === "warn" || data.level === "error" || data.level === "success")
          ? data.level
          : "info";
        const msg = typeof data.message === "string" ? data.message : "";
        setToasts((prev) => [...prev.slice(-4), { id, level: lvl as Toast["level"], message: msg }]);
        window.setTimeout(() => {
          setToasts((prev) => prev.filter((t) => t.id !== id));
        }, 4000);
      } else if (data.type === "error") {
        setWidgetError(typeof data.message === "string" ? data.message : "Widget crashed");
      } else if (data.type === "ready") {
        onIframeReadyRef.current?.();
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  // Ref-indirect onIframeReady so the message handler (one-time useEffect)
  // doesn't stale-close over an older identity if the parent recreates the
  // callback on rerender.
  const onIframeReadyRef = useRef(onIframeReady);
  useEffect(() => {
    onIframeReadyRef.current = onIframeReady;
  }, [onIframeReady]);
  const toastTone = (level: Toast["level"]) => {
    if (level === "error") return { fg: t.danger, bg: t.dangerSubtle };
    if (level === "warn") return { fg: t.warning, bg: t.warningSubtle };
    if (level === "success") return { fg: t.success, bg: t.successSubtle };
    return { fg: t.textMuted, bg: t.overlayLight };
  };

  const rawBody = useMemo(() => {
    if (pathMode) return fileQuery.data?.content ?? "";
    return typeof envelope.body === "string" ? envelope.body : "";
  }, [pathMode, fileQuery.data?.content, envelope.body]);

  // Resolve the effective runtime: envelope-declared value wins; falls back
  // to YAML frontmatter parsed off the body (so library / path-mode widgets
  // can self-declare `runtime: react` without the bot needing to pass the
  // emit-time param). Default `html`.
  const effectiveRuntime = useMemo<"html" | "react">(() => {
    const declared = envelope.runtime;
    if (declared === "react") return "react";
    if (declared === "html") return "html";
    const fromBody = parseFrontmatterRuntime(rawBody);
    return fromBody === "react" ? "react" : "html";
  }, [envelope.runtime, rawBody]);

  // CSP is derived per-envelope — widgets declare their third-party origin
  // needs via ``extra_csp`` (Maps, Mapbox, etc.). ``buildCsp`` merges onto
  // the locked-down baseline and drops anything that isn't a concrete
  // ``https://`` origin. `runtime: react` widgets additionally need the
  // app origin allowed under `script-src` so vendored React + Babel can
  // be loaded across the cross-origin dev split.
  const cspString = useMemo(
    () =>
      buildCsp(envelope.extra_csp, serverUrl, {
        allowAppScripts: effectiveRuntime === "react",
      }),
    [envelope.extra_csp, serverUrl, effectiveRuntime],
  );

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
        // Chips (32px compact variant) are content-measured: no 24px buffer
        // (would let the 80px min win every time) and no 80px floor (would
        // oversize the iframe and overflow the h-8 host wrapper, pushing the
        // chip HTML out the top under `items-center`).
        const isChipLayout = layout === "chip";
        const h = Math.min(root.scrollHeight + (isChipLayout ? 0 : 24), MAX_IFRAME_HEIGHT);
        setHeight(Math.max(isChipLayout ? 0 : 80, h));
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
        // Flip the html attribute that the preamble's scrollbar CSS keys on.
        // Toggling here (rather than in srcDoc) keeps iframe identity stable
        // when the dashboard setting changes at runtime.
        if (hoverScrollbars) {
          doc.documentElement.setAttribute("data-hover-scrollbars", "1");
        } else {
          doc.documentElement.removeAttribute("data-hover-scrollbars");
        }
        const root = doc.getElementById("__sd_root") ?? doc.body;
        observer = new ResizeObserver(updateHeight);
        observer.observe(root);
      } catch {
        // ignored
      }
    };
    iframe.addEventListener("load", onLoad);
    onLoad();
    return () => {
      iframe.removeEventListener("load", onLoad);
      if (observer) observer.disconnect();
    };
  }, [bodyWithoutPreamble, layout]);

  // Keep the hover-scrollbars attribute in sync when the dashboard toggle
  // flips after the iframe has already loaded. Tolerates contentDocument
  // being null (same-origin guard mid-navigation).
  useEffect(() => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc?.documentElement) return;
    if (hoverScrollbars) {
      doc.documentElement.setAttribute("data-hover-scrollbars", "1");
    } else {
      doc.documentElement.removeAttribute("data-hover-scrollbars");
    }
  }, [hoverScrollbars]);

  useEffect(() => {
    const doc = iframeRef.current?.contentDocument;
    if (doc?.documentElement) {
      doc.documentElement.setAttribute("data-spindrel-host-surface", hostSurface);
    }
    if (doc?.body) {
      doc.body.setAttribute("data-sd-host-surface", hostSurface);
    }
    const root = doc?.getElementById("__sd_root");
    if (root) {
      root.setAttribute("data-sd-host-surface", hostSurface);
    }
    try {
      const w = iframeRef.current?.contentWindow as
        | (Window & { spindrel?: { __setHostSurface?: (surface: HostSurface) => void } })
        | null
        | undefined;
      w?.spindrel?.__setHostSurface?.(hostSurface);
    } catch {
      // Mid-navigation or pooled iframe swap; the next successful sync/load
      // will reapply the host-surface hint.
    }
  }, [hostSurface]);

  // 404 is handled by a sticky toast (see fileQuery effect above) so a
  // glitched/offscreen widget still surfaces its own "I'm broken" signal.
  // Transient errors (5xx / network) keep the in-card banner since those
  // are worth seeing next to the widget you're looking at.
  const fileErrorIs404 =
    fileQuery.error instanceof ApiError && fileQuery.error.status === 404;
  const errorOverlay =
    pathMode && fileQuery.error && !fileErrorIs404 ? (
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
  const isAdmin = useIsAdmin();
  const authErrorInfo = (() => {
    if (!shouldMint || !tokenQuery.error) return null;
    const err = tokenQuery.error;
    let reason: string | null = null;
    let detailBotId: string | null = null;
    let detailBotName: string | null = null;
    let message: string;
    if (err instanceof ApiError) {
      if (typeof err.body === "string") {
        try {
          const parsed = JSON.parse(err.body);
          const d = parsed?.detail;
          if (d && typeof d === "object") {
            if (typeof d.reason === "string") reason = d.reason;
            if (typeof d.bot_id === "string") detailBotId = d.bot_id;
            if (typeof d.bot_name === "string") detailBotName = d.bot_name;
          }
        } catch {
          // fall through to .detail getter
        }
      }
      message = err.detail ?? err.message;
    } else if (err instanceof Error) {
      message = err.message;
    } else {
      message = "unknown error";
    }
    return { reason, message, bot_id: detailBotId, bot_name: detailBotName };
  })();
  const authError = authErrorInfo?.message ?? null;
  const keepAliveKey = dashboardPinId ? `dashboard-pin:${dashboardPinId}` : null;
  const iframeTitle = envelope.display_label || "Interactive HTML widget";
  const srcDoc = useMemo(
    () => `${wrapHtml(
      bodyWithoutPreamble,
      effectiveChannelId,
      sessionId ?? null,
      sourceBotId,
      botName,
      serverUrl,
      widgetToken,
      frozenInitialToolResultRef.current,
      themeCss,
      themeJson,
      isDark,
      dashboardPinId ?? null,
      sourcePath,
      cspString,
      frozenGridDimensionsRef.current,
      layout ?? "grid",
      hostSurface,
      presentationFamily,
      !!hoverScrollbars,
      effectiveRuntime,
    )}\n<!-- reload:${reloadNonce} -->`,
    [
      bodyWithoutPreamble,
      effectiveChannelId,
      sessionId,
      sourceBotId,
      botName,
      widgetToken,
      themeCss,
      themeJson,
      isDark,
      dashboardPinId,
      sourcePath,
      cspString,
      layout,
      hostSurface,
      presentationFamily,
      hoverScrollbars,
      reloadNonce,
      effectiveRuntime,
    ],
  );

  useLayoutEffect(() => {
    const host = iframeHostRef.current;
    if (!host) return;
    let iframe: HTMLIFrameElement;
    let reusedPooledIframe = false;
    if (keepAliveKey) {
      const pooled = touchPinnedWidgetIframeEntry(keepAliveKey);
      if (pooled) {
        iframe = pooled.iframe;
        reusedPooledIframe = true;
      } else {
        iframe = document.createElement("iframe");
        PINNED_WIDGET_IFRAME_POOL.set(keepAliveKey, {
          iframe,
          srcDoc: "",
          parkedAt: null,
          cleanupTimer: null,
        });
        trimPinnedWidgetIframePool();
      }
    } else {
      iframe = document.createElement("iframe");
    }
    iframeRef.current = iframe;
    host.replaceChildren(iframe);
    // Reattached pooled iframes often keep their live document and JS state
    // across dashboard drag/remount cycles, so they won't necessarily post a
    // second `spindrel:ready` message after adoption. Treat a reused iframe as
    // ready once it's back under this host so PinnedToolWidget doesn't stay
    // behind its preload skeleton until a full page refresh.
    if (reusedPooledIframe) {
      onIframeReadyRef.current?.();
      window.requestAnimationFrame(() => {
        if (iframeRef.current === iframe) onIframeReadyRef.current?.();
      });
    }
    try {
      const readyState = iframe.contentDocument?.readyState;
      if (readyState === "interactive" || readyState === "complete") {
        onIframeReadyRef.current?.();
      }
    } catch {
      // Mid-navigation or inaccessible document — ready/load effects handle it.
    }
    return () => {
      if (keepAliveKey) {
        const parkingLot = getPinnedWidgetIframeParkingLot();
        if (parkingLot) {
          parkingLot.appendChild(iframe);
          schedulePinnedWidgetIframeEviction(keepAliveKey);
          trimPinnedWidgetIframePool();
        } else {
          evictPinnedWidgetIframe(keepAliveKey);
        }
      } else if (iframe.parentElement === host) {
        host.removeChild(iframe);
      }
      if (iframeRef.current === iframe) iframeRef.current = null;
    };
  }, [keepAliveKey]);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    iframe.setAttribute(
      "sandbox",
      "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox",
    );
    iframe.setAttribute("title", iframeTitle);
    iframe.style.width = "100%";
    iframe.style.height = fillHeight ? "100%" : `${height}px`;
    iframe.style.flex = fillHeight ? "1 1 auto" : "";
    iframe.style.border = "none";
    iframe.style.display = "block";
    const pooled = keepAliveKey ? PINNED_WIDGET_IFRAME_POOL.get(keepAliveKey) : null;
    const lastSrcDoc = pooled?.srcDoc ?? iframe.getAttribute("data-spindrel-srcdoc") ?? "";
    if (lastSrcDoc !== srcDoc) {
      iframe.srcdoc = srcDoc;
      if (pooled) pooled.srcDoc = srcDoc;
      else iframe.setAttribute("data-spindrel-srcdoc", srcDoc);
    }
  }, [fillHeight, height, iframeTitle, keepAliveKey, srcDoc]);

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
      {authError && authErrorInfo && (() => {
        const isAccessDenied = authErrorInfo.reason === "bot_access_denied";
        // Access-denied is softer than a bot_missing_api_key: it's a
        // permissions gap, not a misconfig. Tone it down to amber + give the
        // right CTA for the viewer role.
        const tone = isAccessDenied
          ? { fg: t.accent, bg: t.accentSubtle }
          : { fg: t.danger, bg: t.dangerSubtle };
        const grantHref = authErrorInfo.bot_id
          ? `/admin/bots/${encodeURIComponent(authErrorInfo.bot_id)}#grants`
          : null;
        const displayMsg = isAccessDenied
          ? (isAdmin && authErrorInfo.bot_name
              ? `Viewers can't use '${authErrorInfo.bot_name}' yet — grant access to make this widget work for them.`
              : authErrorInfo.bot_name
                ? `Ask an admin for access to '${authErrorInfo.bot_name}' so this widget can load.`
                : authError)
          : authError;
        return (
          <div
            style={{
              padding: "6px 10px",
              fontSize: 11,
              color: tone.fg,
              background: tone.bg,
              borderBottom: `1px solid ${t.surfaceBorder}`,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ flex: 1 }}>{displayMsg}</span>
            {isAccessDenied && isAdmin && grantHref && (
              <Link
                to={grantHref}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  padding: "2px 8px",
                  fontSize: 11,
                  color: t.text,
                  background: t.surfaceOverlay,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 4,
                  textDecoration: "none",
                  fontFamily: "inherit",
                }}
              >
                Grant access
              </Link>
            )}
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
        );
      })()}
      {/* Subtle auth-scope chip — bottom-left so it doesn't collide with
          the "updated Xm ago" indicator (top-right). Tells the viewer
          whose credentials this widget's API calls use. Suppressed in
          chip layout (header strip) — the 32px-tall compact form has no
          room for hover chrome and the overlay would block clicks on the
          underlying widget content. */}
      {layout !== "chip" && (botName || userScopedToken) && (
        <div
          className="widget-hover-chip"
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
            zIndex: 1,
          }}
          title={
            botName
              ? `Widget runs as @${botName}. API calls use this bot's permissions, not yours.`
              : "Widget runs as you. API calls use your own permissions."
          }
        >
          <BotIcon size={10} />
          <span>{botName ? `@${botName}` : "as you"}</span>
        </div>
      )}
      {layout !== "chip" && pathMode && lastUpdated && (
        <div
          aria-hidden
          className="widget-hover-chip"
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
      {widgetError && (
        <div
          role="alert"
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
          <span style={{ flex: 1 }}>
            Widget error: {widgetError}
          </span>
          <button
            type="button"
            onClick={() => {
              setWidgetError(null);
              setReloadNonce((n) => n + 1);
            }}
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
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            <RefreshCw size={10} />
            Reload
          </button>
        </div>
      )}
      {toasts.length > 0 && (
        <div
          aria-live="polite"
          style={{
            position: "absolute",
            top: 6,
            left: 8,
            right: 40,
            display: "flex",
            flexDirection: "column",
            gap: 4,
            zIndex: 2,
            pointerEvents: "none",
          }}
        >
          {toasts.map((toast) => {
            const tone = toastTone(toast.level);
            return (
              <div
                key={toast.id}
                style={{
                  padding: "4px 8px",
                  fontSize: 11,
                  color: tone.fg,
                  background: tone.bg,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 4,
                  pointerEvents: "auto",
                  cursor: "pointer",
                }}
                onClick={() =>
                  setToasts((prev) => prev.filter((x) => x.id !== toast.id))
                }
              >
                {toast.message}
              </div>
            );
          })}
        </div>
      )}
      <div
        ref={iframeHostRef}
        style={{
          width: "100%",
          height: fillHeight ? "100%" : height,
          flex: fillHeight ? 1 : undefined,
        }}
      />
    </div>
  );
}
