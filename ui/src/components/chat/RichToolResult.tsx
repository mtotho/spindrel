/**
 * RichToolResult — mimetype dispatcher for rendering tool result envelopes
 * inside chat bubbles.
 *
 * Driven by the `ToolResultEnvelope` carried on `Message.metadata.tool_results`
 * (persisted) and on the live `TurnState.toolCalls[i].envelope` (during
 * streaming). Picks one of the renderers off `content_type`:
 *
 *   text/plain                              → TextRenderer
 *   text/markdown                           → MarkdownContent (existing)
 *   application/json                        → JsonTreeRenderer
 *   text/html                               → SandboxedHtmlRenderer  (strict: no JS, no network)
 *   application/vnd.spindrel.html+interactive → InteractiveHtmlRenderer (JS + same-origin fetch)
 *   application/vnd.spindrel.diff+text      → DiffRenderer
 *   application/vnd.spindrel.file-listing+json → FileListingRenderer
 *   application/vnd.spindrel.components+json → ComponentRenderer
 *   application/vnd.spindrel.native-app+json → NativeAppRenderer
 *
 * Truncated envelopes (body=null, truncated=true, record_id set) render a
 * "Show full output" button. On click, the full body is fetched from the
 * session-scoped tool-call result endpoint and the matching renderer is
 * mounted with the fetched body. The lazy-fetch state is local — collapse
 * + re-expand re-fetches.
 */
