import { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Check, ChevronDown, Home, Loader2, Pin, Search, SlidersHorizontal } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannel } from "@/src/api/hooks/useChannels";
import {
  previewWidgetPreset,
  useWidgetPresets,
  type WidgetPresetField,
  type WidgetPresetOption,
  type WidgetPresetBindingSchema,
} from "@/src/api/hooks/useWidgetPresets";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useThemeTokens } from "@/src/theme/tokens";
import type { ToolResultEnvelope } from "@/src/types/api";

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
  const { data: bots } = useBots();
  const { data: scopedChannel } = useChannel(scopeChannelId ?? undefined);
  const pinPreset = useDashboardPinsStore((s) => s.pinPreset);
  const t = useThemeTokens();
  const [selectedBotId, setSelectedBotId] = useState("");

  const { data: presets, isLoading, error } = useWidgetPresets(
    selectedBotId || null,
    scopeChannelId ?? null,
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (presets ?? []).filter((preset) => {
      if (!q) return true;
      return [preset.name, preset.description ?? "", preset.integration_id ?? ""]
        .some((value) => value.toLowerCase().includes(q));
    });
  }, [presets, query]);

  const [internalPresetId, setInternalPresetId] = useState("");
  const [optimisticPresetId, setOptimisticPresetId] = useState("");
  const lastControlledPresetIdRef = useRef<string | undefined>(selectedPresetId);
  const activePresetId = optimisticPresetId || selectedPresetId || internalPresetId;
  const setActivePresetId = (presetId: string) => {
    setOptimisticPresetId(presetId);
    onSelectedPresetIdChange?.(presetId);
    if (selectedPresetId === undefined) setInternalPresetId(presetId);
  };
  const selectedPreset = filtered.find((preset) => preset.id === activePresetId) ?? filtered[0] ?? null;

  useEffect(() => {
    if (selectedPresetId === lastControlledPresetIdRef.current) return;
    lastControlledPresetIdRef.current = selectedPresetId;
    setOptimisticPresetId(selectedPresetId ?? "");
  }, [selectedPresetId]);

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
  const [sourceErrors, setSourceErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!selectedPreset || !selectedBotId) {
      setSourceOptions({});
      setSourceLoading({});
      setSourceErrors({});
      return;
    }
    const nextOptions: Record<string, WidgetPresetOption[]> = {};
    const nextLoading: Record<string, boolean> = {};
    const nextErrors: Record<string, string> = {};
    const fields = selectedPreset.binding_schema.properties ?? {};
    for (const field of Object.values(fields)) {
      const sourceId = field.ui?.source;
      if (!sourceId) continue;
      nextOptions[sourceId] = selectedPreset.resolved_binding_options?.[sourceId] ?? [];
      nextLoading[sourceId] = false;
      const sourceErrorMessage = selectedPreset.binding_source_errors?.[sourceId];
      if (sourceErrorMessage) nextErrors[sourceId] = sourceErrorMessage;
    }
    setSourceOptions(nextOptions);
    setSourceLoading(nextLoading);
    setSourceErrors(nextErrors);
  }, [selectedPreset, selectedBotId, scopeChannelId]);

  const sourceError = useMemo(
    () => Object.values(sourceErrors)[0] ?? null,
    [sourceErrors],
  );

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
  const [pinError, setPinError] = useState<string | null>(null);

  const bindingFields = selectedPreset?.binding_schema.properties ?? {};
  const requiredFields = selectedPreset?.binding_schema.required ?? [];

  const resolvePickerOptions = (
    fieldId: string,
    field: WidgetPresetField,
    fields: Record<string, WidgetPresetField>,
    nextConfig: Record<string, unknown> = config,
  ): WidgetPresetOption[] => {
    const sourceId = field.ui?.source;
    if (sourceId) {
      return sourceOptions[sourceId] ?? [];
    }

    const parentFieldId = field.ui?.options_from_field;
    if (!parentFieldId) {
      return [];
    }
    const parentField = fields[parentFieldId];
    if (!parentField?.ui?.source) {
      return [];
    }
    const parentOptions = sourceOptions[parentField.ui.source] ?? [];
    const selectedParentValue = String(nextConfig[parentFieldId] ?? "");
    const selectedParentOption = parentOptions.find((option) => option.value === selectedParentValue);
    const metaKey = field.ui?.options_from_meta || "options";
    const rawOptions = selectedParentOption?.meta?.[metaKey];
    if (!Array.isArray(rawOptions)) {
      return [];
    }
    return rawOptions
      .filter((option): option is WidgetPresetOption => (
        !!option
        && typeof option === "object"
        && typeof (option as WidgetPresetOption).value === "string"
        && typeof (option as WidgetPresetOption).label === "string"
      ));
  };

  const normalizeDependentConfig = (
    nextConfig: Record<string, unknown>,
    fields: Record<string, WidgetPresetField>,
    changedFieldId: string,
  ) => {
    const normalized = { ...nextConfig };
    for (const [candidateFieldId, candidateField] of Object.entries(fields)) {
      if (candidateField.ui?.options_from_field !== changedFieldId) continue;
      const validOptions = resolvePickerOptions(candidateFieldId, candidateField, fields, normalized);
      const currentValue = String(normalized[candidateFieldId] ?? "");
      if (!currentValue) continue;
      if (validOptions.some((option) => option.value === currentValue)) continue;
      normalized[candidateFieldId] = candidateField.default ?? "";
    }
    return normalized;
  };

  const runPreview = async () => {
    if (!selectedPreset || !selectedBotId) return;
    setPreviewState((prev) => ({ ...prev, running: true, error: null, envelope: null }));
    setPinSuccess(false);
    setPinError(null);
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

  const canAutoPreview = useMemo(() => {
    if (!selectedPreset || !selectedBotId) return false;
    return requiredFields.every((fieldId) => {
      const value = config[fieldId];
      if (typeof value === "boolean") return true;
      return value !== undefined && value !== null && String(value).trim() !== "";
    });
  }, [config, requiredFields, selectedBotId, selectedPreset]);

  const previewSignature = useMemo(
    () => JSON.stringify({
      presetId: selectedPreset?.id ?? null,
      botId: selectedBotId || null,
      channelId: scopeChannelId ?? null,
      config,
    }),
    [config, scopeChannelId, selectedBotId, selectedPreset?.id],
  );
  const lastAutoPreviewSignatureRef = useRef("");

  useEffect(() => {
    if (!canAutoPreview) return;
    if (previewState.running) return;
    if (previewSignature === lastAutoPreviewSignatureRef.current) return;
    const timer = window.setTimeout(() => {
      lastAutoPreviewSignatureRef.current = previewSignature;
      void runPreview();
    }, 250);
    return () => window.clearTimeout(timer);
  }, [canAutoPreview, previewSignature, previewState.running]);

  const pinDisabled = mode !== "pin" || !selectedPreset || !selectedBotId || !previewState.envelope || pinning;
  const handlePin = async () => {
    if (!selectedPreset || pinDisabled) return;
    setPinning(true);
    setPinError(null);
    try {
      const created = await pinPreset(selectedPreset.id, {
        config: previewState.config,
        source_bot_id: selectedBotId,
        source_channel_id: scopeChannelId ?? null,
        display_label: selectedEntityLabel,
      });
      setPinSuccess(true);
      onPinCreated?.(created.id);
    } catch (err) {
      setPinError(err instanceof Error ? err.message : "Failed to pin preset");
    } finally {
      setPinning(false);
    }
  };

  const builder = layout === "builder";

  return (
    <div className={builder ? "flex h-full min-h-0 min-w-0 flex-col overflow-x-hidden" : "flex flex-col gap-3 p-3"}>
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
          ? "flex min-h-0 min-w-0 flex-1 flex-col gap-6 overflow-x-hidden px-5 pb-5 xl:grid xl:grid-cols-[260px_minmax(0,1fr)] 2xl:grid-cols-[260px_360px_minmax(0,1fr)]"
          : "grid gap-3 lg:grid-cols-[240px_minmax(0,1fr)]"}
      >
        <section className={builder ? "relative z-20 min-w-0 shrink-0 overflow-hidden bg-transparent xl:min-h-0" : "min-h-0 border border-surface-border bg-surface"}>
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
          <div className={builder ? "space-y-1 xl:max-h-full xl:overflow-auto" : "max-h-full space-y-1 overflow-auto p-2"}>
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
                      ? "relative z-10 w-full px-3 py-3 text-left transition-colors"
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

        <section className={builder ? "relative min-w-0 overflow-hidden bg-transparent xl:min-h-0" : "min-h-0 rounded-xl border border-surface-border bg-surface"}>
          {!selectedPreset ? (
            <div className="flex h-full min-h-[220px] items-center justify-center px-6 text-center text-[12px] text-text-muted">
              Select a preset to configure it.
            </div>
          ) : (
            <div className="flex min-w-0 flex-col 2xl:h-full 2xl:min-h-0">
              <div className={builder ? "px-1 py-2" : "border-b border-surface-border px-4 py-3"}>
                <div className="flex flex-col gap-4 2xl:flex-row 2xl:items-start 2xl:justify-between">
                  <div className="min-w-0">
                    <div className="text-[15px] font-semibold text-text">{selectedPreset.name}</div>
                    <div className="mt-1 text-[11px] text-text-muted">{selectedPreset.description}</div>
                  </div>
                  <div className="w-full 2xl:max-w-[240px]">
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

              <div className={builder ? "min-w-0 px-1 py-4 2xl:flex-1 2xl:overflow-auto" : "flex-1 overflow-auto p-4"}>
                <div className="grid gap-3">
                  {Object.entries(selectedPreset.binding_schema.properties ?? {}).map(([fieldId, field]) => (
                    <PresetField
                      key={fieldId}
                      fieldId={fieldId}
                      field={field}
                      value={config[fieldId]}
                      options={resolvePickerOptions(fieldId, field, bindingFields)}
                      loading={sourceLoading[field.ui?.source ?? ""] ?? false}
                      pickerError={field.ui?.source ? sourceErrors[field.ui.source] : undefined}
                      placeholder={fieldId === "entity_id" ? "Search entities..." : "Search options..."}
                      onChange={(next) => {
                        setConfig((prev) => {
                          const nextConfig = { ...prev, [fieldId]: next };
                          return normalizeDependentConfig(nextConfig, bindingFields, fieldId);
                        });
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
                {pinError && (
                  <div className="mt-4 rounded-md bg-danger/10 px-3 py-2 text-[12px] text-danger">
                    {pinError}
                  </div>
                )}
              </div>

              <div className={builder ? "px-1 py-3" : "border-t border-surface-border px-4 py-3"}>
                <div className="flex flex-wrap items-center gap-2">
                  {!builder && (
                    <button
                      type="button"
                      onClick={runPreview}
                      disabled={!selectedBotId || previewState.running}
                      className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
                    >
                      {previewState.running ? <Loader2 size={13} className="animate-spin" /> : <Home size={13} />}
                      Run preview
                    </button>
                  )}
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
          <section className={builder ? "relative min-w-0 overflow-hidden bg-transparent xl:col-span-2 2xl:col-span-1 2xl:min-h-0" : "min-h-0 rounded-xl border border-surface-border bg-surface"}>
            <div className={builder ? "px-1 py-2" : "border-b border-surface-border px-4 py-3"}>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">
                Preview
              </div>
              <div className="mt-1 text-[11px] text-text-muted">
                Confirm the widget before pinning it onto the dashboard.
              </div>
            </div>
            <div className={builder ? "flex min-h-[180px] min-w-0 flex-col overflow-x-hidden px-1 py-4 2xl:h-full 2xl:overflow-auto" : "flex h-full min-h-[320px] flex-col overflow-auto p-4"}>
              {previewState.running ? (
                <div className="flex flex-1 items-center justify-center text-[12px] text-text-muted">
                  <Loader2 size={16} className="mr-2 animate-spin" />
                  Rendering preview…
                </div>
              ) : previewState.envelope ? (
                <div className="min-h-0 min-w-0 overflow-x-hidden bg-surface-overlay/10 p-3">
                  <RichToolResult
                    envelope={previewState.envelope}
                    channelId={scopeChannelId ?? undefined}
                    botId={selectedBotId || undefined}
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
  pickerError,
  placeholder,
  onChange,
}: {
  fieldId: string;
  field: WidgetPresetField;
  value: unknown;
  options: WidgetPresetOption[];
  loading: boolean;
  pickerError?: string;
  placeholder?: string;
  onChange: (next: unknown) => void;
}) {
  const control = field.ui?.control;

  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
        {field.title ?? fieldId}
      </span>
      {control === "picker" ? (
        pickerError ? (
          <input
            value={typeof value === "string" ? value : ""}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Enter id manually…"
            className="w-full min-w-0 rounded-md border border-surface-border bg-input px-2.5 py-2 text-[12px] text-text outline-none focus:border-accent/50"
          />
        ) : (
          <OptionPicker
            value={typeof value === "string" ? value : ""}
            options={options}
            loading={loading}
            placeholder={placeholder ?? "Select…"}
            onChange={onChange}
          />
        )
      ) : field.type === "boolean" ? (
        <button
          type="button"
          onClick={() => onChange(!value)}
          className={[
            "inline-flex w-full min-w-0 items-center justify-between rounded-md border px-3 py-2 text-[12px]",
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
          className="w-full min-w-0 rounded-md border border-surface-border bg-input px-2.5 py-2 text-[12px] text-text outline-none focus:border-accent/50"
        />
      )}
      {field.description && control !== "boolean" && (
        <span className="text-[10px] text-text-dim">{field.description}</span>
      )}
      {pickerError && (
        <span className="text-[10px] text-danger">
          Picker unavailable for this field: {pickerError}
        </span>
      )}
    </label>
  );
}

function OptionPicker({
  value,
  options,
  loading,
  placeholder,
  onChange,
}: {
  value: string;
  options: WidgetPresetOption[];
  loading: boolean;
  placeholder: string;
  onChange: (next: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 });

  const selected = useMemo(
    () => options.find((option) => option.value === value) ?? null,
    [options, value],
  );

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return options;
    return options.filter((option) => (
      option.label.toLowerCase().includes(term)
      || (option.description ?? "").toLowerCase().includes(term)
      || (option.group ?? "").toLowerCase().includes(term)
    ));
  }, [options, search]);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (
        triggerRef.current && !triggerRef.current.contains(event.target as Node)
        && dropdownRef.current && !dropdownRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  const openDropdown = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left, width: Math.max(rect.width, 320) });
    }
    setOpen((prev) => !prev);
  };

  const pick = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
    setSearch("");
  };

  return (
    <div className="relative min-w-0">
      <button
        ref={triggerRef}
        type="button"
        onClick={openDropdown}
        className={`flex w-full min-w-0 items-center gap-2 rounded-md border px-3 py-2 text-left transition-colors ${
          open
            ? "border-accent bg-surface"
            : "border-surface-border bg-input hover:border-accent/50"
        }`}
      >
        <div className="min-w-0 flex-1">
          <div className={`truncate text-[12px] ${selected ? "text-text" : "text-text-dim"}`}>
            {selected ? selected.label : (loading ? "Loading…" : placeholder)}
          </div>
          {selected?.group && (
            <div className="truncate text-[10px] text-text-dim">
              {selected.group}
            </div>
          )}
        </div>
        <ChevronDown size={12} className="shrink-0 text-text-dim" />
      </button>

      {open && ReactDOM.createPortal(
        <div
          ref={dropdownRef}
          className="fixed z-[10060] flex max-h-[360px] flex-col overflow-hidden rounded-lg border border-surface-border bg-surface shadow-xl"
          style={{ top: pos.top, left: pos.left, width: pos.width, maxWidth: "calc(100vw - 24px)" }}
        >
          <div className="border-b border-surface-border p-2">
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={placeholder}
              autoFocus
              className="w-full rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-xs text-text outline-none focus:border-accent/40"
            />
          </div>
          <div className="overflow-y-auto">
            <button
              type="button"
              onClick={() => pick("")}
              className={`flex w-full items-center gap-2 px-3 py-2 text-left transition-colors ${
                !value ? "bg-accent/10 text-accent" : "text-text-dim hover:bg-surface-raised"
              }`}
            >
              <span className="text-xs italic">None</span>
            </button>
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-center text-[11px] text-text-dim">No matches</div>
            ) : (
              filtered.map((option) => {
                const isSelected = option.value === value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => pick(option.value)}
                    className={`flex w-full items-start gap-2 px-3 py-2 text-left transition-colors ${
                      isSelected ? "bg-accent/10" : "hover:bg-surface-raised"
                    }`}
                  >
                    <span className={`mt-0.5 h-2 w-2 rounded-full ${isSelected ? "bg-accent" : "bg-surface-border"}`} />
                    <div className="min-w-0 flex-1">
                      <div className={`truncate text-xs font-medium ${isSelected ? "text-accent" : "text-text"}`}>
                        {option.label}
                      </div>
                      {(option.group || option.description) && (
                        <div className="truncate text-[10px] text-text-dim">
                          {[option.group, option.description].filter(Boolean).join(" · ")}
                        </div>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
