import { useState } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import {
  Section, FormRow, TextInput, Toggle, Row, Col,
} from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { InfoBanner } from "@/src/components/shared/SettingsControls";
import { AlertTriangle } from "lucide-react";
import { DocsMarkdownModal } from "@/src/components/shared/DocsMarkdownModal";
import type { ChannelSettings } from "@/src/types/api";

// Sub-components extracted from this file
import { HistoryModeSection } from "./history/HistoryModeSection";
import { BackfillButton } from "./history/BackfillSection";
import { SectionsViewer } from "./history/SectionsViewer";
import { SectionIndexSettings } from "./history/SectionIndexSettings";
import { CompactionActivity } from "./history/CompactionActivity";
import { SectionSearch } from "./history/SectionSearch";

// Re-export sub-components for convenience
export { HistoryModeSection, BackfillButton, SectionsViewer, SectionIndexSettings, CompactionActivity, SectionSearch };

// ---------------------------------------------------------------------------
// History Tab — orchestrator
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
  const isMobile = useIsMobile();
  const [guideOpen, setGuideOpen] = useState(false);
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const isFileOrStructured = effectiveMode === "file" || effectiveMode === "structured";

  return (
    <>
      {/* 1. History Mode cards — always visible at top */}
      <HistoryModeSection form={form} patch={patch} botHistoryMode={botHistoryMode} onOpenGuide={() => setGuideOpen(true)} />

      {/* 2. Compaction settings — conditional on mode */}
      {isFileOrStructured ? (
        <>
        <Section
          title="Archival Settings"
          description="Interval is the normal archival cadence, Keep Turns is the recent verbatim floor, and token guards can archive earlier if live history gets too large for the prompt budget."
          noDivider
        >
          <div style={{ fontSize: 12, lineHeight: "1.6", color: t.textDim }}>
            {effectiveMode === "structured"
              ? "Structured mode archives old turns into searchable sections and auto-retrieves the relevant ones on future turns."
              : "File mode archives old turns into titled sections the bot can browse on demand with read_conversation_history."}
          </div>

          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Interval (user turns)" description="Normal archival cadence. Lower values create smaller, more frequent sections.">
                <TextInput
                  value={form.compaction_interval?.toString() ?? ""}
                  onChangeText={(v) => { const n = parseInt(v); patch("compaction_interval", isNaN(n) ? undefined : n); }}
                  placeholder="recommended (20)"
                  type="number"
                />
              </FormRow>
            </Col>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Keep Turns" description="Recent turns kept verbatim after each compaction run. Must stay below Interval.">
                <TextInput
                  value={form.compaction_keep_turns?.toString() ?? ""}
                  onChangeText={(v) => { const n = parseInt(v); patch("compaction_keep_turns", isNaN(n) ? undefined : n); }}
                  placeholder="recommended (6)"
                  type="number"
                />
              </FormRow>
            </Col>
          </Row>

          <LlmModelDropdown
            label="Compaction Model"
            value={form.compaction_model ?? ""}
            selectedProviderId={form.compaction_model_provider_id ?? undefined}
            onChange={(v, pid) => { patch("compaction_model", v || undefined); patch("compaction_model_provider_id", pid ?? undefined); }}
            placeholder="inherit (bot model)"
          />
          <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
            Used for section generation, executive summaries, and backfill. Fast, inexpensive models usually work well because this is mostly summarization and labeling.
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
                Model used for the memory flush pass. This benefits from a more capable model because it has to decide what is worth preserving before archival.
              </div>

              {memoryScheme === "workspace-files" ? (
                <InfoBanner variant="info">
                  <strong style={{ color: t.text }}>Workspace-files mode:</strong> Uses a built-in prompt that tells the bot to write to MEMORY.md, daily logs, and reference files. Custom prompts below are ignored.
                </InfoBanner>
              ) : (
                <>
                  <WorkspaceFilePrompt
                    workspaceId={form.memory_flush_workspace_id ?? workspaceId}
                    filePath={form.memory_flush_workspace_file_path ?? null}
                    onLink={(path, wsId) => { patch("memory_flush_workspace_file_path", path); patch("memory_flush_workspace_id", wsId); patch("memory_flush_prompt_template_id", undefined); }}
                    onUnlink={() => { patch("memory_flush_workspace_file_path", undefined); patch("memory_flush_workspace_id", undefined); }}
                  />
                  {!form.memory_flush_workspace_file_path && (
                    <LlmPrompt
                      label="Memory Flush Prompt"
                      value={form.memory_flush_prompt ?? ""}
                      onChange={(v: string) => patch("memory_flush_prompt", v || undefined)}
                      placeholder="Uses global default memory flush prompt"
                      fieldType="memory_flush"
                      channelId={channelId}
                    />
                  )}
                </>
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
          <InfoBanner variant="warning" icon={<AlertTriangle size={12} />}>
            Backfill makes one LLM call per chunk of messages plus one for the executive summary. For example,
            500 messages at chunk size 50 = ~11 LLM calls using your compaction model. Set your interval and keep
            turns first. Resume only processes uncovered messages; re-chunk deletes everything and starts fresh.
          </InfoBanner>
          <BackfillButton channelId={channelId} historyMode={effectiveMode} />
        </Section>

        <Section title="Section Search" description="Search archived sections by topic, content, or semantic similarity.">
          <SectionSearch channelId={channelId} />
        </Section>

        <Section title="Archived Sections" description="Browse and manage archived conversation sections. Transcripts are stored in the database; file writing is optional (see global settings).">
          <SectionsViewer channelId={channelId} />
        </Section>
        </>
      ) : (
        <Section title="Compaction" description="Summary mode keeps a rolling summary plus recent live turns. Interval sets the normal cadence, Keep Turns holds the recent verbatim floor, and token guards can compact earlier when prompt pressure gets high." noDivider>
          <Toggle
            value={form.context_compaction ?? true}
            onChange={(v) => patch("context_compaction", v)}
            label="Enable auto-compaction"
          />
          {form.context_compaction && (
            <>
              <Row stack={isMobile}>
                <Col minWidth={isMobile ? 0 : 200}>
                  <FormRow label="Interval (user turns)" description="Normal compaction cadence. Lower values compact sooner and keep live history smaller.">
                    <TextInput
                      value={form.compaction_interval?.toString() ?? ""}
                      onChangeText={(v) => { const n = parseInt(v); patch("compaction_interval", isNaN(n) ? undefined : n); }}
                      placeholder="default (30)"
                      type="number"
                    />
                  </FormRow>
                </Col>
                <Col minWidth={isMobile ? 0 : 200}>
                  <FormRow label="Keep Turns" description="Recent turns kept verbatim after each compaction run. Higher values preserve more raw context but consume more budget.">
                    <TextInput
                      value={form.compaction_keep_turns?.toString() ?? ""}
                      onChangeText={(v) => { const n = parseInt(v); patch("compaction_keep_turns", isNaN(n) ? undefined : n); }}
                      placeholder="default (10)"
                      type="number"
                    />
                  </FormRow>
                </Col>
              </Row>

              <LlmModelDropdown
                label="Compaction Model"
                value={form.compaction_model ?? ""}
                selectedProviderId={form.compaction_model_provider_id ?? undefined}
                onChange={(v, pid) => { patch("compaction_model", v || undefined); patch("compaction_model_provider_id", pid ?? undefined); }}
                placeholder="inherit (bot model)"
              />
              <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
                Used for summarization. Fast, inexpensive models usually work well because the task is mostly condensation rather than open-ended reasoning.
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
                    <InfoBanner variant="info">
                      <strong style={{ color: t.text }}>Workspace-files mode:</strong> Uses a built-in prompt that tells the bot to write to MEMORY.md, daily logs, and reference files. Custom prompts are ignored.
                    </InfoBanner>
                  ) : (
                    <>
                      <WorkspaceFilePrompt
                        workspaceId={form.memory_flush_workspace_id ?? workspaceId}
                        filePath={form.memory_flush_workspace_file_path ?? null}
                        onLink={(path, wsId) => { patch("memory_flush_workspace_file_path", path); patch("memory_flush_workspace_id", wsId); patch("memory_flush_prompt_template_id", undefined); }}
                        onUnlink={() => { patch("memory_flush_workspace_file_path", undefined); patch("memory_flush_workspace_id", undefined); }}
                      />
                      {!form.memory_flush_workspace_file_path && (
                        <LlmPrompt
                          label="Memory Flush Prompt"
                          value={form.memory_flush_prompt ?? ""}
                          onChange={(v: string) => patch("memory_flush_prompt", v || undefined)}
                          placeholder="Uses global default memory flush prompt"
                          fieldType="memory_flush"
                          channelId={channelId}
                        />
                      )}
                    </>
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

      {/* Compaction activity — visible for all modes */}
      <Section title="Compaction Activity" description="Recent compaction events.">
        <CompactionActivity channelId={channelId} />
      </Section>

      {guideOpen && (
        <DocsMarkdownModal
          path="guides/context-management"
          title="Context Management"
          errorMessage="Failed to load context-management documentation."
          onClose={() => setGuideOpen(false)}
        />
      )}
    </>
  );
}
