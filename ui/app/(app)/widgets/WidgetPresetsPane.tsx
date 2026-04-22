import { useEffect, useMemo, useState } from "react";
import { Check, Home, Loader2, Pin, SlidersHorizontal } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannel } from "@/src/api/hooks/useChannels";
import {
  getWidgetPresetBindingOptions,
  previewWidgetPreset,
  useWidgetPresets,
  type WidgetPreset,
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

export function WidgetPresetsPane({
  mode,
  query = "",
  scopeChannelId,
  onPinCreated,
}: {
  mode: "pin" | "browse";
  query?: string;
  scopeChannelId?: string | null;
  onPinCreated?: (pinId: string) => void;
}) {
  const t = useThemeTokens();
  const { data: presets, isLoading, error } = useWidgetPresets();
  const { data: bots } = useBots();
  const { data: scopedChannel } = useChannel(scopeChannelId ?? undefined);
  const pinPreset = useDashboardPinsStore((s) => s.pinPreset);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = (presets ?? []).filter((preset) => {
      if (!q) return true;
      return [
        preset.name,
        preset.description ?? "",
        preset.integration_id ?? "",
      ].some((value) => value.toLowerCase().includes(q));
    });
    return rows;
  }, [presets, query]);

  const [selectedPresetId, setSelectedPresetId] = useState<string>("");
  const selectedPreset = filtered.find((preset) => preset.id === selectedPresetId) ?? filtered[0] ?? null;

  useEffect(() => {
    if (!selectedPresetId && filtered[0]?.id) setSelectedPresetId(filtered[0].id);
    if (selectedPresetId && !filtered.some((preset) => preset.id === selectedPresetId)) {
      setSelectedPresetId(filtered[0]?.id ?? "");
    }
  }, [filtered, selectedPresetId]);

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
    if (!selectedPreset) {
      setSourceOptions({});
      setSourceLoading({});
      setSourceError(null);
      return;
    }
    if (!selectedBotId) {
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
        setPreviewState({ running: false, error: first, envelope: null, config: resp.config ?? {} });
        return;
      }
      setPreviewState({
        running: false,
        error: null,
        envelope: resp.envelope as unknown as ToolResultEnvelope,
        config: resp.config ?? {},
      });
    } catch (err) {
      setPreviewState({
        running: false,
        error: err instanceof Error ? err.message : "Preview failed",
        envelope: null,
        config,
      });
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

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-start gap-2 rounded-md bg-accent/5 px-3 py-2 text-[11px] text-text-muted">
        <Home size={12} className="mt-0.5 shrink-0 text-accent/70" />
        <span>
          Presets are ready-made widgets with a guided binding flow. Pick a preset, bind it to a Home Assistant entity,
          preview it, then pin it without touching raw tool args or YAML.
        </span>
      </div>

      <div className="grid gap-3 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div className="rounded-md bg-surface p-2">
          <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-text-dim">
            Presets
          </div>
          {isLoading && (
            <div className="space-y-2 p-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-10 animate-pulse rounded-md bg-surface-overlay/40" />
              ))}
            </div>
          )}
          {error && (
            <p className="px-2 py-4 text-[12px] text-danger">
              Failed to load presets: {(error as Error).message}
            </p>
          )}
          {!isLoading && !error && filtered.length === 0 && (
            <p className="px-2 py-4 text-[12px] text-text-muted">No presets match the current filter.</p>
          )}
          <div className="space-y-1">
            {filtered.map((preset) => {
              const active = preset.id === selectedPreset?.id;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => setSelectedPresetId(preset.id)}
                  className={[
                    "w-full rounded-md px-2.5 py-2 text-left transition-colors",
                    active ? "bg-accent/10 text-text" : "hover:bg-surface-overlay text-text-muted",
                  ].join(" ")}
                >
                  <div className="text-[12px] font-medium">{preset.name}</div>
                  <div className="mt-0.5 text-[10px] text-text-dim">{preset.description}</div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="rounded-md bg-surface p-3">
          {!selectedPreset ? (
            <div className="flex min-h-[220px] items-center justify-center text-[12px] text-text-muted">
              Select a preset to configure it.
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[14px] font-semibold text-text">{selectedPreset.name}</div>
                  <div className="mt-0.5 text-[11px] text-text-muted">{selectedPreset.description}</div>
                </div>
                <div className="min-w-[220px]">
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

              <div className="grid gap-3 md:grid-cols-2">
                {Object.entries(selectedPreset.binding_schema.properties ?? {}).map(([fieldId, field]) => {
                  const control = field.ui?.control;
                  const sourceId = field.ui?.source;
                  const value = config[fieldId];
                  return (
                    <label key={fieldId} className="flex flex-col gap-1.5">
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                        {field.title ?? fieldId}
                      </span>
                      {control === "picker" ? (
                        <select
                          value={typeof value === "string" ? value : ""}
                          onChange={(e) => setConfig((prev) => ({ ...prev, [fieldId]: e.target.value }))}
                          className="rounded-md border border-surface-border bg-input px-2.5 py-2 text-[12px] text-text outline-none focus:border-accent/50"
                        >
                          <option value="">
                            {sourceLoading[sourceId ?? ""] ? "Loading…" : "Select…"}
                          </option>
                          {(sourceOptions[sourceId ?? ""] ?? []).map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.group ? `${option.group} · ${option.label}` : option.label}
                            </option>
                          ))}
                        </select>
                      ) : field.type === "boolean" ? (
                        <button
                          type="button"
                          onClick={() => setConfig((prev) => ({ ...prev, [fieldId]: !prev[fieldId] }))}
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
                          onChange={(e) => setConfig((prev) => ({ ...prev, [fieldId]: e.target.value }))}
                          className="rounded-md border border-surface-border bg-input px-2.5 py-2 text-[12px] text-text outline-none focus:border-accent/50"
                        />
                      )}
                      {field.description && control !== "boolean" && (
                        <span className="text-[10px] text-text-dim">{field.description}</span>
                      )}
                    </label>
                  );
                })}
              </div>

              {sourceError && (
                <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12px] text-danger">
                  {sourceError}
                </div>
              )}

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={runPreview}
                  disabled={!selectedBotId || previewState.running}
                  className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:opacity-40"
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

              {previewState.error && (
                <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12px] text-danger">
                  {previewState.error}
                </div>
              )}

              <div className="min-h-[180px] rounded-md border border-surface-border bg-surface-overlay/20 p-3">
                {previewState.running && (
                  <span className="inline-flex items-center gap-1.5 text-[12px] text-text-muted">
                    <Loader2 size={12} className="animate-spin" /> Rendering…
                  </span>
                )}
                {!previewState.running && previewState.envelope && (
                  <RichToolResult envelope={previewState.envelope} dispatcher={NOOP_DISPATCHER} t={t} />
                )}
                {!previewState.running && !previewState.envelope && (
                  <span className="text-[12px] text-text-dim">
                    Run a preview to render this preset with the selected entity.
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
