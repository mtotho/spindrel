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
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../../api/client";
import type { ToolResultEnvelope } from "../../../types/api";
import type { ThemeTokens } from "../../../theme/tokens";

interface Props {
  envelope: ToolResultEnvelope;
  t: ThemeTokens;
}

const CSP =
  "default-src 'self'; " +
  "script-src 'unsafe-inline' 'self'; " +
  "style-src 'unsafe-inline' 'self'; " +
  "img-src data: blob: 'self'; " +
  "font-src data: 'self'; " +
  "connect-src 'self'";

function wrapHtml(body: string): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${CSP}" />
<style>
  html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13px; color: #333; background: #ffffff; }
  body { padding: 8px 12px; }
  * { max-width: 100%; box-sizing: border-box; }
  img, video { max-width: 100%; height: auto; }
  table { border-collapse: collapse; }
  td, th { padding: 4px 8px; border: 1px solid #ddd; }
</style>
</head>
<body>
${body}
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

export function InteractiveHtmlRenderer({ envelope, t }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(200);

  const sourcePath = envelope.source_path || null;
  const sourceChannelId = envelope.source_channel_id || null;
  const pathMode = !!sourcePath && !!sourceChannelId;

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

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const handler = () => {
      try {
        const doc = iframe.contentDocument;
        if (doc?.body) {
          const h = Math.min(doc.body.scrollHeight + 24, 800);
          setHeight(Math.max(80, h));
        }
      } catch {
        // contentDocument may be cross-origin-blocked in some edge cases
      }
    };
    iframe.addEventListener("load", handler);
    return () => iframe.removeEventListener("load", handler);
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
          // tick is read for its side effect on formatRelative via Date.now
          title={`Refreshed ${formatRelative(lastUpdated)} (polling every 3s). tick=${tick}`}
        >
          {formatRelative(lastUpdated)}
        </div>
      )}
      <iframe
        ref={iframeRef}
        srcDoc={wrapHtml(body)}
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
