import { useEffect, useMemo, useRef, useState } from "react";
import type { ThemeTokens } from "@/src/theme/tokens";
import type { ToolResultEnvelope } from "@/src/types/api";
import { apiFetch } from "@/src/api/client";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { usePinnedWidgetsStore } from "@/src/stores/pinnedWidgets";
import type { HostSurface, WidgetLayout } from "../InteractiveHtmlRenderer";

export interface NativeAppRendererProps {
  envelope: ToolResultEnvelope;
  sessionId?: string;
  dashboardPinId?: string;
  channelId?: string;
  gridDimensions?: { width: number; height: number };
  layout?: WidgetLayout;
  hostSurface?: HostSurface;
  t: ThemeTokens;
}

export interface NativeWidgetAction {
  id: string;
  description?: string;
}

export interface NativeTodoItem {
  id: string;
  title: string;
  done: boolean;
  position: number;
  created_at?: string;
  updated_at?: string;
}

export interface NativeWidgetPayload {
  widget_ref?: string;
  widget_instance_id?: string;
  display_label?: string;
  state?: Record<string, unknown>;
  config?: Record<string, unknown>;
  actions?: NativeWidgetAction[];
}

export function parsePayload(envelope: ToolResultEnvelope): NativeWidgetPayload {
  const body = envelope.body;
  if (!body) return {};
  if (typeof body === "string") {
    try {
      return JSON.parse(body) as NativeWidgetPayload;
    } catch {
      return {};
    }
  }
  return body as NativeWidgetPayload;
}

export function parseIso(value: unknown): number {
  if (typeof value !== "string" || !value) return 0;
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : 0;
}

export function PreviewCard({
  title,
  description,
  t,
}: {
  title: string;
  description: string;
  t: ThemeTokens;
}) {
  return (
    <div
      style={{
        border: `1px solid ${t.surfaceBorder}`,
        background: t.surface,
        borderRadius: 12,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ fontWeight: 600, color: t.text }}>{title}</div>
      <div style={{ fontSize: 13, color: t.textMuted }}>{description}</div>
      <div style={{ fontSize: 12, color: t.textDim }}>Pin this widget to create its stateful instance.</div>
    </div>
  );
}

export function useNativeEnvelopeState(
  envelope: ToolResultEnvelope,
  widgetRefFallback: string,
  channelId?: string,
  dashboardPinId?: string,
) {
  const dashboardBroadcast = useDashboardPinsStore((s) => s.broadcastEnvelope);
  const channelBroadcast = usePinnedWidgetsStore((s) => s.broadcastEnvelope);
  const [currentEnvelope, setCurrentEnvelope] = useState(envelope);
  const currentPayload = useMemo(() => parsePayload(currentEnvelope), [currentEnvelope]);

  useEffect(() => {
    const incoming = parsePayload(envelope);
    const current = parsePayload(currentEnvelope);
    const incomingBody = JSON.stringify(incoming.state ?? {});
    const currentBody = JSON.stringify(current.state ?? {});
    const incomingUpdatedAt = parseIso((incoming.state ?? {}).updated_at);
    const currentUpdatedAt = parseIso((current.state ?? {}).updated_at);
    if (incomingUpdatedAt < currentUpdatedAt) return;
    if (incomingUpdatedAt === currentUpdatedAt && incomingBody === currentBody) return;
    setCurrentEnvelope(envelope);
  }, [envelope, currentEnvelope]);

  async function dispatchNativeAction(
    action: string,
    args: Record<string, unknown>,
  ): Promise<ToolResultEnvelope> {
    const widgetInstanceId = currentPayload.widget_instance_id;
    const resp = await apiFetch<{ ok: boolean; envelope?: ToolResultEnvelope | null; error?: string | null }>(
      "/api/v1/widget-actions",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dispatch: "native_widget",
          dashboard_pin_id: dashboardPinId,
          widget_instance_id: widgetInstanceId,
          action,
          args,
        }),
      },
    );
    if (!resp.ok || !resp.envelope) {
      throw new Error(resp.error ?? "Action failed");
    }
    setCurrentEnvelope(resp.envelope);
    const widgetRef = currentPayload.widget_ref || widgetRefFallback;
    if (dashboardPinId) dashboardBroadcast(widgetRef, resp.envelope);
    if (channelId) channelBroadcast(channelId, widgetRef, resp.envelope);
    return resp.envelope;
  }

  return { currentEnvelope, currentPayload, dispatchNativeAction };
}

export function useLastCommittedValue(value: string) {
  const ref = useRef(value);
  return ref;
}
