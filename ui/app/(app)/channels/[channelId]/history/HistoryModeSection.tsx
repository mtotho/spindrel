import { BookOpen } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section, FormRow, SelectInput } from "@/src/components/shared/FormControls";
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

export function HistoryModeSection({ form, patch, botHistoryMode, onOpenGuide }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  botHistoryMode?: string | null;
  onOpenGuide?: () => void;
}) {
  const t = useThemeTokens();
  const isInherited = !form.history_mode;
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const mode = HISTORY_MODES.find((m) => m.value === effectiveMode) || HISTORY_MODES[0];

  return (
    <Section
      title="History Mode"
      action={onOpenGuide ? (
        <button
          type="button"
          onClick={onOpenGuide}
          className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2 py-1 text-[12px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text"
          aria-label="Read context management guide"
          title="Read the guide"
        >
          <BookOpen size={12} />
          Docs
        </button>
      ) : null}
    >
      <FormRow
        label="Mode"
        description={isInherited ? `Inherited from bot default${botHistoryMode ? ` (${botHistoryMode})` : ""}.` : "Override the bot default for this channel."}
      >
        <SelectInput
          value={isInherited ? "__inherit__" : effectiveMode}
          onChange={(value) => patch("history_mode", (value === "__inherit__" ? null : value) as ChannelSettings["history_mode"])}
          options={[
            { label: `Inherit bot default${botHistoryMode ? ` (${botHistoryMode})` : ""}`, value: "__inherit__" },
            ...HISTORY_MODES.map((entry) => ({
              label: entry.recommended ? `${entry.label} (recommended)` : entry.label,
              value: entry.value,
            })),
          ]}
        />
      </FormRow>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: mode.accentColor,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
            }}
          >
            {mode.label}
          </span>
          <span style={{ fontSize: 12, color: t.text }}>
            {mode.summary}
          </span>
        </div>
        <div style={{ fontSize: 12, lineHeight: "1.6", color: t.textDim }}>
          {mode.detail}
        </div>
      </div>
    </Section>
  );
}
