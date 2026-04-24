import { BookOpen } from "lucide-react";
import { Section, FormRow, SelectInput } from "@/src/components/shared/FormControls";
import { ActionButton } from "@/src/components/shared/SettingsControls";
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
  const isInherited = !form.history_mode;
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const mode = getHistoryModeMeta(effectiveMode);

  return (
    <Section
      title="History Mode"
      action={onOpenGuide ? (
        <ActionButton label="Docs" onPress={onOpenGuide} icon={<BookOpen size={12} />} variant="secondary" size="small" />
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

      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
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
          <span className="text-xs text-text">
            {mode.summary}
          </span>
        </div>
        <div className="text-xs leading-relaxed text-text-dim">
          {mode.detail}
        </div>
      </div>
    </Section>
  );
}
