import { useCallback, useState } from "react";
import { ActivityIndicator } from "react-native";
import { AlertTriangle, Play, RotateCw } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  Section, FormRow, TextInput, SelectInput, Toggle,
  Row, Col,
} from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { apiFetch } from "@/src/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ChannelSettings } from "@/src/types/api";

// ---------------------------------------------------------------------------
// History modes — visual mode selector data
// Uses rgba backgrounds that work on both light and dark surfaces
// ---------------------------------------------------------------------------
// HISTORY_MODES uses domain-specific accent/bg/border per mode — these are
// intentionally kept as constants since they represent three distinct mode identities
// (blue = summary, purple = structured, amber = file) that don't map 1:1 to tokens.
const HISTORY_MODES: ReadonlyArray<{
  value: string; label: string; icon: string; accentColor: string;
  bg: string; border: string; summary: string; detail: string | null;
  recommended?: boolean;
}> = [
  {
    value: "summary",
    label: "Summary",
    icon: "\ud83d\udcdd",
    accentColor: "#2563eb",
    bg: "rgba(59,130,246,0.06)",
    border: "rgba(59,130,246,0.3)",
    summary: "Flat rolling summary \u2014 simple and efficient.",
    detail:
      "Each compaction replaces the previous summary with a new one covering the full conversation. " +
      "The bot sees only a single summary block plus recent messages. Best for straightforward conversations " +
      "where historical detail isn't important.",
  },
  {
    value: "structured",
    label: "Structured",
    icon: "\ud83d\udd0d",
    accentColor: "#9333ea",
    bg: "rgba(147,51,234,0.06)",
    border: "rgba(147,51,234,0.3)",
    summary: "Semantic retrieval \u2014 automatically surfaces relevant history.",
    detail:
      "Conversation is archived into titled sections with embeddings, also written as .md files in the bot's " +
      "workspace. Each turn, the system automatically retrieves sections most relevant to the current query " +
      "via cosine similarity and injects them into context. The bot doesn't need to do anything \u2014 relevant " +
      "history appears automatically. Best for long-running channels where past context matters but you " +
      "don't want the bot spending tool calls to find it.",
  },
  {
    value: "file",
    label: "File",
    icon: "\ud83d\udcc2",
    accentColor: "#d97706",
    bg: "rgba(217,119,6,0.06)",
    border: "rgba(217,119,6,0.3)",
    summary: "Tool-based navigation \u2014 the bot browses history on demand.",
    detail:
      "Conversation is archived into titled sections, each written as a .md file in the bot's workspace " +
      "(.history/<channel>/ directory). The bot gets an executive summary plus a section index, and can use " +
      "the read_conversation_history tool to open any section. Transcripts are real files \u2014 readable via " +
      "read_file too, and visible to orchestrators browsing the workspace. " +
      "Best for knowledge-heavy channels where the bot needs to reference specific past discussions.",
    recommended: true,
  },
];

// ---------------------------------------------------------------------------
// Verbosity options for section index
// ---------------------------------------------------------------------------
const VERBOSITY_OPTIONS = [
  { label: "Compact", value: "compact" },
  { label: "Standard", value: "standard" },
  { label: "Detailed", value: "detailed" },
];

