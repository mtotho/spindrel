import { useEffect, useState } from "react";
import { AlertTriangle, Ban, ChevronDown, ChevronRight, XCircle } from "lucide-react";
import {
  useCancelIntegrationTasks,
  useIntegrationDebugAction,
  useIntegrationTasks,
  type DebugAction,
  type IntegrationTaskItem,
} from "@/src/api/hooks/useIntegrations";
import {
  ActionButton,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

function formatTimeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function statusVariant(status: string): "success" | "warning" | "danger" | "info" | "neutral" | "purple" {
  if (status === "pending") return "warning";
  if (status === "running") return "info";
  if (status === "complete" || status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "active") return "purple";
  return "neutral";
}

function TaskStats({ stats }: { stats: Record<string, number> }) {
  const entries = Object.entries(stats).sort((a, b) => {
    const order = ["pending", "running", "failed", "complete", "completed", "cancelled", "active"];
    return order.indexOf(a[0]) - order.indexOf(b[0]);
  });
  if (entries.length === 0) return <div className="text-[12px] text-text-dim">No tasks</div>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([status, count]) => (
        <StatusBadge key={status} label={`${count} ${status}`} variant={statusVariant(status)} />
      ))}
    </div>
  );
}

function DebugActionButton({
  action,
  integrationId,
}: {
  action: DebugAction;
  integrationId: string;
}) {
  const mut = useIntegrationDebugAction(integrationId);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [showResult, setShowResult] = useState(false);

  const handleClick = () => {
    mut.mutate(
      { endpoint: action.endpoint, method: action.method },
      {
        onSuccess: (data) => {
          setResult(data);
          if (action.method === "GET") setShowResult(true);
        },
      },
    );
  };

  const variant = action.style === "danger" ? "danger" : action.style === "warning" ? "secondary" : "primary";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <ActionButton
          label={mut.isPending ? "Running..." : action.label}
          onPress={handleClick}
          disabled={mut.isPending}
          variant={variant}
          size="small"
        />
        {mut.isSuccess && action.method !== "GET" && <StatusBadge label="Done" variant="success" />}
        {mut.isError && <StatusBadge label="Failed" variant="danger" />}
        {result && action.method === "GET" && (
          <ActionButton
            label={showResult ? "Hide result" : "Show result"}
            onPress={() => setShowResult((current) => !current)}
            variant="secondary"
            size="small"
            icon={showResult ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          />
        )}
      </div>
      {action.description && <div className="text-[11px] text-text-dim">{action.description}</div>}
      {showResult && result && (
        <pre className="m-0 max-h-[300px] overflow-auto rounded-md bg-surface-raised/45 px-3 py-2 font-mono text-[11px] leading-relaxed text-text whitespace-pre-wrap break-words">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}

function TaskRow({ task }: { task: IntegrationTaskItem }) {
  return (
    <SettingsControlRow
      leading={<span className="h-1.5 w-1.5 rounded-full bg-current" />}
      title={task.title || task.prompt || "(no prompt)"}
      description={task.error || task.task_type}
      meta={
        <span className="inline-flex items-center gap-1.5">
          <StatusBadge label={task.status} variant={statusVariant(task.status)} />
          <span>{formatTimeAgo(task.created_at)}</span>
          {task.error && <XCircle size={12} className="text-danger" />}
        </span>
      }
    />
  );
}

export function IntegrationDebugSection({
  integrationId,
  debugActions,
}: {
  integrationId: string;
  debugActions?: DebugAction[];
}) {
  const { data, isLoading } = useIntegrationTasks(integrationId, { limit: 30 });
  const cancelMut = useCancelIntegrationTasks(integrationId);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [lastCancelledCount, setLastCancelledCount] = useState<number | null>(null);
  const stats = data?.stats ?? {};
  const tasks = data?.tasks ?? [];
  const pendingCount = stats.pending ?? 0;
  const showCancelSuccess = lastCancelledCount !== null && lastCancelledCount > 0;

  useEffect(() => {
    if (!showCancelSuccess) return;
    const timer = window.setTimeout(() => setLastCancelledCount(null), 5000);
    return () => window.clearTimeout(timer);
  }, [showCancelSuccess]);

  const handleCancel = () => {
    if (!confirmCancel) {
      setConfirmCancel(true);
      return;
    }
    cancelMut.mutate(undefined, {
      onSuccess: (result) => {
        setConfirmCancel(false);
        setLastCancelledCount(result.cancelled);
      },
    });
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Activity" />
        {isLoading ? <div className="text-[12px] text-text-dim">Loading tasks...</div> : <TaskStats stats={stats} />}
        {pendingCount > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <ActionButton
              label={confirmCancel ? `Confirm cancel ${pendingCount}` : `Cancel ${pendingCount} pending`}
              onPress={handleCancel}
              disabled={cancelMut.isPending}
              variant="danger"
              size="small"
              icon={<Ban size={12} />}
            />
            {confirmCancel && !cancelMut.isPending && (
              <ActionButton label="Nevermind" onPress={() => setConfirmCancel(false)} variant="ghost" size="small" />
            )}
          </div>
        )}
        {showCancelSuccess && <StatusBadge label={`Cancelled ${lastCancelledCount} tasks`} variant="success" />}
      </div>

      {debugActions && debugActions.length > 0 && (
        <div className="flex flex-col gap-2">
          <SettingsGroupLabel label="Actions" count={debugActions.length} />
          <div className="flex flex-col gap-2">
            {debugActions.map((action) => (
              <div key={action.id} className="rounded-md bg-surface-raised/35 p-3">
                <DebugActionButton action={action} integrationId={integrationId} />
              </div>
            ))}
          </div>
        </div>
      )}

      {tasks.length > 0 && (
        <div className="flex flex-col gap-2">
          <SettingsGroupLabel label="Recent Tasks" count={tasks.length} />
          <div className="flex max-h-[320px] flex-col gap-1.5 overflow-auto">
            {tasks.map((task) => <TaskRow key={task.id} task={task} />)}
          </div>
        </div>
      )}

      {pendingCount > 20 && (
        <InfoBanner variant="danger" icon={<AlertTriangle size={14} />}>
          High pending task count ({pendingCount}). Consider cancelling to prevent a spam storm on restart.
        </InfoBanner>
      )}
    </div>
  );
}
