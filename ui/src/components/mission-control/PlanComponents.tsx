import { View, Text } from "react-native";
import {
  Circle,
  CheckCircle2,
  Loader2,
  MinusCircle,
  AlertCircle,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { MCPlanStep } from "@/src/api/hooks/useMissionControl";
import { STATUS_COLORS, STATUS_LABELS } from "./planConstants";

export function StepIcon({ status }: { status: string }) {
  switch (status) {
    case "done":
      return <CheckCircle2 size={14} color="#22c55e" />;
    case "in_progress":
      return <Loader2 size={14} color="#3b82f6" />;
    case "skipped":
      return <MinusCircle size={14} color="#9ca3af" />;
    case "failed":
      return <AlertCircle size={14} color="#ef4444" />;
    default:
      return <Circle size={14} color="#d1d5db" />;
  }
}

export function ProgressBar({ steps }: { steps: MCPlanStep[] }) {
  const t = useThemeTokens();
  const total = steps.length;
  if (total === 0) return null;
  const done = steps.filter(
    (s) => s.status === "done" || s.status === "skipped" || s.status === "failed"
  ).length;
  const pct = Math.round((done / total) * 100);

  return (
    <View style={{ gap: 4 }}>
      <View
        style={{
          height: 4,
          borderRadius: 2,
          backgroundColor: t.surfaceBorder,
          overflow: "hidden",
        }}
      >
        <View
          style={{
            height: 4,
            borderRadius: 2,
            backgroundColor: pct === 100 ? "#22c55e" : "#3b82f6",
            width: `${pct}%`,
          }}
        />
      </View>
      <Text style={{ fontSize: 10, color: t.textDim }}>
        {done}/{total} steps ({pct}%)
      </Text>
    </View>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.draft;
  const label = STATUS_LABELS[status] || status;
  return (
    <View
      style={{
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 10,
        backgroundColor: colors.bg,
        borderWidth: 1,
        borderColor: colors.border,
      }}
    >
      <Text
        style={{
          fontSize: 10,
          fontWeight: "700",
          color: colors.text,
          textTransform: "uppercase",
        }}
      >
        {label}
      </Text>
    </View>
  );
}
