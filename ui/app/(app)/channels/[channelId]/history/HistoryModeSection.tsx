import { useThemeTokens } from "@/src/theme/tokens";
import { Section } from "@/src/components/shared/FormControls";
import type { ChannelSettings } from "@/src/types/api";

export const HISTORY_MODES: ReadonlyArray<{
  value: string; label: string; accentColor: string;
  summary: string; detail: string;
  recommended?: boolean;
}> = [
  {
    value: "summary",
    label: "Summary",
    accentColor: "#2563eb",
    summary: "Flat rolling summary",
    detail:
      "Each compaction replaces the previous summary with a new one. " +
      "The bot sees only a single summary block plus recent messages. Best for straightforward conversations " +
      "where historical detail isn't important.",
  },
  {
    value: "structured",
    label: "Structured",
    accentColor: "#9333ea",
    summary: "Auto-retrieves relevant sections",
    detail:
      "Conversation is archived into titled sections with embeddings. Each turn, the system retrieves " +
      "sections most relevant to the current query via cosine similarity and injects them into context. " +
      "The bot doesn't need to do anything \u2014 relevant history appears automatically.",
  },
  {
    value: "file",
    label: "File",
    accentColor: "#d97706",
    summary: "Bot navigates history on demand",
    detail:
      "Conversation is archived into titled, searchable sections stored in the database. " +
      "The bot gets an executive summary plus a section index, and can search or open any section with the " +
      "read_conversation_history tool (keyword, content grep, and semantic search). " +
      "Best for knowledge-heavy channels where the bot needs to reference specific past discussions.",
    recommended: true,
  },
];

export function HistoryModeSection({ form, patch, botHistoryMode }: {
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
      {/* Compact horizontal selector */}
      <div style={{ display: "flex", gap: 6 }}>
        {HISTORY_MODES.map((m) => {
          const isSelected = effectiveMode === m.value;
          return (
            <button
              key={m.value}
              onClick={() => patch("history_mode", m.value)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "6px 12px", borderRadius: 6, cursor: "pointer",
                background: isSelected ? `${m.accentColor}12` : "none",
                border: `1px solid ${isSelected ? m.accentColor : t.surfaceOverlay}`,
                transition: "all 0.12s ease",
              }}
            >
              <span style={{
                fontSize: 12, fontWeight: isSelected ? 700 : 500,
                color: isSelected ? m.accentColor : t.textMuted,
              }}>
                {m.label}
              </span>
              {m.recommended && (
                <span style={{
                  fontSize: 9, fontWeight: 600, color: t.warningMuted,
                  padding: "0 4px", background: "rgba(217,119,6,0.08)", borderRadius: 4,
                }}>rec</span>
              )}
            </button>
          );
        })}
        {!isInherited && (
          <button
            onClick={() => patch("history_mode", null)}
            style={{
              padding: "6px 10px", fontSize: 10, fontWeight: 600,
              color: t.textDim, background: "none", border: `1px solid ${t.surfaceOverlay}`,
              borderRadius: 6, cursor: "pointer",
            }}
          >
            Reset{botHistoryMode ? ` (${botHistoryMode})` : ""}
          </button>
        )}
      </div>

      {isInherited && (
        <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
          Inherited from bot default
        </div>
      )}

      {/* Detail for selected mode */}
      <div style={{
        marginTop: 6, padding: "10px 12px",
        background: t.codeBg, border: `1px solid ${t.codeBorder}`,
        borderRadius: 6, fontSize: 11, lineHeight: "1.5", color: t.textMuted,
      }}>
        <span style={{ fontWeight: 600, color: mode.accentColor }}>{mode.label}:</span>{" "}
        {mode.summary}. {mode.detail}
      </div>
    </Section>
  );
}
