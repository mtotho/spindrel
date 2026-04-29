/**
 * TaskFormFields — shared presentational field groups for task create/edit.
 *
 * Three named exports: ContentFields, ExecutionFields, TriggerFields.
 * Each receives a slice of TaskFormState and renders the appropriate form controls.
 */
import { useState, useRef } from "react";
import { ChevronRight, Code2, LayoutList } from "lucide-react";
import type { StepDef } from "@/src/api/hooks/useTasks";
import { LlmPrompt } from "../LlmPrompt";
import { PromptTemplateLink } from "../PromptTemplateLink";
import { WorkspaceFilePrompt } from "../WorkspaceFilePrompt";
import { FormRow, SelectInput, Toggle } from "../FormControls";
import { LlmModelDropdown } from "../LlmModelDropdown";
import { FallbackModelList } from "../FallbackModelList";
import { TriggerSection, type TriggerConfig } from "../TriggerSection";
import { TaskStepEditor } from "../TaskStepEditor";
import { StepsJsonEditor } from "./StepsJsonEditor";
import { StepsSchemaModal } from "./StepsSchemaModal";
import { BotPicker } from "../BotPicker";
import { ChannelPicker } from "../ChannelPicker";
import { SessionTargetPicker } from "../SessionTargetPicker";
import { ChipPicker, ToolMultiPicker } from "./ChipPicker";
import type { TaskFormState } from "./useTaskFormState";

// ---------------------------------------------------------------------------
// Content Fields — Title, Prompt/Steps toggle, prompt or pipeline editor
// ---------------------------------------------------------------------------

