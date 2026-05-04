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
 *   application/vnd.spindrel.native-app+json → renderNativeWidget (nativeApps registry)
 *
 * Truncated envelopes (body=null, truncated=true, record_id set) render a
 * "Show full output" button. On click, the full body is fetched from the
 * session-scoped tool-call result endpoint and the matching renderer is
 * mounted with the fetched body. The lazy-fetch state is local — collapse
 * + re-expand re-fetches.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ToolCallSummary, ToolResultEnvelope } from "../../types/api";
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
import { renderNativeWidget } from "./renderers/nativeApps/registry";
import { PlanResultRenderer } from "./renderers/PlanResultRenderer";
import {
  DefaultSearchResultsRenderer,
  TerminalSearchResultsRenderer,
  isSearchResultsPayload,
} from "./renderers/SearchResultsRenderer";
import { renderCommandResultView } from "./renderers/machineControl/CommandResultRenderer";
import { renderMachineAccessRequiredView } from "./renderers/machineControl/MachineAccessRequiredRenderer";
import { renderMachineTargetStatusView } from "./renderers/machineControl/MachineTargetStatusRenderer";
import type { WidgetActionDispatcher } from "./renderers/ComponentRenderer";
import { WidgetActionContext } from "./renderers/ComponentRenderer";
import type {
  RichRendererChromeMode,
  RichRendererVariant,
} from "./renderers/genericRendererChrome";
import { getChatModeConfig } from "./chatModes";
import {
  createResultViewRegistry,
  envelopeViewKey,
  type ResultViewRendererProps,
} from "./resultViewRegistry";
import type { PresentationFamily } from "@/src/lib/widgetHostPolicy";

type CompactionRunPayload = {
  origin?: string;
  status?: string;
  title?: string | null;
  detail?: string | null;
  summary_text?: string | null;
  summary_len?: number | null;
  trigger_reason?: string | null;
  result_kind?: string | null;
  error?: string | null;
};

const PLAN_CONTENT_TYPE = "application/vnd.spindrel.plan+json";

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
  presentationFamily?: PresentationFamily;
  rendererVariant?: RichRendererVariant;
  chromeMode?: RichRendererChromeMode;
  summary?: ToolCallSummary | null;
  t: ThemeTokens;
}

function resolveRendererTokens(base: ThemeTokens, rendererVariant: RichRendererVariant): ThemeTokens {
  if (rendererVariant !== "terminal-chat") return base;
  return {
    ...base,
    surfaceRaised: base.surface,
    surfaceOverlay: base.surface,
    surfaceBorder: base.overlayBorder,
    inputBg: base.surface,
    inputBorder: base.overlayBorder,
    accentSubtle: base.overlayLight,
    purpleSubtle: base.overlayLight,
    botMessageBg: "transparent",
  };
}

export interface RichResultViewProps extends ResultViewRendererProps {
  envelope: ToolResultEnvelope;
  summary?: ToolCallSummary | null;
  body: string;
  data: unknown;
  sessionId?: string;
  channelId?: string;
  fillHeight?: boolean;
  dashboardPinId?: string;
  gridDimensions?: { width: number; height: number };
  onIframeReady?: () => void;
  hoverScrollbars?: boolean;
  layout?: WidgetLayout;
  hostSurface?: HostSurface;
  presentationFamily?: PresentationFamily;
  rendererVariant: RichRendererVariant;
  chromeMode: RichRendererChromeMode;
  showJson: boolean;
  t: ThemeTokens;
}

function renderMarkdownView({ body, t, mode }: RichResultViewProps) {
  return (
    <div style={{ padding: "4px 0" }}>
      <MarkdownContent text={body} t={t} chatMode={mode === "terminal" ? "terminal" : "default"} />
    </div>
  );
}

function renderJsonView({ body, rendererVariant, chromeMode, t }: RichResultViewProps) {
  return <JsonTreeRenderer body={body} rendererVariant={rendererVariant} chromeMode={chromeMode} t={t} />;
}

function renderTextView({ body, rendererVariant, chromeMode, t }: RichResultViewProps) {
  return <TextRenderer body={body} rendererVariant={rendererVariant} chromeMode={chromeMode} t={t} />;
}

