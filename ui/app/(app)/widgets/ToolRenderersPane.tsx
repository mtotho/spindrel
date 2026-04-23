import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot as BotIcon,
  Check,
  ChevronDown,
  FileCode,
  Hash,
  Loader2,
  Pin,
  Play,
  Wrench,
} from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import {
  previewDashboardWidgetForTool,
  useWidgetPackages,
  type PreviewEnvelope,
  type ValidationIssue,
  type WidgetPackageListItem,
} from "@/src/api/hooks/useWidgetPackages";
import {
  usePublicToolSignature,
  type PublicToolSignature,
} from "@/src/api/hooks/useTools";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";
import { adaptToToolResultEnvelope } from "@/src/components/chat/renderers/resolveEnvelope";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { ChannelPicker } from "@/src/components/shared/ChannelPicker";
import { useThemeTokens } from "@/src/theme/tokens";
import type { ToolResultEnvelope } from "@/src/types/api";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { ToolArgsForm } from "./dev/ToolArgsForm";
import type { PinScope } from "./WidgetLibrary";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

function resolvedToolName(signature: PublicToolSignature | null, fallback: string): string {
  return signature?.name ?? fallback;
}

type RendererMode = "pin" | "browse";

export function ToolRenderersPane({
  query,
  mode,
  pinScope,
  scopeChannelId,
  onPinCreated,
}: {
  query: string;
  mode: RendererMode;
  pinScope?: PinScope;
  scopeChannelId?: string | null;
  onPinCreated?: (pinId: string) => void;
}) {
  const { data: packages, isLoading, error } = useWidgetPackages();
  const q = query.trim().toLowerCase();
  const [expandedTool, setExpandedTool] = useState<string | null>(null);

  const grouped = useMemo<Map<string, WidgetPackageListItem[]>>(() => {
    const by = new Map<string, WidgetPackageListItem[]>();
    if (!packages) return by;
    for (const pkg of packages) {
      const matchesQuery =
        !q
        || pkg.tool_name.toLowerCase().includes(q)
        || (pkg.name ?? "").toLowerCase().includes(q)
        || (pkg.description ?? "").toLowerCase().includes(q)
        || (pkg.group_ref ?? "").toLowerCase().includes(q);
      if (!matchesQuery) continue;
      const arr = by.get(pkg.tool_name) ?? [];
      arr.push(pkg);
      by.set(pkg.tool_name, arr);
    }
    return by;
  }, [packages, q]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-2 rounded-md bg-accent/5 px-3 py-2 text-[11px] text-text-muted">
        <Wrench size={12} className="mt-0.5 shrink-0 text-accent/70" />
        <span>
          Tool renderers are the template/native rendering lane for a specific tool result, not a
          separate widget kind. In this surface you can run the tool with real arguments, preview
          the active renderer, and
          {mode === "pin" ? " pin the configured instance to the dashboard." : " inspect the configured instance before pinning elsewhere."}
        </span>
      </div>
      {isLoading && (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 animate-pulse rounded-md bg-surface-overlay/40" />
          ))}
        </div>
      )}
      {error && (
        <p className="p-5 text-[12px] text-danger">
          Failed to load tool renderers: {(error as Error).message}
        </p>
      )}
      {!isLoading && !error && grouped.size === 0 && (
        <p className="px-2 py-6 text-center text-[12px] text-text-muted">
          No tool renderers{q ? " match the filter" : ""}.
        </p>
      )}
      {Array.from(grouped.entries()).map(([toolName, pkgs]) => (
        <RendererToolCard
          key={toolName}
          toolName={toolName}
          packages={pkgs}
          mode={mode}
          pinScope={pinScope}
          scopeChannelId={scopeChannelId ?? null}
          expanded={expandedTool === toolName}
          onToggle={() => setExpandedTool(expandedTool === toolName ? null : toolName)}
          onPinCreated={onPinCreated}
        />
      ))}
    </div>
  );
}

