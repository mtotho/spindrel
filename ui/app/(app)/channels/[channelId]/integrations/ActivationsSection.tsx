import { useState } from "react";
import { AlertTriangle, Search, X } from "lucide-react";
import {
  useActivatableIntegrations,
  useActivateIntegration,
  useDeactivateIntegration,
} from "@/src/api/hooks/useChannels";
import { Section } from "@/src/components/shared/FormControls";
import { InfoBanner } from "@/src/components/shared/SettingsControls";
import type { ActivationResult } from "@/src/types/api";
import { ActivationCard } from "./ActivationCard";

function GroupLabel({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center gap-1.5 pt-1">
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
        {label}
      </span>
      <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] font-semibold text-text-dim">
        {count}
      </span>
    </div>
  );
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
              <div className="flex min-h-[34px] items-center gap-1.5 rounded-md bg-surface-raised/50 px-2.5 text-text-dim transition-colors focus-within:bg-surface-overlay/45 focus-within:ring-2 focus-within:ring-accent/30 sm:w-64">
                <Search size={13} className="shrink-0" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filter add-ons..."
                  className="min-w-0 flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
                />
                {query && (
                  <button
                    type="button"
                    onClick={() => setQuery("")}
                    aria-label="Clear add-on filter"
                    className="inline-flex items-center p-0 text-text-dim transition-colors hover:text-text"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
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
