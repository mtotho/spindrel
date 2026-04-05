import { RefreshCw } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useThemeTokens } from "@/src/theme/tokens";
import { FormRow, Toggle, Section } from "@/src/components/shared/FormControls";
import { WorkspaceSkills } from "./WorkspaceSkills";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
export interface SkillsTabProps {
  workspaceId: string;
  isNew: boolean;
  skillsEnabled: boolean;
  setSkillsEnabled: (v: boolean) => void;
  basePromptEnabled: boolean;
  setBasePromptEnabled: (v: boolean) => void;
  dbSkills: { id: string; mode?: string }[];
  setDbSkills: (v: { id: string; mode?: string }[]) => void;
}

// ---------------------------------------------------------------------------
// Skills tab
// ---------------------------------------------------------------------------
export function SkillsTab({
  workspaceId,
  isNew,
  skillsEnabled,
  setSkillsEnabled,
  basePromptEnabled,
  setBasePromptEnabled,
  dbSkills,
  setDbSkills,
}: SkillsTabProps) {
  const t = useThemeTokens();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Workspace Skills */}
      <Section title="Workspace Skills" description="Auto-discover skill .md files from workspace filesystem and inject into bot context.">
        <FormRow label="Enable workspace skills injection">
          <Toggle value={skillsEnabled} onChange={setSkillsEnabled} />
        </FormRow>
        <div style={{ padding: "8px 0", fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
          <div style={{ fontWeight: 600, color: t.textMuted, marginBottom: 4 }}>Directory conventions:</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span><code style={{ color: t.accent }}>common/skills/pinned/*.md</code> {"\u2014"} injected into every request</span>
            <span><code style={{ color: t.accent }}>common/skills/rag/*.md</code> {"\u2014"} available via tool call (same as on-demand)</span>
            <span><code style={{ color: t.accent }}>common/skills/on-demand/*.md</code> {"\u2014"} available via tool call</span>
            <span><code style={{ color: t.accent }}>common/skills/*.md</code> {"\u2014"} top-level defaults to pinned</span>
            <span style={{ marginTop: 4 }}><code style={{ color: t.warningMuted }}>{"bots/<bot-id>/skills/..."}</code> {"\u2014"} same structure, scoped to specific bot</span>
          </div>
        </div>
        {!isNew && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 4 }}>
            <button
              onClick={async () => {
                try {
                  const data = await apiFetch<{ embedded?: number; unchanged?: number; errors?: number }>(
                    `/api/v1/workspaces/${workspaceId}/reindex-skills`,
                    { method: "POST" },
                  );
                  alert(`Reindexed: ${data.embedded || 0} embedded, ${data.unchanged || 0} unchanged, ${data.errors || 0} errors`);
                } catch {
                  alert("Failed to reindex skills");
                }
              }}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "5px 12px", fontSize: 11, fontWeight: 600,
                border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                background: "transparent", color: t.textMuted, cursor: "pointer",
              }}
            >
              <RefreshCw size={11} /> Reindex Skills
            </button>
          </div>
        )}
      </Section>

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
