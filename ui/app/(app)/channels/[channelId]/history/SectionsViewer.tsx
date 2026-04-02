import { useState } from "react";
import { ActivityIndicator } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { SectionsStats } from "./BackfillSection";

export function SectionsViewer({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const qc = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [migrating, setMigrating] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["channel-sections", channelId],
    queryFn: () => apiFetch<{ sections: Array<{
      id: string; sequence: number; title: string; summary: string;
      transcript_path: string | null; message_count: number; chunk_size: number;
      period_start: string | null; period_end: string | null;
      created_at: string | null; view_count: number;
      last_viewed_at: string | null; tags: string[];
      file_exists: boolean | null;
      has_transcript: boolean;
    }>; total: number; stats: SectionsStats }>(`/api/v1/admin/channels/${channelId}/sections`),
  });

  if (isLoading) return <ActivityIndicator size="small" color={t.textDim} style={{ marginTop: 8 }} />;
  if (!data?.sections?.length) return (
    <div style={{ fontSize: 11, color: t.textDim, padding: "8px 0" }}>
      No sections yet. Use backfill or let compaction create them automatically.
    </div>
  );

  const missingTranscripts = data.sections.filter((s) => !s.has_transcript && s.transcript_path).length;

  const migrateTranscripts = async () => {
    setMigrating(true);
    try {
      await apiFetch(`/api/v1/admin/channels/${channelId}/backfill-transcripts`, { method: "POST" });
      qc.invalidateQueries({ queryKey: ["channel-sections", channelId] });
    } catch { /* ignore */ }
    setMigrating(false);
  };

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted }}>
          Archived Sections ({data.total})
        </div>
        {missingTranscripts > 0 && (
          <button
            onClick={migrateTranscripts}
            disabled={migrating}
            style={{
              padding: "2px 8px", borderRadius: 4, border: `1px solid ${t.accentSubtle}`,
              background: "none", color: t.accent, fontSize: 10, cursor: migrating ? "wait" : "pointer",
            }}
          >
            {migrating ? "Migrating..." : `Migrate ${missingTranscripts} to DB`}
          </button>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 600, minHeight: 0, overflowY: "auto" }}>
        {[...data.sections].reverse().map((s) => {
          const isOpen = expandedId === s.id;
          const dateStr = s.period_start
            ? new Date(s.period_start).toLocaleDateString(undefined, { month: "short", day: "numeric" })
            : "";
          // Transcript indicator: green = DB transcript, blue = file only, red = missing file, gray = nothing
          const dotColor = s.has_transcript ? t.success
            : s.file_exists === true ? t.accent
            : s.file_exists === false ? t.danger
            : t.textDim;
          return (
            <div key={s.id} style={{
              background: t.inputBg, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6,
              overflow: "hidden", flexShrink: 0,
            }}>
              <button
                onClick={() => setExpandedId(isOpen ? null : s.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%",
                  padding: "8px 12px", background: "none", border: "none",
                  cursor: "pointer", textAlign: "left", minHeight: 36,
                }}
              >
                <span style={{ fontSize: 10, color: t.textDim, minWidth: 20 }}>#{s.sequence}</span>
                <span style={{
                  width: 6, height: 6, borderRadius: 3, flexShrink: 0,
                  background: dotColor,
                }} />
                <span style={{ fontSize: 12, color: t.text, flex: 1 }}>{s.title}</span>
                {s.tags?.length > 0 && (
                  <span style={{ display: "flex", gap: 3, flexShrink: 0 }}>
                    {s.tags.slice(0, 3).map((tag, i) => (
                      <span key={i} style={{
                        fontSize: 9, color: t.accent, background: t.accentSubtle,
                        padding: "1px 5px", borderRadius: 8, whiteSpace: "nowrap",
                      }}>{tag}</span>
                    ))}
                  </span>
                )}
                <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>{s.message_count} msgs</span>
                {s.view_count > 0 && (
                  <span style={{
                    fontSize: 9, color: t.purple, background: t.purpleSubtle,
                    padding: "1px 5px", borderRadius: 8, fontWeight: 600, flexShrink: 0,
                  }}>{s.view_count}x viewed</span>
                )}
                {dateStr && <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>{dateStr}</span>}
                <span style={{ fontSize: 10, color: t.textDim, transform: isOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s", flexShrink: 0 }}>{"\u25bc"}</span>
              </button>
              {isOpen && (
                <div style={{ padding: "0 12px 10px", borderTop: `1px solid ${t.surfaceOverlay}` }}>
                  {/* Period + message count */}
                  {(s.period_start || s.period_end) && (
                    <div style={{ fontSize: 10, color: t.textDim, padding: "6px 0 2px" }}>
                      {s.period_start && new Date(s.period_start).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      {s.period_start && s.period_end && " \u2014 "}
                      {s.period_end && new Date(s.period_end).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      {" \u00b7 "}{s.message_count} messages
                    </div>
                  )}
                  <div style={{ fontSize: 11, color: t.textMuted, padding: "6px 0 4px", fontWeight: 600 }}>Summary</div>
                  <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.5", whiteSpace: "pre-wrap" }}>{s.summary}</div>
                  {s.tags?.length > 0 && (
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>
                      {s.tags.map((tag, i) => (
                        <span key={i} style={{
                          fontSize: 10, color: t.accent, background: t.accentSubtle,
                          padding: "2px 8px", borderRadius: 10,
                        }}>{tag}</span>
                      ))}
                    </div>
                  )}
                  {/* Transcript storage status */}
                  <div style={{
                    marginTop: 8, padding: "6px 10px", background: t.codeBg,
                    border: `1px solid ${t.codeBorder}`, borderRadius: 6,
                    display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap",
                  }}>
                    {s.has_transcript ? (
                      <span style={{
                        fontSize: 9, color: t.success, background: t.successSubtle,
                        padding: "1px 6px", borderRadius: 8, fontWeight: 600, flexShrink: 0,
                      }}>DB Transcript</span>
                    ) : (
                      <span style={{
                        fontSize: 9, color: t.warningMuted, background: t.warningSubtle,
                        padding: "1px 6px", borderRadius: 8, fontWeight: 600, flexShrink: 0,
                      }}>No DB Transcript</span>
                    )}
                    {s.transcript_path && (
                      <>
                        <span style={{ fontSize: 10, color: t.textMuted, fontFamily: "monospace", wordBreak: "break-all" }}>
                          {s.transcript_path}
                        </span>
                        {s.file_exists === true && (
                          <span style={{
                            fontSize: 9, color: t.success, background: t.successSubtle,
                            padding: "1px 6px", borderRadius: 8, fontWeight: 600, flexShrink: 0,
                          }}>File OK</span>
                        )}
                        {s.file_exists === false && (
                          <span style={{
                            fontSize: 9, color: t.danger, background: t.dangerSubtle,
                            padding: "1px 6px", borderRadius: 8, fontWeight: 600, flexShrink: 0,
                          }}>File Missing</span>
                        )}
                      </>
                    )}
                    {!s.has_transcript && !s.transcript_path && (
                      <span style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>
                        No transcript stored — re-run backfill to populate
                      </span>
                    )}
                  </div>
                  {s.view_count > 0 && s.last_viewed_at && (
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 4 }}>
                      Viewed {s.view_count}x {"\u00b7"} last {new Date(s.last_viewed_at).toLocaleDateString()}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