import { useMemo, useState } from "react";
import type { ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { apiFetch } from "../../api/client";
import { useWidgetAction } from "../../api/hooks/useWidgetAction";
import { MarkdownContent } from "./MarkdownContent";
import { TextRenderer } from "./renderers/TextRenderer";
import { JsonTreeRenderer } from "./renderers/JsonTreeRenderer";
import { SandboxedHtmlRenderer } from "./renderers/SandboxedHtmlRenderer";
import {
  InteractiveHtmlRenderer,
  type HostSurface,
  type WidgetLayout,
} from "./renderers/InteractiveHtmlRenderer";
import { DiffRenderer } from "./renderers/DiffRenderer";
import { FileListingRenderer } from "./renderers/FileListingRenderer";
import { ComponentRenderer } from "./renderers/ComponentRenderer";
import { NativeAppRenderer } from "./renderers/NativeAppRenderer";
import type { WidgetActionDispatcher } from "./renderers/ComponentRenderer";
import { WidgetActionContext } from "./renderers/ComponentRenderer";

interface Props {
  envelope: ToolResultEnvelope;
  /** Session id, for lazy-fetching truncated bodies via
   *  GET /api/v1/sessions/{sid}/tool-calls/{record_id}/result */
  sessionId?: string;
  /** Channel + bot context for interactive widget actions. When a `dispatcher`
   *  is explicitly passed, channelId/botId are ignored for dispatch construction
   *  (the caller already built the right one — e.g. pin-scoped from PinnedToolWidget). */
  channelId?: string;
  botId?: string;
  /** Pre-built dispatcher. Surfaces that need a non-channel-scoped dispatcher
   *  (pinned widgets, dev panel with NOOP) pass this instead of channelId+botId. */
  dispatcher?: WidgetActionDispatcher;
  /** When true, interactive HTML widgets fill their container height instead
   *  of measuring their inner content. Dashboard grid tiles opt in so a
   *  user-resized tile actually renders the widget at the tile's size. */
  fillHeight?: boolean;
  /** When the rendered widget lives on a dashboard pin, pass the pin id so
   *  interactive HTML widgets can dispatch ``widget_config`` patches that
   *  persist against the pin (star-to-save, toggle state, etc.). Undefined
   *  for inline chat widgets — config changes stay local-only. */
  dashboardPinId?: string;
  /** Pre-measured tile dimensions, forwarded onto the interactive-HTML
   *  iframe so its initial height matches the final tile size. Lets the
   *  enclosing PinnedToolWidget hold a pre-load skeleton at the real
   *  dimensions without the 200px → final-size pop. */
  gridDimensions?: { width: number; height: number };
  /** Fires once the interactive-HTML iframe has booted and its preamble
   *  has posted a ``ready`` handshake. PinnedToolWidget uses this to drop
   *  its pre-load skeleton in lockstep with the iframe's first paint. */
  onIframeReady?: () => void;
  /** Forwarded to the interactive-HTML iframe so its document-level
   *  scrollbar follows the dashboard's "Scrollbars on hover" toggle. */
  hoverScrollbars?: boolean;
  /** Host-zone classification forwarded to interactive HTML widgets as
   *  ``window.spindrel.layout``. Callers that know the zone (chip row, dock
   *  rail, left rail, grid canvas) pass it; inline chat omits it and the
   *  renderer falls through to ``"grid"``. */
  layout?: WidgetLayout;
  /** Host wrapper shell mode for pinned surfaces. Interactive HTML widgets
   *  receive this as ``window.spindrel.hostSurface`` and a document-level
   *  attribute so widget CSS can decide whether to draw its own inner card
   *  or rely on the host's surfaced shell. */
  hostSurface?: HostSurface;
  t: ThemeTokens;
}

export function RichToolResult({
  envelope,
  sessionId,
  channelId,
  botId,
  dispatcher,
  fillHeight,
  dashboardPinId,
  gridDimensions,
  onIframeReady,
  hoverScrollbars,
  layout,
  hostSurface,
  t,
}: Props) {
  const [fetched, setFetched] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [showJson, setShowJson] = useState(false);

  // Widget action context — prefer the explicit dispatcher prop; otherwise
  // build a channel-scoped one from channelId/botId (chat path).
  const internalDispatchAction = useWidgetAction(channelId, botId ?? "default");
  const actionCtx = useMemo(
    () => {
      if (dispatcher) return dispatcher;
      if (channelId) return { dispatchAction: internalDispatchAction };
      return null;
    },
    [dispatcher, channelId, internalDispatchAction],
  );

  // body may be a pre-parsed object from JSONB metadata — normalize to string
  const rawBody = fetched ?? envelope.body;
  const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : JSON.stringify(rawBody);

  // Truncated and not yet fetched — show the lazy-load affordance.
  if (envelope.truncated && body == null) {
    const canFetch = sessionId && envelope.record_id;
    return (
      <div
        style={{
          padding: "6px 10px",
          borderRadius: 8,
          border: `1px dashed ${t.surfaceBorder}`,
          background: t.overlayLight,
          fontSize: 11,
          color: t.textMuted,
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span>{envelope.plain_body || "Output exceeds inline limit."}</span>
        {canFetch && (
          <button
            type="button"
            onClick={async () => {
              setFetching(true);
              setFetchError(null);
              try {
                const data = await apiFetch<{ body: string }>(
                  `/api/v1/sessions/${sessionId}/tool-calls/${envelope.record_id}/result`,
                );
                setFetched(data.body ?? "");
              } catch (e) {
                setFetchError(e instanceof Error ? e.message : "Fetch failed");
              } finally {
                setFetching(false);
              }
            }}
            disabled={fetching}
            style={{
              padding: "2px 8px",
              borderRadius: 4,
              border: `1px solid ${t.accentBorder}`,
              background: t.accentSubtle,
              color: t.accent,
              fontSize: 11,
              cursor: fetching ? "wait" : "pointer",
              transition: "background-color 0.15s",
            }}
            onMouseEnter={(e) => { if (!fetching) e.currentTarget.style.backgroundColor = t.accentMuted; }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = t.accentSubtle; }}
          >
            {fetching ? "Loading\u2026" : "Show full output"}
          </button>
        )}
        {fetchError && (
          <span style={{ color: t.danger }}>· {fetchError}</span>
        )}
      </div>
    );
  }

  if (body == null) return null;

  // Components content type supports a JSON toggle for debugging
  const isComponents = envelope.content_type === "application/vnd.spindrel.components+json";

  let content: React.ReactNode;
  if (isComponents && showJson) {
    // Force JSON view of the component body
    content = <JsonTreeRenderer body={body} t={t} />;
  } else {
    switch (envelope.content_type) {
      case "text/markdown":
        content = (
          <div style={{ padding: "4px 0" }}>
            <MarkdownContent text={body} t={t} />
          </div>
        );
        break;
      case "application/json":
        content = <JsonTreeRenderer body={body} t={t} />;
        break;
      case "text/html":
        content = <SandboxedHtmlRenderer body={body} t={t} />;
        break;
      case "application/vnd.spindrel.html+interactive":
        content = (
          <InteractiveHtmlRenderer
            envelope={envelope}
            channelId={channelId}
            fillHeight={fillHeight}
            dashboardPinId={dashboardPinId}
            gridDimensions={gridDimensions}
            onIframeReady={onIframeReady}
            hoverScrollbars={hoverScrollbars}
            layout={layout}
            hostSurface={hostSurface}
            t={t}
          />
        );
        break;
      case "application/vnd.spindrel.diff+text":
        content = <DiffRenderer body={body} t={t} />;
        break;
      case "application/vnd.spindrel.file-listing+json":
        content = <FileListingRenderer body={body} t={t} />;
        break;
      case "application/vnd.spindrel.components+json":
        content = <ComponentRenderer body={body} t={t} />;
        break;
      case "application/vnd.spindrel.native-app+json":
        content = (
          <NativeAppRenderer
            envelope={envelope}
            dashboardPinId={dashboardPinId}
            channelId={channelId}
            t={t}
          />
        );
        break;
      case "text/plain":
      default:
        content = <TextRenderer body={body} t={t} />;
        break;
    }
  }

  const wrapped = actionCtx ? (
    <WidgetActionContext.Provider value={actionCtx}>
      {content}
    </WidgetActionContext.Provider>
  ) : content;

  // For components content type, add a subtle JSON toggle
  if (isComponents) {
    return (
      <div>
        {wrapped}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 2 }}>
          <button
            type="button"
            onClick={() => setShowJson(!showJson)}
            style={{
              background: "none", border: "none", cursor: "pointer",
              fontSize: 10, color: t.textDim, opacity: 0.6,
              padding: "2px 4px",
              transition: "opacity 0.15s",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.opacity = "1"; }}
            onMouseLeave={(e) => { e.currentTarget.style.opacity = "0.6"; }}
          >
            {showJson ? "widget" : "json"}
          </button>
        </div>
      </div>
    );
  }

  return <>{wrapped}</>;
}
