import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface WidgetPresetFieldUi {
  control?: string;
  source?: string;
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
  errors: Array<{ phase: string; message: string; line?: number | null; severity?: string }>;
  config: Record<string, unknown>;
}

export function useWidgetPresets() {
  return useQuery({
    queryKey: ["widget-presets"],
    queryFn: async () => {
      const resp = await apiFetch<{ presets: WidgetPreset[] }>("/api/v1/widgets/presets");
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
  return apiFetch<{ options: WidgetPresetOption[] }>(
    `/api/v1/widgets/presets/${encodeURIComponent(presetId)}/binding-options`,
    {
      method: "POST",
      body: JSON.stringify({ ...body, source_id: sourceId }),
    },
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