export function ContentFields({ form, promptRows, hideStepEditor }: { form: TaskFormState; promptRows?: number; hideStepEditor?: boolean }) {
  const {
    title, setTitle, prompt, setPrompt,
    promptTemplateId, setPromptTemplateId,
    workspaceFilePath, setWorkspaceFilePath, workspaceId, setWorkspaceId,
    workflowId, steps, setSteps, stepsMode,
    botId, channelId, selectedBot, existingTask,
  } = form;

  const stashedSteps = useRef<StepDef[] | null>(null);
  const [jsonMode, setJsonMode] = useState(false);

  const toggleToSteps = () => {
    if (!stepsMode) {
      // Restore previously stashed steps if available
      if (stashedSteps.current && stashedSteps.current.length > 0) {
        setSteps(stashedSteps.current);
        stashedSteps.current = null;
      } else {
        const initial: StepDef[] = prompt.trim()
          ? [{ id: "step_1", type: "agent", prompt, label: "", on_failure: "abort" }]
          : [];
        setSteps(initial);
      }
    }
  };

  const toggleToPrompt = () => {
    if (stepsMode) {
      // Stash current steps so toggling back restores them
      stashedSteps.current = steps && steps.length > 0 ? [...steps] : null;
      if (steps && steps.length === 1 && steps[0].type === "agent") {
        form.setPrompt(steps[0].prompt ?? "");
      }
      setSteps(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <FormRow label="Title">
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Task title (optional)"
          className="bg-input border border-surface-border rounded-lg px-3 py-2 text-text text-[13px] outline-none w-full focus:border-accent/40"
        />
      </FormRow>

      {/* Mode toggle: Prompt | Pipeline */}
      {!workflowId && (
        <div className="flex flex-row items-center gap-0 bg-surface-raised/40 rounded-md p-1 w-fit">
          <button
            onClick={toggleToPrompt}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md border-none transition-colors ${
              !stepsMode
                ? "bg-surface-overlay text-text"
                : "bg-transparent text-text-dim hover:text-text cursor-pointer"
            }`}
          >
            Prompt
          </button>
          <button
            onClick={toggleToSteps}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md border-none transition-colors ${
              stepsMode
                ? "bg-surface-overlay text-text"
                : "bg-transparent text-text-dim hover:text-text cursor-pointer"
            }`}
          >
            Pipeline
          </button>
        </div>
      )}

      {/* Prompt mode */}
      {!stepsMode && (
        <>
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
                rows={promptRows ?? 6}
                fieldType="task_prompt"
                botId={botId}
                channelId={channelId}
              />
            </>
          )}
        </>
      )}

      {/* Steps mode — hint when editor is hidden (canvas tile) */}
      {stepsMode && hideStepEditor && (
        <div className="px-3 py-3 rounded-md bg-surface-raised/40 border border-surface-border/60 text-[11.5px] text-text-dim leading-snug">
          Pipeline steps live as tiles on the canvas. Use <span className="font-semibold text-text">+ Add Step</span> to create one.
        </div>
      )}

      {/* Steps mode */}
      {stepsMode && !hideStepEditor && (
        <>
          {/* Visual / JSON tab strip + schema help */}
          <div className="flex flex-row items-center gap-2">
            <div
              data-testid="steps-tab-strip"
              className="flex flex-row items-center gap-0 bg-surface-raised/40 rounded-md p-1"
            >
              <button
                onClick={() => setJsonMode(false)}
                data-testid="steps-tab-visual"
                className={`flex flex-row items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded border-none transition-colors ${
                  !jsonMode
                    ? "bg-surface-overlay text-text"
                    : "bg-transparent text-text-dim hover:text-text cursor-pointer"
                }`}
              >
                <LayoutList size={12} />
                Visual
              </button>
              <button
                onClick={() => setJsonMode(true)}
                data-testid="steps-tab-json"
                className={`flex flex-row items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded border-none transition-colors ${
                  jsonMode
                    ? "bg-surface-overlay text-text"
                    : "bg-transparent text-text-dim hover:text-text cursor-pointer"
                }`}
              >
                <Code2 size={12} />
                JSON
              </button>
            </div>
            {jsonMode && <StepsSchemaModal />}
          </div>

          {jsonMode ? (
            <StepsJsonEditor
              steps={steps!}
              onChange={setSteps}
            />
          ) : (
            <TaskStepEditor
              steps={steps!}
              onChange={setSteps}
              stepStates={existingTask?.parent_task_id ? existingTask?.step_states : undefined}
              readOnly={false}
            />
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Execution Fields — Bot, Channel, Skills & Tools, Model, Fallback
// ---------------------------------------------------------------------------

export function ExecutionFields({ form, disableChannel }: { form: TaskFormState; disableChannel?: boolean }) {
  const {
    botId, setBotId, channelId, setChannelId,
    selectedSkillIds, setSelectedSkillIds,
    selectedToolKeys, setSelectedToolKeys,
    modelOverride, setModelOverride,
    harnessEffort, setHarnessEffort,
    skipToolApproval, setSkipToolApproval,
    fallbackModels, setFallbackModels,
    bots, channels, skillOptions, allTools,
    sessionTarget, setSessionTarget,
    postFinalToChannel, setPostFinalToChannel,
    historyMode, setHistoryMode,
    historyRecentCount, setHistoryRecentCount,
  } = form;

  return (
    <div className="flex flex-col gap-5">
      <FormRow label="Bot">
        <BotPicker
          value={botId}
          onChange={setBotId}
          bots={bots ?? []}
        />
      </FormRow>

      <FormRow label="Channel" description="Assign to a channel for dispatch">
        <ChannelPicker
          value={channelId}
          onChange={disableChannel ? () => {} : setChannelId}
          channels={channels ?? []}
          bots={bots}
          allowNone
          disabled={disableChannel}
        />
      </FormRow>

      <FormRow label="Run target" description="Choose which channel session scheduled and manual runs use.">
        <SessionTargetPicker
          channelId={channelId || null}
          value={sessionTarget}
          onChange={setSessionTarget}
          disabled={disableChannel}
        />
      </FormRow>

      {/* Skills & Tools */}
      <div className="flex flex-col gap-4">
        <ChipPicker
          label="Skills"
          items={skillOptions}
          selected={selectedSkillIds}
          onAdd={(id) => setSelectedSkillIds([...selectedSkillIds, id])}
          onRemove={(id) => setSelectedSkillIds(selectedSkillIds.filter((x) => x !== id))}
        />
        <ToolMultiPicker
          tools={allTools}
          selected={selectedToolKeys}
          onAdd={(key) => setSelectedToolKeys([...selectedToolKeys, key])}
          onRemove={(key) => setSelectedToolKeys(selectedToolKeys.filter((x) => x !== key))}
        />
        <Toggle
          value={skipToolApproval}
          onChange={setSkipToolApproval}
          label="Auto-approve tool calls"
          description="For automated runs only. Selected tools can run without waiting for manual approval."
        />
      </div>

      {/* Channel output — dispatch + history */}
      {channelId && (
        <div className="flex flex-col gap-3 rounded-lg border border-surface-border/70 bg-surface-raised/30 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">
            Channel output
          </div>
          <Toggle
            value={postFinalToChannel}
            onChange={setPostFinalToChannel}
            label="Post summary to channel"
            description="Off: run lives only in the envelope card. On: a condensed summary is dispatched through the channel's connected integrations (Slack, Discord, etc.)."
          />
          <FormRow
            label="Chat context"
            description="What prior channel messages each agent step sees."
          >
            <div className="flex items-center gap-1 rounded-md border border-surface-border bg-input p-0.5 w-fit">
              {(["none", "recent", "full"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setHistoryMode(m)}
                  className={`px-3 py-1 rounded text-[11.5px] font-medium capitalize cursor-pointer border-none transition-colors ${
                    historyMode === m
                      ? "bg-accent/20 text-accent"
                      : "bg-transparent text-text-muted hover:text-text"
                  }`}
                >
                  {m === "recent" ? `last ${historyRecentCount}` : m}
                </button>
              ))}
            </div>
          </FormRow>
          {historyMode === "recent" && (
            <FormRow label="Messages">
              <input
                type="range"
                min={1}
                max={50}
                step={1}
                value={historyRecentCount}
                onChange={(e) => setHistoryRecentCount(Number(e.target.value))}
                className="w-full accent-accent"
              />
              <span className="ml-2 font-mono text-[11.5px] text-text-muted">
                {historyRecentCount}
              </span>
            </FormRow>
          )}
        </div>
      )}

      {/* Advanced — model config */}
      <AdvancedDisclosure label="Model Configuration">
        <FormRow label="Model Override">
          <LlmModelDropdown
            value={modelOverride}
            onChange={setModelOverride}
            placeholder="Inherit from bot"
            allowClear
          />
        </FormRow>
        {form.selectedBot?.harness_runtime && (
          <FormRow label="Harness Effort">
            <SelectInput
              value={harnessEffort || ""}
              onChange={(value) => setHarnessEffort(value || "")}
              options={[
                { label: "inherit", value: "" },
                { label: "low", value: "low" },
                { label: "medium", value: "medium" },
                { label: "high", value: "high" },
              ]}
            />
          </FormRow>
        )}
        <FormRow label="Fallback Models">
          <FallbackModelList
            value={fallbackModels}
            onChange={setFallbackModels}
          />
        </FormRow>
      </AdvancedDisclosure>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trigger Fields — Trigger type, schedule config, max run time, RAG loop
// ---------------------------------------------------------------------------

export function TriggerFields({ form }: { form: TaskFormState }) {
  const {
    triggerConfig, setTriggerConfig,
    scheduledAt, setScheduledAt,
    recurrence, setRecurrence,
    maxRunSeconds, setMaxRunSeconds,
    triggerRagLoop, setTriggerRagLoop,
  } = form;

  return (
    <div className="flex flex-col gap-5">
      <TriggerSection
        triggerConfig={triggerConfig}
        onTriggerConfigChange={setTriggerConfig}
        scheduledAt={scheduledAt}
        onScheduledAtChange={setScheduledAt}
        recurrence={recurrence}
        onRecurrenceChange={setRecurrence}
      />

      <FormRow label="Max run time (seconds)">
        <input
          type="number"
          value={maxRunSeconds}
          onChange={(e) => setMaxRunSeconds(e.target.value)}
          placeholder="Inherit from channel/global"
          className="bg-input border border-surface-border rounded-lg px-3 py-[7px] text-text text-[13px] outline-none w-full focus:border-accent/40"
        />
      </FormRow>

      <Toggle
        value={triggerRagLoop}
        onChange={setTriggerRagLoop}
        label="Trigger RAG Loop"
        description="Create follow-up agent turn after task completes"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// AdvancedDisclosure — collapsible section for rarely-used options
// ---------------------------------------------------------------------------

function AdvancedDisclosure({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex flex-row items-center gap-1.5 text-[11px] font-semibold text-text-dim uppercase tracking-wider bg-transparent border-none cursor-pointer hover:text-text transition-colors py-1"
      >
        <ChevronRight
          size={12}
          className={`transition-transform duration-150 ${open ? "rotate-90" : ""}`}
        />
        {label}
      </button>
      {open && (
        <div className="flex flex-col gap-4 mt-2 pl-1">
          {children}
        </div>
      )}
    </div>
  );
}
