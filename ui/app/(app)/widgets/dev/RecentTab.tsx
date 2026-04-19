/**
 * RecentTab — browse recent ToolCall rows and hand them off to the Templates
 * editor or pin them directly to the dashboard.
 *
 * Two-pane layout mirrors ToolsSandbox. Left: filter bar + scrollable list.
 * Right: selected call detail with arguments, raw result, rendered preview,
 * and import / pin actions.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertCircle,
  Check,
  ExternalLink,
  Loader2,
  Pin,
  RefreshCw,
  Wand2,
  X,
} from "lucide-react";
import {
  useToolCall,
  useToolCalls,
  type ToolCallItem,
} from "@/src/api/hooks/useToolCalls";
import { useBots } from "@/src/api/hooks/useBots";
import { useTools } from "@/src/api/hooks/useTools";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { ToolSelector, shortToolName } from "@/src/components/shared/ToolSelector";
import { genericRenderWidget } from "@/src/api/hooks/useWidgetPackages";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import { resolveToolEnvelope } from "@/src/components/chat/renderers/resolveEnvelope";
import { JsonTreeRenderer } from "@/src/components/chat/renderers/JsonTreeRenderer";
import { useThemeTokens } from "@/src/theme/tokens";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useWidgetImportStore } from "@/src/stores/widgetImport";
import { formatRelativeTime } from "@/src/utils/format";
import type { ToolResultEnvelope } from "@/src/types/api";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

const SINCE_PRESETS: { label: string; hours: number | null }[] = [
  { label: "Last 1h", hours: 1 },
  { label: "Last 24h", hours: 24 },
  { label: "Last 7d", hours: 24 * 7 },
  { label: "All time", hours: null },
];

/** Drop MCP server prefix: "homeassistant-HassTurnOn" → "HassTurnOn". */
function cleanToolName(name: string): string {
  const idx = name.indexOf("-");
  return idx >= 0 ? name.slice(idx + 1) : name;
}

