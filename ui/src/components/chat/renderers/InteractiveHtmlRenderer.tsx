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
  t: ThemeTokens;
}

const CSP =
  "default-src 'self'; " +
  "script-src 'unsafe-inline' 'self'; " +
  "style-src 'unsafe-inline' 'self'; " +
  "img-src data: blob: 'self'; " +
  "font-src data: 'self'; " +
  "connect-src 'self'";

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
): string {
  return `<script>
(function () {
  const channelId = ${jsonForScript(channelId)};
  const botId = ${jsonForScript(botId)};
  const botName = ${jsonForScript(botName)};
  // Token mutated in-place by the host on re-mint — read fresh per call.
  const state = { token: ${jsonForScript(widgetToken)} };
  const initialToolResult = ${initialToolResultJson ?? "null"};
  const initialTheme = ${themeJson};
  // Like fetch() but bearer-attached. Returns the raw Response so callers
  // can choose how to consume the body (.blob() for images, .json(), .text(),
  // streaming, whatever). Use this for anything non-JSON (image/video blobs,
  // file downloads). For JSON endpoints, api() below is the convenience
  // wrapper that throws on !ok and parses the body for you.
  async function apiFetch(path, options) {
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
    const url = "/api/v1/channels/" + encodeURIComponent(cid) +
      "/workspace/files/content?path=" + encodeURIComponent(path);
    const data = await api(url);
    return data.content;
  }
  async function writeWorkspaceFile(path, content) {
    const cid = requireChannel();
    const url = "/api/v1/channels/" + encodeURIComponent(cid) +
      "/workspace/files/content?path=" + encodeURIComponent(path);
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
  window.spindrel = {
    channelId: channelId,
    botId: botId,
    botName: botName,
    api: api,
    apiFetch: apiFetch,
    readWorkspaceFile: readWorkspaceFile,
    writeWorkspaceFile: writeWorkspaceFile,
    listWorkspaceFiles: listWorkspaceFiles,
    toolResult: initialToolResult,
    theme: initialTheme,
    __setToken: function (t) { state.token = t || null; },
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

// Matches the server-side preamble written in
// `_build_html_widget_body`. We snapshot-extract the JSON so refreshes can
// postMessage-equivalent push fresh data into a live iframe without
// rebuilding srcDoc.
const TOOL_RESULT_PREAMBLE_RE =
  /window\.spindrel\.toolResult\s*=\s*([\s\S]+?);<\/script>/;

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
): string {
  return `<!doctype html>
<html${isDark ? ' class="dark"' : ""}>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${CSP}" />
<style id="__spindrel_theme">${themeCss}</style>
${spindrelBootstrap(channelId, botId, botName, widgetToken, initialToolResultJson, themeJson)}
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

export function InteractiveHtmlRenderer({ envelope, channelId, t }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(200);
  const themeMode = useThemeStore((s) => s.mode);
  const isDark = themeMode === "dark";

  const sourcePath = envelope.source_path || null;
  const sourceChannelId = envelope.source_channel_id || null;
  const sourceBotId = envelope.source_bot_id || null;
  const pathMode = !!sourcePath && !!sourceChannelId;
  const effectiveChannelId = channelId ?? sourceChannelId;

  const themeCss = useMemo(
    () => buildWidgetThemeCss({ tokens: t, isDark }),
    [t, isDark],
  );
  const themeJson = useMemo(
    () => JSON.stringify(buildWidgetThemeObject({ tokens: t, isDark })),
    [t, isDark],
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
    enabled: !!sourceBotId,
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
    if (!sourceBotId || !tokenQuery.error) return null;
    const err = tokenQuery.error;
    if (err instanceof ApiError && err.detail) return err.detail;
    if (err instanceof Error) return err.message;
    return "unknown error";
  })();

  return (
    <div
      style={{
        borderRadius: 8,
        border: `1px solid ${t.surfaceBorder}`,
        overflow: "hidden",
        background: t.surfaceRaised,
        position: "relative",
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
        )}
        sandbox="allow-scripts allow-same-origin"
        title={envelope.display_label || "Interactive HTML widget"}
        style={{
          width: "100%",
          height,
          border: "none",
          display: "block",
        }}
      />
    </div>
  );
}
