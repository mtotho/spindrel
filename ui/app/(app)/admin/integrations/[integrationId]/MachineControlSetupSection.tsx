import { ExternalLink, KeyRound, Monitor } from "lucide-react";
import { useMemo } from "react";

import { useThemeTokens } from "@/src/theme/tokens";
import { useAdminMachines } from "@/src/api/hooks/useMachineTargets";
import type { IntegrationMachineControlInfo } from "@/src/api/hooks/useIntegrations";

export function MachineControlSetupSection({
  machineControl,
}: {
  integrationId: string;
  machineControl: IntegrationMachineControlInfo;
  enableRemoteProvisioning: boolean;
}) {
  const t = useThemeTokens();
  const { data: machineData } = useAdminMachines(true);
  const provider = useMemo(
    () => machineData?.providers.find((item) => item.provider_id === machineControl.provider_id) ?? null,
    [machineData, machineControl.provider_id],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 12, color: t.textDim, lineHeight: "18px" }}>
        Machine lifecycle is owned by the core machine center. This integration page only covers provider-wide settings and status.
      </div>

      <div
        style={{
          display: "grid",
          gap: 10,
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 12px",
            borderRadius: 8,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surfaceRaised,
            fontSize: 12,
            color: t.textDim,
          }}
        >
          <Monitor size={14} />
          Driver: {machineControl.driver}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 12px",
            borderRadius: 8,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surfaceRaised,
            fontSize: 12,
            color: t.textDim,
          }}
        >
          <Monitor size={14} />
          Targets: {provider?.target_count ?? 0}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 12px",
            borderRadius: 8,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surfaceRaised,
            fontSize: 12,
            color: t.textDim,
          }}
        >
          <KeyRound size={14} />
          Profiles: {provider?.profile_count ?? 0}
        </div>
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
          padding: 12,
          borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.surfaceRaised,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Open Machine Center</div>
          <div style={{ fontSize: 11, color: t.textDim, lineHeight: "16px" }}>
            Manage machine profiles, enroll targets, probe readiness, and remove targets in `Admin &gt; Machines`.
            Chat remains the place where session leases are granted or revoked.
          </div>
        </div>
        <a
          href="/admin/machines"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
            fontWeight: 700,
            color: t.accent,
            textDecoration: "none",
          }}
        >
          Open machine center
          <ExternalLink size={12} />
        </a>
      </div>
    </div>
  );
}