function parseResult(raw: string | null): unknown {
  if (raw == null) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

export function RecentTab() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const setImport = useWidgetImportStore((s) => s.set);
  const pinWidget = useDashboardPinsStore((s) => s.pinWidget);

  const [toolFilter, setToolFilter] = useState<string>("");
  const [botFilter, setBotFilter] = useState<string>("");
  const [errorOnly, setErrorOnly] = useState(false);
  const [sinceHours, setSinceHours] = useState<number | null>(24);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const sinceIso = useMemo(() => {
    if (sinceHours === null) return undefined;
    return new Date(Date.now() - sinceHours * 3600_000).toISOString();
  }, [sinceHours]);

  const { data: calls, isLoading, refetch } = useToolCalls({
    tool_name: toolFilter || undefined,
    bot_id: botFilter || undefined,
    error_only: errorOnly,
    since: sinceIso,
    limit: 100,
  });

  const { data: tools } = useTools();
  const { data: bots } = useBots();

  // Auto-select the first row when the list refreshes.
  useEffect(() => {
    if (!selectedId && calls && calls.length > 0) {
      setSelectedId(calls[0].id);
    }
  }, [calls, selectedId]);

  // ToolSelector wants ToolItem[]; a freshly-appearing tool in the call log
  // that isn't in the live index just won't surface in the picker, which is
  // fine — users can still narrow via free-text match on the server side.
  const toolItems = tools ?? [];

  return (
    <div className="flex-1 flex flex-col md:flex-row min-h-0 overflow-hidden">
      {/* Left column */}
      <div className="flex flex-col w-full md:w-[340px] md:shrink-0 md:border-r md:border-surface-border md:min-h-0 max-h-[45vh] md:max-h-none">
        {/* Filters */}
        <div className="flex flex-col gap-2 px-3 py-2 bg-surface-raised">
          <div className="flex gap-1">
            {SINCE_PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => setSinceHours(p.hours)}
                className={
                  "flex-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors " +
                  (sinceHours === p.hours
                    ? "border-accent/60 bg-accent/10 text-accent"
                    : "border-surface-border text-text-muted hover:bg-surface-overlay")
                }
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="flex items-stretch gap-1">
            <div className="flex-1 min-w-0">
              <ToolSelector
                value={toolFilter || null}
                tools={toolItems}
                onChange={(v) => setToolFilter(v)}
                resolveValue={shortToolName}
                placeholder="All tools"
                size="sm"
              />
            </div>
            {toolFilter && (
              <button
                type="button"
                onClick={() => setToolFilter("")}
                className="shrink-0 rounded-md border border-surface-border px-1.5 text-text-dim hover:bg-surface-overlay"
                title="Clear tool filter"
                aria-label="Clear tool filter"
              >
                <X size={12} />
              </button>
            )}
          </div>
          <BotPicker
            value={botFilter}
            onChange={setBotFilter}
            bots={bots ?? []}
            allowNone
            placeholder="All bots"
          />
          <div className="flex items-center justify-between">
            <label className="inline-flex items-center gap-1.5 text-[11px] text-text-muted">
              <input
                type="checkbox"
                checked={errorOnly}
                onChange={(e) => setErrorOnly(e.target.checked)}
                className="accent-accent"
              />
              Errors only
            </label>
            <button
              type="button"
              onClick={() => void refetch()}
              className="inline-flex items-center gap-1 rounded p-1 text-text-muted hover:bg-surface-overlay"
              title="Refresh"
            >
              <RefreshCw size={12} />
            </button>
          </div>
        </div>
        {/* List */}
        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <div className="p-4 text-center text-[12px] text-text-muted">
              <Loader2 size={14} className="inline animate-spin" /> Loading…
            </div>
          )}
          {!isLoading && (calls?.length ?? 0) === 0 && (
            <div className="p-6 text-center text-[12px] text-text-dim">
              No tool calls match these filters.
            </div>
          )}
          {(calls ?? []).map((c) => (
            <CallRow
              key={c.id}
              call={c}
              isSelected={c.id === selectedId}
              onClick={() => setSelectedId(c.id)}
            />
          ))}
        </div>
      </div>

      {/* Right column */}
      <div className="flex-1 flex flex-col min-w-0">
        {selectedId ? (
          <CallDetail
            key={selectedId}
            callId={selectedId}
            onImport={(toolName, sample) => {
              setImport({ toolName, samplePayload: sample });
              navigate(
                `/widgets/dev?tool=${encodeURIComponent(toolName)}#templates`,
              );
            }}
            onPinGeneric={async (toolName, toolArgs, rawResult, label, resolvedEnvelope, channelId, botId) => {
              // Prefer the envelope currently rendered (tool-declared _envelope
              // or widget template); only fall back to generic-render when the
              // resolver produced nothing.
              let envelope: ToolResultEnvelope | null = resolvedEnvelope;
              if (!envelope) {
                const preview = await genericRenderWidget({
                  tool_name: toolName,
                  raw_result: rawResult,
                });
                if (!preview.ok || !preview.envelope) {
                  throw new Error("Generic render failed");
                }
                envelope = preview.envelope as unknown as ToolResultEnvelope;
              }
              // Carry the origin call's channel/bot through so pinning to a
              // channel dashboard satisfies the source_channel_id constraint
              // and the widget refresh path resolves identity correctly.
              await pinWidget({
                source_kind: channelId ? "channel" : "adhoc",
                source_bot_id: botId,
                source_channel_id: channelId,
                tool_name: toolName,
                tool_args: toolArgs,
                widget_config: {
                  generic_view: true,
                  imported_from_call: selectedId,
                },
                envelope,
                display_label: label,
              });
            }}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-[12px] text-text-dim">
            Select a tool call to inspect.
          </div>
        )}
      </div>
    </div>
  );
}

