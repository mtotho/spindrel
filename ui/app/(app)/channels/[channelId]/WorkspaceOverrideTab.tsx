import { useThemeTokens } from "@/src/theme/tokens";
import { Section, FormRow, SelectInput } from "@/src/components/shared/FormControls";
import { RotateCw } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import type { ChannelSettings } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Workspace override tab
// ---------------------------------------------------------------------------
export function WorkspaceOverrideTab({
  form,
  patch,
  workspaceId,
  channelId,
  onSave,
  saving,
  saved,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  workspaceId?: string | null;
  channelId: string;
  onSave: () => void;
  saving: boolean;
  saved: boolean;
}) {
  const t = useThemeTokens();
  return (
    <>
      <Section title="Workspace Skills" description="Override the workspace-level skill injection setting for this channel.">
        <FormRow label="Skills injection" description="null = inherit from workspace, on/off = override">
          <SelectInput
            value={form.workspace_skills_enabled === null || form.workspace_skills_enabled === undefined ? "inherit" : form.workspace_skills_enabled ? "on" : "off"}
            options={[
              { label: "Inherit from workspace", value: "inherit" },
              { label: "Enabled", value: "on" },
              { label: "Disabled", value: "off" },
            ]}
            onChange={(v) => patch("workspace_skills_enabled" as any, v === "inherit" ? null : v === "on")}
          />
        </FormRow>
        <div style={{ fontSize: 11, color: t.textDim, padding: "4px 0" }}>
          When enabled, skill .md files from the workspace filesystem are discovered and injected into the bot's context by mode (pinned/rag/on-demand).
        </div>
        {workspaceId && (
          <div style={{ marginTop: 8 }}>
            <button
              onClick={async () => {
                try {
                  const data = await apiFetch<{ embedded?: number; unchanged?: number; errors?: number }>(
                    `/api/v1/workspaces/${workspaceId}/reindex-skills`,
                    { method: "POST" },
                  );
                  alert(`Reindexed: ${data.embedded || 0} embedded, ${data.unchanged || 0} unchanged, ${data.errors || 0} errors`);
                } catch (e) {
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
              <RotateCw size={11} /> Reindex Skills
            </button>
          </div>
        )}
      </Section>

      <Section title="Workspace Base Prompt" description="Override the workspace-level base prompt setting for this channel.">
        <FormRow label="Base prompt override" description="null = inherit from workspace, on/off = override">
          <SelectInput
            value={form.workspace_base_prompt_enabled === null || form.workspace_base_prompt_enabled === undefined ? "inherit" : form.workspace_base_prompt_enabled ? "on" : "off"}
            options={[
              { label: "Inherit from workspace", value: "inherit" },
              { label: "Enabled", value: "on" },
              { label: "Disabled", value: "off" },
            ]}
            onChange={(v) => patch("workspace_base_prompt_enabled" as any, v === "inherit" ? null : v === "on")}
          />
        </FormRow>
        <div style={{ fontSize: 11, color: t.textDim, padding: "4px 0" }}>
          When enabled, <code>common/prompts/base.md</code> from the workspace replaces the global base prompt. Per-bot additions from <code>bots/&lt;bot-id&gt;/prompts/base.md</code> are concatenated after.
        </div>
      </Section>
    </>
  );
}
