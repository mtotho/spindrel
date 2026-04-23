import type { CSSProperties } from "react";

import type { ThemeTokens } from "@/src/theme/tokens";
import type { MachineTarget, SessionMachineTargetLease, SessionMachineTargetState } from "@/src/api/hooks/useMachineTargets";

export type MachineTargetStatusPayload = SessionMachineTargetState & {
  connected_target_count?: number;
};

export type CommandResultPayload = {
  provider_id?: string;
  provider_label?: string;
  command?: string;
  working_dir?: string;
  target_id?: string;
  target_label?: string;
  target_hostname?: string;
  target_platform?: string;
  stdout?: string;
  stderr?: string;
  exit_code?: number;
  duration_ms?: number;
  truncated?: boolean;
};

export type MachineAccessRequiredPayload = {
  reason?: string;
  execution_policy?: string;
  requested_tool?: string;
  session_id?: string | null;
  lease?: SessionMachineTargetLease | null;
  targets?: MachineTarget[];
  connected_targets?: MachineTarget[];
  connected_target_count?: number;
  admin_machines_href?: string;
  integration_admin_href?: string;
};

function isMachineTarget(value: unknown): value is MachineTarget {
  return Boolean(value && typeof value === "object" && "target_id" in value && "provider_id" in value);
}

function isMachineLease(value: unknown): value is SessionMachineTargetLease {
  return Boolean(value && typeof value === "object" && "lease_id" in value && "provider_id" in value);
}

function coerceMachineTargets(value: unknown): MachineTarget[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isMachineTarget);
}

export function coerceMachineTargetState(value: unknown): MachineTargetStatusPayload {
  const payload = (value && typeof value === "object") ? (value as Record<string, unknown>) : {};
  return {
    session_id: typeof payload.session_id === "string" ? payload.session_id : "",
    lease: isMachineLease(payload.lease) ? payload.lease : null,
    targets: coerceMachineTargets(payload.targets),
    connected_target_count: typeof payload.connected_target_count === "number"
      ? payload.connected_target_count
      : undefined,
  };
}

export function coerceMachineAccessRequiredPayload(value: unknown): MachineAccessRequiredPayload {
  const payload = (value && typeof value === "object") ? (value as Record<string, unknown>) : {};
  return {
    reason: typeof payload.reason === "string" ? payload.reason : undefined,
    execution_policy: typeof payload.execution_policy === "string" ? payload.execution_policy : undefined,
    requested_tool: typeof payload.requested_tool === "string" ? payload.requested_tool : undefined,
    session_id: typeof payload.session_id === "string" ? payload.session_id : null,
    lease: isMachineLease(payload.lease) ? payload.lease : null,
    targets: coerceMachineTargets(payload.targets),
    connected_targets: coerceMachineTargets(payload.connected_targets),
    connected_target_count: typeof payload.connected_target_count === "number"
      ? payload.connected_target_count
      : undefined,
    admin_machines_href: typeof payload.admin_machines_href === "string"
      ? payload.admin_machines_href
      : "/admin/machines",
    integration_admin_href: typeof payload.integration_admin_href === "string"
      ? payload.integration_admin_href
      : "/admin/machines",
  };
}

export function coerceCommandResultPayload(value: unknown): CommandResultPayload {
  const payload = (value && typeof value === "object") ? (value as Record<string, unknown>) : {};
  return {
    provider_id: typeof payload.provider_id === "string" ? payload.provider_id : "",
    provider_label: typeof payload.provider_label === "string" ? payload.provider_label : "",
    command: typeof payload.command === "string" ? payload.command : "",
    working_dir: typeof payload.working_dir === "string" ? payload.working_dir : "",
    target_id: typeof payload.target_id === "string" ? payload.target_id : "",
    target_label: typeof payload.target_label === "string" ? payload.target_label : "",
    target_hostname: typeof payload.target_hostname === "string" ? payload.target_hostname : "",
    target_platform: typeof payload.target_platform === "string" ? payload.target_platform : "",
    stdout: typeof payload.stdout === "string" ? payload.stdout : "",
    stderr: typeof payload.stderr === "string" ? payload.stderr : "",
    exit_code: typeof payload.exit_code === "number" ? payload.exit_code : 0,
    duration_ms: typeof payload.duration_ms === "number" ? payload.duration_ms : 0,
    truncated: Boolean(payload.truncated),
  };
}

