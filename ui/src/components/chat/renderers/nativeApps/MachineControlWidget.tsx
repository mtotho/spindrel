import { useState } from "react";

import {
  useClearSessionMachineTargetLease,
  useGrantSessionMachineTargetLease,
  useProbeAnyMachineTarget,
  useSessionMachineTarget,
  type MachineTarget,
} from "@/src/api/hooks/useMachineTargets";

import { PreviewCard, parsePayload, type NativeAppRendererProps } from "./shared";
import { deriveNativeWidgetLayoutProfile } from "./nativeWidgetLayout";
import {
  MachineLeaseSummary,
  MachineTargetRow,
  machineButtonStyle,
  machineCardStyle,
  machineMetaTextStyle,
} from "../machineControl/shared";

function ReadonlyState({ t }: { t: NativeAppRendererProps["t"] }) {
  return (
    <div style={{ ...machineCardStyle(t), background: t.surface }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontWeight: 700, color: t.text }}>Machine control is session-scoped.</div>
        <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
          Open the channel chat to grant, revoke, or probe machine targets. This widget only exposes live controls when
          a session is active.
        </div>
      </div>
    </div>
  );
}

function SectionLabel({
  label,
  t,
}: {
  label: string;
  t: NativeAppRendererProps["t"];
}) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: t.textDim,
      }}
    >
      {label}
    </div>
  );
}

export function MachineControlWidget({
  envelope,
  sessionId,
  layout,
  gridDimensions,
  t,
}: NativeAppRendererProps) {
  const payload = parsePayload(envelope);
  const profile = deriveNativeWidgetLayoutProfile(layout, gridDimensions, {
    compactMaxWidth: 360,
    compactMaxHeight: 190,
    wideMinWidth: 640,
    wideMinHeight: 200,
    tallMinHeight: 280,
  });
  const live = useSessionMachineTarget(sessionId, Boolean(sessionId));
  const grantLease = useGrantSessionMachineTargetLease(sessionId ?? "");
  const clearLease = useClearSessionMachineTargetLease(sessionId ?? "");
  const probeTarget = useProbeAnyMachineTarget();
  const [actionError, setActionError] = useState<string | null>(null);

  if (!payload.widget_instance_id) {
    return (
      <PreviewCard
        title="Machine control"
        description="Session-scoped machine status and quick lease controls."
        t={t}
      />
    );
  }

  if (!sessionId) {
    return <ReadonlyState t={t} />;
  }

  const state = live.data;
  const lease = state?.lease ?? null;
  const targets = state?.targets ?? [];
  const readyTargets = targets.filter((target) => target.ready);
  const busy = grantLease.isPending || clearLease.isPending || probeTarget.isPending;
  const stackGap = profile.compact ? 8 : 10;

  async function refreshState() {
    await live.refetch();
  }

  async function handleUse(target: MachineTarget) {
    setActionError(null);
    try {
      await grantLease.mutateAsync({ provider_id: target.provider_id, target_id: target.target_id });
      await refreshState();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to grant machine access.");
    }
  }

  async function handleRevoke() {
    setActionError(null);
    try {
      await clearLease.mutateAsync();
      await refreshState();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to revoke machine access.");
    }
  }

  async function handleProbe(target: MachineTarget) {
    setActionError(null);
    try {
      await probeTarget.mutateAsync({ providerId: target.provider_id, targetId: target.target_id });
      await refreshState();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to probe machine target.");
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: stackGap }}>
      <div style={machineCardStyle(t)}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ fontWeight: 700, color: t.text }}>Session machine control</div>
              <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.5 }}>
                {lease
                  ? "This session currently holds a machine lease."
                  : readyTargets.length
                    ? `${readyTargets.length} ready target${readyTargets.length === 1 ? "" : "s"} available.`
                    : "No ready machine targets are currently available."}
              </div>
            </div>
            <a
              href="/admin/machines"
              style={{ ...machineMetaTextStyle(t), textDecoration: "none", color: t.accent, alignSelf: "flex-start" }}
            >
              Admin &gt; Machines
            </a>
          </div>
          {lease ? (
            <div style={{ ...machineCardStyle(t), padding: 10, background: t.surfaceRaised }}>
              <SectionLabel label="Current lease" t={t} />
              <div style={{ marginTop: 8 }}>
                <MachineLeaseSummary lease={lease} t={t} />
              </div>
              <div style={{ marginTop: 10 }}>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleRevoke()}
                  style={machineButtonStyle(t, "danger", busy)}
                >
                  Revoke
                </button>
              </div>
            </div>
          ) : null}
          {!targets.length ? (
            <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
              Enroll targets from Admin &gt; Machines. Provider setup lives there; this widget only reflects and controls
              the current session.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
              <SectionLabel label="Targets" t={t} />
              <div style={{ marginTop: 8 }}>
                {targets.map((target, index) => (
                  <div key={`${target.provider_id}:${target.target_id}`} style={{ display: "flex", flexDirection: "column" }}>
                    <MachineTargetRow
                      target={target}
                      activeLeaseTargetId={lease?.target_id}
                      busy={busy}
                      showTopBorder={index !== 0}
                      onUse={handleUse}
                      onRevoke={lease?.target_id === target.target_id ? handleRevoke : undefined}
                      t={t}
                    />
                    <div
                      style={{
                        display: "flex",
                        justifyContent: profile.compact ? "flex-start" : "flex-end",
                        marginTop: -4,
                        paddingBottom: 10,
                      }}
                    >
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void handleProbe(target)}
                        style={machineButtonStyle(t, "default", busy)}
                      >
                        Probe
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {actionError ? <div style={{ fontSize: 11, color: t.danger }}>{actionError}</div> : null}
        </div>
      </div>
    </div>
  );
}