function renderSandboxedHtmlView({ body, chromeMode, t }: RichResultViewProps) {
  return <SandboxedHtmlRenderer body={body} chromeMode={chromeMode} t={t} />;
}

function renderInteractiveHtmlView({
  envelope,
  sessionId,
  channelId,
  fillHeight,
  dashboardPinId,
  gridDimensions,
  onIframeReady,
  hoverScrollbars,
  layout,
  hostSurface,
  presentationFamily,
  t,
}: RichResultViewProps) {
  return (
    <InteractiveHtmlRenderer
      envelope={envelope}
      sessionId={sessionId}
      channelId={channelId}
      fillHeight={fillHeight}
      dashboardPinId={dashboardPinId}
      gridDimensions={gridDimensions}
      onIframeReady={onIframeReady}
      hoverScrollbars={hoverScrollbars}
      layout={layout}
      hostSurface={hostSurface}
      presentationFamily={presentationFamily}
      t={t}
    />
  );
}

function renderDiffView({ body, rendererVariant, summary, t }: RichResultViewProps) {
  return <DiffRenderer body={body} rendererVariant={rendererVariant} summary={summary} t={t} />;
}

function renderFileListingView({ body, rendererVariant, chromeMode, t }: RichResultViewProps) {
  return <FileListingRenderer body={body} rendererVariant={rendererVariant} chromeMode={chromeMode} t={t} />;
}

function renderComponentsView({
  body,
  showJson,
  rendererVariant,
  chromeMode,
  layout,
  hostSurface,
  presentationFamily,
  gridDimensions,
  t,
}: RichResultViewProps) {
  if (showJson) {
    return <JsonTreeRenderer body={body} rendererVariant={rendererVariant} chromeMode={chromeMode} t={t} />;
  }
  return (
    <ComponentRenderer
      body={body}
      layout={layout}
      hostSurface={hostSurface}
      presentationFamily={presentationFamily}
      gridDimensions={gridDimensions}
      t={t}
    />
  );
}

function renderNativeAppView({
  envelope,
  sessionId,
  dashboardPinId,
  channelId,
  gridDimensions,
  layout,
  hostSurface,
  rendererVariant,
  t,
}: RichResultViewProps) {
  return (
    <>
      {renderNativeWidget({
        envelope,
        sessionId,
        dashboardPinId,
        channelId,
        gridDimensions,
        layout,
        hostSurface: hostSurface ?? (rendererVariant === "terminal-chat" ? "plain" : "surface"),
        t,
      })}
    </>
  );
}

function renderPlanView({ envelope, body, mode, sessionId }: RichResultViewProps) {
  return <PlanResultRenderer envelope={envelope} body={body} chatMode={mode === "terminal" ? "terminal" : "default"} sessionId={sessionId} />;
}

function renderDefaultSearchResultsView({ data, t }: RichResultViewProps) {
  if (isSearchResultsPayload(data)) {
    return <DefaultSearchResultsRenderer payload={data} t={t} />;
  }
  return null;
}

function renderTerminalSearchResultsView({ data, t }: RichResultViewProps) {
  if (isSearchResultsPayload(data)) {
    return <TerminalSearchResultsRenderer payload={data} t={t} />;
  }
  return null;
}

function parseCompactionRunPayload(data: unknown, envelope: ToolResultEnvelope): CompactionRunPayload {
  const payload = (data && typeof data === "object") ? (data as CompactionRunPayload) : {};
  return {
    origin: payload.origin ?? "manual",
    status: payload.status ?? "completed",
    title: payload.title ?? null,
    detail: payload.detail ?? envelope.plain_body ?? null,
    summary_text: payload.summary_text ?? null,
    summary_len: payload.summary_len ?? null,
    trigger_reason: payload.trigger_reason ?? null,
    result_kind: payload.result_kind ?? payload.status ?? null,
    error: payload.error ?? null,
  };
}

function resolveCompactionStatusCopy(payload: CompactionRunPayload): {
  label: string;
  accent: "info" | "success" | "warning" | "danger";
} {
  if (payload.status === "queued") return { label: "Queued", accent: "warning" };
  if (payload.status === "running") return { label: "Compacting...", accent: "info" };
  if (payload.status === "failed") return { label: "Failed", accent: "danger" };
  if (payload.result_kind === "noop") return { label: "Nothing to compact", accent: "warning" };
  return { label: "Compacted", accent: "success" };
}

