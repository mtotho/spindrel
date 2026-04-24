import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { apiFetch } from "@/src/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { SectionsStats } from "./BackfillSection";
import { EmptyState } from "@/src/components/shared/FormControls";
import { ActionButton, QuietPill, StatusBadge } from "@/src/components/shared/SettingsControls";

export function SectionsViewer({ channelId }: { channelId: string }) {
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

  if (isLoading) return <Spinner size={16} />;
  if (!data?.sections?.length) return (
    <EmptyState message="No sections yet. Use backfill or let compaction create them automatically." />
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
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-[12px] font-semibold text-text-muted">
          Archived Sections ({data.total})
        </div>
        {missingTranscripts > 0 && (
          <ActionButton
            label={migrating ? "Migrating..." : `Migrate ${missingTranscripts} to DB`}
            onPress={migrateTranscripts}
            disabled={migrating}
            size="small"
            variant="secondary"
          />
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        {[...data.sections].reverse().map((s) => {
          const isOpen = expandedId === s.id;
          const dateStr = s.period_start
            ? new Date(s.period_start).toLocaleDateString(undefined, { month: "short", day: "numeric" })
            : "";
          const transcriptTone = s.has_transcript ? "success" : s.file_exists === false ? "danger" : s.file_exists === true ? "info" : "neutral";
          return (
            <div key={s.id} className={`rounded-md ${isOpen ? "bg-surface-raised/45" : "bg-surface-raised/30"}`}>
              <button
                type="button"
                onClick={() => setExpandedId(isOpen ? null : s.id)}
                className="grid min-h-[34px] w-full grid-cols-[48px_minmax(0,1fr)_auto_auto_auto_auto] items-center gap-2 rounded-md px-3 py-1 text-left transition-colors hover:bg-surface-overlay/35 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 max-md:grid-cols-[40px_minmax(0,1fr)_auto_auto]"
              >
                <span className="font-mono text-[10px] leading-none text-text-dim">#{s.sequence}</span>
                <span className="min-w-0 truncate text-[12px] font-semibold leading-none text-text">{s.title}</span>
                <span className="hidden items-center justify-end gap-1.5 md:flex">
                  {s.tags?.slice(0, 3).map((tag, i) => (
                    <QuietPill key={i} label={tag} title={tag} maxWidthClass="max-w-[180px]" />
                  ))}
                </span>
                <span className="justify-self-end whitespace-nowrap text-[10px] leading-none text-text-dim">{s.message_count} msgs</span>
                <span className="hidden justify-self-end whitespace-nowrap text-[10px] leading-none text-text-dim sm:inline">{dateStr}</span>
                <span className={`justify-self-end text-[10px] leading-none text-text-dim transition-transform ${isOpen ? "rotate-180" : ""}`}>{"\u25bc"}</span>
              </button>
              {isOpen && (
                <div className="flex flex-col gap-2 border-t border-surface-border/40 px-3 pb-3 pt-2">
                  {/* Period + message count */}
                  {(s.period_start || s.period_end) && (
                    <div className="text-[10px] text-text-dim">
                      {s.period_start && new Date(s.period_start).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      {s.period_start && s.period_end && " \u2014 "}
                      {s.period_end && new Date(s.period_end).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      {" \u00b7 "}{s.message_count} messages
                    </div>
                  )}
                  <div className="text-[11px] font-semibold text-text-muted">Summary</div>
                  <div className="whitespace-pre-wrap text-[11px] leading-relaxed text-text-muted">{s.summary}</div>
                  {s.tags?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {s.tags.map((tag, i) => (
                        <QuietPill key={i} label={tag} title={tag} maxWidthClass="max-w-none" />
                      ))}
                    </div>
                  )}
                  {/* Transcript storage status */}
                  <div className="flex flex-wrap items-center gap-1.5 rounded-md bg-surface-overlay/35 px-2.5 py-1.5">
                    <StatusBadge label={s.has_transcript ? "DB Transcript" : "No DB Transcript"} variant={transcriptTone} />
                    {s.transcript_path && (
                      <>
                        <span className="break-all font-mono text-[10px] text-text-muted">
                          {s.transcript_path}
                        </span>
                        {s.file_exists === true && <StatusBadge label="File OK" variant="success" />}
                        {s.file_exists === false && <StatusBadge label="File Missing" variant="danger" />}
                      </>
                    )}
                    {!s.has_transcript && !s.transcript_path && (
                      <span className="text-[10px] italic text-text-dim">
                        No transcript stored — re-run backfill to populate
                      </span>
                    )}
                  </div>
                  {s.view_count > 0 && s.last_viewed_at && (
                    <div className="text-[10px] text-text-dim">
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
