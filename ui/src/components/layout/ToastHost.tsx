import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";
import { useToastStore, type ToastMessage } from "@/src/stores/toast";
import { cn } from "@/src/lib/cn";

const ICONS = {
  success: CheckCircle2,
  info: Info,
  error: AlertCircle,
} as const;

const ACCENT = {
  success: "border-success/40 bg-success/10 text-success",
  info: "border-accent/40 bg-accent/10 text-accent",
  error: "border-danger/40 bg-danger/10 text-danger",
} as const;

export function ToastHost() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div
      className="pointer-events-none absolute inset-x-0 bottom-4 z-[10050] flex flex-col items-center gap-2 px-4"
      role="status"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastMessage; onDismiss: () => void }) {
  const Icon = ICONS[toast.kind];
  return (
    <div
      className={cn(
        "pointer-events-auto flex items-center gap-2.5 rounded-full border bg-surface-raised px-4 py-2 text-[12.5px] shadow-lg shadow-black/30 animate-toast-in",
        ACCENT[toast.kind],
      )}
    >
      <Icon size={14} className="shrink-0" />
      <span className="text-text">{toast.message}</span>
      {toast.action && (
        <button
          type="button"
          onClick={() => {
            toast.action?.onClick();
            onDismiss();
          }}
          className="ml-1 rounded-full bg-surface-overlay px-2 py-0.5 text-[11px] font-medium text-text hover:bg-surface-overlay/80 transition-colors"
        >
          {toast.action.label}
        </button>
      )}
      <button
        type="button"
        onClick={onDismiss}
        className="ml-1 rounded p-0.5 text-text-dim hover:bg-surface-overlay hover:text-text transition-colors"
        aria-label="Dismiss"
      >
        <X size={11} />
      </button>
    </div>
  );
}
