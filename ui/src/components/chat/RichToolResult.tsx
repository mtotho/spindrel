/**
 * RichToolResult — mimetype dispatcher for rendering tool result envelopes
 * inside chat bubbles.
 *
 * Driven by the `ToolResultEnvelope` carried on `Message.metadata.tool_results`
 * (persisted) and on the live `TurnState.toolCalls[i].envelope` (during
 * streaming). Picks one of six renderers off `content_type`:
 *
 *   text/plain                              → TextRenderer
 *   text/markdown                           → MarkdownContent (existing)
 *   application/json                        → JsonTreeRenderer
 *   text/html                               → SandboxedHtmlRenderer
 *   application/vnd.spindrel.diff+text      → DiffRenderer
 *   application/vnd.spindrel.file-listing+json → FileListingRenderer
 *
 * Truncated envelopes (body=null, truncated=true, record_id set) render a
 * "Show full output" button. On click, the full body is fetched from the
 * session-scoped tool-call result endpoint and the matching renderer is
 * mounted with the fetched body. The lazy-fetch state is local — collapse
 * + re-expand re-fetches.
 */
import { useState } from "react";
import type { ToolResultEnvelope } from "../../types/api";
import type { ThemeTokens } from "../../theme/tokens";
import { apiFetch } from "../../api/client";
import { MarkdownContent } from "./MarkdownContent";
import { TextRenderer } from "./renderers/TextRenderer";
import { JsonTreeRenderer } from "./renderers/JsonTreeRenderer";
import { SandboxedHtmlRenderer } from "./renderers/SandboxedHtmlRenderer";
import { DiffRenderer } from "./renderers/DiffRenderer";
import { FileListingRenderer } from "./renderers/FileListingRenderer";
import { ComponentRenderer } from "./renderers/ComponentRenderer";

interface Props {
  envelope: ToolResultEnvelope;
  /** Session id, for lazy-fetching truncated bodies via
   *  GET /api/v1/sessions/{sid}/tool-calls/{record_id}/result */
  sessionId?: string;
  t: ThemeTokens;
}

export function RichToolResult({ envelope, sessionId, t }: Props) {
  const [fetched, setFetched] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const body = fetched ?? envelope.body;

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
          display: "flex",
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

  switch (envelope.content_type) {
    case "text/markdown":
      return (
        <div style={{ padding: "4px 0" }}>
          <MarkdownContent text={body} t={t} />
        </div>
      );
    case "application/json":
      return <JsonTreeRenderer body={body} t={t} />;
    case "text/html":
      return <SandboxedHtmlRenderer body={body} t={t} />;
    case "application/vnd.spindrel.diff+text":
      return <DiffRenderer body={body} t={t} />;
    case "application/vnd.spindrel.file-listing+json":
      return <FileListingRenderer body={body} t={t} />;
    case "application/vnd.spindrel.components+json":
      return <ComponentRenderer body={body} t={t} />;
    case "text/plain":
    default:
      return <TextRenderer body={body} t={t} />;
  }
}
