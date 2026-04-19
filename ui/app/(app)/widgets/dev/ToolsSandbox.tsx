import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Play, Loader2, Search, Pin, Check, ArrowRight } from "lucide-react";
import { useTools, executeTool, type ToolItem } from "@/src/api/hooks/useTools";
import {
  genericRenderWidget,
  previewWidgetForTool,
  type PreviewEnvelope,
  type ValidationIssue,
} from "@/src/api/hooks/useWidgetPackages";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import { adaptToToolResultEnvelope } from "@/src/components/chat/renderers/resolveEnvelope";
import { JsonTreeRenderer } from "@/src/components/chat/renderers/JsonTreeRenderer";
import { useThemeTokens } from "@/src/theme/tokens";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import type { ToolResultEnvelope } from "@/src/types/api";
import { ToolArgsForm } from "./ToolArgsForm";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

function toolDisplayName(tool: ToolItem): string {
  return tool.tool_name.includes("-")
    ? tool.tool_name.split("-").slice(1).join("-")
    : tool.tool_name;
}

function PinActionBar({
  selected,
  envelope,
  pinLabel,
  setPinLabel,
  pinState,
  onPin,
  onOpenDashboard,
}: {
  selected: ToolItem;
  envelope: PreviewEnvelope;
  pinLabel: string;
  setPinLabel: (v: string) => void;
  pinState: "idle" | "pinning" | "success" | "error";
  onPin: () => void;
  onOpenDashboard: () => void;
}) {
  const disabled = pinState === "pinning";
  const refreshHint = envelope.refreshable
    ? envelope.refresh_interval_seconds
      ? `Auto-refreshes every ${envelope.refresh_interval_seconds}s.`
      : "Auto-refreshes on load."
    : "Static snapshot — will not auto-refresh.";

  if (pinState === "success") {
    return (
      <button
        type="button"
        onClick={onOpenDashboard}
        className="inline-flex items-center gap-1.5 rounded-md border border-success/40 bg-success/10 px-2.5 py-1.5 text-[12px] font-medium text-success hover:bg-success/15 transition-colors"
      >
        <Check size={13} />
        Pinned
        <span className="mx-1 opacity-60">·</span>
        Open dashboard
        <ArrowRight size={12} />
      </button>
    );
  }

  return (
    <div className="flex flex-col items-end gap-1 min-w-[260px]">
      <div className="flex items-center gap-2 w-full">
        <input
          value={pinLabel}
          onChange={(e) => setPinLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !disabled) onPin();
          }}
          placeholder={toolDisplayName(selected)}
          disabled={disabled}
          className="flex-1 min-w-0 rounded-md border border-surface-border bg-input px-2 py-1.5 text-[12px] text-text outline-none focus:border-accent disabled:opacity-50"
        />
        <button
          type="button"
          onClick={onPin}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:opacity-50 transition-opacity whitespace-nowrap"
        >
          {disabled ? <Loader2 size={13} className="animate-spin" /> : <Pin size={13} />}
          Pin to dashboard
        </button>
      </div>
      <div className="text-[10px] text-text-dim">{refreshHint}</div>
    </div>
  );
}

type PinState = "idle" | "pinning" | "success" | "error";

