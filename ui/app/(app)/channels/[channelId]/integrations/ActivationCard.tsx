import { Zap, Power, Layers } from "lucide-react";
import { Link } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import { prettyIntegrationName } from "@/src/utils/format";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
import type { ActivatableIntegration } from "@/src/types/api";
import { ActivationConfigFields } from "./ActivationConfigFields";
import { HudPresetPicker } from "./HudPresetPicker";

function CarapacePill({ id, t }: { id: string; t: any }) {
  return (
    <Link href={`/admin/carapaces/${id}` as any} asChild>
      <a
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          borderRadius: 5,
          background: t.accentSubtle,
          border: `1px solid ${t.accentBorder}`,
          textDecoration: "none",
          cursor: "pointer",
        }}
      >
        <Layers size={10} color={t.accent} />
        <span style={{ fontSize: 11, fontWeight: 600, color: t.accent }}>{id}</span>
      </a>
    </Link>
  );
}

function InjectionSummaryLine({ ig }: { ig: ActivatableIntegration }) {
  const parts: string[] = [];
  if (ig.tools.length > 0) parts.push(`${ig.tools.length} tools`);
  if (ig.skill_count > 0) parts.push(`${ig.skill_count} skills`);
  if (ig.has_system_prompt) parts.push("system prompt");
  if (parts.length === 0) return null;
  const carapaceLabel = ig.carapaces.length > 0
    ? ig.carapaces.join(", ")
    : null;
  return (
    <span>
      Adds {parts.join(", ")}
      {carapaceLabel ? ` via ${carapaceLabel} capability` : ""}
    </span>
  );
}

function InjectionDetails({ ig, t }: { ig: ActivatableIntegration; t: any }) {
  if (ig.tools.length === 0 && ig.skill_count === 0 && !ig.has_system_prompt && ig.carapaces.length === 0) return null;
  return (
    <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${t.surfaceBorder}` }}>
      {ig.carapaces.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: t.text }}>Capability:</span>
          {ig.carapaces.map((id) => (
            <CarapacePill key={id} id={id} t={t} />
          ))}
          <span style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>
            from {prettyIntegrationName(ig.integration_type)}
          </span>
        </div>
      )}
      {ig.tools.length > 0 && (
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 3 }}>
          <span style={{ fontWeight: 600, color: t.text }}>Tools: </span>
          {ig.tools.join(", ")}
        </div>
      )}
      {ig.skill_count > 0 && (
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 3 }}>
          <span style={{ fontWeight: 600, color: t.text }}>Skills: </span>
          {ig.skill_count}
        </div>
      )}
      {ig.has_system_prompt && (
        <div style={{ fontSize: 11, color: t.textDim }}>
          <span style={{ fontWeight: 600, color: t.text }}>System prompt: </span>
          injected
        </div>
      )}
    </div>
  );
}

export function ActivationCard({
  ig,
  channelId,
  workspaceEnabled,
  toggling,
  onToggle,
}: {
  ig: ActivatableIntegration;
  channelId: string;
  workspaceEnabled: boolean;
  toggling: boolean;
  onToggle: () => void;
}) {
  const t = useThemeTokens();
  const disabled = ig.requires_workspace && !workspaceEnabled && !ig.activated;

  return (
    <div
      style={{
        borderRadius: 10,
        border: `1px solid ${ig.activated ? t.accentBorder : t.surfaceBorder}`,
        background: ig.activated ? t.accentSubtle : t.surfaceRaised,
        transition: "all 0.15s ease",
        overflow: "hidden",
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "flex",
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
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            transition: "background 0.15s",
          }}
        >
          <Zap
            size={16}
            color={ig.activated ? "#fff" : t.textDim}
            fill={ig.activated ? "#fff" : "none"}
          />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
              {prettyIntegrationName(ig.integration_type)}
            </span>
            {ig.activated && <StatusBadge label="Active" variant="success" />}
            {ig.includes?.length > 0 && (
              <span style={{
                fontSize: 10,
                fontWeight: 600,
                color: t.textDim,
                padding: "1px 6px",
                borderRadius: 3,
                background: t.surfaceOverlay,
              }}>
                includes {ig.includes.map(i => prettyIntegrationName(i)).join(", ")}
              </span>
            )}
            {ig.requires_workspace && !workspaceEnabled && (
              <StatusBadge label="Requires workspace" variant="warning" />
            )}
          </div>
          {ig.description && (
            <div style={{ fontSize: 11, color: t.textDim, marginTop: 3, lineHeight: "1.4" }}>
              {ig.description}
            </div>
          )}
          {!ig.activated && (ig.tools.length > 0 || ig.skill_count > 0) && (
            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 3, fontStyle: "italic" }}>
              <InjectionSummaryLine ig={ig} />
            </div>
          )}
        </div>

        <button
          onClick={() => !disabled && !toggling && onToggle()}
          disabled={disabled || toggling}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            padding: "6px 12px",
            borderRadius: 6,
            border: ig.activated
              ? `1px solid ${t.dangerBorder}`
              : `1px solid ${t.accentBorder}`,
            background: ig.activated ? "transparent" : t.accent,
            color: ig.activated ? t.danger : "#fff",
            fontSize: 11,
            fontWeight: 600,
            cursor: disabled || toggling ? "not-allowed" : "pointer",
            opacity: disabled ? 0.4 : 1,
            flexShrink: 0,
            transition: "all 0.12s",
          }}
        >
          {toggling ? (
            <span
              style={{
                width: 12,
                height: 12,
                border: `2px solid ${ig.activated ? t.danger : "#fff"}`,
                borderTopColor: "transparent",
                borderRadius: "50%",
                display: "inline-block",
                animation: "spin 0.6s linear infinite",
              }}
            />
          ) : (
            <Power size={12} />
          )}
          {ig.activated ? "Deactivate" : "Activate"}
        </button>
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
