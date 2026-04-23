import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { WidgetConfigSchema, WidgetContract, WidgetLayoutHints, WidgetPresentation } from "@/src/types/api";

export interface WidgetPresetFieldUi {
  control?: string;
  source?: string;
  options_from_field?: string;
  options_from_meta?: string;
}

export interface WidgetPresetField {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  ui?: WidgetPresetFieldUi;
}

export interface WidgetPresetBindingSchema {
  type?: string;
  required?: string[];
  properties?: Record<string, WidgetPresetField>;
}

export interface WidgetPresetBindingSource {
  tool?: string;
  args?: Record<string, unknown>;
  transform?: string;
  params?: Record<string, unknown>;
}

export interface WidgetPresetDependencyContract {
  tool_family?: {
    id: string;
    label: string;
    tools: string[];
  } | null;
  tools: string[];
}

export interface WidgetPreset {
  id: string;
  integration_id: string | null;
  name: string;
  description?: string | null;
  icon?: string | null;
  tool_name?: string | null;
  binding_schema: WidgetPresetBindingSchema;
  binding_sources: Record<string, WidgetPresetBindingSource>;
  default_config: Record<string, unknown>;
  config_schema?: WidgetConfigSchema | null;
  widget_contract?: WidgetContract | null;
  widget_presentation?: WidgetPresentation | null;
  layout_hints?: WidgetLayoutHints | null;
  dependency_contract?: WidgetPresetDependencyContract | null;
  resolved_binding_options?: Record<string, WidgetPresetOption[]>;
  binding_source_errors?: Record<string, string>;
}

export interface WidgetPresetOption {
  value: string;
  label: string;
  description?: string | null;
  group?: string | null;
  meta?: Record<string, unknown> | null;
}

export interface WidgetPresetPreviewResponse {
  ok: boolean;
  envelope: {
    content_type: string;
    body: string;
    display: string;
    display_label?: string | null;
    refreshable: boolean;
    refresh_interval_seconds?: number | null;
    source_bot_id?: string | null;
    source_channel_id?: string | null;
  } | null;
  widget_contract?: WidgetContract | null;
  config_schema?: WidgetConfigSchema | null;
  errors: Array<{ phase: string; message: string; line?: number | null; severity?: string }>;
  config: Record<string, unknown>;
}

export function useWidgetPresets(sourceBotId?: string | null, sourceChannelId?: string | null) {
  return useQuery({
    queryKey: ["widget-presets", sourceBotId ?? null, sourceChannelId ?? null],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (sourceBotId) params.set("source_bot_id", sourceBotId);
      if (sourceChannelId) params.set("source_channel_id", sourceChannelId);
      if (sourceBotId || sourceChannelId) params.set("include_binding_options", "true");
      const query = params.toString();
      const resp = await apiFetch<{ presets: WidgetPreset[] }>(
        `/api/v1/widgets/presets${query ? `?${query}` : ""}`,
      );
      return resp.presets ?? [];
    },
    staleTime: 60_000,
  });
}

export function getWidgetPresetBindingOptions(
  presetId: string,
  sourceId: string,
  body: {
    source_bot_id?: string | null;
    source_channel_id?: string | null;
  },
) {
  const params = new URLSearchParams();
  params.set("source_id", sourceId);
  if (body.source_bot_id) {
    params.set("source_bot_id", body.source_bot_id);
  }
  if (body.source_channel_id) {
    params.set("source_channel_id", body.source_channel_id);
  }
  return apiFetch<{ options: WidgetPresetOption[] }>(
    `/api/v1/widgets/presets/${encodeURIComponent(presetId)}/binding-options?${params.toString()}`,
  );
}

export function previewWidgetPreset(
  presetId: string,
  body: {
    config?: Record<string, unknown> | null;
    source_bot_id?: string | null;
    source_channel_id?: string | null;
  },
) {
  return apiFetch<WidgetPresetPreviewResponse>(
    `/api/v1/widgets/presets/${encodeURIComponent(presetId)}/preview`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}
