import { useThemeTokens } from "@/src/theme/tokens";
import { FormRow, Toggle, Section } from "@/src/components/shared/FormControls";
import { WorkspaceSkills } from "./WorkspaceSkills";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
export interface SkillsTabProps {
  workspaceId: string;
  isNew: boolean;
  basePromptEnabled: boolean;
  setBasePromptEnabled: (v: boolean) => void;
  dbSkills: { id: string; mode?: string }[];
  setDbSkills: (v: { id: string; mode?: string }[]) => void;
}

// ---------------------------------------------------------------------------
// Skills tab
// ---------------------------------------------------------------------------
export function SkillsTab({
  basePromptEnabled,
  setBasePromptEnabled,
  dbSkills,
  setDbSkills,
}: SkillsTabProps) {
  const t = useThemeTokens();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* DB Skills */}
      <Section title="DB Skills" description="Assign global skills from the skills table to all bots in this workspace.">
        <WorkspaceSkills skills={dbSkills} onChange={setDbSkills} />
      </Section>

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
