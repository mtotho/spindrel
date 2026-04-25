import { useState } from "react";

import { useClearSessionMachineTargetLease, useGrantSessionMachineTargetLease, useSessionMachineTarget } from "@/src/api/hooks/useMachineTargets";

import type { RichResultViewProps } from "../../RichToolResult";
import {
  MachineLeaseSummary,
  MachineStarterPromptButton,
  MachineTargetRow,
  coerceMachineTargetState,
  machineCardStyle,
  machineMetaTextStyle,
} from "./shared";

export function MachineTargetStatusRenderer({
  data,
  sessionId,
  t,
}: RichResultViewProps) {
  const initial = coerceMachineTargetState(data);
  const live = useSessionMachineTarget(sessionId, Boolean(sessionId));
  const liveState = live.data ?? (sessionId ? undefined : initial);
  const state = liveState ?? initial;
  const targets = state.targets ?? [];
  const readyTargets = targets.filter((target) => target.ready);
  const lease = state.lease ?? null;
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={machineCardStyle(t)}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ fontWeight: 700, color: t.text }}>Machine Control</div>
            <div style={machineMetaTextStyle(t)}>
              {lease
                ? "This session currently has a machine lease."
                : readyTargets.length
                  ? `${readyTargets.length} ready target${readyTargets.length === 1 ? "" : "s"} available.`
                  : "No ready machine targets are available for this session."}
            </div>
          </div>
          {sessionId ? (
            <span style={machineMetaTextStyle(t)}>{sessionId.slice(0, 8)}</span>
          ) : null}
        </div>
        {lease ? (
          <div style={{ marginTop: 10, ...machineCardStyle(t), padding: 10, background: t.surfaceRaised }}>
            <MachineLeaseSummary lease={lease} t={t} />
            <div style={{ marginTop: 10 }}>
              <MachineStarterPromptButton targetLabel={lease.target_label || lease.target_id} leaseActive t={t} />
            </div>
          </div>
        ) : null}
        {!targets.length ? (
          <div style={{ marginTop: 10, ...machineMetaTextStyle(t) }}>
            Enroll a target from Admin &gt; Machines, then use the provider-specific setup flow to make it ready.
          </div>
        ) : (
          <div style={{ marginTop: 10 }}>
            {targets.map((target, index) => (
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
            {readyTargets.length > 0 && !lease ? (
              <div style={{ marginTop: 10 }}>
                <MachineStarterPromptButton targetLabel={readyTargets[0]?.label || readyTargets[0]?.target_id} t={t} />
              </div>
            ) : null}
          </div>
        )}
        {actionError ? (
          <div style={{ marginTop: 8, fontSize: 11, color: t.danger }}>{actionError}</div>
        ) : null}
      </div>
    </div>
  );
}

export function renderMachineTargetStatusView(props: RichResultViewProps) {
  return <MachineTargetStatusRenderer {...props} />;
}
