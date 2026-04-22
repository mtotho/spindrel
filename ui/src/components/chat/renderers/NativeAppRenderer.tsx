import { useEffect, useMemo, useRef, useState } from "react";
import type { ThemeTokens } from "@/src/theme/tokens";
import type { ToolResultEnvelope } from "@/src/types/api";
import { apiFetch } from "@/src/api/client";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { usePinnedWidgetsStore } from "@/src/stores/pinnedWidgets";

interface NativeAppRendererProps {
  envelope: ToolResultEnvelope;
  dashboardPinId?: string;
  channelId?: string;
  t: ThemeTokens;
}

interface NativeWidgetPayload {
  widget_ref?: string;
  widget_instance_id?: string;
  display_label?: string;
  state?: Record<string, unknown>;
  config?: Record<string, unknown>;
  actions?: Array<{ id: string; description?: string }>;
}

function parsePayload(envelope: ToolResultEnvelope): NativeWidgetPayload {
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

function PreviewCard({
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

function NativeNotesWidget({
  envelope,
  payload,
  dashboardPinId,
  channelId,
  t,
}: {
  envelope: ToolResultEnvelope;
  payload: NativeWidgetPayload;
  dashboardPinId?: string;
  channelId?: string;
  t: ThemeTokens;
}) {
  const dashboardBroadcast = useDashboardPinsStore((s) => s.broadcastEnvelope);
  const channelBroadcast = usePinnedWidgetsStore((s) => s.broadcastEnvelope);
  const [currentEnvelope, setCurrentEnvelope] = useState(envelope);
  const currentPayload = useMemo(() => parsePayload(currentEnvelope), [currentEnvelope]);
  const body = String(currentPayload.state?.body ?? "");
  const updatedAt = String(currentPayload.state?.updated_at ?? "");
  const [draft, setDraft] = useState(body);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingSaveRef = useRef<string | null>(null);

  useEffect(() => {
    setCurrentEnvelope(envelope);
  }, [envelope]);

  useEffect(() => {
    setDraft(body);
  }, [body]);

  const widgetInstanceId = currentPayload.widget_instance_id;
  if (!widgetInstanceId) {
    return <PreviewCard title="Notes" description="Persistent scratchpad for quick context, reminders, and bot handoff notes." t={t} />;
  }

  const save = async (nextBody: string) => {
    const normalized = nextBody.replace(/\r\n/g, "\n");
    if (normalized === body || pendingSaveRef.current === normalized) return;
    pendingSaveRef.current = normalized;
    setSaving(true);
    setError(null);
    try {
      const resp = await apiFetch<{ ok: boolean; envelope?: ToolResultEnvelope | null; error?: string | null }>(
        "/api/v1/widget-actions",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dispatch: "native_widget",
            dashboard_pin_id: dashboardPinId,
            widget_instance_id: widgetInstanceId,
            action: "replace_body",
            args: { body: normalized },
          }),
        },
      );
      if (!resp.ok || !resp.envelope) {
        throw new Error(resp.error ?? "Save failed");
      }
      setCurrentEnvelope(resp.envelope);
      if (dashboardPinId) dashboardBroadcast(currentPayload.widget_ref || "core/notes_native", resp.envelope);
      if (channelId) channelBroadcast(channelId, currentPayload.widget_ref || "core/notes_native", resp.envelope);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      pendingSaveRef.current = null;
      setSaving(false);
    }
  };

  useEffect(() => {
    if (!widgetInstanceId || draft === body) return;
    const handle = window.setTimeout(() => {
      void save(draft);
    }, 500);
    return () => window.clearTimeout(handle);
  }, [draft, body, widgetInstanceId]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: "100%",
      }}
    >
      <textarea
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          if (error) setError(null);
        }}
        onBlur={() => {
          if (draft !== body) void save(draft);
        }}
        placeholder="No notes yet. Use this pinned scratchpad for reminders, context, or handoff notes."
        style={{
          minHeight: 180,
          flex: 1,
          width: "100%",
          resize: "none",
          border: "none",
          outline: "none",
          background: "transparent",
          color: t.text,
          padding: 0,
          fontSize: 13,
          lineHeight: 1.7,
        }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 12, color: error ? t.danger : t.textDim }}>
        <span>
          {error
            ? error
            : saving
              ? "Saving..."
              : updatedAt
                ? `Updated ${new Date(updatedAt).toLocaleString()}`
                : "Autosaves after you stop typing."}
        </span>
        <span style={{ color: t.textDim }}>
          Plain text or markdown
        </span>
      </div>
    </div>
  );
}

export function NativeAppRenderer({
  envelope,
  dashboardPinId,
  channelId,
  t,
}: NativeAppRendererProps) {
  const payload = useMemo(() => parsePayload(envelope), [envelope]);
  switch (payload.widget_ref) {
    case "core/notes_native":
      return (
        <NativeNotesWidget
          envelope={envelope}
          payload={payload}
          dashboardPinId={dashboardPinId}
          channelId={channelId}
          t={t}
        />
      );
    default:
      return (
        <PreviewCard
          title={payload.display_label || "Native widget"}
          description={`No renderer registered for ${payload.widget_ref || "unknown widget"}.`}
          t={t}
        />
      );
  }
}