function CompactionRunRenderer({
  envelope,
  data,
  mode,
  t,
}: RichResultViewProps) {
  const payload = parseCompactionRunPayload(data, envelope);
  const status = resolveCompactionStatusCopy(payload);
  const [expanded, setExpanded] = useState(false);
  const isTerminal = mode === "terminal";
  const summaryText = payload.summary_text?.trim() ?? "";
  const accentColor = status.accent === "success"
    ? t.success
    : status.accent === "warning"
      ? t.warning
      : status.accent === "danger"
        ? t.danger
        : t.accent;
  const metaBits = [
    payload.origin === "auto" ? "auto" : "manual",
    payload.title ? payload.title : null,
    typeof payload.summary_len === "number" ? `${payload.summary_len.toLocaleString()} chars` : null,
    payload.trigger_reason ? payload.trigger_reason : null,
  ].filter(Boolean);

  useEffect(() => {
    if (payload.status === "completed" || payload.result_kind === "noop") {
      setExpanded(false);
    }
  }, [payload.result_kind, payload.status]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: expanded ? 8 : 4,
        color: t.textMuted,
        fontFamily: isTerminal ? "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace" : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            padding: isTerminal ? "0" : "1px 6px",
            borderRadius: 999,
            border: isTerminal ? "none" : `1px solid ${t.surfaceBorder}`,
            background: isTerminal ? "transparent" : t.overlayLight,
            color: t.textMuted,
            fontSize: isTerminal ? 11 : 11,
            fontWeight: 600,
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 6,
              height: 6,
              borderRadius: 999,
              background: accentColor,
              opacity: status.accent === "success" ? 0.7 : 0.9,
            }}
          />
          {status.label}
        </span>
        {payload.detail && status.accent !== "success" && (
          <span
            style={{
              color: t.textMuted,
              fontSize: isTerminal ? 12 : 13,
              lineHeight: 1.5,
            }}
          >
            {payload.detail}
          </span>
        )}
      </div>

      {metaBits.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            color: t.textDim,
            fontSize: 11,
            lineHeight: 1.45,
          }}
        >
          {metaBits.map((bit, index) => (
            <span key={bit}>{index === 0 ? bit : `· ${bit}`}</span>
          ))}
        </div>
      )}

      {(summaryText || payload.error) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <button
            type="button"
            onClick={() => setExpanded((current) => !current)}
            style={{
              alignSelf: "flex-start",
              padding: 0,
              border: "none",
              background: "transparent",
              color: t.textDim,
              cursor: "pointer",
              fontSize: 11,
              fontWeight: 500,
            }}
          >
            {expanded ? "Hide summary" : "Show summary"}
          </button>
          {expanded && (
            <div
              style={{
                paddingLeft: 12,
                borderLeft: `2px solid ${t.surfaceBorder}`,
              }}
            >
              {summaryText ? (
                <MarkdownContent text={summaryText} t={t} chatMode={mode === "terminal" ? "terminal" : "default"} />
              ) : payload.error ? (
                <TextRenderer body={payload.error} rendererVariant={isTerminal ? "terminal-chat" : "default-chat"} chromeMode="embedded" t={t} />
              ) : null}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function renderCompactionRunView(props: RichResultViewProps) {
  return <CompactionRunRenderer {...props} />;
}

function SafeFallbackResult({
  envelope,
  body,
  data,
  viewKey,
  mode,
  rendererVariant,
  chromeMode,
  t,
}: RichResultViewProps) {
  const label = envelope.display_label || envelope.plain_body || viewKey;
  const hasStructuredData = data !== undefined && data !== null;
  const canShowBody = envelope.content_type !== "application/vnd.spindrel.html+interactive";
  const fallbackBody = hasStructuredData
    ? JSON.stringify(data, null, 2)
    : canShowBody
      ? body
      : "";
  const isTerminal = mode === "terminal";
  return (
    <details
      style={{
        fontFamily: isTerminal ? "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace" : undefined,
        fontSize: isTerminal ? 12 : 12,
        lineHeight: 1.45,
        color: t.textMuted,
      }}
    >
      <summary style={{ cursor: "pointer", color: isTerminal ? t.textMuted : t.accent }}>
        {label}
      </summary>
      {fallbackBody ? (
        hasStructuredData ? (
          <JsonTreeRenderer body={fallbackBody} rendererVariant={rendererVariant} chromeMode={chromeMode} t={t} />
        ) : (
          <TextRenderer body={fallbackBody} rendererVariant={rendererVariant} chromeMode={chromeMode} t={t} />
        )
      ) : (
        <div style={{ paddingTop: 6 }}>No {mode} renderer is registered for {viewKey}.</div>
      )}
    </details>
  );
}

function parseStructuredData(envelope: ToolResultEnvelope, body: string): unknown {
  if (envelope.data !== undefined) return envelope.data;
  if (
    envelope.content_type === "application/json"
    || envelope.content_type === "application/vnd.spindrel.file-listing+json"
    || envelope.content_type === "application/vnd.spindrel.components+json"
    || envelope.content_type === "application/vnd.spindrel.native-app+json"
    || envelope.content_type === PLAN_CONTENT_TYPE
  ) {
    try {
      return JSON.parse(body);
    } catch {
      return undefined;
    }
  }
  return undefined;
}

const resultViews = createResultViewRegistry<RichResultViewProps>();
resultViews.register("core.markdown", { any: renderMarkdownView });
resultViews.register("core.json", { any: renderJsonView });
resultViews.register("core.text", { any: renderTextView });
resultViews.register("core.html", { default: renderSandboxedHtmlView });
resultViews.register("core.interactive_html", { default: renderInteractiveHtmlView });
resultViews.register("core.diff", { any: renderDiffView });
resultViews.register("core.file_listing", { any: renderFileListingView });
resultViews.register("core.components", { default: renderComponentsView, terminal: renderJsonView });
resultViews.register("core.native_app", { any: renderNativeAppView });
resultViews.register("core.plan", { default: renderPlanView, terminal: renderPlanView });
resultViews.register("core.search_results", {
  default: renderDefaultSearchResultsView,
  terminal: renderTerminalSearchResultsView,
});
resultViews.register("core.machine_target_status", { any: renderMachineTargetStatusView });
resultViews.register("core.command_result", { any: renderCommandResultView });
resultViews.register("core.machine_access_required", { any: renderMachineAccessRequiredView });
resultViews.register("compaction_run", { any: renderCompactionRunView });

function unwrapFetchedToolResultBody(envelope: ToolResultEnvelope, fetched: string): string | Record<string, unknown> {
  if (envelope.content_type !== PLAN_CONTENT_TYPE) return fetched;
  try {
    const parsed = JSON.parse(fetched) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return fetched;
    const record = parsed as Record<string, unknown>;
    const embeddedEnvelope = record._envelope;
    if (embeddedEnvelope && typeof embeddedEnvelope === "object" && !Array.isArray(embeddedEnvelope)) {
      const embeddedBody = (embeddedEnvelope as Record<string, unknown>).body;
      if (embeddedBody != null) {
        return typeof embeddedBody === "string" || (typeof embeddedBody === "object" && !Array.isArray(embeddedBody))
          ? embeddedBody as string | Record<string, unknown>
          : JSON.stringify(embeddedBody);
      }
    }
    const plan = record.plan;
    if (plan && typeof plan === "object" && !Array.isArray(plan)) {
      return plan as Record<string, unknown>;
    }
  } catch {
    return fetched;
  }
  return fetched;
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
  presentationFamily,
  rendererVariant = "default-chat",
  chromeMode = "standalone",
  summary,
  t,
}: Props) {
  const [fetched, setFetched] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const showJson = false;
  const rendererTokens = useMemo(
    () => resolveRendererTokens(t, rendererVariant),
    [rendererVariant, t],
  );

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

  const fetchFullOutput = useCallback(async () => {
    if (!sessionId || !envelope.record_id) return;
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
  }, [envelope.record_id, sessionId]);

  const shouldAutoFetchPlan = Boolean(
    envelope.content_type === PLAN_CONTENT_TYPE
    && envelope.truncated
    && envelope.body == null
    && sessionId
    && envelope.record_id
    && fetched == null
    && !fetching
    && !fetchError,
  );

  useEffect(() => {
    if (!shouldAutoFetchPlan) return;
    void fetchFullOutput();
  }, [fetchFullOutput, shouldAutoFetchPlan]);

  // body may be a pre-parsed object from JSONB metadata — normalize to string
  const rawBody = fetched == null ? envelope.body : unwrapFetchedToolResultBody(envelope, fetched);
  const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : JSON.stringify(rawBody);
  const isTerminalRenderer = rendererVariant === "terminal-chat";
  const renderMode = getChatModeConfig(isTerminalRenderer ? "terminal" : "default").resultMode;

  // Truncated and not yet fetched — show the lazy-load affordance.
  if (envelope.truncated && body == null) {
    const canFetch = sessionId && envelope.record_id;
    const isEmbedded = chromeMode === "embedded";
    const isTerminal = rendererVariant === "terminal-chat";
    return (
      <div
        style={{
          padding: isEmbedded ? (isTerminal ? "0" : "0") : "6px 10px",
          borderRadius: isEmbedded ? 0 : 8,
          border: isEmbedded ? "none" : `1px dashed ${rendererTokens.surfaceBorder}`,
          background: isEmbedded ? "transparent" : rendererTokens.overlayLight,
          fontSize: 11,
          color: rendererTokens.textMuted,
          display: "flex",
          flexDirection: isTerminal ? "column" : "row",
          alignItems: isTerminal ? "flex-start" : "center",
          gap: isTerminal ? 4 : 8,
          fontFamily: isTerminal ? "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace" : undefined,
        }}
      >
        <span style={{ display: "block", maxWidth: "100%" }}>
          {envelope.plain_body || "Output exceeds inline limit."}
        </span>
        {canFetch && (
          <button
            type="button"
            onClick={fetchFullOutput}
            disabled={fetching}
            style={{
              padding: isTerminal ? 0 : "2px 8px",
              borderRadius: isTerminal ? 0 : 4,
              border: isTerminal ? "none" : `1px solid ${rendererTokens.accentBorder}`,
              background: isTerminal ? "transparent" : isEmbedded ? "transparent" : rendererTokens.accentSubtle,
              color: rendererTokens.accent,
              fontSize: 11,
              display: "block",
              alignSelf: isTerminal ? "flex-start" : undefined,
              whiteSpace: "nowrap",
              cursor: fetching ? "wait" : "pointer",
              transition: "background-color 0.15s",
            }}
            onMouseEnter={(e) => {
              if (!fetching && !isTerminal) e.currentTarget.style.backgroundColor = rendererTokens.accentMuted;
            }}
            onMouseLeave={(e) => {
              if (!isTerminal) e.currentTarget.style.backgroundColor = rendererTokens.accentSubtle;
            }}
          >
            {fetching ? "Loading\u2026" : "Show full output"}
          </button>
        )}
        {fetchError && (
          <span style={{ color: rendererTokens.danger }}>· {fetchError}</span>
        )}
      </div>
    );
  }

  if (body == null) return null;

  const viewKey = envelopeViewKey(envelope);
  const data = parseStructuredData(envelope, body);
  const viewProps: RichResultViewProps = {
    viewKey,
    mode: renderMode,
    envelope,
    summary,
    body,
    data,
    sessionId,
    channelId,
    fillHeight,
    dashboardPinId,
    gridDimensions,
    onIframeReady,
    hoverScrollbars,
    layout,
    hostSurface,
    presentationFamily,
    rendererVariant,
    chromeMode,
    showJson,
    t: rendererTokens,
  };
  const renderer = resultViews.resolve(viewKey, renderMode);
  const rendered = renderer?.(viewProps);
  const content = rendered ?? <SafeFallbackResult {...viewProps} />;

  const wrapped = actionCtx ? (
    <WidgetActionContext.Provider value={actionCtx}>
      {content}
    </WidgetActionContext.Provider>
  ) : content;

  return <>{wrapped}</>;
}
