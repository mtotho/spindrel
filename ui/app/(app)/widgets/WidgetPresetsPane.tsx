import { useEffect, useMemo, useState } from "react";
import { Check, Home, Loader2, Pin, Search, SlidersHorizontal } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannel } from "@/src/api/hooks/useChannels";
import {
  getWidgetPresetBindingOptions,
  previewWidgetPreset,
  useWidgetPresets,
  type WidgetPreset,
  type WidgetPresetField,
  type WidgetPresetOption,
} from "@/src/api/hooks/useWidgetPresets";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useThemeTokens } from "@/src/theme/tokens";
import type { ToolResultEnvelope } from "@/src/types/api";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

type PresetStep = "catalog" | "configure" | "preview";

interface Props {
  mode: "pin" | "browse";
  query?: string;
  scopeChannelId?: string | null;
  onPinCreated?: (pinId: string) => void;
  selectedPresetId?: string;
  onSelectedPresetIdChange?: (presetId: string) => void;
  step?: PresetStep;
  onStepChange?: (step: PresetStep) => void;
  layout?: "compact" | "builder";
}

export function WidgetPresetsPane({
  mode,
  query = "",
  scopeChannelId,
  onPinCreated,
  selectedPresetId,
  onSelectedPresetIdChange,
  step,
  onStepChange,
  layout = "compact",
}: Props) {
  const { data: presets, isLoading, error } = useWidgetPresets();
  const { data: bots } = useBots();
  const { data: scopedChannel } = useChannel(scopeChannelId ?? undefined);
  const pinPreset = useDashboardPinsStore((s) => s.pinPreset);
  const t = useThemeTokens();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (presets ?? []).filter((preset) => {
      if (!q) return true;
      return [preset.name, preset.description ?? "", preset.integration_id ?? ""]
        .some((value) => value.toLowerCase().includes(q));
    });
  }, [presets, query]);

  const [internalPresetId, setInternalPresetId] = useState("");
  const activePresetId = selectedPresetId ?? internalPresetId;
  const setActivePresetId = (presetId: string) => {
    onSelectedPresetIdChange?.(presetId);
    if (selectedPresetId === undefined) setInternalPresetId(presetId);
  };
  const selectedPreset = filtered.find((preset) => preset.id === activePresetId) ?? filtered[0] ?? null;

  useEffect(() => {
    if (!activePresetId && filtered[0]?.id) setActivePresetId(filtered[0].id);
    if (activePresetId && !filtered.some((preset) => preset.id === activePresetId)) {
      setActivePresetId(filtered[0]?.id ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, activePresetId]);

  const [internalStep, setInternalStep] = useState<PresetStep>("catalog");
  const activeStep = step ?? internalStep;
  const setActiveStep = (next: PresetStep) => {
    onStepChange?.(next);
    if (step === undefined) setInternalStep(next);
  };

  useEffect(() => {
    if (!selectedPreset) setActiveStep("catalog");
    else if (activeStep === "catalog") setActiveStep("configure");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPreset?.id]);

  const [selectedBotId, setSelectedBotId] = useState("");
  useEffect(() => {
    if (scopeChannelId && scopedChannel?.bot_id) {
      setSelectedBotId(scopedChannel.bot_id);
      return;
    }
    if (!selectedBotId && (bots?.length ?? 0) === 1) {
      setSelectedBotId(bots?.[0]?.id ?? "");
    }
  }, [scopeChannelId, scopedChannel?.bot_id, bots, selectedBotId]);

  const [config, setConfig] = useState<Record<string, unknown>>({});
  useEffect(() => {
    if (!selectedPreset) {
      setConfig({});
      return;
    }
    setConfig({ ...(selectedPreset.default_config ?? {}) });
  }, [selectedPreset?.id]);

  const [sourceOptions, setSourceOptions] = useState<Record<string, WidgetPresetOption[]>>({});
  const [sourceLoading, setSourceLoading] = useState<Record<string, boolean>>({});
  const [sourceError, setSourceError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedPreset || !selectedBotId) {
      setSourceOptions({});
      setSourceLoading({});
      setSourceError(null);
      return;
    }
    let cancelled = false;
    setSourceOptions({});
    setSourceLoading({});
    setSourceError(null);

    const fields = selectedPreset.binding_schema.properties ?? {};
    for (const field of Object.values(fields)) {
      const sourceId = field.ui?.source;
      if (!sourceId) continue;
      setSourceLoading((prev) => ({ ...prev, [sourceId]: true }));
      void getWidgetPresetBindingOptions(selectedPreset.id, sourceId, {
        source_bot_id: selectedBotId || null,
        source_channel_id: scopeChannelId ?? null,
      }).then((resp) => {
        if (cancelled) return;
        setSourceOptions((prev) => ({ ...prev, [sourceId]: resp.options ?? [] }));
        setSourceLoading((prev) => ({ ...prev, [sourceId]: false }));
      }).catch((err) => {
        if (cancelled) return;
        setSourceError(err instanceof Error ? err.message : String(err));
        setSourceLoading((prev) => ({ ...prev, [sourceId]: false }));
      });
    }

    return () => { cancelled = true; };
  }, [selectedPreset?.id, selectedBotId, scopeChannelId]);

  const [previewState, setPreviewState] = useState<{
    running: boolean;
    error: string | null;
    envelope: ToolResultEnvelope | null;
    config: Record<string, unknown>;
  }>({
    running: false,
    error: null,
    envelope: null,
    config: {},
  });

  const [pinning, setPinning] = useState(false);
  const [pinSuccess, setPinSuccess] = useState(false);

  const runPreview = async () => {
    if (!selectedPreset || !selectedBotId) return;
    setPreviewState((prev) => ({ ...prev, running: true, error: null, envelope: null }));
    setPinSuccess(false);
    try {
      const resp = await previewWidgetPreset(selectedPreset.id, {
        config,
        source_bot_id: selectedBotId,
        source_channel_id: scopeChannelId ?? null,
      });
      if (!resp.ok || !resp.envelope) {
        const first = resp.errors[0]?.message ?? "Preview failed";
        setPreviewState({ running: false, error: first, envelope: null, config: resp.config ?? config });
        setActiveStep("configure");
        return;
      }
      setPreviewState({
        running: false,
        error: null,
        envelope: resp.envelope as unknown as ToolResultEnvelope,
        config: resp.config ?? config,
      });
      setActiveStep("preview");
    } catch (err) {
      setPreviewState({
        running: false,
        error: err instanceof Error ? err.message : "Preview failed",
        envelope: null,
        config,
      });
      setActiveStep("configure");
    }
  };

  const selectedEntityLabel = useMemo(() => {
    const entityId = String(config.entity_id ?? "");
    if (!selectedPreset || !entityId) return null;
    const sourceId = selectedPreset.binding_schema.properties?.entity_id?.ui?.source;
    if (!sourceId) return null;
    return sourceOptions[sourceId]?.find((option) => option.value === entityId)?.label ?? null;
  }, [config.entity_id, selectedPreset, sourceOptions]);

  const pinDisabled = mode !== "pin" || !selectedPreset || !selectedBotId || !previewState.envelope || pinning;
  const handlePin = async () => {
    if (!selectedPreset || pinDisabled) return;
    setPinning(true);
    try {
      const created = await pinPreset(selectedPreset.id, {
        config: previewState.config,
        source_bot_id: selectedBotId,
        source_channel_id: scopeChannelId ?? null,
        display_label: selectedEntityLabel,
      });
      setPinSuccess(true);
      onPinCreated?.(created.id);
    } finally {
      setPinning(false);
    }
  };

  const builder = layout === "builder";

  return (
    <div className={builder ? "flex h-full min-h-0 flex-col" : "flex flex-col gap-3 p-3"}>
      {!builder && (
        <div className="flex items-start gap-2 rounded-md bg-accent/5 px-3 py-2 text-[11px] text-text-muted">
          <Home size={12} className="mt-0.5 shrink-0 text-accent/70" />
          <span>
            Presets are ready-made widgets with a guided binding flow. Pick a preset, bind it, preview it, then pin it without touching raw tool args or YAML.
          </span>
        </div>
      )}

      <div
        className={builder
          ? "grid min-h-0 flex-1 gap-6 px-5 pb-5 lg:grid-cols-[240px_minmax(0,1fr)] 2xl:grid-cols-[260px_360px_minmax(0,1fr)]"
          : "grid gap-3 lg:grid-cols-[240px_minmax(0,1fr)]"}
      >
        <section className={builder ? "min-h-0 bg-transparent" : "min-h-0 border border-surface-border bg-surface"}>
          <div className={builder ? "px-1 py-2" : "border-b border-surface-border px-3 py-2"}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">
              Presets
            </div>
            {builder && (
              <div className="mt-1 text-[11px] text-text-muted">
                Ready-made widget flows with guided inputs.
              </div>
            )}
          </div>
          {isLoading && (
            <div className="space-y-2 p-3">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-14 animate-pulse rounded-md bg-surface-overlay/40" />
              ))}
            </div>
          )}
          {error && (
            <p className="px-3 py-4 text-[12px] text-danger">
              Failed to load presets: {(error as Error).message}
            </p>
          )}
          {!isLoading && !error && filtered.length === 0 && (
            <div className="px-3 py-6 text-[12px] text-text-muted">
              <div className="inline-flex items-center gap-1.5 text-text-dim">
                <Search size={13} />
                No presets match the current filter.
              </div>
            </div>
          )}
          <div className={builder ? "max-h-full space-y-1 overflow-auto" : "max-h-full space-y-1 overflow-auto p-2"}>
            {filtered.map((preset) => {
              const active = preset.id === selectedPreset?.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => {
                    setActivePresetId(preset.id);
                    setActiveStep("configure");
                    setPinSuccess(false);
                  }}
                  className={[
                    builder
                      ? "w-full px-3 py-3 text-left transition-colors"
                      : "w-full rounded-lg border px-3 py-3 text-left transition-colors",
                    active
                      ? builder
                        ? "bg-accent/[0.08] text-text"
                        : "border-accent/50 bg-accent/10 text-text"
                      : builder
                        ? "text-text-muted hover:bg-surface-overlay/60"
                        : "border-transparent text-text-muted hover:border-surface-border hover:bg-surface-overlay",
                  ].join(" ")}
                >
                  <div className="text-[13px] font-medium text-text">{preset.name}</div>
                  <div className="mt-1 text-[11px] text-text-dim">{preset.description}</div>
                </button>
              );
            })}
          </div>
        </section>

        <section className={builder ? "min-h-0 bg-transparent" : "min-h-0 rounded-xl border border-surface-border bg-surface"}>
          {!selectedPreset ? (
            <div className="flex h-full min-h-[220px] items-center justify-center px-6 text-center text-[12px] text-text-muted">
              Select a preset to configure it.
            </div>
          ) : (
            <div className="flex h-full min-h-0 flex-col">
              <div className={builder ? "px-1 py-2" : "border-b border-surface-border px-4 py-3"}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[15px] font-semibold text-text">{selectedPreset.name}</div>
                    <div className="mt-1 text-[11px] text-text-muted">{selectedPreset.description}</div>
                  </div>
                  <div className="w-full max-w-[240px]">
                    <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                      Run as bot
                    </label>
                    <BotPicker
                      bots={bots ?? []}
                      value={selectedBotId}
                      onChange={setSelectedBotId}
                      placeholder="Choose bot"
                    />
                  </div>
                </div>
                {builder && (
                  <div className="mt-4 flex items-center gap-2 text-[10px] font-medium uppercase tracking-wide text-text-dim">
                    <StepPill active={activeStep === "catalog"} label="Catalog" />
                    <StepPill active={activeStep === "configure"} label="Configure" />
                    <StepPill active={activeStep === "preview"} label="Preview" />
                  </div>
                )}
              </div>

              <div className={builder ? "flex-1 overflow-auto px-1 py-4" : "flex-1 overflow-auto p-4"}>
                <div className="grid gap-3">
                  {Object.entries(selectedPreset.binding_schema.properties ?? {}).map(([fieldId, field]) => (
                    <PresetField
                      key={fieldId}
                      fieldId={fieldId}
                      field={field}
                      value={config[fieldId]}
                      options={sourceOptions[field.ui?.source ?? ""] ?? []}
                      loading={sourceLoading[field.ui?.source ?? ""] ?? false}
                      onChange={(next) => {
                        setConfig((prev) => ({ ...prev, [fieldId]: next }));
                        setActiveStep("configure");
                        setPinSuccess(false);
                      }}
                    />
                  ))}
                </div>

                {sourceError && (
                  <div className="mt-4 rounded-md bg-danger/10 px-3 py-2 text-[12px] text-danger">
                    {sourceError}
                  </div>
                )}
                {previewState.error && (
                  <div className="mt-4 rounded-md bg-danger/10 px-3 py-2 text-[12px] text-danger">
                    {previewState.error}
                  </div>
                )}
              </div>

              <div className={builder ? "px-1 py-3" : "border-t border-surface-border px-4 py-3"}>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={runPreview}
                    disabled={!selectedBotId || previewState.running}
                    className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
                  >
                    {previewState.running ? <Loader2 size={13} className="animate-spin" /> : <Home size={13} />}
                    Run preview
                  </button>
                  {mode === "pin" && (
                    <button
                      type="button"
                      onClick={handlePin}
                      disabled={pinDisabled}
                      className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-3 py-1.5 text-[12px] font-medium text-text-muted hover:bg-surface-overlay disabled:opacity-40"
                    >
                      {pinning ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : pinSuccess ? (
                        <Check size={13} className="text-success" />
                      ) : (
                        <Pin size={13} />
                      )}
                      {pinSuccess ? "Pinned" : "Pin preset"}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>

        {(builder || previewState.envelope || previewState.running || previewState.error) && (
          <section className={builder ? "min-h-0 bg-transparent lg:col-span-2 2xl:col-span-1" : "min-h-0 rounded-xl border border-surface-border bg-surface"}>
            <div className={builder ? "px-1 py-2" : "border-b border-surface-border px-4 py-3"}>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">
                Preview
              </div>
              <div className="mt-1 text-[11px] text-text-muted">
                Confirm the widget before pinning it onto the dashboard.
              </div>
            </div>
            <div className={builder ? "flex h-full min-h-[320px] flex-col overflow-auto px-1 py-4" : "flex h-full min-h-[320px] flex-col overflow-auto p-4"}>
              {previewState.running ? (
                <div className="flex flex-1 items-center justify-center text-[12px] text-text-muted">
                  <Loader2 size={16} className="mr-2 animate-spin" />
                  Rendering preview…
                </div>
              ) : previewState.envelope ? (
                <div className="min-h-0 bg-surface-overlay/10 p-3">
                  <RichToolResult
                    envelope={previewState.envelope}
                    dispatcher={NOOP_DISPATCHER}
                    t={t}
                  />
                </div>
              ) : (
                <div className="flex flex-1 items-center justify-center text-center text-[12px] text-text-muted">
                  Run a preview to see the widget render here.
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function StepPill({ active, label }: { active: boolean; label: string }) {
  return (
    <span
      className={[
        "py-0.5",
        active ? "text-accent" : "text-text-dim",
      ].join(" ")}
    >
      {label}
    </span>
  );
}

function PresetField({
  fieldId,
  field,
  value,
  options,
  loading,
  onChange,
}: {
  fieldId: string;
  field: WidgetPresetField;
  value: unknown;
  options: WidgetPresetOption[];
  loading: boolean;
  onChange: (next: unknown) => void;
}) {
  const control = field.ui?.control;

  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
        {field.title ?? fieldId}
      </span>
      {control === "picker" ? (
        <select
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-surface-border bg-input px-2.5 py-2 text-[12px] text-text outline-none focus:border-accent/50"
        >
          <option value="">
            {loading ? "Loading…" : "Select…"}
          </option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.group ? `${option.group} · ${option.label}` : option.label}
            </option>
          ))}
        </select>
      ) : field.type === "boolean" ? (
        <button
          type="button"
          onClick={() => onChange(!value)}
          className={[
            "inline-flex items-center justify-between rounded-md border px-3 py-2 text-[12px]",
            value ? "border-accent/50 bg-accent/10 text-text" : "border-surface-border text-text-muted",
          ].join(" ")}
        >
          <span>{field.description ?? field.title ?? fieldId}</span>
          <span className="inline-flex items-center gap-1">
            <SlidersHorizontal size={12} />
            {value ? "On" : "Off"}
          </span>
        </button>
      ) : (
        <input
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-surface-border bg-input px-2.5 py-2 text-[12px] text-text outline-none focus:border-accent/50"
        />
      )}
      {field.description && control !== "boolean" && (
        <span className="text-[10px] text-text-dim">{field.description}</span>
      )}
    </label>
  );
}
