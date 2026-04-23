import { useEffect, useState } from "react";
import { PreviewCard, useLastCommittedValue, useNativeEnvelopeState, type NativeAppRendererProps } from "./shared";
import { deriveNativeWidgetLayoutProfile } from "./nativeWidgetLayout";

export function NotesWidget({
  envelope,
  dashboardPinId,
  channelId,
  gridDimensions,
  layout,
  t,
}: NativeAppRendererProps) {
  const profile = deriveNativeWidgetLayoutProfile(layout, gridDimensions, {
    compactMaxWidth: 360,
    compactMaxHeight: 180,
    wideMinWidth: 620,
    wideMinHeight: 220,
    tallMinHeight: 320,
  });
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

  const statusLabel = error
    ? error
    : saving
      ? "Saving..."
      : updatedAt
        ? `Updated ${new Date(updatedAt).toLocaleString()}`
        : "Autosaves after you stop typing.";
  const compactBarMode = (layout === "header" || layout === "chip") && profile.height > 0 && profile.height <= 96;
  const editorMinHeight = compactBarMode ? 0 : profile.tall || profile.wide ? 260 : 180;
  const showFooter = !compactBarMode;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: showFooter ? 10 : 0,
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
          minHeight: compactBarMode ? 0 : profile.compact ? 120 : editorMinHeight,
          flex: 1,
          width: "100%",
          resize: profile.compact ? "none" : "vertical",
          border: "none",
          outline: "none",
          background: "transparent",
          color: t.text,
          padding: 0,
          fontSize: 13,
          lineHeight: compactBarMode ? 1.45 : 1.7,
        }}
      />
      {showFooter ? (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            borderTop: `1px solid ${t.surfaceBorder}`,
            paddingTop: 6,
            fontSize: 11,
            color: error ? t.danger : t.textDim,
          }}
        >
          <span>{statusLabel}</span>
          <span style={{ color: t.textDim }}>Markdown ok</span>
        </div>
      ) : null}
    </div>
  );
}
