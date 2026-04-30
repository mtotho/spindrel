import { useState, useMemo } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { CalendarPlus, Plus, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { EmptyState, FormRow, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { ActionButton, QuietPill, SettingsSegmentedControl } from "@/src/components/shared/SettingsControls";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { RecurrencePicker, ScheduleSummary, ScheduledAtPicker } from "@/src/components/shared/SchedulingPickers";
import { TaskEditor as TaskEditorShared } from "@/src/components/shared/TaskEditor";
import { TaskCardRow } from "@/src/components/shared/TaskCardRow";
import type { TaskItem } from "@/src/components/shared/TaskConstants";
import { apiFetch } from "@/src/api/client";
import { useCreateTask } from "@/src/api/hooks/useTasks";
import type { TaskCreatePayload } from "@/src/api/hooks/useTasks";
import { useRunPresets } from "@/src/api/hooks/useRunPresets";
import type { RunPreset } from "@/src/api/hooks/useRunPresets";
import { useQuery, useQueryClient } from "@tanstack/react-query";

// Task types that users create and can edit inline
const EDITABLE_TASK_TYPES = new Set(["scheduled", "agent"]);

type StatusFilter = "all" | "active" | "failed";

const STATUS_PILL_KEYS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "failed", label: "Failed" },
];

const ACTIVE_STATUSES = new Set(["pending", "running", "active"]);

type QuickAutomationDraft = {
  title: string;
  prompt: string;
  scheduled_at: string;
  recurrence: string;
  post_final_to_channel: boolean;
};

const START_OFFSET_MS: Record<string, number> = {
  s: 1000,
  m: 60_000,
  h: 3_600_000,
  d: 86_400_000,
  w: 604_800_000,
};

function toLocalDateTimeInput(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function scheduledAtForPicker(value: string | null | undefined): string {
  if (!value) return "";
  const match = value.match(/^\+(\d+)([smhdw])$/);
  if (!match) return value;
  const amount = Number.parseInt(match[1], 10);
  const unit = match[2];
  const ms = amount * (START_OFFSET_MS[unit] ?? 0);
  return toLocalDateTimeInput(new Date(Date.now() + ms));
}

function draftFromPreset(preset: RunPreset): QuickAutomationDraft {
  const defaults = preset.task_defaults!;
  return {
    title: defaults.title,
    prompt: defaults.prompt,
    scheduled_at: scheduledAtForPicker(defaults.scheduled_at),
    recurrence: defaults.recurrence ?? "",
    post_final_to_channel: defaults.post_final_to_channel,
  };
}

function buildPresetTaskPayload(
  preset: RunPreset,
  draft: QuickAutomationDraft,
  channelId: string,
  botId: string,
): TaskCreatePayload {
  const defaults = preset.task_defaults;
  if (!defaults) throw new Error("Task preset is missing task defaults.");
  return {
    bot_id: botId,
    channel_id: channelId,
    session_target: { mode: "primary" },
    title: draft.title.trim() || defaults.title,
    prompt: draft.prompt,
    scheduled_at: draft.scheduled_at || null,
    recurrence: draft.recurrence || null,
    task_type: defaults.task_type,
    trigger_config: defaults.trigger_config,
    skills: defaults.skills,
    tools: defaults.tools,
    post_final_to_channel: draft.post_final_to_channel,
    history_mode: defaults.history_mode,
    history_recent_count: defaults.history_recent_count,
    skip_tool_approval: defaults.skip_tool_approval,
  };
}

function TaskGroup({
  label,
  count,
  children,
}: {
  label: string;
  count: number;
  children: ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
          {label}
        </span>
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] font-semibold text-text-dim">
          {count}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  );
}

