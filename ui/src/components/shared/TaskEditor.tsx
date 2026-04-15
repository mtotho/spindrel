/**
 * TaskEditor — full-screen overlay for editing tasks.
 *
 * Two-pane layout on desktop (left: content, right: config).
 * Uses shared useTaskFormState hook and field group components.
 */
import { useCallback } from "react";
import ReactDOM from "react-dom";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, Trash2, Copy, FileText } from "lucide-react";
import { useTaskFormState } from "./task/useTaskFormState";
import { ContentFields, ExecutionFields, TriggerFields } from "./task/TaskFormFields";
import { formatDateTime } from "@/src/utils/time";
import {
  EnableToggle,
  InfoRow,
  STATUS_OPTIONS,
  TASK_TYPE_OPTIONS_CREATE,
} from "@/src/components/shared/SchedulingPickers";
import { FormRow, SelectInput, Section } from "@/src/components/shared/FormControls";

// ---------------------------------------------------------------------------
// TaskEditor (near-fullscreen overlay)
// ---------------------------------------------------------------------------
export interface TaskEditorProps {
  taskId: string | null;        // null = create mode
  onClose: () => void;
  onSaved: () => void;
  defaultChannelId?: string;
  defaultBotId?: string;
  onClone?: (taskId: string) => void;
  cloneFromId?: string;
  extraQueryKeysToInvalidate?: string[][];
}

