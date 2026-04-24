import { Check, X } from "lucide-react";
import type { IntegrationEnvVar } from "@/src/api/hooks/useIntegrations";
import { QuietPill, StatusBadge as SharedStatusBadge } from "@/src/components/shared/SettingsControls";

export function integrationStatusInfo(status: string): {
  label: string;
  variant: "success" | "warning" | "neutral";
} {
  if (status === "enabled") return { label: "Enabled", variant: "success" };
  if (status === "needs_setup") return { label: "Needs setup", variant: "warning" };
  return { label: "Available", variant: "neutral" };
}

export function StatusBadge({ status }: { status: string }) {
  const info = integrationStatusInfo(status);
  return <SharedStatusBadge label={info.label} variant={info.variant} />;
}

export function CapBadge({ label, active }: { label: string; active: boolean }) {
  return (
    <QuietPill
      label={label}
      className={active ? "bg-accent/10 text-accent" : "bg-surface-overlay/25 text-text-dim"}
      maxWidthClass="max-w-[140px]"
    />
  );
}

export function EnvVarPill({ v }: { v: IntegrationEnvVar }) {
  const variant = v.is_set ? "success" : v.required ? "danger" : "neutral";
  return (
    <span
      title={v.description + (v.default ? ` (default: ${v.default})` : "")}
      className={
        `inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold ` +
        (variant === "success"
          ? "bg-success/10 text-success"
          : variant === "danger"
            ? "bg-danger/10 text-danger"
            : "bg-surface-overlay text-text-muted")
      }
    >
      {v.is_set ? <Check size={10} /> : v.required ? <X size={10} /> : null}
      {v.key}
      {v.default && !v.required && <span className="font-sans text-[9px] text-text-dim">{v.default}</span>}
      {!v.required && !v.default && <span className="font-sans text-[9px] text-text-dim">opt</span>}
    </span>
  );
}

export function formatUptime(seconds: number | null): string {
  if (seconds == null) return "";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}
