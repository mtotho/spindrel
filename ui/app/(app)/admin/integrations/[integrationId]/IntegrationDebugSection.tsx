import { useState, useEffect } from "react";
import { AlertTriangle, Ban, ChevronDown, ChevronRight, XCircle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useIntegrationTasks,
  useCancelIntegrationTasks,
  useIntegrationDebugAction,
  type DebugAction,
  type IntegrationTaskItem,
} from "@/src/api/hooks/useIntegrations";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

const STATUS_COLORS: Record<string, string> = {
  pending: "#eab308",
  running: "#3b82f6",
  complete: "#22c55e",
  completed: "#22c55e",
  failed: "#ef4444",
  cancelled: "#6b7280",
  active: "#a855f7",
};

function TaskStatusDot({ status }: { status: string }) {
  const color = STATUS_COLORS[status] || "#6b7280";
  return (
    <span
      style={{
        display: "inline-block",
        width: 7,
        height: 7,
        borderRadius: "50%",
        background: color,
        flexShrink: 0,
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Stats bar
// ---------------------------------------------------------------------------

function TaskStats({ stats }: { stats: Record<string, number> }) {
  const t = useThemeTokens();
  const entries = Object.entries(stats).sort((a, b) => {
    const order = ["pending", "running", "failed", "complete", "completed", "cancelled", "active"];
    return order.indexOf(a[0]) - order.indexOf(b[0]);
  });
  if (entries.length === 0) {
    return <span style={{ fontSize: 12, color: t.textDim }}>No tasks</span>;
  }
  return (
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
      {entries.map(([status, count]) => (
        <span
          key={status}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontSize: 12,
            color: STATUS_COLORS[status] || t.textMuted,
            fontWeight: 600,
          }}
        >
          <TaskStatusDot status={status} />
          {count} {status}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom debug action button
// ---------------------------------------------------------------------------

function ActionButton({
  action,
  integrationId,
}: {
  action: DebugAction;
  integrationId: string;
}) {
  const t = useThemeTokens();
  const mut = useIntegrationDebugAction(integrationId);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [showResult, setShowResult] = useState(false);

  const styleMap: Record<string, { bg: string; color: string }> = {
    default: { bg: "rgba(59,130,246,0.15)", color: "#3b82f6" },
    warning: { bg: "rgba(234,179,8,0.15)", color: "#ca8a04" },
    danger: { bg: "rgba(239,68,68,0.15)", color: "#ef4444" },
  };
  const s = styleMap[action.style || "default"] || styleMap.default;

  const handleClick = () => {
    mut.mutate(
      { endpoint: action.endpoint, method: action.method },
      {
        onSuccess: (data) => {
          setResult(data);
          if (action.method === "GET") setShowResult(true);
        },
      }
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <button
          onClick={handleClick}
          disabled={mut.isPending}
          title={action.description}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 12px",
            borderRadius: 5,
            border: "none",
            background: s.bg,
            color: s.color,
            fontSize: 11,
            fontWeight: 600,
            cursor: mut.isPending ? "wait" : "pointer",
            opacity: mut.isPending ? 0.5 : 1,
          }}
        >
          {mut.isPending ? "..." : action.label}
        </button>
        {mut.isSuccess && action.method !== "GET" && (
          <span style={{ fontSize: 11, color: "#22c55e" }}>Done</span>
        )}
        {mut.isError && (
          <span style={{ fontSize: 11, color: "#ef4444" }}>Failed</span>
        )}
        {result && action.method === "GET" && (
          <button
            onClick={() => setShowResult(!showResult)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              display: "flex",
              alignItems: "center",
              gap: 2,
              fontSize: 11,
              color: t.accent,
            }}
          >
            {showResult ? (
              <ChevronDown size={12} />
            ) : (
              <ChevronRight size={12} />
            )}
            {showResult ? "Hide" : "Show"} result
          </button>
        )}
      </div>
      {showResult && result && (
        <pre
          style={{
            margin: 0,
            padding: 10,
            borderRadius: 6,
            background: t.surface,
            border: `1px solid ${t.surfaceBorder}`,
            fontSize: 11,
            fontFamily: "monospace",
            color: t.text,
            overflow: "auto",
            maxHeight: 300,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Task feed
// ---------------------------------------------------------------------------

function TaskRow({ task }: { task: IntegrationTaskItem }) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "5px 0",
        borderBottom: `1px solid ${t.surfaceRaised}`,
        fontSize: 12,
      }}
    >
      <TaskStatusDot status={task.status} />
      <span
        style={{
          fontSize: 10,
          color: t.textDim,
          fontFamily: "monospace",
          minWidth: 48,
          flexShrink: 0,
        }}
      >
        {formatTimeAgo(task.created_at)}
      </span>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          color: STATUS_COLORS[task.status] || t.textMuted,
          minWidth: 60,
          flexShrink: 0,
        }}
      >
        {task.status}
      </span>
      <span
        style={{
          color: t.text,
          flex: 1,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {task.title || task.prompt || "(no prompt)"}
      </span>
      {task.error && (
        <span
          title={task.error}
          style={{ color: "#ef4444", fontSize: 10, flexShrink: 0 }}
        >
          <XCircle size={12} />
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function IntegrationDebugSection({
  integrationId,
  debugActions,
}: {
  integrationId: string;
  debugActions?: DebugAction[];
}) {
  const t = useThemeTokens();
  const { data, isLoading } = useIntegrationTasks(integrationId, { limit: 30 });
  const cancelMut = useCancelIntegrationTasks(integrationId);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const stats = data?.stats ?? {};
  const tasks = data?.tasks ?? [];
  const pendingCount = stats.pending ?? 0;
  const [lastCancelledCount, setLastCancelledCount] = useState<number | null>(null);

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

  // Clear the success banner after 5s
  const showCancelSuccess = lastCancelledCount !== null && lastCancelledCount > 0;
  useEffect(() => {
    if (!showCancelSuccess) return;
    const timer = setTimeout(() => setLastCancelledCount(null), 5000);
    return () => clearTimeout(timer);
  }, [showCancelSuccess]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: 14,
        background: t.inputBg,
        borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: t.textDim,
          textTransform: "uppercase",
          letterSpacing: 0.6,
        }}
      >
        Activity & Debug
      </div>

      {/* Stats + cancel */}
      {isLoading ? (
        <span style={{ fontSize: 12, color: t.textDim }}>Loading tasks...</span>
      ) : (
        <>
          <TaskStats stats={stats} />

          {pendingCount > 0 && (
            <div
              style={{ display: "flex", alignItems: "center", gap: 8 }}
            >
              <button
                onClick={handleCancel}
                disabled={cancelMut.isPending}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "4px 12px",
                  borderRadius: 5,
                  border: "none",
                  background: confirmCancel
                    ? "rgba(239,68,68,0.2)"
                    : "rgba(239,68,68,0.12)",
                  color: "#ef4444",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: cancelMut.isPending ? "wait" : "pointer",
                  opacity: cancelMut.isPending ? 0.5 : 1,
                }}
              >
                <Ban size={11} />
                {confirmCancel
                  ? `Confirm: Cancel ${pendingCount} Pending Tasks`
                  : `Cancel ${pendingCount} Pending Tasks`}
              </button>
              {confirmCancel && !cancelMut.isPending && (
                <button
                  onClick={() => setConfirmCancel(false)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontSize: 11,
                    color: t.textDim,
                  }}
                >
                  Nevermind
                </button>
              )}
            </div>
          )}
          {showCancelSuccess && (
            <span style={{ fontSize: 11, color: "#22c55e" }}>
              Cancelled {lastCancelledCount} tasks
            </span>
          )}
        </>
      )}

      {/* Custom debug actions */}
      {debugActions && debugActions.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: t.textDim,
              textTransform: "uppercase",
              letterSpacing: 0.4,
              marginTop: 4,
            }}
          >
            Actions
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "flex-start" }}>
            {debugActions.map((action) => (
              <ActionButton
                key={action.id}
                action={action}
                integrationId={integrationId}
              />
            ))}
          </div>
        </div>
      )}

      {/* Task feed */}
      {tasks.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 0, marginTop: 4 }}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: t.textDim,
              textTransform: "uppercase",
              letterSpacing: 0.4,
              marginBottom: 4,
            }}
          >
            Recent Tasks
          </div>
          <div
            style={{
              maxHeight: 300,
              overflow: "auto",
              borderRadius: 6,
              background: t.surface,
              border: `1px solid ${t.surfaceBorder}`,
              padding: "4px 10px",
            }}
          >
            {tasks.map((task) => (
              <TaskRow key={task.id} task={task} />
            ))}
          </div>
        </div>
      )}

      {/* Spam warning */}
      {pendingCount > 20 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "6px 10px",
            borderRadius: 6,
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.2)",
            fontSize: 11,
            color: "#ef4444",
          }}
        >
          <AlertTriangle size={14} />
          High pending task count ({pendingCount}). Consider cancelling to prevent
          a spam storm on restart.
        </div>
      )}
    </div>
  );
}
