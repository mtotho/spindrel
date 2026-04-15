import { useOperations, type Operation } from "@/src/api/hooks/useOperations";
import { useThemeTokens } from "@/src/theme/tokens";
import { Loader } from "lucide-react";

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function OperationCard({ op }: { op: Operation }) {
  const t = useThemeTokens();
  const pct = op.total > 0 ? Math.round((op.current / op.total) * 100) : 0;
  const isRunning = op.status === "running";
  const isFailed = op.status === "failed";

  const barColor = isFailed ? t.danger : isRunning ? t.accent : t.success;
  const borderColor = isFailed ? t.dangerBorder : t.surfaceRaised;

  return (
    <div style={{
      padding: "12px 16px", background: t.inputBg, borderRadius: 8,
      border: `1px solid ${borderColor}`,
    }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
        {isRunning && (
          <Loader size={14} color={t.accent} style={{ animation: "spin 1s linear infinite" }} />
        )}
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
          {op.label}
        </span>
        <span style={{
          fontSize: 11, fontWeight: 600,
          color: isFailed ? t.danger : isRunning ? t.accent : t.success,
        }}>
          {op.status}
        </span>
        <span style={{ fontSize: 11, color: t.textDim }}>
          {formatElapsed(op.elapsed)}
        </span>
      </div>

      {/* Progress bar */}
      {op.total > 0 && (
        <div style={{
          height: 6, borderRadius: 3, background: t.surface, overflow: "hidden", marginBottom: 6,
        }}>
          <div style={{
            height: "100%", borderRadius: 3,
            width: `${pct}%`, background: barColor,
            transition: "width 0.3s ease",
          }} />
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", fontSize: 11 }}>
        {op.total > 0 && (
          <span style={{ color: t.textDim }}>
            {op.current}/{op.total} ({pct}%)
          </span>
        )}
        {op.message && (
          <span style={{
            color: t.textDim, fontFamily: "monospace",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            maxWidth: "60%", textAlign: "right",
          }}>
            {op.message}
          </span>
        )}
      </div>
    </div>
  );
}

export function OperationsPanel() {
  const t = useThemeTokens();
  const { data: operations } = useOperations();

  if (!operations || operations.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{
        fontSize: 12, fontWeight: 600, color: t.warning,
        textTransform: "uppercase", letterSpacing: 1,
      }}>
        Active Operations
      </div>
      {operations.map((op) => (
        <OperationCard key={op.id} op={op} />
      ))}
    </div>
  );
}
