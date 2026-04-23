import { Puzzle, Plus, X as XIcon } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { prettyIntegrationName } from "@/src/utils/format";
import { ActionButton, StatusBadge } from "@/src/components/shared/SettingsControls";
import type { ActivatableIntegration } from "@/src/types/api";
import { ActivationConfigFields } from "./ActivationConfigFields";
import { HudPresetPicker } from "./HudPresetPicker";

function InjectionSummaryLine({ ig }: { ig: ActivatableIntegration }) {
  const parts: string[] = [];
  if (ig.tools.length > 0) parts.push(`${ig.tools.length} tools`);
  if (ig.has_system_prompt) parts.push("system prompt");
  if (parts.length === 0) return null;
  return <span>Adds {parts.join(", ")}</span>;
}

function InjectionDetails({ ig, t }: { ig: ActivatableIntegration; t: any }) {
  if (ig.tools.length === 0 && !ig.has_system_prompt) return null;

  // Compact single-line summary for the injection metadata
  const meta: string[] = [];
  if (ig.tools.length > 0) meta.push(`${ig.tools.length} tools`);
  if (ig.has_system_prompt) meta.push("system prompt");

  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${t.surfaceBorder}` }}>
      {meta.length > 0 && (
        <div style={{ fontSize: 11, color: t.textDim }}>
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
  const t = useThemeTokens();
  const disabled = false;

  return (
    <div
      style={{
        borderRadius: 6,
        border: `1px solid ${ig.activated ? t.accentBorder : t.surfaceBorder}`,
        background: ig.activated ? t.accentSubtle : t.surfaceRaised,
        transition: "all 0.15s ease",
        overflow: "hidden",
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 12,
          padding: "12px 14px",
        }}
      >
        <div
          style={{
            width: 34,
            height: 34,
            borderRadius: 8,
            background: ig.activated ? t.accent : t.surfaceOverlay,
            display: "flex", flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            transition: "background 0.15s",
          }}
        >
          <Puzzle
            size={16}
            color={ig.activated ? "#fff" : t.textDim}
          />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
              {prettyIntegrationName(ig.integration_type)}
            </span>
            {ig.activated && <StatusBadge label="Added" variant="success" />}
            {ig.includes?.length > 0 && (
              <span style={{
                fontSize: 10,
                fontWeight: 500,
                color: t.textMuted,
            padding: "2px 8px",
                borderRadius: 6,
                background: t.surfaceOverlay,
                letterSpacing: 0.2,
              }}>
                + {ig.includes.map(i => prettyIntegrationName(i)).join(", ")}
              </span>
            )}
          </div>
          {ig.description && (
            <div style={{ fontSize: 11, color: t.textDim, marginTop: 3, lineHeight: "1.4" }}>
              {ig.description}
            </div>
          )}
          {!ig.activated && ig.tools.length > 0 && (
            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 3, fontStyle: "italic" }}>
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
        <div style={{ padding: "0 14px 12px" }}>
          <InjectionDetails ig={ig} t={t} />
          <ActivationConfigFields ig={ig} channelId={channelId} />
          <HudPresetPicker ig={ig} channelId={channelId} />
        </div>
      )}
    </div>
  );
}
