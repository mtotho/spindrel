import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import {
  useActivatableIntegrations,
  useActivateIntegration,
  useDeactivateIntegration,
} from "@/src/api/hooks/useChannels";
import { Section } from "@/src/components/shared/FormControls";
import { InfoBanner, SettingsGroupLabel, SettingsSearchBox } from "@/src/components/shared/SettingsControls";
import type { ActivationResult } from "@/src/types/api";
import { ActivationCard } from "./ActivationCard";

function GroupLabel({ label, count }: { label: string; count: number }) {
  return <SettingsGroupLabel label={label} count={count} />;
}

export function ActivationsSection({ channelId }: { channelId: string }) {
  const { data: integrations, isLoading } = useActivatableIntegrations(channelId);
  const activateMut = useActivateIntegration(channelId);
  const deactivateMut = useDeactivateIntegration(channelId);
  const [warnings, setWarnings] = useState<ActivationResult["warnings"]>([]);
  const [togglingType, setTogglingType] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  if (isLoading || !integrations || integrations.length === 0) return null;

  // Filter out integrations provided by a parent (included_by)
  const visible = integrations.filter((ig) => !ig.included_by || ig.included_by.length === 0);
  if (visible.length === 0) return null;
  const active = visible.filter((ig) => ig.activated);
  const available = visible.filter((ig) => !ig.activated);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredAvailable = normalizedQuery
    ? available.filter((ig) => {
        const name = ig.integration_type.replace(/_/g, " ");
        return (
          name.toLowerCase().includes(normalizedQuery) ||
          ig.integration_type.toLowerCase().includes(normalizedQuery) ||
          ig.description.toLowerCase().includes(normalizedQuery)
        );
      })
    : available;

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
      title="Integration Add-ons"
      description="Installed integrations can add tools, skills, and prompts to this channel."
    >
      <div className="flex flex-col gap-5">
        {active.length > 0 && (
          <div className="flex flex-col gap-2">
            <GroupLabel label="Added to this channel" count={active.length} />
            <div className="flex flex-col gap-1.5">
              {active.map((ig) => (
                <ActivationCard
                  key={ig.integration_type}
                  ig={ig}
                  channelId={channelId}
                  toggling={togglingType === ig.integration_type}
                  onToggle={() => handleToggle(ig.integration_type, ig.activated)}
                />
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <GroupLabel label="Available add-ons" count={available.length} />
            {available.length > 6 && (
              <SettingsSearchBox
                value={query}
                onChange={setQuery}
                placeholder="Filter add-ons..."
                className="sm:w-64"
              />
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            {filteredAvailable.map((ig) => (
              <ActivationCard
                key={ig.integration_type}
                ig={ig}
                channelId={channelId}
                toggling={togglingType === ig.integration_type}
                onToggle={() => handleToggle(ig.integration_type, ig.activated)}
              />
            ))}
            {filteredAvailable.length === 0 && (
              <div className="rounded-md bg-surface-raised/40 px-3 py-5 text-center text-[12px] text-text-dim">
                No add-ons match this filter.
              </div>
            )}
          </div>
        </div>
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
