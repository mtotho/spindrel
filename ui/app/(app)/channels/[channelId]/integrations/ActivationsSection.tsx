import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import {
  useActivatableIntegrations,
  useActivateIntegration,
  useDeactivateIntegration,
} from "@/src/api/hooks/useChannels";
import { Section } from "@/src/components/shared/FormControls";
import { InfoBanner } from "@/src/components/shared/SettingsControls";
import type { ActivationResult } from "@/src/types/api";
import { ActivationCard } from "./ActivationCard";

export function ActivationsSection({
  channelId,
  workspaceEnabled,
}: {
  channelId: string;
  workspaceEnabled: boolean;
}) {
  const { data: integrations, isLoading } = useActivatableIntegrations(channelId);
  const activateMut = useActivateIntegration(channelId);
  const deactivateMut = useDeactivateIntegration(channelId);
  const [warnings, setWarnings] = useState<ActivationResult["warnings"]>([]);
  const [togglingType, setTogglingType] = useState<string | null>(null);

  if (isLoading || !integrations || integrations.length === 0) return null;

  // Filter out integrations provided by a parent (included_by)
  const visible = integrations.filter((ig) => !ig.included_by || ig.included_by.length === 0);
  if (visible.length === 0) return null;

  const handleToggle = async (integrationType: string, currentlyActive: boolean) => {
    setTogglingType(integrationType);
    setWarnings([]);
    try {
      if (currentlyActive) {
        await deactivateMut.mutateAsync(integrationType);
      } else {
        const result = await activateMut.mutateAsync(integrationType);
        if (result.warnings?.length) {
          setWarnings(result.warnings);
        }
      }
    } finally {
      setTogglingType(null);
    }
  };

  return (
    <Section
      title="Capabilities"
      description="Add tools, skills, and system prompts to this channel's bot. Activating a capability gives the bot new abilities without any external routing."
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {visible.map((ig) => (
          <ActivationCard
            key={ig.integration_type}
            ig={ig}
            channelId={channelId}
            workspaceEnabled={workspaceEnabled}
            toggling={togglingType === ig.integration_type}
            onToggle={() => handleToggle(ig.integration_type, ig.activated)}
          />
        ))}
      </div>

      {warnings.length > 0 && (
        <InfoBanner variant="warning" icon={<AlertTriangle size={14} />}>
          <div>
            {warnings.map((w, i) => (
              <div key={i}>{w.message}</div>
            ))}
          </div>
        </InfoBanner>
      )}
    </Section>
  );
}
