import { useState } from "react";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import {
  Section, FormRow, SelectInput, TextInput, Toggle, Row, Col,
} from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { InfoBanner, QuietPill, SettingsSegmentedControl } from "@/src/components/shared/SettingsControls";
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
export type SectionScope = "current" | "all";

type NativeContextPolicy = NonNullable<ChannelSettings["effective_native_context_policy"]>;

function resolvedNativeContextPolicy(form: Partial<ChannelSettings>): NativeContextPolicy {
  if (form.native_context_policy && form.native_context_policy !== "default") {
    return form.native_context_policy;
  }
  return form.effective_native_context_policy ?? "standard";
}

function replayBudgetLabel(policy?: string | null): string {
  switch (policy) {
    case "lean":
      return "Low Budget";
    case "rich":
      return "High Budget";
    case "manual":
      return "Manual";
    case "standard":
    default:
      return "Medium Budget";
  }
}

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
  const isMobile = useIsMobile();
  const [guideOpen, setGuideOpen] = useState(false);
  const [sectionScope, setSectionScope] = useState<SectionScope>("current");
  const effectiveMode = form.history_mode || botHistoryMode || "file";
  const isFileOrStructured = effectiveMode === "file" || effectiveMode === "structured";
  const activeContextPolicy = resolvedNativeContextPolicy(form);
  const serverContextPolicy = form.server_native_context_policy_default ?? "standard";
  const activeContextSource = form.native_context_policy && form.native_context_policy !== "default" ? "channel override" : "server default";
  const effectiveContextLabel = replayBudgetLabel(activeContextPolicy);
  const serverContextLabel = replayBudgetLabel(serverContextPolicy);

  return (
    <>
      {/* 1. History Mode cards — always visible at top */}
      <HistoryModeSection form={form} patch={patch} botHistoryMode={botHistoryMode} onOpenGuide={() => setGuideOpen(true)} />

      <Section
        title="Model Replay Budget"
        description="Controls how much recent raw chat normal Spindrel turns try to replay into the model. Replay is token-fit and model-scaled; harness agents and scheduled work use separate policies."
        noDivider
        action={<QuietPill label={`effective: ${effectiveContextLabel}${activeContextSource === "channel override" ? " (channel override)" : ""}`} />}
      >
        <FormRow
          label="Replay budget preset"
          description="Low, Medium, and High choose the token slice for raw conversation replay. This does not decide when older history is archived."
        >
          <SelectInput
            value={(form.native_context_policy ?? "default") as string}
            onChange={(value) => patch("native_context_policy", value as ChannelSettings["native_context_policy"])}
            options={[
              { label: `Default — inherit server: ${serverContextLabel}`, value: "default" },
              { label: "Low Budget — tight token-fit replay, on-demand context", value: "lean" },
              { label: "Medium Budget — adaptive replay plus selected RAG/context", value: "standard" },
              { label: "High Budget — larger replay and broader ambient context", value: "rich" },
              { label: "Manual — custom replay and pressure thresholds", value: "manual" },
            ]}
          />
        </FormRow>
        {form.native_context_policy === "manual" && (
          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Replay Budget" description="Fraction of usable model context reserved for raw chat replay. Example: 0.45 = 45%.">
                <TextInput
                  value={form.native_context_live_history_ratio?.toString() ?? ""}
                  onChangeText={(v) => { const n = parseFloat(v); patch("native_context_live_history_ratio", Number.isNaN(n) ? undefined : n); }}
                  placeholder="0.45"
                  type="number"
                />
              </FormRow>
            </Col>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Recent Floor" description="Newest user turns kept even if they exceed the replay target.">
                <TextInput
                  value={form.native_context_min_recent_turns?.toString() ?? ""}
                  onChangeText={(v) => { const n = parseInt(v); patch("native_context_min_recent_turns", Number.isNaN(n) ? undefined : n); }}
                  placeholder="2"
                  type="number"
                />
              </FormRow>
            </Col>
          </Row>
        )}
        <InfoBanner variant="info">
          <strong className="text-text">Relationship:</strong> Replay budget answers "what raw recent chat can the model see now?" Archive cadence below answers "when do older messages get summarized into sections?" Section Index is the compact map of archived sections.
        </InfoBanner>
      </Section>

      {/* 2. Compaction settings — conditional on mode */}
      {isFileOrStructured ? (
        <>
        <Section
          title="Archive / Compaction Cadence"
          description="Controls when Spindrel writes older conversation into summaries or sections. These settings do not cap normal chat replay; replay is token-budgeted by Model Replay Budget above."
          noDivider
        >
          <div className="text-xs leading-relaxed text-text-dim">
            {effectiveMode === "structured"
              ? "Structured mode is a legacy compatibility path that archives older turns into searchable sections and tries to retrieve relevant history automatically."
              : "File mode archives older turns into titled sections. Normal chat still replays recent raw turns by token budget; archived sections remain searchable on demand with read_conversation_history."}
          </div>

          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Archive every (user turns)" description="Normal cadence for creating archived sections. Lower values create smaller, more frequent sections.">
                <TextInput
                  value={form.compaction_interval?.toString() ?? ""}
                  onChangeText={(v) => { const n = parseInt(v); patch("compaction_interval", isNaN(n) ? undefined : n); }}
                  placeholder="recommended (20)"
                  type="number"
                />
              </FormRow>
            </Col>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Keep out of archive" description="Newest user turns excluded from each archive run so they remain raw recent history. Normal chat may replay more raw turns when token budget allows.">
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
            className="md:max-w-[560px]"
          />
          <div className="-mt-1 mb-1 text-[10px] text-text-dim">
            Used for section generation, executive summaries, and backfill. Fast, inexpensive models usually work well because this is mostly summarization and labeling.
          </div>

          {/* Memory Flush */}
          <Toggle
            value={!!form.memory_flush_enabled}
            onChange={(v) => patch("memory_flush_enabled", v || undefined)}
            label="Memory flush before compaction"
          />
          <div className="-mt-1 mb-1 text-[10px] text-text-dim">
            {memoryScheme === "workspace-files"
              ? "Before archiving, the bot gets one pass to save important context — updating MEMORY.md, daily logs, and reference files via the file tool."
              : "Before archiving, the bot gets one pass to save important context using its configured memory tools."
            }
          </div>

          {form.memory_flush_enabled && (
            <>
              <LlmModelDropdown
                label="Memory Flush Model"
                value={form.memory_flush_model ?? ""}
                selectedProviderId={form.memory_flush_model_provider_id ?? undefined}
                onChange={(v, pid) => { patch("memory_flush_model", v || undefined); patch("memory_flush_model_provider_id", pid ?? undefined); }}
                placeholder="inherit (bot model)"
                className="md:max-w-[560px]"
              />
              <div className="-mt-1 mb-1 text-[10px] text-text-dim">
                Model used for the memory flush pass. This benefits from a more capable model because it has to decide what is worth preserving before archival.
              </div>

              {memoryScheme === "workspace-files" ? (
                <InfoBanner variant="info">
                  <strong className="text-text">Workspace-files mode:</strong> Uses a built-in prompt that tells the bot to write to MEMORY.md, daily logs, and reference files. Custom prompts below are ignored.
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
              <div className="-mt-1 mb-1 text-[10px] text-text-dim">
                Legacy option — fires channel heartbeats before compaction. Use "Memory flush" above instead for a dedicated, configurable flush pass.
              </div>
            </>
          )}
        </Section>

        <Section title="Section Index" description="Overrides the section-index part of the replay budget policy. This is why lean replay can still preserve older topic recall without replaying the whole chat.">
          <SectionIndexSettings form={form} patch={patch} channelId={channelId} />
        </Section>

        <Section title="Backfill" description="Retroactively create archived sections from existing message history.">
          <div className="flex max-w-[95ch] items-start gap-2 text-[12px] leading-relaxed text-text-dim">
            <AlertTriangle size={12} className="mt-0.5 shrink-0 text-warning-muted/80" />
            <span>
              Backfill works on the channel's current primary session. It makes one LLM call per chunk plus one
              executive-summary call. At 500 messages with chunk size 50, expect about 11 calls. Resume only covers
              uncovered messages in the current session; re-chunk deletes that session's existing sections and starts over.
            </span>
          </div>
          <BackfillButton channelId={channelId} historyMode={effectiveMode} />
        </Section>

        <Section title="Archive Scope" description="Current session mirrors what the active chat can browse. All sessions is an admin inventory view across this channel's sessions.">
          <SettingsSegmentedControl<SectionScope>
            value={sectionScope}
            onChange={setSectionScope}
            options={[
              { value: "current", label: "Current session" },
              { value: "all", label: "All sessions" },
            ]}
          />
        </Section>

        <Section title="Section Search" description={sectionScope === "current" ? "Search the active session's archived sections by topic, content, or semantic similarity." : "Search archived sections across sessions in this channel."}>
          <SectionSearch channelId={channelId} scope={sectionScope} />
        </Section>

        <Section title="Archived Sections" description={sectionScope === "current" ? "Browse the active session archive. Transcripts are stored in the database; file writing is optional." : "Browse the channel archive inventory grouped by session."}>
          <SectionsViewer channelId={channelId} scope={sectionScope} onScopeChange={setSectionScope} />
        </Section>
        </>
      ) : (
        <Section title="Summary Compaction Cadence" description="Controls when summary-mode sessions roll older conversation into the running summary. These settings do not directly cap normal chat replay." noDivider>
          <Toggle
            value={form.context_compaction ?? true}
            onChange={(v) => patch("context_compaction", v)}
            label="Enable auto-compaction"
          />
          {form.context_compaction && (
            <>
              <Row stack={isMobile}>
                <Col minWidth={isMobile ? 0 : 200}>
                  <FormRow label="Compact every (user turns)" description="Normal cadence for rolling older turns into the summary.">
                    <TextInput
                      value={form.compaction_interval?.toString() ?? ""}
                      onChangeText={(v) => { const n = parseInt(v); patch("compaction_interval", isNaN(n) ? undefined : n); }}
                      placeholder="default (30)"
                      type="number"
                    />
                  </FormRow>
                </Col>
                <Col minWidth={isMobile ? 0 : 200}>
                  <FormRow label="Keep out of summary" description="Newest user turns excluded from each summary pass. Higher values preserve more raw context before summary-mode compaction.">
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
                className="md:max-w-[560px]"
              />
              <div className="-mt-1 mb-1 text-[10px] text-text-dim">
                Used for summarization. Fast, inexpensive models usually work well because the task is mostly condensation rather than open-ended reasoning.
              </div>

              {/* Memory Flush */}
              <Toggle
                value={!!form.memory_flush_enabled}
                onChange={(v) => patch("memory_flush_enabled", v || undefined)}
                label="Memory flush before compaction"
              />
              <div className="-mt-1 mb-1 text-[10px] text-text-dim">
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
                    selectedProviderId={form.memory_flush_model_provider_id ?? undefined}
                    onChange={(v, pid) => { patch("memory_flush_model", v || undefined); patch("memory_flush_model_provider_id", pid ?? undefined); }}
                    placeholder="inherit (bot model)"
                    className="md:max-w-[560px]"
                  />

                  {memoryScheme === "workspace-files" ? (
                    <InfoBanner variant="info">
                      <strong className="text-text">Workspace-files mode:</strong> Uses a built-in prompt that tells the bot to write to MEMORY.md, daily logs, and reference files. Custom prompts are ignored.
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
                  <div className="-mt-1 mb-1 text-[10px] text-text-dim">
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
