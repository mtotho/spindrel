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
import { InteractiveHtmlRenderer } from "./renderers/InteractiveHtmlRenderer";
import { DiffRenderer } from "./renderers/DiffRenderer";
import { FileListingRenderer } from "./renderers/FileListingRenderer";
import { ComponentRenderer } from "./renderers/ComponentRenderer";
import { WidgetActionContext } from "./renderers/ComponentRenderer";

interface Props {
  envelope: ToolResultEnvelope;
  /** Session id, for lazy-fetching truncated bodies via
   *  GET /api/v1/sessions/{sid}/tool-calls/{record_id}/result */
  sessionId?: string;
  /** Channel + bot context for interactive widget actions */
  channelId?: string;
  botId?: string;
  t: ThemeTokens;
}

export function RichToolResult({ envelope, sessionId, channelId, botId, t }: Props) {
  const [fetched, setFetched] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [showJson, setShowJson] = useState(false);

  // Widget action context — provide whenever we have at least a channelId
  // (botId may be missing on some persisted messages but actions can still work)
  const dispatchAction = useWidgetAction(channelId, botId ?? "default");
  const actionCtx = useMemo(
    () => (channelId ? { dispatchAction } : null),
    [channelId, dispatchAction],
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
        content = <InteractiveHtmlRenderer envelope={envelope} t={t} />;
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
