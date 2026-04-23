import { useEffect, useState } from "react";
import type { ToolResultEnvelope } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { PreviewCard, useLastCommittedValue, useNativeEnvelopeState } from "./shared";

export function NotesWidget({
  envelope,
  dashboardPinId,
  channelId,
  t,
}: {
  envelope: ToolResultEnvelope;
  dashboardPinId?: string;
  channelId?: string;
  t: ThemeTokens;
}) {
  const { currentPayload, dispatchNativeAction } = useNativeEnvelopeState(
    envelope,
    "core/notes_native",
    channelId,
    dashboardPinId,
  );
  const body = String(currentPayload.state?.body ?? "");
  const updatedAt = String(currentPayload.state?.updated_at ?? "");
  const [draft, setDraft] = useState(body);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastCommittedBodyRef = useLastCommittedValue(body);

  useEffect(() => {
    const previousCommitted = lastCommittedBodyRef.current;
    const wasDirty = draft !== previousCommitted;
    lastCommittedBodyRef.current = body;
    if (!wasDirty) {
      setDraft(body);
    }
  }, [body, draft, lastCommittedBodyRef]);

  const widgetInstanceId = currentPayload.widget_instance_id;
  if (!widgetInstanceId) {
    return <PreviewCard title="Notes" description="Persistent scratchpad for quick context, reminders, and bot handoff notes." t={t} />;
  }

  const save = async (nextBody: string) => {
    const normalized = nextBody.replace(/\r\n/g, "\n");
    if (normalized === lastCommittedBodyRef.current) return;
    setSaving(true);
    setError(null);
    try {
      await dispatchNativeAction("replace_body", { body: normalized });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (!widgetInstanceId || draft === lastCommittedBodyRef.current) return;
    const handle = window.setTimeout(() => {
      void save(draft);
    }, 500);
    return () => window.clearTimeout(handle);
  }, [draft, widgetInstanceId, lastCommittedBodyRef]);

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
          if (draft !== lastCommittedBodyRef.current) void save(draft);
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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", borderTop: `1px solid ${t.surfaceBorder}`, paddingTop: 6, fontSize: 11, color: error ? t.danger : t.textDim }}>
        <span>
          {error
            ? error
            : saving
              ? "Saving..."
              : updatedAt
                ? `Updated ${new Date(updatedAt).toLocaleString()}`
                : "Autosaves after you stop typing."}
        </span>
        <span style={{ color: t.textDim }}>Markdown ok</span>
      </div>
    </div>
  );
}
