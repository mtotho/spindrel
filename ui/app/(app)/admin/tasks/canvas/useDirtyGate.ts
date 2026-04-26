import { useCallback, useEffect, useMemo, useRef } from "react";
import type { TaskFormState } from "@/src/components/shared/task/useTaskFormState";

/**
 * useDirtyGate — tracks whether the editor has unsaved changes vs the
 * last loaded baseline. Used to gate Esc / Close so the user can't
 * silently discard work.
 *
 * Baseline is captured the first render where the form has loaded
 * (existingTask is present for edits, or `initialized` flips true for
 * fresh creates). Subsequent saves should update the baseline by
 * calling `markClean()`.
 */
export interface DirtyGate {
  isDirty: boolean;
  markClean: () => void;
  /** Run the gate: returns `true` if it's safe to proceed (clean,
   *  or user confirmed discard). Returns `false` to cancel. */
  guard: () => boolean;
}

function snapshotOf(form: TaskFormState): string {
  return JSON.stringify({
    title: form.title,
    prompt: form.prompt,
    promptTemplateId: form.promptTemplateId,
    workspaceFilePath: form.workspaceFilePath,
    workspaceId: form.workspaceId,
    botId: form.botId,
    channelId: form.channelId,
    status: form.status,
    taskType: form.taskType,
    scheduledAt: form.scheduledAt,
    recurrence: form.recurrence,
    triggerRagLoop: form.triggerRagLoop,
    modelOverride: form.modelOverride,
    fallbackModels: form.fallbackModels,
    maxRunSeconds: form.maxRunSeconds,
    workflowId: form.workflowId,
    workflowSessionMode: form.workflowSessionMode,
    triggerConfig: form.triggerConfig,
    selectedSkillIds: form.selectedSkillIds,
    selectedToolKeys: form.selectedToolKeys,
    steps: form.steps,
    layout: form.layout,
    postFinalToChannel: form.postFinalToChannel,
    historyMode: form.historyMode,
    historyRecentCount: form.historyRecentCount,
  });
}

export function useDirtyGate(form: TaskFormState, isCreate: boolean): DirtyGate {
  const baseline = useRef<string | null>(null);
  const ready = !isCreate ? !!form.existingTask : !!form.botId;

  // Capture baseline on first ready render
  useEffect(() => {
    if (!ready) return;
    if (baseline.current !== null) return;
    baseline.current = snapshotOf(form);
    // intentionally no deps — capture once when ready flips true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  const current = snapshotOf(form);
  const isDirty = useMemo(() => {
    if (baseline.current === null) return false;
    return current !== baseline.current;
  }, [current]);

  const markClean = useCallback(() => {
    baseline.current = snapshotOf(form);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  const guard = useCallback(() => {
    if (!isDirty) return true;
    if (typeof window === "undefined") return true;
    return window.confirm("Discard unsaved changes?");
  }, [isDirty]);

  return { isDirty, markClean, guard };
}
