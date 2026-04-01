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
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const isFileOrStructured = effectiveMode === "file" || effectiveMode === "structured";

  return (
    <>
      {/* 1. History Mode cards — always visible at top */}
      <HistoryModeSection form={form} patch={patch} botHistoryMode={botHistoryMode} />

      {/* 2. Compaction settings — conditional on mode */}
      {isFileOrStructured ? (
        <>
        <Section title="Archival Settings" description="Manages long conversations by archiving old turns into titled sections.">
          {/* Locked banner */}
          <InfoBanner variant="warning">
            <span style={{ fontWeight: 600 }}>
              Auto-compaction is always on in {effectiveMode} mode — it creates the archived sections the bot navigates.
            </span>
          </InfoBanner>

          {/* File-mode guidance */}
          <div style={{
            padding: "12px 14px", background: t.codeBg, border: `1px solid ${t.codeBorder}`,
            borderRadius: 8, fontSize: 11, color: t.textMuted, lineHeight: "1.6",
          }}>
            After every <strong style={{ color: t.text }}>Interval</strong> user turns, the oldest messages are
            archived into a titled, summarized section. The bot keeps the last <strong style={{ color: t.text }}>Keep Turns</strong> verbatim,
            plus an executive summary and section index. It can open any section with the <code style={{ color: t.codeText }}>read_conversation_history</code> tool.
            <div style={{ marginTop: 8, color: t.warningMuted }}>
              Recommended: Interval 20, Keep Turns 6 — lower interval = more granular sections.
              The bot can always read full transcripts, so aggressive archival is safe.
            </div>
          </div>

          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Interval (user turns)" description="Compaction triggers after this many user messages. Lower = more frequent archival.">
                <TextInput
                  value={form.compaction_interval?.toString() ?? ""}
                  onChangeText={(v) => patch("compaction_interval", v ? parseInt(v) || undefined : undefined)}
                  placeholder="recommended (20)"
                  type="number"
                />
              </FormRow>
            </Col>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Keep Turns" description="Recent turns always kept verbatim — never archived.">
                <TextInput
                  value={form.compaction_keep_turns?.toString() ?? ""}
                  onChangeText={(v) => patch("compaction_keep_turns", v ? parseInt(v) || undefined : undefined)}
                  placeholder="recommended (6)"
                  type="number"
                />
              </FormRow>
            </Col>
          </Row>

          <LlmModelDropdown
            label="Compaction Model"
            value={form.compaction_model ?? ""}
            onChange={(v) => patch("compaction_model", v || undefined)}
            placeholder="inherit (bot model)"
          />
          <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
            Used for section generation, executive summaries, and backfill. A cheap/fast model works well here — the prompts are straightforward summarization.
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
                Model used for the memory flush pass. A capable model works best here since it needs to reason about what to save.
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
        <Section title="Compaction" description="Manages long conversations by periodically summarizing old turns.">
          <Toggle
            value={form.context_compaction ?? true}
            onChange={(v) => patch("context_compaction", v)}
            label="Enable auto-compaction"
          />
          {form.context_compaction && (
            <>
              <div style={{
                padding: "14px 16px", background: t.codeBg, border: `1px solid ${t.codeBorder}`,
                borderRadius: 8, marginBottom: 4,
              }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: t.accent, marginBottom: 8 }}>How Compaction Works</div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.6" }}>
                  After every <strong style={{ color: t.text }}>Interval</strong> user turns, the oldest messages
                  are archived and summarized by an LLM. The most recent <strong style={{ color: t.text }}>Keep Turns</strong> are
                  always preserved verbatim. If memory flush is enabled below, the bot gets a "last chance" pass
                  to save important context before summarization.
                </div>
                <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.6", marginTop: 8 }}>
                  <strong style={{ color: t.text }}>Example:</strong> Interval=30, Keep Turns=10 {"\u2192"} after 30 user messages,
                  the oldest 20 are summarized. The bot always sees the last 10 turns plus the summary.
                </div>
              </div>

              <Row stack={isMobile}>
                <Col minWidth={isMobile ? 0 : 200}>
                  <FormRow label="Interval (user turns)" description="Compaction triggers after this many user messages accumulate. Lower = more frequent, tighter context. Default: 30.">
                    <TextInput
                      value={form.compaction_interval?.toString() ?? ""}
                      onChangeText={(v) => patch("compaction_interval", v ? parseInt(v) || undefined : undefined)}
                      placeholder="default (30)"
                      type="number"
                    />
                  </FormRow>
                </Col>
                <Col minWidth={isMobile ? 0 : 200}>
                  <FormRow label="Keep Turns" description="Recent turns always kept verbatim — never summarized. Higher = more immediate context but less room for RAG/tools. Default: 10.">
                    <TextInput
                      value={form.compaction_keep_turns?.toString() ?? ""}
                      onChangeText={(v) => patch("compaction_keep_turns", v ? parseInt(v) || undefined : undefined)}
                      placeholder="default (10)"
                      type="number"
                    />
                  </FormRow>
                </Col>
              </Row>

              <div style={{
                padding: "12px 14px", background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 8, display: "flex", flexDirection: "column", gap: 6,
              }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted }}>Quick Guide</div>
                <div style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5" }}>
                  <strong style={{ color: t.contentText }}>Casual chatbot:</strong> Interval 20, Keep 6 — compacts often, keeps things lean.
                </div>
                <div style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5" }}>
                  <strong style={{ color: t.contentText }}>Project assistant:</strong> Interval 30, Keep 10 — balanced, good for task tracking.
                </div>
                <div style={{ fontSize: 11, color: t.textDim, lineHeight: "1.5" }}>
                  <strong style={{ color: t.contentText }}>Long-running agent:</strong> Interval 40+, Keep 12 — more raw context, fewer compaction LLM calls.
                </div>
                <div style={{ fontSize: 11, color: t.warningMuted, lineHeight: "1.5", marginTop: 4 }}>
                  Keep Turns must be less than Interval — otherwise nothing gets summarized.
                </div>
              </div>

              <LlmModelDropdown
                label="Compaction Model"
                value={form.compaction_model ?? ""}
                onChange={(v) => patch("compaction_model", v || undefined)}
                placeholder="inherit (bot model)"
              />
              <div style={{ fontSize: 10, color: t.textDim, marginTop: -4, marginBottom: 4 }}>
                Used for summarization. A cheap/fast model works well — the prompts are straightforward.
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
    </>
  );
}