// ---------------------------------------------------------------------------
// History Mode section — visual mode selector with contextual details
// ---------------------------------------------------------------------------
function HistoryModeSection({ form, patch, botHistoryMode }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  botHistoryMode?: string | null;
}) {
  const t = useThemeTokens();
  const isInherited = !form.history_mode;
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const mode = HISTORY_MODES.find((m) => m.value === effectiveMode) || HISTORY_MODES[0];

  return (
    <Section title="History Mode">
      {/* Mode selector cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
        {HISTORY_MODES.map((m) => {
          const isSelected = effectiveMode === m.value;
          return (
            <button
              key={m.value}
              onClick={() => patch("history_mode", m.value)}
              style={{
                display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
                padding: "14px 10px", borderRadius: 8, cursor: "pointer",
                background: isSelected ? m.bg : t.inputBg,
                border: `2px solid ${isSelected ? m.accentColor : t.surfaceOverlay}`,
                transition: "all 0.15s ease",
              }}
            >
              <span style={{ fontSize: 22 }}>{m.icon}</span>
              <span style={{
                fontSize: 12, fontWeight: 700,
                color: isSelected ? m.accentColor : t.textMuted,
              }}>
                {m.label}
              </span>
              {m.recommended && (
                <span style={{ fontSize: 9, fontWeight: 700, color: t.warningMuted, letterSpacing: "0.03em" }}>
                  Recommended
                </span>
              )}
              {isSelected && isInherited && (
                <span style={{ fontSize: 9, fontWeight: 600, color: t.textDim, letterSpacing: "0.03em" }}>
                  Inherited from bot
                </span>
              )}
              <span style={{
                fontSize: 10, color: isSelected ? t.textMuted : t.textDim,
                textAlign: "center", lineHeight: "1.3",
              }}>
                {m.summary}
              </span>
            </button>
          );
        })}
      </div>

      {/* Reset to inherited when channel has an explicit override */}
      {!isInherited && (
        <button
          onClick={() => patch("history_mode", null)}
          style={{
            marginTop: 4, padding: "4px 10px", fontSize: 11, fontWeight: 600,
            color: t.textDim, background: "none", border: "none", cursor: "pointer",
            textDecoration: "underline", textUnderlineOffset: 2,
          }}
        >
          Reset to bot default{botHistoryMode ? ` (${botHistoryMode})` : ""}
        </button>
      )}

      {/* Detail panel for selected mode */}
      {mode.detail && (
        <div style={{
          marginTop: 10, padding: "12px 14px",
          background: mode.bg, border: `1px solid ${mode.border}`,
          borderRadius: 8, fontSize: 12, lineHeight: "1.5", color: t.contentText,
        }}>
          {mode.detail}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Backfill sections — coverage bar + Resume / Re-chunk buttons
// ---------------------------------------------------------------------------
type SectionsStats = {
  total_messages: number;
  covered_messages: number;
  estimated_remaining: number;
  files_ok: number;
  files_missing: number;
  files_none: number;
  periods_missing: number;
};

function BackfillButton({ channelId, historyMode }: { channelId: string; historyMode: string }) {
  const t = useThemeTokens();
  const [running, setRunning] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<{ repaired: number } | null>(null);
  const [progress, setProgress] = useState<{ section: number; total: number; title?: string } | null>(null);
  const [result, setResult] = useState<{ sections: number; error?: string } | null>(null);
  const queryClient = useQueryClient();
  const { data: sectionsData } = useQuery({
    queryKey: ["channel-sections", channelId],
    queryFn: () => apiFetch<{ total: number; stats: SectionsStats }>(`/api/v1/admin/channels/${channelId}/sections`),
  });
  const existingSections = sectionsData?.total ?? 0;
  const stats = sectionsData?.stats;

  const runBackfill = useCallback(async (clearExisting: boolean) => {
    if (clearExisting && existingSections > 0 && !window.confirm(
      `This will delete all ${existingSections} existing section${existingSections !== 1 ? "s" : ""} (DB + .history files) and re-chunk everything from scratch. Continue?`
    )) return;

    setRunning(true);
    setProgress(null);
    setResult(null);
    try {
      const { task_id } = await apiFetch<{ task_id: string }>(
        `/api/v1/admin/channels/${channelId}/backfill-sections`,
        { method: "POST", body: JSON.stringify({
          history_mode: historyMode,
          clear_existing: clearExisting,
        }) },
      );

      // Poll every 2s until complete or failed
      while (true) {
        await new Promise((r) => setTimeout(r, 2000));
        const job = await apiFetch<{
          status: string; sections_created: number; total_chunks: number;
          current_title?: string; error?: string;
        }>(`/api/v1/admin/channels/${channelId}/backfill-status/${task_id}`);

        if (job.status === "running") {
          setProgress({ section: job.sections_created, total: job.total_chunks, title: job.current_title });
        } else if (job.status === "complete") {
          setResult({ sections: job.sections_created });
          break;
        } else if (job.status === "failed") {
          setResult({ sections: job.sections_created, error: job.error || "Backfill failed" });
          break;
        }
      }
    } catch (e) {
      setResult({ sections: 0, error: e instanceof Error ? e.message : "Unknown error" });
    } finally {
      setRunning(false);
      queryClient.invalidateQueries({ queryKey: ["channel-sections", channelId] });
    }
  }, [channelId, historyMode, queryClient, existingSections]);

  const runRepairPeriods = useCallback(async () => {
    setRepairing(true);
    setRepairResult(null);
    try {
      const res = await apiFetch<{ repaired: number }>(
        `/api/v1/admin/channels/${channelId}/repair-section-periods`,
        { method: "POST" },
      );
      setRepairResult(res);
    } catch (e) {
      setRepairResult({ repaired: -1 });
    } finally {
      setRepairing(false);
      queryClient.invalidateQueries({ queryKey: ["channel-sections", channelId] });
    }
  }, [channelId, queryClient]);

  const pct = stats && stats.total_messages > 0
    ? Math.round((stats.covered_messages / stats.total_messages) * 100) : 0;
  const progressPct = progress && progress.total > 0
    ? Math.round((progress.section / progress.total) * 100) : 0;

  return (
    <div style={{ padding: "10px 0" }}>
      {/* Coverage bar — shown when sections exist and stats are available */}
      {stats && existingSections > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{
            height: 6, borderRadius: 3, background: t.surfaceOverlay, overflow: "hidden", marginBottom: 4,
          }}>
            <div style={{
              height: "100%", borderRadius: 3, transition: "width 0.3s",
              width: `${pct}%`,
              background: pct >= 100 ? t.success : t.warning,
            }} />
          </div>
          <div style={{ fontSize: 11, color: t.textMuted }}>
            {stats.covered_messages}/{stats.total_messages} messages
            {" \u00b7 "}{existingSections} section{existingSections !== 1 ? "s" : ""}
            {stats.estimated_remaining > 0 && ` \u00b7 ~${stats.estimated_remaining} remaining`}
          </div>
          {stats.files_missing > 0 && (
            <div style={{ fontSize: 11, color: t.warningMuted, marginTop: 2 }}>
              <AlertTriangle size={10} style={{ display: "inline", verticalAlign: "middle", marginRight: 4 }} />
              {stats.files_missing} section{stats.files_missing !== 1 ? "s" : ""} missing transcript files — re-run backfill to regenerate
            </div>
          )}
          {stats.periods_missing > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.warningMuted, marginTop: 2 }}>
              <AlertTriangle size={10} style={{ flexShrink: 0 }} />
              <span>
                {stats.periods_missing} section{stats.periods_missing !== 1 ? "s" : ""} missing timestamps
              </span>
              <button
                onClick={runRepairPeriods}
                disabled={repairing}
                style={{
                  padding: "1px 8px", fontSize: 11, fontWeight: 600,
                  border: "none", cursor: repairing ? "default" : "pointer", borderRadius: 4,
                  background: t.warningSubtle, color: t.warningMuted,
                  opacity: repairing ? 0.6 : 1,
                }}
              >
                {repairing ? "Repairing..." : "Repair"}
              </button>
              {repairResult && (
                <span style={{ color: repairResult.repaired >= 0 ? t.success : t.danger }}>
                  {repairResult.repaired >= 0 ? `Fixed ${repairResult.repaired}` : "Failed"}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Buttons */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {existingSections > 0 && stats && stats.estimated_remaining > 0 && (
          <button
            onClick={() => runBackfill(false)}
            disabled={running}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", cursor: running ? "default" : "pointer", borderRadius: 6,
              background: running ? t.surfaceBorder : t.warningSubtle,
              color: running ? t.textDim : t.warningMuted,
              opacity: running ? 0.7 : 1,
            }}
          >
            <Play size={12} color={running ? t.textDim : t.warningMuted} />
            {running ? "Resuming..." : "Resume Backfill"}
          </button>
        )}
        {existingSections > 0 ? (
          <button
            onClick={() => runBackfill(true)}
            disabled={running}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: `1px solid ${t.surfaceBorder}`, cursor: running ? "default" : "pointer", borderRadius: 6,
              background: "transparent",
              color: running ? t.textDim : t.textMuted,
              opacity: running ? 0.7 : 1,
            }}
          >
            <RotateCw size={12} color={running ? t.textDim : t.textMuted} />
            Re-chunk from Scratch
          </button>
        ) : (
          <button
            onClick={() => runBackfill(false)}
            disabled={running}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", cursor: running ? "default" : "pointer", borderRadius: 6,
              background: running ? t.surfaceBorder : t.warningSubtle,
              color: running ? t.textDim : t.warningMuted,
              opacity: running ? 0.7 : 1,
            }}
          >
            <Play size={12} color={running ? t.textDim : t.warningMuted} />
            {running ? "Backfilling..." : "Backfill Sections"}
          </button>
        )}
        <span style={{ fontSize: 11, color: t.textDim, flex: 1, minWidth: 0 }}>
          {existingSections > 0 && stats && stats.estimated_remaining > 0
            ? "Resume adds new sections for uncovered messages. Re-chunk deletes everything and starts fresh."
            : existingSections > 0
            ? "All messages covered. Re-chunk to regenerate with different settings."
            : "Chunk existing messages into navigable sections with .md transcripts."
          }
        </span>
      </div>

      {/* Progress bar during backfill */}
      {progress && progress.total > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
            Section {progress.section}/{progress.total}{progress.title ? `: "${progress.title}"` : ""}
          </div>
          <div style={{
            height: 4, borderRadius: 2, background: t.surfaceOverlay, overflow: "hidden",
          }}>
            <div style={{
              height: "100%", borderRadius: 2, transition: "width 0.3s",
              width: `${progressPct}%`, background: t.accent,
            }} />
          </div>
        </div>
      )}
      {result && !result.error && (
        <div style={{ marginTop: 8, fontSize: 11, color: t.success }}>
          Done — {result.sections} section{result.sections !== 1 ? "s" : ""} created
        </div>
      )}
      {result?.error && (
        <div style={{ marginTop: 8, fontSize: 11, color: t.danger }}>
          {result.error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sections viewer — shows existing conversation sections with file badges
// ---------------------------------------------------------------------------
function SectionsViewer({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["channel-sections", channelId],
    queryFn: () => apiFetch<{ sections: Array<{
      id: string; sequence: number; title: string; summary: string;
      transcript_path: string | null; message_count: number; chunk_size: number;
      period_start: string | null; period_end: string | null;
      created_at: string | null; view_count: number;
      last_viewed_at: string | null; tags: string[];
      file_exists: boolean | null;
    }>; total: number; stats: SectionsStats }>(`/api/v1/admin/channels/${channelId}/sections`),
  });

  if (isLoading) return <ActivityIndicator size="small" color={t.textDim} style={{ marginTop: 8 }} />;
  if (!data?.sections?.length) return (
    <div style={{ fontSize: 11, color: t.textDim, padding: "8px 0" }}>
      No sections yet. Use backfill or let compaction create them automatically.
    </div>
  );

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 6 }}>
        Archived Sections ({data.total})
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 600, minHeight: 0, overflowY: "auto" }}>
        {[...data.sections].reverse().map((s) => {
          const isOpen = expandedId === s.id;
          const dateStr = s.period_start
            ? new Date(s.period_start).toLocaleDateString(undefined, { month: "short", day: "numeric" })
            : "";
          // File integrity dot: green = exists, red = missing, gray = no path
          const dotColor = s.file_exists === true ? t.success : s.file_exists === false ? t.danger : t.textDim;
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
                <span style={{ fontSize: 10, color: t.textDim, transform: isOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s", flexShrink: 0 }}>\u25bc</span>
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
                  {s.transcript_path ? (
                    <div style={{
                      marginTop: 8, padding: "6px 10px", background: t.codeBg,
                      border: `1px solid ${s.file_exists === false ? t.dangerBorder : t.codeBorder}`,
                      borderRadius: 6,
                      display: "flex", alignItems: "center", gap: 6,
                    }}>
                      <span style={{ fontSize: 12 }}>\ud83d\udcc4</span>
                      <span style={{ fontSize: 10, color: t.textMuted, fontFamily: "monospace", flex: 1, wordBreak: "break-all" }}>
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
                    </div>
                  ) : (
                    <div style={{
                      marginTop: 8, padding: "6px 10px", background: t.dangerSubtle,
                      border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
                      fontSize: 10, color: t.danger, fontStyle: "italic",
                    }}>
                      No transcript file — re-run backfill to generate .md files.
                    </div>
                  )}
                  {s.view_count > 0 && s.last_viewed_at && (
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 4 }}>
                      Viewed {s.view_count}x \u00b7 last {new Date(s.last_viewed_at).toLocaleDateString()}
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

// ---------------------------------------------------------------------------
// Section Index Settings — controls + live preview
// ---------------------------------------------------------------------------
function SectionIndexSettings({ form, patch, channelId }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
}) {
  const t = useThemeTokens();
  const count = form.section_index_count ?? 10;
  const verbosity = form.section_index_verbosity ?? "standard";

  const { data: preview } = useQuery({
    queryKey: ["section-index-preview", channelId, count, verbosity],
    queryFn: () => apiFetch<{ content: string; section_count: number; chars: number }>(
      `/api/v1/admin/channels/${channelId}/section-index-preview?count=${count}&verbosity=${verbosity}`,
    ),
    enabled: count > 0,
  });

  return (
    <div>
      <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 8, lineHeight: "1.5" }}>
        The bot sees what's in the archive without spending a tool call and can use <code style={{ color: t.codeText }}>read_conversation_history</code> with a section number to read full transcripts.
      </div>
      <Row>
        <Col>
          <FormRow label="Index Sections" description="Recent sections injected into context each turn. 0 = disabled.">
            <TextInput
              value={count === 10 && form.section_index_count == null ? "" : count.toString()}
              onChangeText={(v) => patch("section_index_count", v ? parseInt(v) || 0 : undefined)}
              placeholder="10"
              type="number"
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow label="Verbosity" description="How much detail to show per section.">
            <SelectInput
              value={verbosity}
              onChange={(v) => patch("section_index_verbosity", v || undefined)}
              options={VERBOSITY_OPTIONS}
            />
          </FormRow>
        </Col>
      </Row>

      {/* Live preview */}
      {count > 0 && (
        <div style={{ marginTop: 8 }}>
          {preview && preview.section_count > 0 ? (
            <>
              <div style={{
                background: t.codeBg, border: `1px solid ${t.codeBorder}`, borderRadius: 8,
                padding: "12px 14px", fontFamily: "monospace", fontSize: 11,
                color: t.contentText, whiteSpace: "pre-wrap", lineHeight: "1.5",
                maxHeight: 300, overflow: "auto",
              }}>
                {preview.content}
              </div>
              <div style={{ fontSize: 10, color: t.textDim, marginTop: 4 }}>
                ~{preview.chars.toLocaleString()} chars per turn
              </div>
            </>
          ) : (
            <div style={{
              padding: "12px 14px", background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 8, fontSize: 11, color: t.textDim, fontStyle: "italic",
            }}>
              No sections to preview — run backfill first.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// History Tab — history mode, compaction settings, backfill
// ---------------------------------------------------------------------------
export function HistoryTab({ form, patch, channelId, workspaceId, memoryScheme, botHistoryMode }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
  workspaceId?: string | null;
  memoryScheme?: string | null;
  botHistoryMode?: string | null;
}) {
  const t = useThemeTokens();
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const isFileOrStructured = effectiveMode === "file" || effectiveMode === "structured";

  return (
    <>
      {/* 1. History Mode cards — always visible at top */}
      <HistoryModeSection form={form} patch={patch} botHistoryMode={botHistoryMode} />

      {/* 2. Compaction settings — conditional on mode */}
      {isFileOrStructured ? (
        <>
        <Section title="Archival Settings" description="Manages long conversations by archiving old turns into titled sections.">
          {/* Locked banner */}
          <div style={{
            padding: "10px 14px", background: t.warningSubtle, border: `1px solid ${t.warningBorder}`,
            borderRadius: 8, fontSize: 12, color: t.warningMuted, fontWeight: 600,
          }}>
            Auto-compaction is always on in {effectiveMode} mode — it creates the archived sections the bot navigates.
          </div>

          {/* File-mode guidance */}
          <div style={{
            padding: "12px 14px", background: t.codeBg, border: `1px solid ${t.codeBorder}`,
            borderRadius: 8, fontSize: 11, color: t.textMuted, lineHeight: "1.6",
          }}>
            After every <strong style={{ color: t.text }}>Interval</strong> user turns, the oldest messages are
            archived into a titled, summarized section. The bot keeps the last <strong style={{ color: t.text }}>Keep Turns</strong> verbatim,
            plus an executive summary and section index. It can open any section with the <code style={{ color: t.codeText }}>read_conversation_history</code> tool.
            <div style={{ marginTop: 8, color: t.warningMuted }}>
              Recommended: Interval 20, Keep Turns 6 — lower interval = more granular sections.
              The bot can always read full transcripts, so aggressive archival is safe.
            </div>
          </div>

          <Row>
            <Col>
              <FormRow label="Interval (user turns)" description="Compaction triggers after this many user messages. Lower = more frequent archival.">
                <TextInput
                  value={form.compaction_interval?.toString() ?? ""}
                  onChangeText={(v) => patch("compaction_interval", v ? parseInt(v) || undefined : undefined)}
                  placeholder="recommended (20)"
                  type="number"
                />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Keep Turns" description="Recent turns always kept verbatim — never archived.">
                <TextInput
                  value={form.compaction_keep_turns?.toString() ?? ""}
                  onChangeText={(v) => patch("compaction_keep_turns", v ? parseInt(v) || undefined : undefined)}
                  placeholder="recommended (6)"
                  type="number"
                />
              </FormRow>
            </Col>
          </Row>

          <LlmModelDropdown
            label="Compaction Model"
            value={form.compaction_model ?? ""}
            onChange={(v) => patch("compaction_model", v || undefined)}
            placeholder="inherit (bot model)"
          />
          <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
            Used for section generation, executive summaries, and backfill. A cheap/fast model works well here — the prompts are straightforward summarization.
          </div>

          {/* Memory Flush */}
          <Toggle
            value={!!form.memory_flush_enabled}
            onChange={(v) => patch("memory_flush_enabled", v || undefined)}
            label="Memory flush before compaction"
          />
          <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
            {memoryScheme === "workspace-files"
              ? "Before archiving, the bot gets one pass to save important context — updating MEMORY.md, daily logs, and reference files via exec_command."
              : "Before archiving, the bot gets one pass to save important context using its configured memory tools."
            }
          </div>

          {form.memory_flush_enabled && (
            <>
              <LlmModelDropdown
                label="Memory Flush Model"
                value={form.memory_flush_model ?? ""}
                onChange={(v) => patch("memory_flush_model", v || undefined)}
                placeholder="inherit (bot model)"
              />
              <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
                Model used for the memory flush pass. A capable model works best here since it needs to reason about what to save.
              </div>

              {memoryScheme === "workspace-files" ? (
                <div style={{
                  padding: "10px 14px", background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
                  borderRadius: 8, fontSize: 11, color: t.textMuted, lineHeight: "1.5",
                }}>
                  <strong style={{ color: t.text }}>Workspace-files mode:</strong> Uses a built-in prompt that tells the bot to write to MEMORY.md, daily logs, and reference files. Custom prompts below are ignored.
                </div>
              ) : (
                <LlmPrompt
                  label="Memory Flush Prompt"
                  value={form.memory_flush_prompt ?? ""}
                  onChange={(v: string) => patch("memory_flush_prompt", v || undefined)}
                  placeholder="Uses global default memory flush prompt"
                />
              )}
            </>
          )}

          {/* Legacy heartbeat trigger (hidden if memory flush is enabled) */}
          {!form.memory_flush_enabled && (
            <>
              <Toggle
                value={!!form.trigger_heartbeat_before_compaction}
                onChange={(v) => patch("trigger_heartbeat_before_compaction", v || undefined)}
                label="Trigger heartbeat before compaction (legacy)"
              />
              <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
                Legacy option — fires channel heartbeats before compaction. Use "Memory flush" above instead for a dedicated, configurable flush pass.
              </div>
            </>
          )}
        </Section>

        <Section title="Section Index" description="Injects a lightweight section index into context each turn.">
          <SectionIndexSettings form={form} patch={patch} channelId={channelId} />
        </Section>

        <Section title="Backfill" description="Retroactively create archived sections from existing message history.">
          <div style={{
            padding: "10px 14px", background: t.warningSubtle,
            border: `1px solid ${t.warningBorder}`, borderRadius: 8,
            fontSize: 11, color: t.textMuted, lineHeight: "1.5",
          }}>
            <AlertTriangle size={12} color={t.warningMuted} style={{ display: "inline", verticalAlign: "middle", marginRight: 6 }} />
            Backfill makes one LLM call per chunk of messages plus one for the executive summary. For example,
            500 messages at chunk size 50 = ~11 LLM calls using your compaction model. Set your interval and keep
            turns first. Resume only processes uncovered messages; re-chunk deletes everything and starts fresh.
          </div>
          <BackfillButton channelId={channelId} historyMode={effectiveMode} />
        </Section>

        <Section title="Archived Sections" description="Browse and manage archived conversation sections.">
          <SectionsViewer channelId={channelId} />
        </Section>
        </>
      ) : (
        <Section title="Compaction" description="Manages long conversations by periodically summarizing old turns.">
          <Toggle
            value={form.context_compaction ?? true}
            onChange={(v) => patch("context_compaction", v)}
            label="Enable auto-compaction"
          />
          {form.context_compaction && (
            <>
              <div style={{
                padding: "14px 16px", background: t.codeBg, border: `1px solid ${t.codeBorder}`,
                borderRadius: 8, marginBottom: 4,
              }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: t.accent, marginBottom: 8 }}>How Compaction Works</div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.6" }}>
                  After every <strong style={{ color: t.text }}>Interval</strong> user turns, the oldest messages
                  are archived and summarized by an LLM. The most recent <strong style={{ color: t.text }}>Keep Turns</strong> are
                  always preserved verbatim. If memory flush is enabled below, the bot gets a "last chance" pass
                  to save important context before summarization.
                </div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.6", marginTop: 8 }}>
                  <strong style={{ color: t.text }}>Example:</strong> Interval=30, Keep Turns=10 \u2192 after 30 user messages,
                  the oldest 20 are summarized. The bot always sees the last 10 turns plus the summary.
                </div>
              </div>

              <Row>
                <Col>
                  <FormRow label="Interval (user turns)" description="Compaction triggers after this many user messages accumulate. Lower = more frequent, tighter context. Default: 30.">
                    <TextInput
                      value={form.compaction_interval?.toString() ?? ""}
                      onChangeText={(v) => patch("compaction_interval", v ? parseInt(v) || undefined : undefined)}
                      placeholder="default (30)"
                      type="number"
                    />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Keep Turns" description="Recent turns always kept verbatim — never summarized. Higher = more immediate context but less room for RAG/tools. Default: 10.">
                    <TextInput
                      value={form.compaction_keep_turns?.toString() ?? ""}
                      onChangeText={(v) => patch("compaction_keep_turns", v ? parseInt(v) || undefined : undefined)}
                      placeholder="default (10)"
                      type="number"
                    />
                  </FormRow>
                </Col>
              </Row>

              <div style={{
                padding: "12px 14px", background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 8, display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted }}>Quick Guide</div>
                <div style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5" }}>
                  <strong style={{ color: t.contentText }}>Casual chatbot:</strong> Interval 20, Keep 6 — compacts often, keeps things lean.
                </div>
                <div style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5" }}>
                  <strong style={{ color: t.contentText }}>Project assistant:</strong> Interval 30, Keep 10 — balanced, good for task tracking.
                </div>
                <div style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5" }}>
                  <strong style={{ color: t.contentText }}>Long-running agent:</strong> Interval 40+, Keep 12 — more raw context, fewer compaction LLM calls.
                </div>
                <div style={{ fontSize: 11, color: t.warningMuted, lineHeight: "1.5", marginTop: 4 }}>
                  Keep Turns must be less than Interval — otherwise nothing gets summarized.
                </div>
              </div>

              <LlmModelDropdown
                label="Compaction Model"
                value={form.compaction_model ?? ""}
                onChange={(v) => patch("compaction_model", v || undefined)}
                placeholder="inherit (bot model)"
              />
              <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
                Used for summarization. A cheap/fast model works well — the prompts are straightforward.
              </div>

              {/* Memory Flush */}
              <Toggle
                value={!!form.memory_flush_enabled}
                onChange={(v) => patch("memory_flush_enabled", v || undefined)}
                label="Memory flush before compaction"
              />
              <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
                {memoryScheme === "workspace-files"
                  ? "Before summarizing, the bot gets one pass to save important context — updating MEMORY.md, daily logs, and reference files via exec_command."
                  : "Before summarizing, the bot gets one pass to save important context using its configured memory tools."
                }
              </div>

              {form.memory_flush_enabled && (
                <>
                  <LlmModelDropdown
                    label="Memory Flush Model"
                    value={form.memory_flush_model ?? ""}
                    onChange={(v) => patch("memory_flush_model", v || undefined)}
                    placeholder="inherit (bot model)"
                  />

                  {memoryScheme === "workspace-files" ? (
                    <div style={{
                      padding: "10px 14px", background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
                      borderRadius: 8, fontSize: 11, color: t.textMuted, lineHeight: "1.5",
                    }}>
                      <strong style={{ color: t.text }}>Workspace-files mode:</strong> Uses a built-in prompt that tells the bot to write to MEMORY.md, daily logs, and reference files. Custom prompts are ignored.
                    </div>
                  ) : (
                    <LlmPrompt
                      label="Memory Flush Prompt"
                      value={form.memory_flush_prompt ?? ""}
                      onChange={(v: string) => patch("memory_flush_prompt", v || undefined)}
                      placeholder="Uses global default memory flush prompt"
                    />
                  )}
                </>
              )}

              {/* Legacy heartbeat trigger (hidden if memory flush is enabled) */}
              {!form.memory_flush_enabled && (
                <>
                  <Toggle
                    value={!!form.trigger_heartbeat_before_compaction}
                    onChange={(v) => patch("trigger_heartbeat_before_compaction", v || undefined)}
                    label="Trigger heartbeat before compaction (legacy)"
                  />
                  <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
                    Legacy option — fires channel heartbeats before compaction. Use "Memory flush" above instead.
                  </div>
                </>
              )}
            </>
          )}
        </Section>
      )}

    </>
  );
}
