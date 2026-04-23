import React from "react";
import { Monitor, Plug, Power } from "lucide-react";

import { useThemeTokens } from "@/src/theme/tokens";
import {
  useClearSessionMachineTargetLease,
  useGrantSessionMachineTargetLease,
  useSessionMachineTarget,
} from "@/src/api/hooks/useMachineTargets";

export function MachineTargetChip({
  sessionId,
}: {
  sessionId: string;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const { data, isLoading } = useSessionMachineTarget(sessionId, true);
  const grantLease = useGrantSessionMachineTargetLease(sessionId);
  const clearLease = useClearSessionMachineTargetLease(sessionId);

  React.useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  const lease = data?.lease ?? null;
  const targets = data?.targets ?? [];
  const visibleTargets = lease ? targets : targets.filter((target) => target.connected);
  const hasVisibleControl = visibleTargets.length > 0 || !!lease;
  const pending =
    grantLease.isPending
    || clearLease.isPending;

  if (!isLoading && !hasVisibleControl) return null;

  return (
    <div ref={rootRef} style={{ position: "relative", flexShrink: 0 }}>
      <button
        type="button"
        className="header-icon-btn"
        onClick={() => setOpen((v) => !v)}
        disabled={pending}
        title={lease ? `Machine control: ${lease.target_label}` : "Machine control"}
        aria-label={lease ? `Machine control: ${lease.target_label}` : "Machine control"}
        aria-expanded={open}
        aria-haspopup="dialog"
        style={{
          width: 36,
          height: 36,
          backgroundColor: open || lease ? t.surfaceOverlay : undefined,
          opacity: pending ? 0.7 : 1,
        }}
      >
        <Monitor size={16} color={lease ? t.accent : open ? t.text : t.textDim} />
      </button>
      {open ? (
        <div
          role="dialog"
          aria-label="Machine control"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 40,
            width: 320,
            maxWidth: "min(92vw, 320px)",
            borderRadius: 12,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surfaceRaised,
            boxShadow: "0 12px 36px rgba(0,0,0,0.34)",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 8,
              padding: "12px 12px 10px",
              borderBottom: `1px solid ${t.surfaceBorder}`,
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Machine control</div>
              <div style={{ fontSize: 11, color: t.textDim }}>
                {lease ? `Leased to ${lease.target_label}` : "Connected companion targets"}
              </div>
            </div>
            {lease ? (
              <button
                type="button"
                onClick={() => clearLease.mutate()}
                disabled={pending}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  border: `1px solid ${t.surfaceBorder}`,
                  background: "transparent",
                  color: t.text,
                  borderRadius: 999,
                  padding: "6px 8px",
                  fontSize: 11,
                  fontWeight: 600,
                }}
              >
                <Power size={12} />
                Revoke
              </button>
            ) : null}
          </div>

          {isLoading ? (
            <div style={{ padding: 12, fontSize: 12, color: t.textDim }}>Loading machine targets…</div>
          ) : visibleTargets.length === 0 ? (
            <div style={{ padding: 12, fontSize: 12, color: t.textDim }}>
              No connected companion targets.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column" }}>
              {visibleTargets.map((target, index) => {
                const active = lease?.target_id === target.target_id;
                return (
                  <div
                    key={target.target_id}
                    style={{
                      borderTop: index > 0 ? `1px solid ${t.surfaceBorder}` : "none",
                      padding: 12,
                      display: "flex",
                      flexDirection: "column",
                      gap: 10,
                      background: active ? t.accentSubtle : "transparent",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                      <div style={{ minWidth: 0 }}>
                        <div
                          style={{
                            fontSize: 12,
                            fontWeight: 700,
                            color: t.text,
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          <span
                            style={{
                              width: 6,
                              height: 6,
                              borderRadius: "50%",
                              background: target.connected ? (active ? t.accent : "#4ade80") : t.textDim,
                              flexShrink: 0,
                            }}
                          />
                          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {target.label}
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: t.textDim }}>
                          {target.connected ? "Connected" : "Offline"}
                          {target.hostname ? ` · ${target.hostname}` : ""}
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <button
                          type="button"
                          onClick={() => grantLease.mutate({
                            provider_id: target.provider_id,
                            target_id: target.target_id,
                          })}
                          disabled={pending || !target.connected || active}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            border: `1px solid ${active ? t.accentBorder : t.surfaceBorder}`,
                            background: active ? t.accent : "transparent",
                            color: active ? "#fff" : t.text,
                            borderRadius: 999,
                            padding: "6px 8px",
                            fontSize: 11,
                            fontWeight: 600,
                            opacity: pending || !target.connected ? 0.6 : 1,
                          }}
                        >
                          <Plug size={12} />
                          {active ? "Leased" : "Use"}
                        </button>
                      </div>
                    </div>
                    {target.capabilities.length > 0 ? (
                      <div style={{ fontSize: 10, color: t.textDim }}>
                        Capabilities: {target.capabilities.join(", ")}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}

          {(grantLease.error || clearLease.error) ? (
            <div
              style={{
                padding: "10px 12px",
                borderTop: `1px solid ${t.surfaceBorder}`,
                fontSize: 11,
                color: t.textDim,
              }}
            >
              Request failed. Check auth and target state.
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
