import { useEffect, useMemo, useState } from "react";
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
  const [editing, setEditing] = useState(false);
  const currentPayload = useMemo(() => parsePayload(currentEnvelope), [currentEnvelope]);
  const body = String(currentPayload.state?.body ?? "");
  const createdAt = String(currentPayload.state?.created_at ?? "");
  const updatedAt = String(currentPayload.state?.updated_at ?? "");
  const [draft, setDraft] = useState(body);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCurrentEnvelope(envelope);
  }, [envelope]);

  useEffect(() => {
    if (!editing) setDraft(body);
  }, [body, editing]);

  const widgetInstanceId = currentPayload.widget_instance_id;
  if (!widgetInstanceId) {
    return <PreviewCard title="Notes" description="Persistent scratchpad for quick context, reminders, and bot handoff notes." t={t} />;
  }

  const save = async (nextBody: string) => {
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
            args: { body: nextBody },
          }),
        },
      );
      if (!resp.ok || !resp.envelope) {
        throw new Error(resp.error ?? "Save failed");
      }
      setCurrentEnvelope(resp.envelope);
      setEditing(false);
      if (dashboardPinId) dashboardBroadcast(currentPayload.widget_ref || "core/notes_native", resp.envelope);
      if (channelId) channelBroadcast(channelId, currentPayload.widget_ref || "core/notes_native", resp.envelope);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        minHeight: "100%",
      }}
    >
      {editing ? (
        <>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            style={{
              minHeight: 180,
              width: "100%",
              resize: "vertical",
              borderRadius: 10,
              border: `1px solid ${t.inputBorder}`,
              background: t.inputBg,
              color: t.text,
              padding: 12,
              fontSize: 13,
              lineHeight: 1.6,
            }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <div style={{ fontSize: 12, color: t.textDim }}>Markdown/plain text supported.</div>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" onClick={() => { setDraft(body); setEditing(false); }} style={buttonStyle(t, "subtle")} disabled={saving}>
                Cancel
              </button>
              <button type="button" onClick={() => save(draft)} style={buttonStyle(t, "primary")} disabled={saving}>
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </>
      ) : (
        <>
          <div
            style={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              minHeight: 120,
              color: body.trim() ? t.text : t.textMuted,
              fontSize: 13,
              lineHeight: 1.65,
            }}
          >
            {body.trim() || "No notes yet. Use this pinned scratchpad for reminders, context, or handoff notes."}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 12, color: t.textDim }}>
              <span>{updatedAt ? `Updated ${new Date(updatedAt).toLocaleString()}` : "Not saved yet"}</span>
              <span>{createdAt ? `Created ${new Date(createdAt).toLocaleString()}` : ""}</span>
            </div>
            <button type="button" onClick={() => setEditing(true)} style={buttonStyle(t, "subtle")}>
              Edit note
            </button>
          </div>
        </>
      )}
      {error ? <div style={{ fontSize: 12, color: t.danger }}>{error}</div> : null}
    </div>
  );
}

function buttonStyle(t: ThemeTokens, variant: "primary" | "subtle") {
  if (variant === "primary") {
    return {
      borderRadius: 9,
      border: `1px solid ${t.accentBorder}`,
      background: t.accent,
      color: t.text,
      padding: "7px 12px",
      fontSize: 12,
      fontWeight: 600,
      cursor: "pointer",
    } as const;
  }
  return {
    borderRadius: 9,
    border: `1px solid ${t.surfaceBorder}`,
    background: t.surfaceRaised,
    color: t.text,
    padding: "7px 12px",
    fontSize: 12,
    fontWeight: 500,
    cursor: "pointer",
  } as const;
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
