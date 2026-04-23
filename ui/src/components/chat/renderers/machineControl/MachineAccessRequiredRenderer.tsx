import { useState } from "react";

import { useClearSessionMachineTargetLease, useGrantSessionMachineTargetLease, useSessionMachineTarget } from "@/src/api/hooks/useMachineTargets";

import type { RichResultViewProps } from "../../RichToolResult";
import {
  MachineLeaseSummary,
  MachineTargetRow,
  coerceMachineAccessRequiredPayload,
  machineButtonStyle,
  machineCardStyle,
  machineMetaTextStyle,
} from "./shared";

export function MachineAccessRequiredRenderer({
  data,
  sessionId,
  t,
}: RichResultViewProps) {
  const initial = coerceMachineAccessRequiredPayload(data);
  const live = useSessionMachineTarget(sessionId, Boolean(sessionId));
  const liveState = live.data;
  const targets = liveState?.targets ?? initial.targets ?? [];
  const connectedTargets = targets.filter((target) => target.connected);
  const lease = liveState?.lease ?? initial.lease ?? null;
  const reason = initial.reason ?? "Grant machine access for this session before using that tool.";
  const grantLease = useGrantSessionMachineTargetLease(sessionId ?? "");
  const clearLease = useClearSessionMachineTargetLease(sessionId ?? "");
  const [actionError, setActionError] = useState<string | null>(null);
  const canMutate = Boolean(sessionId);
  const busy = grantLease.isPending || clearLease.isPending;

  async function handleUse(target: (typeof targets)[number]) {
    if (!sessionId) return;
    setActionError(null);
    try {
      await grantLease.mutateAsync({ provider_id: target.provider_id, target_id: target.target_id });
      await live.refetch();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to grant machine access.");
    }
  }

  async function handleRevoke() {
    if (!sessionId) return;
    setActionError(null);
    try {
      await clearLease.mutateAsync();
      await live.refetch();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to revoke machine access.");
    }
  }

  const singleConnected = connectedTargets.length === 1 ? connectedTargets[0] : null;

  return (
    <div style={{ ...machineCardStyle(t), display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ fontWeight: 700, color: t.text }}>Machine Access Required</div>
        <div style={machineMetaTextStyle(t)}>
          {reason}
        </div>
      </div>

      {lease ? (
        <div style={{ ...machineCardStyle(t), padding: 10, background: t.surfaceRaised }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <MachineLeaseSummary lease={lease} t={t} />
            {canMutate ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleRevoke()}
                style={machineButtonStyle(t, "danger", busy)}
              >
                Revoke
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {singleConnected ? (
        <div style={{ ...machineCardStyle(t), padding: 10, background: t.surfaceRaised }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
              <div style={{ fontWeight: 600, color: t.text }}>{singleConnected.label || singleConnected.target_id}</div>
              <div style={machineMetaTextStyle(t)}>
                {[singleConnected.provider_label, singleConnected.hostname, singleConnected.platform].filter(Boolean).join(" · ") || singleConnected.target_id}
              </div>
            </div>
            {canMutate ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleUse(singleConnected)}
                style={machineButtonStyle(t, "primary", busy)}
              >
                Use machine
              </button>
            ) : null}
          </div>
        </div>
      ) : connectedTargets.length > 1 ? (
        <div style={{ ...machineCardStyle(t), padding: 10, background: t.surfaceRaised }}>
          <div style={{ fontSize: 11, color: t.textDim, marginBottom: 2 }}>
            Choose a connected machine for this session.
          </div>
          {connectedTargets.map((target, index) => (
            <MachineTargetRow
              key={`${target.provider_id}:${target.target_id}`}
              target={target}
              activeLeaseTargetId={lease?.target_id}
              busy={busy}
              showTopBorder={index !== 0}
              onUse={canMutate ? handleUse : undefined}
              onRevoke={canMutate && lease?.target_id === target.target_id ? handleRevoke : undefined}
              t={t}
            />
          ))}
        </div>
      ) : (
        <div style={{ ...machineCardStyle(t), padding: 10, background: t.surfaceRaised }}>
          <div style={{ fontSize: 11, color: t.textDim, lineHeight: "17px" }}>
            No connected machines are available right now.
          </div>
          <div style={{ marginTop: 8 }}>
            <a
              href={initial.admin_machines_href || initial.integration_admin_href || "/admin/machines"}
              style={{ color: t.accent, fontSize: 11, fontWeight: 600, textDecoration: "none" }}
            >
              Open machine control center
            </a>
          </div>
        </div>
      )}

      {actionError ? (
        <div style={{ fontSize: 11, color: t.danger }}>{actionError}</div>
      ) : null}
    </div>
  );
}

export function renderMachineAccessRequiredView(props: RichResultViewProps) {
  return <MachineAccessRequiredRenderer {...props} />;
}