export function formatMachineDateTime(value?: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString();
}

export function formatMachineDuration(durationMs?: number): string | null {
  if (typeof durationMs !== "number" || !Number.isFinite(durationMs)) return null;
  if (durationMs < 1000) return `${durationMs} ms`;
  const seconds = durationMs / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder}s`;
}

export function machineCardStyle(t: ThemeTokens): CSSProperties {
  return {
    border: `1px solid ${t.surfaceBorder}`,
    borderRadius: 8,
    background: t.inputBg,
    padding: 12,
  };
}

export function machineMetaTextStyle(t: ThemeTokens): CSSProperties {
  return {
    fontSize: 11,
    color: t.textDim,
  };
}

export function machineButtonStyle(
  t: ThemeTokens,
  tone: "default" | "primary" | "danger" = "default",
  disabled = false,
): CSSProperties {
  const borderColor = tone === "primary" ? t.accentBorder : tone === "danger" ? t.danger : t.surfaceBorder;
  const background = tone === "primary"
    ? t.accentSubtle
    : tone === "danger"
      ? t.dangerSubtle
      : t.surfaceRaised;
  const color = tone === "primary" ? t.accent : tone === "danger" ? t.danger : t.text;
  return {
    border: `1px solid ${borderColor}`,
    borderRadius: 6,
    background,
    color,
    padding: "4px 10px",
    fontSize: 11,
    fontWeight: 600,
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.6 : 1,
    transition: "opacity 0.15s ease",
  };
}

export function MachineLeaseSummary({
  lease,
  t,
}: {
  lease: SessionMachineTargetLease;
  t: ThemeTokens;
}) {
  const expiresAt = formatMachineDateTime(lease.expires_at);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <div style={{ fontWeight: 600, color: t.text }}>
        {lease.provider_label ? `${lease.provider_label} · ` : ""}
        {lease.target_label || lease.target_id}
      </div>
      <div style={machineMetaTextStyle(t)}>
        Lease expires {expiresAt ?? lease.expires_at}
      </div>
    </div>
  );
}

export function MachineTargetRow({
  target,
  activeLeaseTargetId,
  busy,
  showTopBorder = true,
  onUse,
  onRevoke,
  t,
}: {
  target: MachineTarget;
  activeLeaseTargetId?: string | null;
  busy: boolean;
  showTopBorder?: boolean;
  onUse?: (target: MachineTarget) => Promise<void>;
  onRevoke?: () => Promise<void>;
  t: ThemeTokens;
}) {
  const isActive = activeLeaseTargetId === target.target_id;
  const meta = [target.provider_label, target.hostname, target.platform].filter(Boolean).join(" · ");
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 10,
        padding: "10px 0",
        borderTop: showTopBorder ? `1px solid ${t.surfaceBorder}` : "none",
      }}
    >
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {target.label || target.target_id}
          </span>
          <span style={{
            ...machineMetaTextStyle(t),
            color: target.connected ? t.success : t.textMuted,
            whiteSpace: "nowrap",
          }}
          >
            {target.connected ? "Connected" : "Offline"}
          </span>
        </div>
        <div style={machineMetaTextStyle(t)}>
          {meta || target.target_id}
        </div>
      </div>
      {target.connected ? (
        isActive ? (
          <button
            type="button"
            disabled={busy || !onRevoke}
            onClick={() => void onRevoke?.()}
            style={machineButtonStyle(t, "danger", busy || !onRevoke)}
          >
            Revoke
          </button>
        ) : (
          <button
            type="button"
            disabled={busy || !onUse}
            onClick={() => void onUse?.(target)}
            style={machineButtonStyle(t, "primary", busy || !onUse)}
          >
            Use
          </button>
        )
      ) : null}
    </div>
  );
}
