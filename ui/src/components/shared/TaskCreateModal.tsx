/**
 * TaskCreateModal — clean centered modal for creating / cloning tasks.
 *
 * Single-column layout with sections: Prompt, Skills & Tools, Trigger, Configuration.
 * Full-screen on mobile, centered `min(95vw, 720px)` on desktop.
 */
import { useState, useCallback, useMemo } from "react";
import ReactDOM from "react-dom";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useTask, useCreateTask } from "@/src/api/hooks/useTasks";
import { useWorkflows } from "@/src/api/hooks/useWorkflows";
import { useSkills } from "@/src/api/hooks/useSkills";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
import { LlmPrompt } from "./LlmPrompt";
import { PromptTemplateLink } from "./PromptTemplateLink";
import { WorkspaceFilePrompt } from "./WorkspaceFilePrompt";
import { FormRow, SelectInput, Toggle, Section } from "./FormControls";
import { LlmModelDropdown } from "./LlmModelDropdown";
import { FallbackModelList } from "./FallbackModelList";
import { localInputToISO } from "@/src/utils/time";
import { useThemeTokens } from "../../theme/tokens";
import { TriggerSection, type TriggerConfig } from "./TriggerSection";
import { TASK_TYPE_OPTIONS_CREATE } from "./SchedulingPickers";

export interface TaskCreateModalProps {
  onClose: () => void;
  onSaved: () => void;
  defaultChannelId?: string;
  defaultBotId?: string;
  cloneFromId?: string;
  extraQueryKeysToInvalidate?: string[][];
}