export function ToolsSandbox() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: tools, isLoading } = useTools();
  const pinWidget = useDashboardPinsStore((s) => s.pinWidget);

  const [filter, setFilter] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [argValues, setArgValues] = useState<Record<string, unknown>>({});
  const [running, setRunning] = useState(false);
  const [rawResult, setRawResult] = useState<unknown | null>(null);
  const [execError, setExecError] = useState<string | null>(null);
  const [envelope, setEnvelope] = useState<PreviewEnvelope | null>(null);
  const [previewErrors, setPreviewErrors] = useState<ValidationIssue[]>([]);
  // True when the envelope came from the generic-render fallback (no widget
  // template for this tool). Stamped into widget_config on pin so future
  // server-side refresh paths can re-apply generic rendering.
  const [isGenericView, setIsGenericView] = useState(false);

  // Pin-to-dashboard state.
  const [pinLabel, setPinLabel] = useState("");
  const [pinState, setPinState] = useState<PinState>("idle");
  const [pinError, setPinError] = useState<string | null>(null);
  const successRevertTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    return () => {
      if (successRevertTimer.current) clearTimeout(successRevertTimer.current);
    };
  }, []);

  const filtered = useMemo(() => {
    const all = tools ?? [];
    if (!filter.trim()) return all;
    const q = filter.toLowerCase();
    return all.filter(
      (tool) =>
        tool.tool_name.toLowerCase().includes(q) ||
        (tool.description ?? "").toLowerCase().includes(q),
    );
  }, [tools, filter]);

  const selected = useMemo(
    () => (tools ?? []).find((tool) => tool.tool_key === selectedKey) ?? null,
    [tools, selectedKey],
  );

  const handlePin = async () => {
    if (!selected || !envelope) return;
    const toolName = toolDisplayName(selected);
    setPinState("pinning");
    setPinError(null);
    try {
      await pinWidget({
        source_kind: "adhoc",
        source_bot_id: null,
        source_channel_id: null,
        tool_name: toolName,
        tool_args: argValues,
        widget_config: isGenericView ? { generic_view: true } : {},
        envelope: envelope as unknown as ToolResultEnvelope,
        display_label: pinLabel.trim() || null,
      });
      setPinState("success");
      if (successRevertTimer.current) clearTimeout(successRevertTimer.current);
      successRevertTimer.current = setTimeout(() => {
        setPinState("idle");
        successRevertTimer.current = null;
      }, 4000);
    } catch (err) {
      setPinError(err instanceof Error ? err.message : "Pin failed");
      setPinState("error");
    }
  };

  const handleRun = async () => {
    if (!selected) return;
    setRunning(true);
    setExecError(null);
    setRawResult(null);
    setEnvelope(null);
    setPreviewErrors([]);
    setIsGenericView(false);
    try {
      const toolName = toolDisplayName(selected);
      const exec = await executeTool(toolName, argValues);
      if (exec.error) {
        setExecError(exec.error);
      }
      setRawResult(exec.result);

      // Pipe result into the active widget template for this tool, if any.
      const payload =
        exec.result && typeof exec.result === "object" && !Array.isArray(exec.result)
          ? (exec.result as Record<string, unknown>)
          : { result: exec.result };
      const preview = await previewWidgetForTool({
        tool_name: toolName,
        sample_payload: payload,
      });
      if (preview.ok && preview.envelope) {
        setEnvelope(preview.envelope);
      } else {
        // No bespoke template — fall back to the generic auto-picker so the
        // result is still pinnable as a static dashboard card.
        const generic = await genericRenderWidget({
          tool_name: toolName,
          raw_result: exec.result,
        });
        if (generic.ok && generic.envelope) {
          setEnvelope(generic.envelope);
          setIsGenericView(true);
        } else if (!preview.ok) {
          setPreviewErrors(preview.errors);
        }
      }
    } catch (err) {
      setExecError(err instanceof Error ? err.message : "Execution failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex flex-1 flex-col md:flex-row overflow-hidden min-h-0">
      {/* Left: tool list */}
      <div className="w-full md:w-64 md:shrink-0 md:border-r md:border-surface-border flex flex-col md:min-h-0 max-h-[35vh] md:max-h-none">
        <div className="border-b border-surface-border px-3 py-2">
          <div className="relative">
            <Search
              size={12}
              className="absolute left-2 top-1/2 -translate-y-1/2 text-text-dim"
            />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search tools…"
              className="w-full rounded-md border border-surface-border bg-input pl-7 pr-2 py-1.5 text-[12px] text-text outline-none focus:border-accent"
            />
          </div>
        </div>
        <div className="flex-1 overflow-auto">
          {isLoading && (
            <div className="px-3 py-4 text-[12px] text-text-dim">Loading…</div>
          )}
          {filtered.map((tool) => {
            const active = tool.tool_key === selectedKey;
            return (
              <button
                key={tool.tool_key}
                onClick={() => {
                  setSelectedKey(tool.tool_key);
                  setArgValues({});
                  setRawResult(null);
                  setEnvelope(null);
                  setPreviewErrors([]);
                  setIsGenericView(false);
                  setExecError(null);
                  setPinLabel("");
                  setPinState("idle");
                  setPinError(null);
                  if (successRevertTimer.current) {
                    clearTimeout(successRevertTimer.current);
                    successRevertTimer.current = null;
                  }
                }}
                className={
                  "w-full text-left px-3 py-2 border-b border-surface-border/60 transition-colors bg-transparent " +
                  (active
                    ? "bg-accent/[0.08] border-l-2 border-l-accent"
                    : "hover:bg-surface-overlay")
                }
              >
                <div className="text-[12px] font-mono text-text truncate">
                  {toolDisplayName(tool)}
                </div>
                {tool.server_name && (
                  <div className="text-[10px] text-text-dim truncate">
                    {tool.server_name}
                  </div>
                )}
              </button>
            );
          })}
          {!isLoading && filtered.length === 0 && (
            <div className="px-3 py-4 text-[12px] text-text-dim">No tools match.</div>
          )}
        </div>
      </div>

      {/* Middle: args + run */}
      <div className="w-full md:w-80 md:shrink-0 md:border-r md:border-surface-border flex flex-col md:min-h-0">
        {selected ? (
          <>
            <div className="border-b border-surface-border px-4 py-3">
              <div className="text-[13px] font-mono text-text mb-0.5">
                {toolDisplayName(selected)}
              </div>
              {selected.description && (
                <div className="text-[11px] text-text-muted leading-snug">
                  {selected.description}
                </div>
              )}
            </div>
            <div className="flex-1 overflow-auto p-4">
              <ToolArgsForm
                schema={selected.parameters}
                values={argValues}
                onChange={setArgValues}
              />
            </div>
            <div className="border-t border-surface-border px-4 py-3">
              <button
                onClick={handleRun}
                disabled={running}
                className="w-full inline-flex items-center justify-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {running ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Play size={13} />
                )}
                Run tool
              </button>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center p-4 text-[12px] text-text-dim text-center">
            Select a tool on the left to run it.
          </div>
        )}
      </div>

      {/* Right: output */}
      <div className="flex-1 flex flex-col min-h-0 min-w-0">
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {execError && (
            <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
              {execError}
            </div>
          )}

          {envelope && selected && previewErrors.length === 0 && (
            <section>
              <div className="flex items-end justify-between mb-2 gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">
                    Rendered widget
                  </div>
                  {isGenericView && (
                    <span
                      title="Auto-rendered from the raw result — author a widget template for richer layouts."
                      className="inline-flex items-center rounded-full border border-surface-border bg-surface-overlay px-2 py-0.5 text-[10px] font-medium text-text-muted"
                    >
                      Generic view
                    </span>
                  )}
                </div>
                <PinActionBar
                  selected={selected}
                  envelope={envelope}
                  pinLabel={pinLabel}
                  setPinLabel={setPinLabel}
                  pinState={pinState}
                  onPin={handlePin}
                  onOpenDashboard={() => navigate("/widgets")}
                />
              </div>
              {pinError && pinState === "error" && (
                <div className="mb-2 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
                  {pinError}
                </div>
              )}
              <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
                <RichToolResult
                  envelope={adaptToToolResultEnvelope(envelope)}
                  dispatcher={NOOP_DISPATCHER}
                  t={t}
                />
              </div>
            </section>
          )}

          {previewErrors.length > 0 && (
            <section>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-text-dim mb-2">
                Widget preview
              </div>
              <div className="rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-[12px] text-text-muted">
                {previewErrors.map((e, i) => (
                  <div key={i} className="font-mono text-[11px]">
                    {e.phase}: {e.message}
                  </div>
                ))}
              </div>
            </section>
          )}

          {rawResult !== null && (
            <section>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-text-dim mb-2">
                Raw result
              </div>
              <div className="rounded-lg border border-surface-border bg-surface-raised p-3 overflow-auto">
                <JsonTreeRenderer body={JSON.stringify(rawResult)} t={t} />
              </div>
            </section>
          )}

          {rawResult === null && !execError && !running && (
            <div className="rounded-lg border border-dashed border-surface-border p-8 text-center text-[12px] text-text-dim">
              Run a tool to see its result here.
            </div>
          )}

          {running && (
            <div className="flex items-center gap-2 text-[12px] text-text-muted">
              <Loader2 size={12} className="animate-spin" />
              Running…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
