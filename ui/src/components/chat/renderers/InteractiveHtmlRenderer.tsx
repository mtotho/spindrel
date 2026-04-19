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
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot as BotIcon } from "lucide-react";
import { apiFetch } from "../../../api/client";
import type { ToolResultEnvelope } from "../../../types/api";
import type { ThemeTokens } from "../../../theme/tokens";

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
 */
function spindrelBootstrap(
  channelId: string | null,
  botId: string | null,
  botName: string | null,
  widgetToken: string | null,
): string {
  return `<script>
(function () {
  const channelId = ${jsonForScript(channelId)};
  const botId = ${jsonForScript(botId)};
  const botName = ${jsonForScript(botName)};
  // Token mutated in-place by the host on re-mint — read fresh per call.
  const state = { token: ${jsonForScript(widgetToken)} };
  async function api(path, options) {
    const opts = options || {};
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      state.token ? { "Authorization": "Bearer " + state.token } : {},
      opts.headers || {}
    );
    const resp = await fetch(path, Object.assign({}, opts, { headers }));
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
    readWorkspaceFile: readWorkspaceFile,
    writeWorkspaceFile: writeWorkspaceFile,
    listWorkspaceFiles: listWorkspaceFiles,
    __setToken: function (t) { state.token = t || null; }
  };
})();
</script>`;
}

function wrapHtml(
  body: string,
  channelId: string | null,
  botId: string | null,
  botName: string | null,
  widgetToken: string | null,
): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${CSP}" />
<style>
  html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13px; color: #333; background: #ffffff; }
  body { padding: 8px 12px; overflow-y: auto; }
  * { max-width: 100%; box-sizing: border-box; }
  img, video { max-width: 100%; height: auto; }
  table { border-collapse: collapse; }
  td, th { padding: 4px 8px; border: 1px solid #ddd; }
  /* Match the host app's thin scrollbar — iframe is a separate document
     so global.css doesn't reach in. Bot CSS can override. */
  * { scrollbar-width: thin; scrollbar-color: rgba(0,0,0,0.2) transparent; }
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.2); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.35); }
  ::-webkit-scrollbar-corner { background: transparent; }
  /* Wrapper div is measured by the host for iframe auto-sizing. Keep
     it as a block so its scrollHeight reflects intrinsic content height
     even when bot CSS sets body{min-height:100vh} (which would otherwise
     pin body height to the iframe's current size and feedback-loop
     against the ResizeObserver). */
  #__sd_root { display: block; }
</style>
${spindrelBootstrap(channelId, botId, botName, widgetToken)}
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

  const sourcePath = envelope.source_path || null;
  const sourceChannelId = envelope.source_channel_id || null;
  const sourceBotId = envelope.source_bot_id || null;
  const pathMode = !!sourcePath && !!sourceChannelId;
  const effectiveChannelId = channelId ?? sourceChannelId;

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

  const body = useMemo(() => {
    if (pathMode) return fileQuery.data?.content ?? "";
    return envelope.body ?? "";
  }, [pathMode, fileQuery.data?.content, envelope.body]);

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
  }, [body]);

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
  // Common cause: bot has no API key configured. Actionable hint beats a
  // silent iframe showing 401s in devtools.
  const authError = sourceBotId && tokenQuery.error
    ? tokenQuery.error instanceof Error
      ? tokenQuery.error.message
      : "unknown error"
    : null;

  return (
    <div
      style={{
        borderRadius: 8,
        border: `1px solid ${t.surfaceBorder}`,
        overflow: "hidden",
        background: "#ffffff",
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
            borderBottom: `1px solid ${t.surfaceBorder}`,
          }}
        >
          Widget auth failed: {authError}. API calls from this widget will
          be unauthenticated.
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
          body,
          effectiveChannelId,
          sourceBotId,
          botName,
          widgetToken,
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
