/**
 * resolveToolEnvelope — the single source of truth for "given a tool call,
 * what envelope should render?"
 *
 * Priority, highest first:
 *   1. Tool-declared envelope. If the raw result is a JSON object with
 *      an `_envelope` key (the opt-in convention documented at
 *      `app/agent/tool_dispatch.py:132-150`), that's the authoritative
 *      answer — the tool picked the content type and body itself.
 *   2. Widget template. `previewWidgetForTool` runs the tool's registered
 *      widget YAML against the raw payload.
 *   3. Generic auto-render. `genericRenderWidget` auto-shapes arbitrary
 *      JSON into a components tree.
 *
 * Used by the dev panel (Recent tab) and any other surface that needs to
 * render a tool result without a persisted envelope.
 */
import type { ToolResultEnvelope } from "../../../types/api";
import {
  previewWidgetForTool,
  genericRenderWidget,
  type PreviewEnvelope,
} from "../../../api/hooks/useWidgetPackages";

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

/**
 * Widens a `PreviewEnvelope` (or a tool-declared `_envelope` object) into a
 * full `ToolResultEnvelope`. Preview-sourced envelopes are always full bodies
 * (`truncated=false`), so lazy-fetch fields stay null.
 */
export function adaptToToolResultEnvelope(
  src: PreviewEnvelope | Record<string, unknown>,
): ToolResultEnvelope {
  const rawBody = (src as { body?: unknown }).body;
  const body =
    rawBody == null
      ? null
      : typeof rawBody === "string"
        ? rawBody
        : JSON.stringify(rawBody);
  const plainBody = typeof rawBody === "string" ? rawBody : "";
  const displayRaw = (src as { display?: unknown }).display;
  const display: ToolResultEnvelope["display"] =
    displayRaw === "badge" || displayRaw === "panel" ? displayRaw : "inline";
  return {
    content_type: String((src as { content_type?: unknown }).content_type ?? "text/plain"),
    body,
    plain_body: plainBody,
    display,
    truncated: false,
    record_id: null,
    byte_size: body ? body.length : 0,
    widget_type: (src as { widget_type?: string }).widget_type,
    display_label: (src as { display_label?: string | null }).display_label ?? null,
    refreshable: Boolean((src as { refreshable?: boolean }).refreshable),
    refresh_interval_seconds:
      ((src as { refresh_interval_seconds?: number | null }).refresh_interval_seconds) ?? null,
    source_path: (src as { source_path?: string | null }).source_path ?? null,
    source_channel_id: (src as { source_channel_id?: string | null }).source_channel_id ?? null,
  };
}

export async function resolveToolEnvelope(input: {
  toolName: string;
  rawResult: unknown;
  widgetConfig?: Record<string, unknown> | null;
}): Promise<ToolResultEnvelope | null> {
  // 1. Tool-declared envelope — opt-in, tool-authored.
  if (isRecord(input.rawResult) && "_envelope" in input.rawResult) {
    const env = input.rawResult._envelope;
    if (isRecord(env) && env.content_type && env.body != null) {
      return adaptToToolResultEnvelope(env);
    }
  }

  // 2. Widget template (integration-authored YAML).
  try {
    const templated = await previewWidgetForTool({
      tool_name: input.toolName,
      sample_payload: isRecord(input.rawResult) ? input.rawResult : null,
      widget_config: input.widgetConfig ?? null,
    });
    if (templated.ok && templated.envelope) {
      return adaptToToolResultEnvelope(templated.envelope);
    }
  } catch {
    // fall through to generic
  }

  // 3. Generic auto-render.
  try {
    const generic = await genericRenderWidget({
      tool_name: input.toolName,
      raw_result: input.rawResult,
    });
    if (generic.ok && generic.envelope) {
      return adaptToToolResultEnvelope(generic.envelope);
    }
  } catch {
    return null;
  }

  return null;
}