function RendererToolCard({
  toolName,
  packages,
  mode,
  pinScope,
  scopeChannelId,
  expanded,
  onToggle,
  onPinCreated,
}: {
  toolName: string;
  packages: WidgetPackageListItem[];
  mode: RendererMode;
  pinScope?: PinScope;
  scopeChannelId: string | null;
  expanded: boolean;
  onToggle: () => void;
  onPinCreated?: (pinId: string) => void;
}) {
  const t = useThemeTokens();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const { data: signature } = usePublicToolSignature(expanded ? toolName : null);
  const pinWidget = useDashboardPinsStore((s) => s.pinWidget);
  const activePackage = packages.find((pkg) => pkg.is_active) ?? null;

  const pinnedBotId = mode === "pin" && pinScope?.kind === "bot" ? pinScope.botId : "";
  const [selectedBotId, setSelectedBotId] = useState(pinnedBotId);
  const [selectedChannelId, setSelectedChannelId] = useState(scopeChannelId ?? "");
  const [argValues, setArgValues] = useState<Record<string, unknown>>({});
  const [running, setRunning] = useState(false);
  const [pinning, setPinning] = useState(false);
  const [pinSuccess, setPinSuccess] = useState(false);
  const [execError, setExecError] = useState<string | null>(null);
  const [previewErrors, setPreviewErrors] = useState<ValidationIssue[]>([]);
  const [envelope, setEnvelope] = useState<PreviewEnvelope | null>(null);
  const [displayLabel, setDisplayLabel] = useState("");

  useEffect(() => {
    setSelectedBotId(pinnedBotId);
  }, [pinnedBotId]);

  useEffect(() => {
    if (scopeChannelId) setSelectedChannelId(scopeChannelId);
  }, [scopeChannelId]);

  useEffect(() => {
    setArgValues({});
    setExecError(null);
    setPreviewErrors([]);
    setEnvelope(null);
    setPinSuccess(false);
    setDisplayLabel("");
  }, [toolName]);

  const effectiveBotId = mode === "pin" ? pinnedBotId : selectedBotId;
  const effectiveChannelId = scopeChannelId ?? selectedChannelId;
  const toolNameForRun = resolvedToolName(signature ?? null, toolName);
  const requiresBot = !!signature?.requires_bot_context;
  const requiresChannel = !!signature?.requires_channel_context;
  const missingBot = requiresBot && !effectiveBotId;
  const missingChannel = requiresChannel && !effectiveChannelId;
  const runDisabledReason =
    running
      ? null
      : mode === "pin" && requiresBot && pinScope?.kind !== "bot"
      ? "Set Runs as to a bot first."
      : missingBot && missingChannel
      ? "Select a bot and a channel first."
      : missingBot
      ? "Select a bot first."
      : missingChannel
      ? "Select a channel first."
      : null;
  const pinDisabledReason =
    !envelope
      ? "Run a preview first."
      : mode !== "pin"
      ? "Pinning is only available from Add Widget."
      : runDisabledReason;

  const handleRun = async () => {
    if (runDisabledReason) return;
    setRunning(true);
    setExecError(null);
    setPreviewErrors([]);
    setEnvelope(null);
    setPinSuccess(false);
    try {
      const preview = await previewDashboardWidgetForTool({
        tool_name: toolNameForRun,
        tool_args: argValues,
        source_bot_id: effectiveBotId || null,
        source_channel_id: effectiveChannelId || null,
      });
      if (preview.ok && preview.envelope) {
        setEnvelope(preview.envelope);
      } else {
        setPreviewErrors(preview.errors);
      }
    } catch (err) {
      setExecError(err instanceof Error ? err.message : "Execution failed");
    } finally {
      setRunning(false);
    }
  };

  const handlePin = async () => {
    if (pinDisabledReason || !envelope) return;
    setPinning(true);
    setExecError(null);
    try {
      const created = await pinWidget({
        source_kind: "adhoc",
        source_bot_id: effectiveBotId || null,
        source_channel_id: effectiveChannelId || null,
        tool_name: toolNameForRun,
        tool_args: argValues,
        widget_config: {},
        envelope: envelope as unknown as ToolResultEnvelope,
        display_label: displayLabel.trim() || null,
      });
      setPinSuccess(true);
      onPinCreated?.(created.id);
    } catch (err) {
      setExecError(err instanceof Error ? err.message : "Pin failed");
    } finally {
      setPinning(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-md bg-surface">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-3 px-3 py-2 text-left transition-colors hover:bg-surface-overlay/60"
      >
        <Wrench size={13} className="mt-0.5 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] font-semibold text-text">{toolName}</span>
            <span className="text-[10px] text-text-dim">
              {packages.length} renderer{packages.length === 1 ? "" : "s"}
            </span>
            {activePackage && (
              <span className="rounded bg-accent/10 px-1 py-px text-[10px] text-accent">
                active: {activePackage.name}
              </span>
            )}
            {!signature && (
              <span className="rounded bg-warning/15 px-1 py-px text-[10px] text-warning">
                tool metadata missing
              </span>
            )}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-text-dim">
            {packages.slice(0, 3).map((pkg) => (
              <span key={pkg.id} className="rounded bg-surface-overlay px-1 py-px">
                {pkg.name}
              </span>
            ))}
            {packages.length > 3 && (
              <span className="rounded bg-surface-overlay px-1 py-px">
                +{packages.length - 3} more
              </span>
            )}
          </div>
        </div>
        <ChevronDown
          size={13}
          className={[
            "shrink-0 text-text-dim transition-transform",
            expanded && "rotate-180 text-accent",
          ].filter(Boolean).join(" ")}
        />
      </button>

      {expanded && (
        <div className="border-t border-surface-border/40 px-3 py-3">
          <div className="flex flex-col gap-3">
            <div className="rounded-md bg-surface-overlay/40 px-3 py-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                Renderer packages
              </div>
              <div className="mt-2 space-y-1.5">
                {packages.map((pkg) => (
                  <div key={pkg.id} className="flex items-start gap-2 text-[11px]">
                    <FileCode size={12} className="mt-0.5 shrink-0 text-text-dim" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-medium text-text">{pkg.name}</span>
                        {pkg.is_active && (
                          <span className="rounded bg-accent/10 px-1 py-px text-[10px] text-accent">
                            active
                          </span>
                        )}
                        {pkg.source_integration && (
                          <span className="rounded bg-accent/10 px-1 py-px text-[10px] text-accent">
                            {pkg.source_integration}
                          </span>
                        )}
                        {pkg.group_kind && pkg.group_ref && (
                          <span className="rounded bg-surface px-1 py-px text-[10px] text-text-muted">
                            {pkg.group_kind}:{pkg.group_ref}
                          </span>
                        )}
                      </div>
                      {pkg.description && (
                        <p className="mt-0.5 text-text-muted">{pkg.description}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {!signature && (
              <div className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-[12px] text-warning">
                This renderer is registered, but the tool catalog entry is missing, so the
                library can’t build an argument form for it yet.
              </div>
            )}

            {signature && (
              <>
                <div className="grid gap-3 md:grid-cols-2">
                  <ContextCard
                    label="Bot"
                    required={requiresBot}
                    fixed={mode === "pin"}
                    fixedValue={mode === "pin"
                      ? pinScope?.kind === "bot"
                        ? bots?.find((b) => b.id === pinnedBotId)?.name ?? pinnedBotId
                        : "Runs as: You"
                      : undefined}
                  >
                    <BotPicker
                      value={selectedBotId}
                      onChange={setSelectedBotId}
                      bots={bots ?? []}
                      allowNone
                      placeholder={mode === "pin" ? "Controlled by Runs as" : "Select bot…"}
                      disabled={mode === "pin"}
                    />
                  </ContextCard>
                  <ContextCard
                    label="Channel"
                    required={requiresChannel}
                    fixed={!!scopeChannelId}
                    fixedValue={
                      scopeChannelId
                        ? channels?.find((ch) => String(ch.id) === scopeChannelId)?.display_name
                          ?? channels?.find((ch) => String(ch.id) === scopeChannelId)?.name
                          ?? scopeChannelId
                        : undefined
                    }
                  >
                    <ChannelPicker
                      value={selectedChannelId}
                      onChange={setSelectedChannelId}
                      channels={channels ?? []}
                      bots={bots ?? []}
                      allowNone
                      placeholder="Select channel…"
                      disabled={!!scopeChannelId}
                    />
                  </ContextCard>
                </div>

                <div>
                  <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                    Tool arguments
                  </div>
                  <ToolArgsForm
                    schema={signature.input_schema}
                    values={argValues}
                    onChange={setArgValues}
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={handleRun}
                    disabled={runDisabledReason !== null}
                    title={runDisabledReason ?? undefined}
                    className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1.5 text-[11px] font-medium text-white hover:opacity-90 disabled:opacity-50"
                  >
                    {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                    Run preview
                  </button>
                  {mode === "pin" && (
                    <>
                      <input
                        value={displayLabel}
                        onChange={(e) => setDisplayLabel(e.target.value)}
                        placeholder={activePackage?.name ?? toolName}
                        className="min-w-[180px] flex-1 rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[11px] text-text outline-none focus:border-accent/40"
                      />
                      <button
                        type="button"
                        onClick={handlePin}
                        disabled={pinDisabledReason !== null || pinning}
                        title={pinDisabledReason ?? undefined}
                        className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1.5 text-[11px] font-medium text-white hover:opacity-90 disabled:opacity-50"
                      >
                        {pinning ? <Loader2 size={12} className="animate-spin" /> : pinSuccess ? <Check size={12} /> : <Pin size={12} />}
                        {pinSuccess ? "Pinned" : "Add to dashboard"}
                      </button>
                    </>
                  )}
                </div>

                {runDisabledReason && (
                  <div className="rounded-md bg-warning/10 px-2.5 py-1.5 text-[11px] text-warning">
                    {runDisabledReason}
                  </div>
                )}
              </>
            )}

            {execError && (
              <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
                {execError}
              </div>
            )}

            {previewErrors.length > 0 && (
              <div className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-[12px] text-warning">
                {previewErrors.map((issue, idx) => (
                  <div key={`${issue.phase}-${idx}`} className="font-mono text-[11px]">
                    {issue.phase}: {issue.message}
                  </div>
                ))}
              </div>
            )}

            {envelope && (
              <div className="rounded-md bg-surface-overlay/40 p-2">
                <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                  <Wrench size={10} className="text-accent" />
                  Preview
                  {envelope.refreshable && (
                    <span className="rounded bg-accent/10 px-1 py-px text-[10px] font-medium text-accent normal-case tracking-normal">
                      refreshable{envelope.refresh_interval_seconds ? ` · ${envelope.refresh_interval_seconds}s` : ""}
                    </span>
                  )}
                </div>
                <RichToolResult
                  envelope={adaptToToolResultEnvelope(envelope)}
                  dispatcher={NOOP_DISPATCHER}
                  t={t}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ContextCard({
  label,
  required,
  fixed,
  fixedValue,
  children,
}: {
  label: string;
  required: boolean;
  fixed: boolean;
  fixedValue?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md bg-surface-overlay/40 px-3 py-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
          {label}
        </span>
        <div className="flex items-center gap-1">
          {required && (
            <span className="rounded bg-accent/10 px-1 py-px text-[10px] font-medium text-accent">
              required
            </span>
          )}
          {fixed && (
            <span className="rounded bg-surface px-1 py-px text-[10px] text-text-muted">
              fixed
            </span>
          )}
        </div>
      </div>
      {fixedValue && (
        <div className="mb-2 flex items-center gap-1.5 rounded bg-surface px-2 py-1 text-[11px] text-text-muted">
          {label === "Bot" ? <BotIcon size={11} /> : <Hash size={11} />}
          <span className="truncate">{fixedValue}</span>
        </div>
      )}
      {children}
      {fixed && !fixedValue && required && (
        <div className="mt-2 flex items-start gap-1.5 text-[11px] text-warning">
          <AlertTriangle size={11} className="mt-0.5 shrink-0" />
          <span>This renderer needs a different dashboard/run scope before it can be instantiated here.</span>
        </div>
      )}
    </div>
  );
}
