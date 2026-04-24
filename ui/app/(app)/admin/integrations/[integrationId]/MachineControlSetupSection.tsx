import { ExternalLink, KeyRound, Monitor } from "lucide-react";
import { useMemo } from "react";

import { useAdminMachines } from "@/src/api/hooks/useMachineTargets";
import type { IntegrationMachineControlInfo } from "@/src/api/hooks/useIntegrations";
import { ActionButton, InfoBanner, SettingsStatGrid } from "@/src/components/shared/SettingsControls";

export function MachineControlSetupSection({
  machineControl,
}: {
  integrationId: string;
  machineControl: IntegrationMachineControlInfo;
  enableRemoteProvisioning: boolean;
}) {
  const { data: machineData } = useAdminMachines(true);
  const provider = useMemo(
    () => machineData?.providers.find((item) => item.provider_id === machineControl.provider_id) ?? null,
    [machineData, machineControl.provider_id],
  );

  return (
    <div className="flex flex-col gap-3">
      <InfoBanner variant="info">
        Machine lifecycle is owned by the core machine center. This integration page only covers provider-wide settings and status.
      </InfoBanner>

      <SettingsStatGrid
        items={[
          { label: "Driver", value: machineControl.driver },
          { label: "Targets", value: provider?.target_count ?? 0, tone: provider?.target_count ? "accent" : "default" },
          { label: "Ready", value: provider?.ready_target_count ?? 0, tone: provider?.ready_target_count ? "success" : "default" },
          { label: "Profiles", value: provider?.profile_count ?? 0, tone: provider?.profile_count ? "accent" : "default" },
        ]}
      />

      <div className="flex flex-col gap-2 rounded-md bg-surface-raised/35 p-3.5 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[12px] font-semibold text-text">
            <Monitor size={13} className="text-text-dim" />
            Open Machine Center
          </div>
          <div className="mt-0.5 text-[11px] leading-snug text-text-dim">
            Manage profiles, enroll targets, probe readiness, and remove targets in Admin &gt; Machines.
          </div>
        </div>
        <ActionButton
          label="Open machine center"
          onPress={() => { window.location.href = "/admin/machines"; }}
          size="small"
          icon={<ExternalLink size={12} />}
        />
      </div>

      {provider?.supports_profiles && (
        <div className="flex items-center gap-1.5 text-[11px] text-text-dim">
          <KeyRound size={12} />
          Profiles are reusable provider-scoped credentials; targets bind to one explicit profile.
        </div>
      )}
    </div>
  );
}