function QuickAutomations({
  presets,
  isLoading,
  onSelect,
}: {
  presets: RunPreset[];
  isLoading: boolean;
  onSelect: (preset: RunPreset) => void;
}) {
  if (!isLoading && presets.length === 0) return null;

  return (
    <div className="flex flex-col gap-2" data-testid="channel-quick-automations">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
            Quick automations
          </div>
          <div className="mt-0.5 text-[12px] text-text-dim">
            Start a useful channel-scoped task here. Full customization lives in Automations.
          </div>
        </div>
        {isLoading && <Spinner />}
      </div>
      {presets.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              data-testid={`quick-automation-${preset.id}`}
              onClick={() => onSelect(preset)}
              className="group flex min-h-[92px] flex-col items-start gap-2 rounded-md bg-surface-raised/45 px-3 py-3 text-left transition-colors hover:bg-surface-overlay/55 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            >
              <div className="flex w-full items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-accent/[0.08] text-accent">
                    <CalendarPlus size={15} />
                  </span>
                  <span className="truncate text-[13px] font-semibold text-text">{preset.title}</span>
                </div>
                <QuietPill label={preset.task_defaults?.recurrence === "+1w" ? "weekly" : "preset"} />
              </div>
              <p className="line-clamp-2 text-[12px] leading-relaxed text-text-dim">
                {preset.description}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PresetReviewDrawer({
  preset,
  draft,
  botId,
  isCreating,
  error,
  onClose,
  onDraftChange,
  onCreate,
  onCreateAndCustomize,
}: {
  preset: RunPreset;
  draft: QuickAutomationDraft;
  botId?: string;
  isCreating: boolean;
  error: unknown;
  onClose: () => void;
  onDraftChange: (draft: QuickAutomationDraft) => void;
  onCreate: () => void;
  onCreateAndCustomize: () => void;
}) {
  if (typeof document === "undefined") return null;

  const defaults = preset.task_defaults!;
  const disabled = isCreating || !botId || !draft.prompt.trim();
  const errorMessage = error instanceof Error ? error.message : error ? "Failed to create task." : null;

  return createPortal(
    <div className="fixed inset-0 z-[10000] flex justify-end" data-testid="quick-automation-review-drawer">
      <button
        type="button"
        aria-label="Close quick automation"
        className="absolute inset-0 bg-black/35"
        onClick={onClose}
      />
      <div className="relative flex h-full w-full max-w-[720px] flex-col border-l border-surface-border bg-surface shadow-2xl">
        <div className="flex min-h-[64px] items-start justify-between gap-3 border-b border-surface-border px-5 py-4">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
              Quick automation
            </div>
            <h2 className="mt-1 truncate text-[16px] font-semibold text-text">{preset.title}</h2>
            <p className="mt-1 max-w-[62ch] text-[12px] leading-relaxed text-text-dim">
              Review the defaults, then create a normal scheduled task for this channel.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 shrink-0 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          <div className="flex flex-col gap-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <FormRow label="Title">
                <TextInput
                  value={draft.title}
                  onChangeText={(title) => onDraftChange({ ...draft, title })}
                  placeholder={defaults.title}
                />
              </FormRow>
              <div className="flex flex-col gap-3">
                <ScheduledAtPicker
                  value={draft.scheduled_at}
                  onChange={(scheduled_at) => onDraftChange({ ...draft, scheduled_at })}
                />
                <RecurrencePicker
                  value={draft.recurrence}
                  onChange={(recurrence) => onDraftChange({ ...draft, recurrence })}
                />
              </div>
            </div>

            <ScheduleSummary scheduledAt={draft.scheduled_at} recurrence={draft.recurrence} />

            <Toggle
              value={draft.post_final_to_channel}
              onChange={(post_final_to_channel) => onDraftChange({ ...draft, post_final_to_channel })}
              label="Post run summaries to this channel"
              description="Off by default so the healthcheck can run quietly unless it has useful work to surface."
            />

            <LlmPrompt
              label="Prompt"
              value={draft.prompt}
              onChange={(prompt) => onDraftChange({ ...draft, prompt })}
              rows={12}
              fieldType="task_prompt"
              botId={botId}
              helpText="This preset includes the widget skills and inspection tools below."
            />

            <div className="flex flex-col gap-2 rounded-md bg-surface-raised/35 px-3 py-3">
              <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
                Prefilled context
              </div>
              <div className="flex flex-wrap gap-1.5">
                <QuietPill label="channel task" />
                <QuietPill label="primary session" />
                <QuietPill label={`${defaults.history_recent_count} recent messages`} />
                {defaults.skills.map((skill) => (
                  <QuietPill key={skill} label={`skill:${skill}`} title={skill} maxWidthClass="max-w-[220px]" />
                ))}
                {defaults.tools.map((tool) => (
                  <QuietPill key={tool} label={`tool:${tool}`} title={tool} maxWidthClass="max-w-[220px]" />
                ))}
              </div>
            </div>

            {!botId && (
              <div className="rounded-md bg-warning/10 px-3 py-2 text-[12px] text-warning-muted">
                This channel does not have a selected bot yet, so the task cannot be created here.
              </div>
            )}
            {errorMessage && (
              <div className="rounded-md bg-danger/10 px-3 py-2 text-[12px] text-danger">
                {errorMessage}
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-border px-5 py-3">
          <p className="max-w-[44ch] text-[11px] leading-relaxed text-text-dim">
            Need steps, model overrides, or trigger details? Create and customize in Automations.
          </p>
          <div className="flex items-center gap-1.5">
            <ActionButton label="Cancel" variant="secondary" onPress={onClose} disabled={isCreating} />
            <ActionButton
              label={isCreating ? "Creating..." : "Create & Customize"}
              variant="secondary"
              onPress={onCreateAndCustomize}
              disabled={disabled}
            />
            <ActionButton
              label={isCreating ? "Creating..." : "Create"}
              onPress={onCreate}
              disabled={disabled}
            />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function TasksTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const createTask = useCreateTask();
  const { data: presetData, isLoading: presetsLoading } = useRunPresets("channel_task");
  const { data, isLoading } = useQuery({
    queryKey: ["channel-tasks", channelId],
    queryFn: () => apiFetch<{ tasks: TaskItem[] }>(`/api/v1/admin/channels/${channelId}/tasks`),
  });
  const allTasks = data?.tasks ?? [];
  const presets = useMemo(
    () => (presetData?.presets ?? []).filter((preset) => !!preset.task_defaults),
    [presetData?.presets],
  );

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const tasks = useMemo(() => {
    if (statusFilter === "all") return allTasks;
    if (statusFilter === "active") return allTasks.filter(tk => ACTIVE_STATUSES.has(tk.status));
    if (statusFilter === "failed") return allTasks.filter(tk => tk.status === "failed");
    return allTasks;
  }, [allTasks, statusFilter]);

  // Counts for filter pill badges
  const activeCt = useMemo(() => allTasks.filter(tk => ACTIVE_STATUSES.has(tk.status)).length, [allTasks]);
  const failedCt = useMemo(() => allTasks.filter(tk => tk.status === "failed").length, [allTasks]);
  const otherTasks = useMemo(
    () => allTasks.filter((tk) => !ACTIVE_STATUSES.has(tk.status) && tk.status !== "failed"),
    [allTasks],
  );

  type EditorState =
    | { mode: "closed" }
    | { mode: "create" }
    | { mode: "edit"; taskId: string };

  const [editorState, setEditorState] = useState<EditorState>({ mode: "closed" });
  const [presetState, setPresetState] = useState<{ preset: RunPreset; draft: QuickAutomationDraft } | null>(null);

  const handleEditorSaved = () => {
    setEditorState({ mode: "closed" });
    queryClient.invalidateQueries({ queryKey: ["channel-tasks", channelId] });
  };

  const handleCreatePresetTask = async (customize: boolean) => {
    if (!presetState || !botId) return;
    const payload = buildPresetTaskPayload(presetState.preset, presetState.draft, channelId, botId);
    const created = await createTask.mutateAsync(payload);
    await queryClient.invalidateQueries({ queryKey: ["channel-tasks", channelId] });
    setPresetState(null);
    if (customize) {
      navigate(`/admin/automations/${created.id}`);
    }
  };

  const editorOpen = editorState.mode !== "closed";
  const editorTaskId = editorState.mode === "edit" ? editorState.taskId : null;
  const renderTask = (task: TaskItem) => (
    <TaskCardRow
      key={task.id}
      task={task}
      onClick={() => {
        if (EDITABLE_TASK_TYPES.has(task.task_type ?? "")) {
          setEditorState({ mode: "edit", taskId: task.id });
        } else {
          navigate(`/admin/automations/${task.id}`);
        }
      }}
      showBotDot={false}
      showBotName={false}
    />
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SettingsSegmentedControl
          value={statusFilter}
          onChange={setStatusFilter}
          options={STATUS_PILL_KEYS.map((pill) => ({
            key: pill.key,
            label: pill.label,
            count: pill.key === "all" ? allTasks.length : pill.key === "active" ? activeCt : failedCt,
          }))}
        />
        <ActionButton
          label="New Task"
          onPress={() => setEditorState({ mode: "create" })}
          size="small"
          icon={<Plus size={12} />}
        />
      </div>

      <QuickAutomations
        presets={presets}
        isLoading={presetsLoading}
        onSelect={(preset) => {
          createTask.reset();
          setPresetState({ preset, draft: draftFromPreset(preset) });
        }}
      />

      {isLoading ? (
        <div className="flex min-h-24 items-center justify-center text-text-dim">
          <Spinner />
        </div>
      ) : !tasks.length ? (
        <EmptyState message={statusFilter === "all" ? "No tasks yet." : `No ${statusFilter} tasks.`} />
      ) : statusFilter === "all" ? (
        <div className="flex flex-col gap-5">
          <TaskGroup label="Needs attention" count={failedCt}>
            {allTasks.filter((task) => task.status === "failed").map(renderTask)}
          </TaskGroup>
          <TaskGroup label="Active" count={activeCt}>
            {allTasks.filter((task) => ACTIVE_STATUSES.has(task.status)).map(renderTask)}
          </TaskGroup>
          <TaskGroup label="Other tasks" count={otherTasks.length}>
            {otherTasks.map(renderTask)}
          </TaskGroup>
        </div>
      ) : (
        <TaskGroup label={statusFilter === "active" ? "Active tasks" : "Failed tasks"} count={tasks.length}>
          {tasks.map(renderTask)}
        </TaskGroup>
      )}

      {editorOpen && (
        <TaskEditorShared
          taskId={editorTaskId}
          onClose={() => setEditorState({ mode: "closed" })}
          onSaved={handleEditorSaved}
          defaultChannelId={channelId}
          defaultBotId={botId}
          extraQueryKeysToInvalidate={[["channel-tasks", channelId]]}
        />
      )}

      {presetState && (
        <PresetReviewDrawer
          preset={presetState.preset}
          draft={presetState.draft}
          botId={botId}
          isCreating={createTask.isPending}
          error={createTask.error}
          onClose={() => {
            if (!createTask.isPending) setPresetState(null);
          }}
          onDraftChange={(draft) => setPresetState({ ...presetState, draft })}
          onCreate={() => void handleCreatePresetTask(false)}
          onCreateAndCustomize={() => void handleCreatePresetTask(true)}
        />
      )}
    </div>
  );
}
