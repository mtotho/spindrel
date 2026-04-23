import { useEffect, useMemo, useState } from "react";
import { PreviewCard, useLastCommittedValue, useNativeEnvelopeState, type NativeAppRendererProps } from "./shared";
import { deriveNativeWidgetLayoutProfile } from "./nativeWidgetLayout";

function previewSnippet(body: string): string {
  const normalized = body.replace(/\s+/g, " ").trim();
  if (!normalized) return "No notes yet. Keep reminders, context, or handoff details here.";
  return normalized.length > 180 ? `${normalized.slice(0, 177)}...` : normalized;
}

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
  const [showCompactEditor, setShowCompactEditor] = useState(false);
  const lastCommittedBodyRef = useLastCommittedValue(body);

  useEffect(() => {
    const previousCommitted = lastCommittedBodyRef.current;
    const wasDirty = draft !== previousCommitted;
    lastCommittedBodyRef.current = body;
    if (!wasDirty) {
      setDraft(body);
    }
  }, [body, draft, lastCommittedBodyRef]);

  useEffect(() => {
    if (!profile.compact) {
      setShowCompactEditor(false);
    }
  }, [profile.compact]);

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
  const editorMinHeight = profile.tall || profile.wide ? 260 : 180;
  const summarySnippet = useMemo(() => previewSnippet(body), [body]);

  if (profile.compact && !showCompactEditor) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          minHeight: "100%",
        }}
      >
        <div
          style={{
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 12,
            background: t.surface,
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <div
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: t.textDim,
            }}
          >
            Scratchpad
          </div>
          <div style={{ color: t.text, fontSize: 13, lineHeight: 1.55 }}>
            {summarySnippet}
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: error ? t.danger : t.textDim }}>{statusLabel}</span>
          <button
            type="button"
            onClick={() => setShowCompactEditor(true)}
            style={{
              borderRadius: 999,
              border: `1px solid ${t.accentBorder}`,
              background: t.accentSubtle,
              color: t.accent,
              padding: "6px 10px",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Edit
          </button>
        </div>
      </div>
    );
  }

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
          minHeight: profile.compact ? 120 : editorMinHeight,
          flex: 1,
          width: "100%",
          resize: profile.compact ? "none" : "vertical",
          border: "none",
          outline: "none",
          background: "transparent",
          color: t.text,
          padding: 0,
          fontSize: 13,
          lineHeight: 1.7,
        }}
      />
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
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {profile.compact ? (
            <button
              type="button"
              onClick={() => setShowCompactEditor(false)}
              style={{
                border: "none",
                background: "transparent",
                color: t.textDim,
                padding: 0,
                fontSize: 11,
                cursor: "pointer",
              }}
            >
              Done
            </button>
          ) : null}
          <span style={{ color: t.textDim }}>Markdown ok</span>
        </div>
      </div>
    </div>
  );
}
