import { CalendarClock, Play } from "lucide-react";
import { useState } from "react";

import {
  useCreateProjectCodingRunSchedule,
  useDisableProjectCodingRunSchedule,
  useProjectCodingRunSchedules,
  useRunProjectCodingRunScheduleNow,
  useUpdateProjectCodingRunSchedule,
} from "@/src/api/hooks/useProjects";
import type { MachineTargetGrant } from "@/src/api/hooks/useTasks";
import { FormRow, Section, SelectInput } from "@/src/components/shared/FormControls";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import { ActionButton, EmptyState, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
import { RecurrencePicker, ScheduleSummary, ScheduledAtPicker } from "@/src/components/shared/SchedulingPickers";
import type { Channel, Project, ProjectCodingRunSchedule } from "@/src/types/api";
import {
  ExecutionAccessControl,
  executionAccessLine,
  formatRunTime,
  RowLink,
  scheduledAtForPicker,
  statusTone,
} from "./ProjectRunControls";

function ScheduleEditForm({
  project,
  schedule,
  channels,
  busy,
  onCancel,
  onSave,
}: {
  project: Project;
  schedule: ProjectCodingRunSchedule;
  channels?: Pick<Channel, "id" | "name" | "bot_id">[];
  busy: boolean;
  onCancel: () => void;
  onSave: (payload: {
    channel_id: string;
    title: string;
    request: string;
    scheduled_at: string | null;
    recurrence: string;
    machine_target_grant: MachineTargetGrant | null;
  }) => void;
}) {
  const [channelId, setChannelId] = useState(schedule.channel_id || channels?.[0]?.id || "");
  const [title, setTitle] = useState(schedule.title);
  const [request, setRequest] = useState(schedule.request || "");
  const [scheduledAt, setScheduledAt] = useState(schedule.scheduled_at || "");
  const [recurrence, setRecurrence] = useState(schedule.recurrence || "+1w");
  const [machineTargetGrant, setMachineTargetGrant] = useState<MachineTargetGrant | null>(schedule.machine_target_grant ?? null);

  return (
    <div className="rounded-md border border-surface-border bg-surface-raised/35 p-3">
      <div className="grid gap-3 md:grid-cols-[minmax(220px,0.75fr)_minmax(0,1.25fr)]">
        <div className="flex flex-col gap-3">
          <FormRow label="Channel">
            <SelectInput
              value={channelId}
              onChange={setChannelId}
              options={
                channels && channels.length > 0
                  ? channels.map((channel) => ({
                    label: `${channel.name} · ${channel.bot_id}`,
                    value: channel.id,
                  }))
                  : [{ label: "Attach a Project channel first", value: "" }]
              }
            />
          </FormRow>
          <FormRow label="Title">
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none focus:border-accent"
            />
          </FormRow>
          <ScheduledAtPicker value={scheduledAt} onChange={(value) => setScheduledAt(scheduledAtForPicker(value))} />
          <RecurrencePicker value={recurrence} onChange={setRecurrence} />
          <ScheduleSummary scheduledAt={scheduledAt} recurrence={recurrence} />
        </div>
        <div className="flex flex-col gap-3">
          <FormRow label="Review request">
            <PromptEditor
              value={request}
              onChange={setRequest}
              label="Scheduled review request"
              rows={5}
              fieldType="task_prompt"
              generateContext={`Project: ${project.name}. Root: /${project.root_path}`}
            />
          </FormRow>
          <ExecutionAccessControl
            value={machineTargetGrant}
            onChange={setMachineTargetGrant}
            testId={`project-schedule-edit-execution-access-${schedule.id}`}
          />
        </div>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <ActionButton label="Cancel" size="small" variant="ghost" disabled={busy} onPress={onCancel} />
        <ActionButton
          label={busy ? "Saving" : "Save schedule"}
          size="small"
          disabled={busy || !channelId}
          onPress={() => onSave({
            channel_id: channelId,
            title: title.trim() || "Scheduled Project coding run",
            request: request.trim(),
            scheduled_at: scheduledAt || null,
            recurrence: recurrence || "+1w",
            machine_target_grant: machineTargetGrant,
          })}
        />
      </div>
    </div>
  );
}

function RecentScheduleRuns({ schedule }: { schedule: ProjectCodingRunSchedule }) {
  const recentRuns = schedule.recent_runs ?? [];
  if (recentRuns.length === 0) return null;
  return (
    <div className="mt-2 flex flex-col gap-1 rounded-md bg-surface-raised/30 px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">Recent runs</div>
      {recentRuns.map((run) => (
        <div key={run.task_id || run.id} className="flex min-w-0 items-center justify-between gap-2 text-[12px] text-text-muted">
          <span className="min-w-0 truncate">
            {run.status || "unknown"} · {run.branch || run.task_id || run.id} · {formatRunTime(run.created_at)}
          </span>
          {run.task_id && <RowLink to={`/admin/tasks/${run.task_id}`}>Agent log</RowLink>}
        </div>
      ))}
    </div>
  );
}

export function ProjectScheduledReviewsSection({
  project,
  channels,
  selectedChannelId,
}: {
  project: Project;
  channels?: Pick<Channel, "id" | "name" | "bot_id">[];
  selectedChannelId: string;
}) {
  const { data: schedules = [] } = useProjectCodingRunSchedules(project.id);
  const createSchedule = useCreateProjectCodingRunSchedule(project.id);
  const updateSchedule = useUpdateProjectCodingRunSchedule(project.id);
  const runScheduleNow = useRunProjectCodingRunScheduleNow(project.id);
  const disableSchedule = useDisableProjectCodingRunSchedule(project.id);
  const [scheduleTitle, setScheduleTitle] = useState("Weekly Project review");
  const [scheduleRequest, setScheduleRequest] = useState("Review the Project for regressions, stale PRs, missing tests, and architecture issues. If changes are needed, implement them, run tests/screenshots, open a PR, and publish a Project run receipt. If no change is needed, publish a no-change receipt.");
  const [scheduleStart, setScheduleStart] = useState("");
  const [scheduleRecurrence, setScheduleRecurrence] = useState("+1w");
  const [scheduleMachineTargetGrant, setScheduleMachineTargetGrant] = useState<MachineTargetGrant | null>(null);
  const [editingScheduleId, setEditingScheduleId] = useState<string | null>(null);
  const selectedChannel = channels?.find((channel) => channel.id === selectedChannelId);
  const scheduleBusy = createSchedule.isPending || updateSchedule.isPending || runScheduleNow.isPending || disableSchedule.isPending;

  const startSchedule = () => {
    if (!selectedChannel || createSchedule.isPending) return;
    createSchedule.mutate({
      channel_id: selectedChannel.id,
      title: scheduleTitle.trim() || "Scheduled Project coding run",
      request: scheduleRequest.trim(),
      scheduled_at: scheduleStart || null,
      recurrence: scheduleRecurrence || "+1w",
      machine_target_grant: scheduleMachineTargetGrant,
    });
  };

  return (
    <Section
      title="Scheduled Reviews"
      description="Recurring Project coding runs for reviews, maintenance sweeps, and no-change receipts."
      action={
        <ActionButton
          label={createSchedule.isPending ? "Saving" : "Create schedule"}
          icon={<CalendarClock size={14} />}
          disabled={!selectedChannel || createSchedule.isPending}
          onPress={startSchedule}
        />
      }
    >
      <div className="grid gap-3 md:grid-cols-[minmax(220px,0.75fr)_minmax(0,1.25fr)]">
        <div className="flex flex-col gap-3">
          <FormRow label="Title">
            <input
              value={scheduleTitle}
              onChange={(event) => setScheduleTitle(event.target.value)}
              className="w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none focus:border-accent"
            />
          </FormRow>
          <ScheduledAtPicker value={scheduleStart} onChange={(value) => setScheduleStart(scheduledAtForPicker(value))} />
          <RecurrencePicker value={scheduleRecurrence} onChange={setScheduleRecurrence} />
          <ScheduleSummary scheduledAt={scheduleStart} recurrence={scheduleRecurrence} />
        </div>
        <div className="flex flex-col gap-3">
          <FormRow label="Review request">
            <PromptEditor
              value={scheduleRequest}
              onChange={setScheduleRequest}
              label="Scheduled review request"
              rows={5}
              fieldType="task_prompt"
              generateContext={`Project: ${project.name}. Root: /${project.root_path}`}
            />
          </FormRow>
          <ExecutionAccessControl
            value={scheduleMachineTargetGrant}
            onChange={setScheduleMachineTargetGrant}
            testId="project-schedule-execution-access"
          />
        </div>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        {schedules.length === 0 ? (
          <EmptyState message="No scheduled Project reviews are configured yet." />
        ) : (
          schedules.map((schedule) => {
            const channel = channels?.find((item) => item.id === schedule.channel_id);
            const isEditing = editingScheduleId === schedule.id;
            return (
              <div key={schedule.id} className="flex flex-col gap-2">
                <SettingsControlRow
                  leading={<CalendarClock size={14} />}
                  title={schedule.title}
                  description={
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span>
                        {schedule.enabled ? "Enabled" : "Disabled"} · {schedule.recurrence || "manual"} · next {formatRunTime(schedule.scheduled_at)}
                      </span>
                      <span className="truncate text-[11px] text-text-dim">
                        {channel ? `${channel.name} · ${channel.bot_id}` : "Project channel"} · {schedule.run_count} run{schedule.run_count === 1 ? "" : "s"}
                      </span>
                      {schedule.last_run && (
                        <span className="truncate text-[11px] text-text-dim">
                          Last run: {schedule.last_run.status} · {schedule.last_run.branch || schedule.last_run.task_id}
                        </span>
                      )}
                      {executionAccessLine(schedule.machine_target_grant) && (
                        <span className="truncate text-[11px] text-text-dim">Execution access: {executionAccessLine(schedule.machine_target_grant)}</span>
                      )}
                    </span>
                  }
                  meta={<StatusBadge label={schedule.enabled ? "active" : "disabled"} variant={schedule.enabled ? "success" : "neutral"} />}
                  action={
                    <div className="flex flex-wrap justify-end gap-1">
                      <ActionButton
                        label={isEditing ? "Editing" : "Edit"}
                        size="small"
                        variant="ghost"
                        disabled={scheduleBusy}
                        onPress={() => setEditingScheduleId(isEditing ? null : schedule.id)}
                      />
                      {schedule.enabled ? (
                        <>
                          <ActionButton
                            label={runScheduleNow.isPending ? "Starting" : "Run now"}
                            icon={<Play size={13} />}
                            size="small"
                            variant="secondary"
                            disabled={scheduleBusy}
                            onPress={() => runScheduleNow.mutate(schedule.id)}
                          />
                          <ActionButton
                            label="Disable"
                            size="small"
                            variant="ghost"
                            disabled={scheduleBusy}
                            onPress={() => disableSchedule.mutate(schedule.id)}
                          />
                        </>
                      ) : (
                        <ActionButton
                          label={updateSchedule.isPending ? "Resuming" : "Resume"}
                          size="small"
                          variant="secondary"
                          disabled={scheduleBusy}
                          onPress={() => updateSchedule.mutate({ scheduleId: schedule.id, enabled: true })}
                        />
                      )}
                      {schedule.last_run?.task_id && <RowLink to={`/admin/tasks/${schedule.last_run.task_id}`}>Last run</RowLink>}
                    </div>
                  }
                />
                {isEditing && (
                  <ScheduleEditForm
                    project={project}
                    schedule={schedule}
                    channels={channels}
                    busy={updateSchedule.isPending}
                    onCancel={() => setEditingScheduleId(null)}
                    onSave={(payload) => updateSchedule.mutate(
                      { scheduleId: schedule.id, ...payload },
                      { onSuccess: () => setEditingScheduleId(null) },
                    )}
                  />
                )}
                <RecentScheduleRuns schedule={schedule} />
              </div>
            );
          })
        )}
      </div>
    </Section>
  );
}
