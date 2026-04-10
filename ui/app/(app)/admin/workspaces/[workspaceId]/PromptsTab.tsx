import { useThemeTokens } from "@/src/theme/tokens";
import { FormRow, Toggle, Section } from "@/src/components/shared/FormControls";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
export interface PromptsTabProps {
  workspaceId: string;
  isNew: boolean;
  basePromptEnabled: boolean;
  setBasePromptEnabled: (v: boolean) => void;
}

// ---------------------------------------------------------------------------
// Prompts tab — workspace-level prompt and persona file overrides
// ---------------------------------------------------------------------------
export function PromptsTab({
  basePromptEnabled,
  setBasePromptEnabled,
}: PromptsTabProps) {
  const t = useThemeTokens();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Workspace Base Prompt */}
      <Section title="Workspace Base Prompt" description="Override the global base prompt with a workspace-level prompt file.">
        <FormRow label="Enable workspace base prompt override">
          <Toggle value={basePromptEnabled} onChange={setBasePromptEnabled} />
        </FormRow>
        <div style={{ padding: "8px 0", fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
          <div style={{ fontWeight: 600, color: t.textMuted, marginBottom: 4 }}>File conventions:</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span><code style={{ color: t.accent }}>common/prompts/base.md</code> {"\u2014"} replaces global base prompt for all workspace bots</span>
            <span><code style={{ color: t.warningMuted }}>{"bots/<bot-id>/prompts/base.md"}</code> {"\u2014"} concatenated after common, resolved per bot at runtime</span>
          </div>
        </div>
      </Section>

      {/* Workspace Persona */}
      <Section title="Workspace Persona" description="Override the DB persona with a workspace file. No toggle needed \u2014 file presence opts in.">
        <div style={{ padding: "8px 0", fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
          <div style={{ fontWeight: 600, color: t.textMuted, marginBottom: 4 }}>File convention:</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span><code style={{ color: t.warningMuted }}>{"bots/<bot-id>/persona.md"}</code> {"\u2014"} overrides DB persona for that bot</span>
          </div>
        </div>
      </Section>
    </div>
  );
}
