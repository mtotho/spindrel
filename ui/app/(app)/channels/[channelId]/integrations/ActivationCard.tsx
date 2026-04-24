import { Puzzle, Plus, X as XIcon } from "lucide-react";
import { prettyIntegrationName } from "@/src/utils/format";
import { ActionButton, StatusBadge } from "@/src/components/shared/SettingsControls";
import type { ActivatableIntegration } from "@/src/types/api";
import { ActivationConfigFields } from "./ActivationConfigFields";

function InjectionSummaryLine({ ig }: { ig: ActivatableIntegration }) {
  const parts: string[] = [];
  if (ig.tools.length > 0) parts.push(`${ig.tools.length} tools`);
  if (ig.has_system_prompt) parts.push("system prompt");
  if (parts.length === 0) return null;
  return <span>Adds {parts.join(", ")}</span>;
}

function InjectionDetails({ ig }: { ig: ActivatableIntegration }) {
  if (ig.tools.length === 0 && !ig.has_system_prompt) return null;

  // Compact single-line summary for the injection metadata
  const meta: string[] = [];
  if (ig.tools.length > 0) meta.push(`${ig.tools.length} tools`);
  if (ig.has_system_prompt) meta.push("system prompt");

  return (
    <div className="mt-2 border-t border-surface-border pt-2">
      {meta.length > 0 && (
        <div className="text-[11px] text-text-dim">
          {meta.join(" \u00b7 ")}
        </div>
      )}
    </div>
  );
}

export function ActivationCard({
  ig,
  channelId,
  toggling,
  onToggle,
}: {
  ig: ActivatableIntegration;
  channelId: string;
  toggling: boolean;
  onToggle: () => void;
}) {
  const disabled = false;

  return (
    <div
      className={
        `relative overflow-hidden rounded-md transition-colors ` +
        (ig.activated
          ? "bg-accent/[0.06] before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-accent"
          : "bg-surface-raised/40 hover:bg-surface-overlay/45")
      }
    >
      {/* Header row */}
      <div className="flex items-center gap-3 px-3 py-2.5">
        <div className={`relative flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors ${ig.activated ? "bg-accent/10" : "bg-surface-overlay/45"}`}>
          <Puzzle
            size={15}
            className={ig.activated ? "text-accent" : "text-text-dim"}
          />
          {ig.activated && (
            <span
              aria-hidden
              className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-success ring-2 ring-surface"
            />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-semibold text-text">
              {prettyIntegrationName(ig.integration_type)}
            </span>
            {ig.activated && <StatusBadge label="Added" variant="success" />}
            {ig.includes?.length > 0 && (
              <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-[10px] font-medium text-text-muted">
                + {ig.includes.map(i => prettyIntegrationName(i)).join(", ")}
              </span>
            )}
          </div>
          {ig.description && (
            <div className="mt-0.5 text-[11px] leading-snug text-text-dim">
              {ig.description}
            </div>
          )}
          {!ig.activated && ig.tools.length > 0 && (
            <div className="mt-0.5 text-[11px] italic text-text-dim">
              <InjectionSummaryLine ig={ig} />
            </div>
          )}
        </div>

        <ActionButton
          label={toggling ? (ig.activated ? "Removing..." : "Adding...") : ig.activated ? "Remove" : "Add"}
          onPress={onToggle}
          disabled={disabled || toggling}
          variant={ig.activated ? "secondary" : "primary"}
          size="small"
          icon={toggling ? undefined : ig.activated ? <XIcon size={12} /> : <Plus size={12} />}
        />
      </div>

      {/* Expanded content for active cards */}
      {ig.activated && (
        <div className="px-3 pb-3">
          <InjectionDetails ig={ig} />
          <ActivationConfigFields ig={ig} channelId={channelId} />
        </div>
      )}
    </div>
  );
}
