import { useMemo, useState } from "react";
import { Play, Loader2, Search } from "lucide-react";
import { useTools, executeTool, type ToolItem } from "@/src/api/hooks/useTools";
import {
  previewWidgetForTool,
  previewWidgetInline,
  type PreviewEnvelope,
  type ValidationIssue,
} from "@/src/api/hooks/useWidgetPackages";
import {
  ComponentRenderer,
  WidgetActionContext,
  type WidgetActionDispatcher,
} from "@/src/components/chat/renderers/ComponentRenderer";
import { JsonTreeRenderer } from "@/src/components/chat/renderers/JsonTreeRenderer";
import { useThemeTokens } from "@/src/theme/tokens";
import { ToolArgsForm } from "./ToolArgsForm";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

function toolDisplayName(tool: ToolItem): string {
  return tool.tool_name.includes("-")
    ? tool.tool_name.split("-").slice(1).join("-")
    : tool.tool_name;
}

export function ToolsSandbox() {
  const t = useThemeTokens();
  const { data: tools, isLoading } = useTools();

  const [filter, setFilter] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [argValues, setArgValues] = useState<Record<string, unknown>>({});
  const [running, setRunning] = useState(false);
  const [rawResult, setRawResult] = useState<unknown | null>(null);
  const [execError, setExecError] = useState<string | null>(null);
  const [envelope, setEnvelope] = useState<PreviewEnvelope | null>(null);
  const [previewErrors, setPreviewErrors] = useState<ValidationIssue[]>([]);

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

  const handleRun = async () => {
    if (!selected) return;
    setRunning(true);
    setExecError(null);
    setRawResult(null);
    setEnvelope(null);
    setPreviewErrors([]);
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
      if (preview.ok) {
        setEnvelope(preview.envelope ?? null);
      } else {
        setPreviewErrors(preview.errors);
      }
    } catch (err) {
      setExecError(err instanceof Error ? err.message : "Execution failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left: tool list */}
      <div className="w-64 shrink-0 border-r border-surface-border flex flex-col min-h-0">
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
              className="w-full rounded-md border border-surface-border bg-input-bg pl-7 pr-2 py-1.5 text-[12px] text-text outline-none focus:border-accent"
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
                  setExecError(null);
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
      <div className="w-80 shrink-0 border-r border-surface-border flex flex-col min-h-0">
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
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {execError && (
            <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
              {execError}
            </div>
          )}

          {envelope && previewErrors.length === 0 && (
            <section>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-text-dim mb-2">
                Rendered widget
              </div>
              <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
                <WidgetActionContext.Provider value={NOOP_DISPATCHER}>
                  <ComponentRenderer body={envelope.body} t={t} />
                </WidgetActionContext.Provider>
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