export function TaskCreateModal({
  onClose,
  onSaved,
  defaultChannelId,
  defaultBotId,
  cloneFromId,
  extraQueryKeysToInvalidate,
}: TaskCreateModalProps) {
  const t = useThemeTokens();
  const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
  const qc = useQueryClient();

  const { data: existingTask, isLoading: loadingClone } = useTask(cloneFromId ?? undefined);
  const createMut = useCreateTask();
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const { data: workflows } = useWorkflows();
  const { data: allSkills } = useSkills();
  const { data: allTools } = useTools();

  // Form state
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [promptTemplateId, setPromptTemplateId] = useState<string | null>(null);
  const [workspaceFilePath, setWorkspaceFilePath] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [botId, setBotId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [taskType, setTaskType] = useState("scheduled");
  const [scheduledAt, setScheduledAt] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [triggerRagLoop, setTriggerRagLoop] = useState(false);
  const [modelOverride, setModelOverride] = useState("");
  const [fallbackModels, setFallbackModels] = useState<Array<{ model: string; provider_id?: string | null }>>([]);
  const [maxRunSeconds, setMaxRunSeconds] = useState<string>("");
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [workflowSessionMode, setWorkflowSessionMode] = useState<string | null>(null);
  const [triggerConfig, setTriggerConfig] = useState<TriggerConfig>({ type: "schedule" });
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [selectedToolKeys, setSelectedToolKeys] = useState<string[]>([]);
  const [initialized, setInitialized] = useState(false);

  // Populate from clone source
  if (cloneFromId && existingTask && !initialized) {
    setTitle((existingTask.title || "") + " (Clone)");
    setPrompt(existingTask.prompt || "");
    setPromptTemplateId(existingTask.prompt_template_id ?? null);
    setWorkspaceFilePath(existingTask.workspace_file_path ?? null);
    setWorkspaceId(existingTask.workspace_id ?? null);
    setBotId(existingTask.bot_id || "");
    setChannelId(existingTask.channel_id || "");
    setTaskType(existingTask.task_type || "scheduled");
    setScheduledAt("");
    setRecurrence(existingTask.recurrence || "");
    setTriggerRagLoop(existingTask.trigger_rag_loop ?? false);
    setModelOverride(existingTask.model_override ?? "");
    setFallbackModels(existingTask.fallback_models ?? []);
    setMaxRunSeconds(existingTask.max_run_seconds != null ? String(existingTask.max_run_seconds) : "");
    setWorkflowId(existingTask.workflow_id ?? null);
    setWorkflowSessionMode(existingTask.workflow_session_mode ?? null);
    if (existingTask.trigger_config) {
      setTriggerConfig(existingTask.trigger_config as TriggerConfig);
    }
    setSelectedSkillIds(existingTask.execution_config?.skills ?? []);
    setSelectedToolKeys(existingTask.execution_config?.tools ?? []);
    setInitialized(true);
  }

  // Set defaults for fresh create
  if (!cloneFromId && !initialized && bots && bots.length > 0) {
    setBotId(defaultBotId || bots[0].id);
    setChannelId(defaultChannelId || "");
    setInitialized(true);
  }

  const saving = createMut.isPending;

  const invalidateExtra = useCallback(() => {
    if (extraQueryKeysToInvalidate) {
      for (const key of extraQueryKeysToInvalidate) {
        qc.invalidateQueries({ queryKey: key });
      }
    }
  }, [qc, extraQueryKeysToInvalidate]);

  const hasPromptOrWorkflow = !!prompt.trim() || !!promptTemplateId || !!workspaceFilePath || !!workflowId;

  const handleSave = useCallback(async () => {
    if (!hasPromptOrWorkflow || !botId) return;
    try {
      const scheduledAtISO = triggerConfig.type === "schedule" ? (localInputToISO(scheduledAt) || null) : null;
      const effectiveRecurrence = triggerConfig.type === "schedule" ? (recurrence || null) : null;
      await createMut.mutateAsync({
        prompt: prompt || undefined,
        title: title || null,
        prompt_template_id: promptTemplateId,
        workspace_file_path: workspaceFilePath,
        workspace_id: workspaceId,
        bot_id: botId,
        channel_id: channelId || null,
        scheduled_at: scheduledAtISO,
        recurrence: effectiveRecurrence,
        task_type: taskType,
        trigger_rag_loop: triggerRagLoop,
        model_override: modelOverride || null,
        fallback_models: fallbackModels.length > 0 ? fallbackModels : null,
        max_run_seconds: maxRunSeconds ? parseInt(maxRunSeconds) : null,
        workflow_id: workflowId || null,
        workflow_session_mode: workflowSessionMode || null,
        trigger_config: triggerConfig,
        skills: selectedSkillIds.length > 0 ? selectedSkillIds : null,
        tools: selectedToolKeys.length > 0 ? selectedToolKeys : null,
      });
      invalidateExtra();
      onSaved();
    } catch {
      // error shown via mutation state
    }
  }, [prompt, title, botId, channelId, scheduledAt, recurrence, taskType, triggerRagLoop, modelOverride, fallbackModels, maxRunSeconds, createMut, onSaved, invalidateExtra, promptTemplateId, workspaceFilePath, workspaceId, workflowId, workflowSessionMode, hasPromptOrWorkflow, triggerConfig, selectedSkillIds, selectedToolKeys]);

  if (typeof document === "undefined") return null;

  const selectedBot = bots?.find((b) => b.id === botId);
  const botOptions = (bots || []).map((b) => ({ label: b.name || b.id, value: b.id }));
  const channelOptions = [
    { label: "\u2014 None \u2014", value: "" },
    ...(channels || []).map((c: any) => ({
      label: c.display_name || c.name || c.id,
      value: String(c.id),
    })),
  ];

  // Skills & tools available for chip picker
  const skillOptions = (allSkills || []).map((s) => ({ id: s.id, name: s.name, category: s.category }));
  const toolOptions = (allTools || []).map((t) => ({ key: t.tool_key, name: t.tool_name, source: t.source_integration }));

  const editorTitle = cloneFromId ? "New Task (Clone)" : "New Task";
  const canSave = hasPromptOrWorkflow && !!botId;

  return ReactDOM.createPortal(
    <div
      className="flex fixed inset-0 z-[10000] flex-row items-center justify-center bg-black/50"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className={`flex bg-surface ${isMobile ? "w-full h-full" : "w-[min(95vw,720px)] max-h-[85vh] rounded-[14px] shadow-2xl border border-surface-border"} overflow-hidden`}>
        {/* Header */}
        <div className="flex flex-row items-center px-5 py-3.5 border-b border-surface-border shrink-0 gap-2.5">
          <button
            onClick={onClose}
            className="flex bg-transparent border-none cursor-pointer p-1 shrink-0 rounded-md items-center justify-center hover:bg-surface-overlay"
          >
            <X size={18} className="text-text-muted" />
          </button>
          <span className="text-text text-[15px] font-bold flex-1 tracking-tight">
            {editorTitle}
          </span>
          <button
            onClick={handleSave}
            disabled={saving || !canSave}
            className={`px-6 py-2 text-[13px] font-semibold border-none rounded-lg shrink-0 transition-all duration-150 ${
              canSave
                ? "bg-accent text-white cursor-pointer hover:bg-accent-hover"
                : "bg-surface-border text-text-dim cursor-not-allowed"
            } ${saving ? "opacity-70" : ""}`}
          >
            {saving ? "Creating..." : "Create"}
          </button>
        </div>

        {/* Error display */}
        {createMut.error && (
          <div className="px-5 py-2 bg-danger/[0.08] text-danger text-xs">
            {createMut.error?.message || "An error occurred"}
          </div>
        )}

        {/* Body */}
        {cloneFromId && loadingClone ? (
          <div className="flex flex-1 items-center justify-center p-10">
            <div className="chat-spinner" />
          </div>
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
            <div className="flex gap-5">

              {/* Title */}
              <FormRow label="Title">
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Task title (optional)"
                  className="bg-input border border-surface-border rounded-lg px-3 py-2 text-text text-[13px] outline-none w-full focus:border-accent"
                />
              </FormRow>

              {/* Prompt */}
              <WorkspaceFilePrompt
                workspaceId={workspaceId ?? selectedBot?.shared_workspace_id}
                filePath={workspaceFilePath}
                onLink={(path, wsId) => { setWorkspaceFilePath(path); setWorkspaceId(wsId); setPromptTemplateId(null); }}
                onUnlink={() => { setWorkspaceFilePath(null); setWorkspaceId(null); }}
              />
              {!workspaceFilePath && (
                <>
                  <PromptTemplateLink
                    templateId={promptTemplateId}
                    onLink={(id) => setPromptTemplateId(id)}
                    onUnlink={() => setPromptTemplateId(null)}
                  />
                  <LlmPrompt
                    value={prompt}
                    onChange={setPrompt}
                    label="Prompt"
                    placeholder={workflowId ? "Optional \u2014 workflow will be triggered directly" : promptTemplateId ? "Using linked template..." : "Describe what this task should do..."}
                    rows={6}
                    fieldType="task_prompt"
                    botId={botId}
                    channelId={channelId}
                  />
                </>
              )}

              {/* Skills & Tools */}
              <Section title="Skills & Tools">
                <ChipPicker
                  label="Skills"
                  items={skillOptions.map((s) => ({ key: s.id, label: s.name, tag: s.category ?? undefined }))}
                  selected={selectedSkillIds}
                  onAdd={(id) => setSelectedSkillIds([...selectedSkillIds, id])}
                  onRemove={(id) => setSelectedSkillIds(selectedSkillIds.filter((x) => x !== id))}
                />
                <ChipPicker
                  label="Tools"
                  items={toolOptions.map((t) => ({ key: t.key, label: t.name, tag: t.source ?? undefined }))}
                  selected={selectedToolKeys}
                  onAdd={(key) => setSelectedToolKeys([...selectedToolKeys, key])}
                  onRemove={(key) => setSelectedToolKeys(selectedToolKeys.filter((x) => x !== key))}
                />
              </Section>

              {/* Trigger */}
              <Section title="Trigger">
                <TriggerSection
                  triggerConfig={triggerConfig}
                  onTriggerConfigChange={setTriggerConfig}
                  scheduledAt={scheduledAt}
                  onScheduledAtChange={setScheduledAt}
                  recurrence={recurrence}
                  onRecurrenceChange={setRecurrence}
                />
              </Section>

              {/* Configuration */}
              <Section title="Configuration">
                <FormRow label="Bot">
                  <SelectInput
                    value={botId}
                    onChange={setBotId}
                    options={botOptions}
                  />
                </FormRow>

                <FormRow label="Channel" description="Assign to a channel for dispatch">
                  <SelectInput
                    value={channelId}
                    onChange={setChannelId}
                    options={channelOptions}
                  />
                </FormRow>

                <FormRow label="Task Type">
                  <SelectInput
                    value={taskType}
                    onChange={setTaskType}
                    options={TASK_TYPE_OPTIONS_CREATE}
                  />
                </FormRow>

                <FormRow label="Workflow" description="Run a workflow instead of a prompt">
                  <SelectInput
                    value={workflowId || ""}
                    onChange={(v) => {
                      setWorkflowId(v || null);
                      if (!v) setWorkflowSessionMode(null);
                    }}
                    options={[
                      { label: "None", value: "" },
                      ...(workflows || []).map((w) => ({ label: `${w.name} (${w.id})`, value: w.id })),
                    ]}
                  />
                </FormRow>
                {workflowId && (
                  <FormRow label="Session Mode">
                    <SelectInput
                      value={workflowSessionMode || ""}
                      onChange={(v) => setWorkflowSessionMode(v || null)}
                      options={[
                        { label: "Default (from workflow)", value: "" },
                        { label: "Shared", value: "shared" },
                        { label: "Isolated", value: "isolated" },
                      ]}
                    />
                  </FormRow>
                )}

                <FormRow label="Model Override">
                  <LlmModelDropdown
                    value={modelOverride}
                    onChange={setModelOverride}
                    placeholder="Inherit from bot"
                    allowClear
                  />
                </FormRow>

                <FormRow label="Fallback Models">
                  <FallbackModelList
                    value={fallbackModels}
                    onChange={setFallbackModels}
                  />
                </FormRow>

                <FormRow label="Max run time (seconds)">
                  <input
                    type="number"
                    value={maxRunSeconds}
                    onChange={(e) => setMaxRunSeconds(e.target.value)}
                    placeholder="Inherit from channel/global"
                    className="bg-input border border-surface-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none w-full focus:border-accent"
                  />
                </FormRow>

                <Toggle
                  value={triggerRagLoop}
                  onChange={setTriggerRagLoop}
                  label="Trigger RAG Loop"
                  description="Create follow-up agent turn after task completes"
                />
              </Section>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// ChipPicker — searchable chip list for skills/tools
// ---------------------------------------------------------------------------
export function ChipPicker({ label, items, selected, onAdd, onRemove }: {
  label: string;
  items: { key: string; label: string; tag?: string }[];
  selected: string[];
  onAdd: (key: string) => void;
  onRemove: (key: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);

  const filtered = useMemo(() => {
    const term = search.toLowerCase();
    return items
      .filter((i) => !selected.includes(i.key))
      .filter((i) => !term || i.label.toLowerCase().includes(term) || (i.tag ?? "").toLowerCase().includes(term))
      .slice(0, 20);
  }, [items, selected, search]);

  const selectedItems = items.filter((i) => selected.includes(i.key));

  return (
    <div className="flex gap-2">
      <div className="text-[11px] text-text-dim font-semibold uppercase tracking-wider">
        {label}
        {selectedItems.length > 0 && (
          <span className="ml-1.5 text-accent font-bold">{selectedItems.length}</span>
        )}
      </div>
      <div className="flex flex-row gap-1.5 flex-wrap items-center min-h-[32px]">
        {selectedItems.map((item) => (
          <span
            key={item.key}
            className="inline-flex flex-row items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-accent/[0.08] text-accent border border-accent/20"
          >
            {item.label}
            <button
              onClick={() => onRemove(item.key)}
              className="bg-transparent border-none cursor-pointer text-sm text-accent p-0 leading-none opacity-60 hover:opacity-100"
            >
              &times;
            </button>
          </span>
        ))}
        <div className="relative">
          <button
            onClick={() => setOpen(!open)}
            className={`px-3 py-1 text-[11px] font-semibold rounded-full bg-transparent cursor-pointer transition-colors duration-150 ${
              open
                ? "border border-dashed border-accent text-accent"
                : "border border-dashed border-surface-border text-text-muted hover:border-accent/50 hover:text-text-muted"
            }`}
          >
            + Add
          </button>
          {open && (
            <div className="absolute top-full left-0 mt-1.5 w-[260px] max-h-[220px] overflow-y-auto bg-surface border border-surface-border rounded-[10px] shadow-xl z-10">
              <div className="p-2 border-b border-surface-border">
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={`Search ${label.toLowerCase()}...`}
                  autoFocus
                  className="w-full px-2.5 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent"
                />
              </div>
              {filtered.length === 0 ? (
                <div className="px-3.5 py-3 text-[11px] text-text-dim">
                  {items.length === 0 ? `No ${label.toLowerCase()} available` : "No matches"}
                </div>
              ) : (
                filtered.map((item) => (
                  <button
                    key={item.key}
                    onClick={() => { onAdd(item.key); setOpen(false); setSearch(""); }}
                    className="flex flex-row items-center gap-2 w-full px-3.5 py-2 text-xs bg-transparent border-none cursor-pointer text-text text-left transition-colors duration-100 hover:bg-surface-raised"
                  >
                    <span className="flex-1">{item.label}</span>
                    {item.tag && (
                      <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-raised">
                        {item.tag}
                      </span>
                    )}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