export function TaskEditor({
  taskId,
  onClose,
  onSaved,
  defaultChannelId,
  defaultBotId,
  onClone,
  cloneFromId,
  extraQueryKeysToInvalidate,
}: TaskEditorProps) {
  const isCreate = !taskId;
  const isWide = typeof window !== "undefined" && window.innerWidth >= 768;

  const form = useTaskFormState({
    mode: isCreate ? "create" : "edit",
    taskId: taskId ?? undefined,
    cloneFromId,
    defaultBotId,
    defaultChannelId,
    extraQueryKeysToInvalidate,
    onSaved,
  });

  const navigate = useNavigate();

  if (typeof document === "undefined") return null;

  const editorTitle = cloneFromId ? "New Task (Clone)" : isCreate ? "New Task" : "Edit Task";

  return ReactDOM.createPortal(
    <div className="flex flex-col fixed inset-0 z-[10000] bg-surface">
      {/* Header */}
      <div className={`flex flex-row items-center border-b border-surface-border shrink-0 gap-2 ${isWide ? "px-5 py-3" : "px-3 py-2.5"}`}>
        <button
          onClick={onClose}
          className="bg-transparent border-none cursor-pointer p-1 shrink-0 rounded-md hover:bg-surface-overlay transition-colors"
        >
          <ChevronLeft size={22} className="text-text-muted" />
        </button>

        <span className="text-text text-sm font-bold shrink-0">
          {editorTitle}
        </span>
        {cloneFromId && (
          <span className="text-[10px] px-2 py-0.5 rounded font-semibold bg-warning/[0.08] text-warning-muted">
            CLONE
          </span>
        )}
        {!isCreate && form.existingTask && isWide && (
          <span className="text-text-dim text-[11px] font-mono">
            {taskId?.slice(0, 8)}
          </span>
        )}

        <div className="flex-1" />

        {/* View Logs button */}
        {!isCreate && form.existingTask?.correlation_id && (
          <button
            onClick={() => {
              onClose();
              navigate(`/admin/logs/${form.existingTask!.correlation_id}`);
            }}
            title="View Logs"
            className={`flex flex-row items-center ${isWide ? "gap-1.5 px-3.5" : "px-2"} py-1.5 text-[13px] border border-accent-muted rounded-md bg-transparent text-accent cursor-pointer shrink-0 hover:bg-accent/[0.06] transition-colors`}
          >
            <FileText size={14} />
            {isWide && "Logs"}
          </button>
        )}

        {/* Clone button */}
        {!isCreate && onClone && taskId && (
          <button
            onClick={() => onClone(taskId)}
            title="Clone"
            className={`flex flex-row items-center ${isWide ? "gap-1.5 px-3.5" : "px-2"} py-1.5 text-[13px] border border-surface-border rounded-md bg-transparent text-text-muted cursor-pointer shrink-0 hover:border-accent/50 hover:text-text transition-colors`}
          >
            <Copy size={14} />
            {isWide && "Clone"}
          </button>
        )}

        {!isCreate && (
          <button
            onClick={form.handleDelete}
            disabled={form.deleteMut.isPending}
            title="Delete"
            className={`flex flex-row items-center ${isWide ? "gap-1.5 px-3.5" : "px-2"} py-1.5 text-[13px] border border-danger/[0.15] rounded-md bg-transparent text-danger cursor-pointer shrink-0 hover:bg-danger/[0.06] transition-colors`}
          >
            <Trash2 size={14} />
            {isWide && "Delete"}
          </button>
        )}
        {!isCreate && (
          <EnableToggle
            enabled={form.status !== "cancelled"}
            onChange={(on) => {
              const isSchedule = !!form.recurrence;
              form.setStatus(on ? (isSchedule ? "active" : "pending") : "cancelled");
            }}
            compact={!isWide}
          />
        )}
        <button
          onClick={form.handleSave}
          disabled={form.saving || !form.canSave}
          className={`${isWide ? "px-5" : "px-3"} py-1.5 text-[13px] font-semibold border-none rounded-md shrink-0 transition-colors ${
            form.canSave
              ? "bg-accent text-white cursor-pointer hover:bg-accent-hover"
              : "bg-surface-border text-text-dim cursor-not-allowed"
          }`}
        >
          {form.saving ? "..." : isCreate ? "Create" : "Save"}
        </button>
      </div>

      {/* Error display */}
      {form.error && (
        <div className="px-5 py-2 bg-danger/[0.08] text-danger text-xs shrink-0">
          {form.error?.message || "An error occurred"}
        </div>
      )}

      {/* Body */}
      {(((!isCreate && !cloneFromId) || cloneFromId) && form.loadingTask) ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="chat-spinner" />
        </div>
      ) : (
        <div className={`flex flex-1 min-h-0 ${isWide ? "flex-row" : "flex-col overflow-y-auto"}`}>
          {/* Left pane — Content */}
          <div className={isWide ? "flex-[3] min-h-0 overflow-y-auto border-r border-surface-overlay" : ""}>
            <div className="px-5 py-4">
              <ContentFields form={form} promptRows={isWide ? 12 : 6} />

              {/* Result/Error display (edit mode) */}
              {!isCreate && form.existingTask?.result && !form.stepsMode && (
                <div className="mt-4">
                  <div className="text-xs font-semibold text-text-muted mb-1.5">Result</div>
                  <div className="p-3 rounded-lg bg-input border border-surface-raised text-xs text-success whitespace-pre-wrap max-h-[300px] overflow-auto font-mono">
                    {form.existingTask.result}
                  </div>
                </div>
              )}

              {!isCreate && form.existingTask?.error && !form.stepsMode && (
                <div className="mt-4">
                  <div className="text-xs font-semibold text-text-muted mb-1.5">Error</div>
                  <div className="p-3 rounded-lg bg-danger/[0.08] border border-danger/[0.15] text-xs text-danger whitespace-pre-wrap max-h-[200px] overflow-auto font-mono">
                    {form.existingTask.error}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Right pane — Configuration */}
          <div className={`px-5 py-4 ${isWide ? "flex-[2] min-h-0 overflow-y-auto" : "flex-shrink-0 border-t border-surface-overlay"}`}>
            <div className="flex flex-col gap-4">
              <Section title="Configuration">
                <ExecutionFields form={form} disableChannel={!isCreate} />
              </Section>

              {!isCreate && (
                <Section title="Status">
                  <FormRow label="Status">
                    <SelectInput
                      value={form.status}
                      onChange={form.setStatus}
                      options={STATUS_OPTIONS}
                    />
                  </FormRow>
                  <FormRow label="Task Type">
                    <SelectInput
                      value={form.taskType}
                      onChange={form.setTaskType}
                      options={TASK_TYPE_OPTIONS_CREATE}
                    />
                  </FormRow>
                </Section>
              )}

              <Section title="Trigger">
                <TriggerFields form={form} />
              </Section>

              {/* Read-only timing info (edit mode) */}
              {!isCreate && form.existingTask && (
                <Section title="Timing">
                  <div className="flex flex-col gap-2">
                    <InfoRow label="Created" value={formatDateTime(form.existingTask.created_at)} />
                    <InfoRow label="Scheduled" value={formatDateTime(form.existingTask.scheduled_at)} />
                    <InfoRow label="Run At" value={formatDateTime(form.existingTask.run_at)} />
                    <InfoRow label="Completed" value={formatDateTime(form.existingTask.completed_at)} />
                    <InfoRow label="Retry Count" value={String(form.existingTask.retry_count)} />
                    {form.existingTask.run_count > 0 && (
                      <InfoRow label="Run Count" value={String(form.existingTask.run_count)} />
                    )}
                  </div>
                </Section>
              )}

              {/* Read-only dispatch info (edit mode) */}
              {!isCreate && form.existingTask && (
                <Section title="Dispatch">
                  <div className="flex flex-col gap-2">
                    <InfoRow label="Type" value={form.existingTask.dispatch_type} />
                    {form.existingTask.delegation_session_id && (
                      <InfoRow label="Delegation Context" value={form.existingTask.delegation_session_id.slice(0, 8) + "..."} />
                    )}
                    {form.existingTask.dispatch_config && (
                      <div>
                        <div className="text-[11px] text-text-dim mb-1">Dispatch Config</div>
                        <pre className="text-[10px] text-text-muted bg-input p-2 rounded-md overflow-auto max-h-[120px] m-0">
                          {JSON.stringify(form.existingTask.dispatch_config, null, 2)}
                        </pre>
                      </div>
                    )}
                    {form.existingTask.execution_config && (
                      <div>
                        <div className="text-[11px] text-text-dim mb-1">Execution Config</div>
                        <pre className="text-[10px] text-text-muted bg-input p-2 rounded-md overflow-auto max-h-[120px] m-0">
                          {JSON.stringify(form.existingTask.execution_config, null, 2)}
                        </pre>
                      </div>
                    )}
                    {form.existingTask.callback_config && (
                      <div>
                        <div className="text-[11px] text-text-dim mb-1">Callback Config</div>
                        <pre className="text-[10px] text-text-muted bg-input p-2 rounded-md overflow-auto max-h-[120px] m-0">
                          {JSON.stringify(form.existingTask.callback_config, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </Section>
              )}
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
