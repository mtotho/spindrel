import { CheckCircle2, XCircle, Clock, SkipForward, PauseCircle } from "lucide-react";
import type { StepState } from "@/src/api/hooks/useTasks";

export function StepResultBadge({ state }: { state: StepState }) {
  const config: Record<string, { classes: string; Icon: typeof CheckCircle2; label: string }> = {
    done: { classes: "bg-success/10 text-success", Icon: CheckCircle2, label: "done" },
    failed: { classes: "bg-danger/10 text-danger", Icon: XCircle, label: "failed" },
    skipped: { classes: "bg-surface-overlay text-text-dim", Icon: SkipForward, label: "skipped" },
    running: { classes: "bg-accent/10 text-accent", Icon: Clock, label: "running" },
    pending: { classes: "bg-surface-overlay text-text-dim", Icon: Clock, label: "pending" },
    awaiting_user_input: { classes: "bg-accent/10 text-accent", Icon: PauseCircle, label: "awaiting input" },
  };
  const { classes, Icon, label } = config[state.status] ?? config.pending;
  return (
    <span className={`inline-flex flex-row items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${classes}`}>
      {state.status === "running" ? <span className="h-1.5 w-1.5 rounded-full bg-current" /> : <Icon size={10} />}
      {label}
    </span>
  );
}