function CallRow({
  call,
  isSelected,
  onClick,
}: {
  call: ToolCallItem;
  isSelected: boolean;
  onClick: () => void;
}) {
  const cleaned = cleanToolName(call.tool_name);
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "w-full flex flex-col gap-0.5 border-b border-surface-border px-3 py-2 text-left transition-colors " +
        (isSelected
          ? "bg-accent/10"
          : "hover:bg-surface-overlay")
      }
    >
      <div className="flex items-center gap-1.5">
        <span className="flex-1 truncate font-mono text-[12px] text-text">
          {cleaned}
        </span>
        {call.error && (
          <AlertCircle size={11} className="text-danger flex-shrink-0" />
        )}
        <span className="text-[10px] text-text-dim">
          {formatRelativeTime(call.created_at)}
        </span>
      </div>
      <div className="flex items-center gap-2 text-[10px] text-text-dim">
        {call.server_name && <span>{call.server_name}</span>}
        {call.bot_id && <span>·</span>}
        {call.bot_id && <span>{call.bot_id}</span>}
        {call.duration_ms != null && <span>·</span>}
        {call.duration_ms != null && <span>{call.duration_ms}ms</span>}
      </div>
    </button>
  );
}

function CallDetail({
  callId,
  onImport,
  onPinGeneric,
}: {
  callId: string;
  onImport: (toolName: string, sample: unknown) => void;
  onPinGeneric: (
    toolName: string,
    toolArgs: Record<string, unknown>,
    rawResult: unknown,
    label: string | null,
    resolvedEnvelope: ToolResultEnvelope | null,
    channelId: string | null,
    botId: string | null,
  ) => Promise<void>;
}) {
  const t = useThemeTokens();
  const { data: detail, isLoading, isError, error } = useToolCall(callId);
  const [resultTab, setResultTab] = useState<"raw" | "rendered">("rendered");
  const [envelope, setEnvelope] = useState<ToolResultEnvelope | null>(null);
  const [envLoading, setEnvLoading] = useState(false);
  const [pinState, setPinState] = useState<"idle" | "pinning" | "success" | "error">("idle");
  const [pinError, setPinError] = useState<string | null>(null);

  const rawResult = useMemo(
    () => (detail?.result ? parseResult(detail.result) : null),
    [detail?.result],
  );

  // (Re)render when the selection or tab changes. Resolver priority:
  // tool-declared `_envelope` → widget template → generic render. Cheap —
  // the backend caches generic output and tool templates by (tool, payload).
  useEffect(() => {
    if (!detail) return;
    if (resultTab !== "rendered") return;
    setEnvelope(null);
    setEnvLoading(true);
    const tool = cleanToolName(detail.tool_name);
    resolveToolEnvelope({
      toolName: tool,
      rawResult,
      sourceBotId: detail.bot_id ?? null,
      sourceChannelId: detail.channel_id ?? null,
    })
      .then((env) => setEnvelope(env))
      .catch(() => {})
      .finally(() => setEnvLoading(false));
  }, [detail, rawResult, resultTab]);

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-[12px] text-text-muted">
        <Loader2 size={14} className="inline animate-spin mr-1.5" /> Loading…
      </div>
    );
  }
  if (isError || !detail) {
    return (
      <div className="flex-1 flex items-center justify-center text-[12px] text-text-muted">
        Failed to load call details{error instanceof Error ? `: ${error.message}` : ""}
      </div>
    );
  }

  const cleaned = cleanToolName(detail.tool_name);

  const handlePin = async () => {
    if (!detail) return;
    setPinState("pinning");
    setPinError(null);
    try {
      await onPinGeneric(
        cleaned,
        detail.arguments,
        rawResult,
        null,
        envelope,
        detail.channel_id ?? null,
        detail.bot_id ?? null,
      );
      setPinState("success");
      window.setTimeout(() => setPinState("idle"), 2500);
    } catch (err) {
      setPinError(err instanceof Error ? err.message : String(err));
      setPinState("error");
    }
  };

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 border-b border-surface-border px-4 py-3 bg-surface-raised">
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
            Tool call
          </span>
          <span className="truncate font-mono text-[14px] text-text">
            {cleaned}
          </span>
        </div>
        <button
          type="button"
          onClick={() => onImport(cleaned, rawResult)}
          disabled={rawResult == null}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
          title={
            rawResult == null
              ? "No result body to import"
              : "Open Templates editor with this call's result as the sample payload"
          }
        >
          <Wand2 size={13} />
          Import into Templates
        </button>
        <button
          type="button"
          onClick={handlePin}
          disabled={pinState === "pinning" || rawResult == null}
          className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-[12px] font-medium text-text-muted hover:bg-surface-overlay disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {pinState === "pinning" ? (
            <Loader2 size={13} className="animate-spin" />
          ) : pinState === "success" ? (
            <Check size={13} className="text-emerald-400" />
          ) : (
            <Pin size={13} />
          )}
          {pinState === "success" ? "Pinned" : "Pin generic view"}
        </button>
      </div>

      {pinError && (
        <div className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-[12px] text-danger">
          {pinError}
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
        {detail.error && (
          <section>
            <SectionHeader text="Error" />
            <pre className="rounded-md border border-danger/30 bg-danger/10 p-3 text-[12px] font-mono text-danger whitespace-pre-wrap break-words">
              {detail.error}
            </pre>
          </section>
        )}

        <section>
          <SectionHeader text="Arguments" />
          <div className="rounded-md border border-surface-border bg-surface p-3">
            <JsonTreeRenderer body={JSON.stringify(detail.arguments ?? {})} t={t} />
          </div>
        </section>

        <section>
          <div className="flex items-center justify-between">
            <SectionHeader text="Result" />
            <div className="flex gap-1">
              {(["rendered", "raw"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setResultTab(tab)}
                  className={
                    "rounded-md border px-2 py-0.5 text-[11px] transition-colors " +
                    (resultTab === tab
                      ? "border-accent/60 bg-accent/10 text-accent"
                      : "border-surface-border text-text-muted hover:bg-surface-overlay")
                  }
                >
                  {tab === "rendered" ? "Rendered" : "Raw"}
                </button>
              ))}
            </div>
          </div>
          {resultTab === "raw" && (
            <div className="rounded-md border border-surface-border bg-surface p-3">
              {rawResult == null ? (
                <span className="text-[12px] text-text-dim">(empty)</span>
              ) : typeof rawResult === "string" ? (
                <pre className="whitespace-pre-wrap break-words text-[12px] font-mono text-text">
                  {rawResult}
                </pre>
              ) : (
                <JsonTreeRenderer body={JSON.stringify(rawResult)} t={t} />
              )}
            </div>
          )}
          {resultTab === "rendered" && (
            <div className="rounded-md border border-surface-border bg-surface p-3 min-h-[80px]">
              {envLoading && (
                <span className="inline-flex items-center gap-1.5 text-[12px] text-text-muted">
                  <Loader2 size={12} className="animate-spin" /> Rendering…
                </span>
              )}
              {!envLoading && envelope && (
                <RichToolResult envelope={envelope} dispatcher={NOOP_DISPATCHER} t={t} />
              )}
              {!envLoading && !envelope && (
                <span className="text-[12px] text-text-dim">
                  No widget available. Try Import into Templates to build one.
                </span>
              )}
            </div>
          )}
        </section>

        <section className="flex items-center gap-3 text-[11px] text-text-dim">
          <span>Created {formatRelativeTime(detail.created_at)} ago</span>
          {detail.duration_ms != null && <span>· {detail.duration_ms}ms</span>}
          {detail.bot_id && <span>· Bot {detail.bot_id}</span>}
          {detail.server_name && <span>· {detail.server_name}</span>}
          {detail.session_id && (
            <a
              href={`/admin/sessions/${detail.session_id}`}
              className="inline-flex items-center gap-1 text-text-muted hover:text-text"
            >
              Open session <ExternalLink size={10} />
            </a>
          )}
        </section>
      </div>
    </div>
  );
}

function SectionHeader({ text }: { text: string }) {
  return (
    <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-dim">
      {text}
    </h3>
  );
}
