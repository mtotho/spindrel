import { useThemeTokens } from "@/src/theme/tokens";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { Section } from "@/src/components/shared/FormControls";
import type { ChannelSettings } from "@/src/types/api";

// Domain-specific accent/bg/border per mode — intentionally kept as constants
// since they represent three distinct mode identities that don't map 1:1 to tokens.
export const HISTORY_MODES: ReadonlyArray<{
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

export function HistoryModeSection({ form, patch, botHistoryMode }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  botHistoryMode?: string | null;
}) {
  const t = useThemeTokens();
  const isMobile = useIsMobile();
  const isInherited = !form.history_mode;
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const mode = HISTORY_MODES.find((m) => m.value === effectiveMode) || HISTORY_MODES[0];

  return (
    <Section title="History Mode">
      {/* Mode selector cards */}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(${isMobile ? "120px" : "140px"}, 1fr))`, gap: 8 }}>
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
