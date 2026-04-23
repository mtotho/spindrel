import { BookOpen } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section, FormRow, SelectInput } from "@/src/components/shared/FormControls";
import type { ChannelSettings } from "@/src/types/api";
import {
  HISTORY_MODE_META,
  getHistoryModeMeta,
  historyModeOptionLabel,
} from "@/src/lib/historyModeMeta";

export function HistoryModeSection({ form, patch, botHistoryMode, onOpenGuide }: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  botHistoryMode?: string | null;
  onOpenGuide?: () => void;
}) {
  const t = useThemeTokens();
  const isInherited = !form.history_mode;
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const mode = getHistoryModeMeta(effectiveMode);

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
            ...HISTORY_MODE_META.map((entry) => ({
              label: historyModeOptionLabel(entry),
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
