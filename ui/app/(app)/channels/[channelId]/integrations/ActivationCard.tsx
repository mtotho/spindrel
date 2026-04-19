import { Puzzle, Plus, X as XIcon, Layers } from "lucide-react";
import { Link } from "react-router-dom";
import { useThemeTokens } from "@/src/theme/tokens";
import { prettyIntegrationName } from "@/src/utils/format";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
import type { ActivatableIntegration } from "@/src/types/api";
import { ActivationConfigFields } from "./ActivationConfigFields";
import { HudPresetPicker } from "./HudPresetPicker";

function CarapacePill({ id, t }: { id: string; t: any }) {
  const href = `/admin/carapaces/${id.replaceAll("/", "--")}`;
  return (
    <Link to={href}>
      <span
        style={{
          display: "inline-flex", flexDirection: "row",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          borderRadius: 4,
          background: t.accentSubtle,
          border: `1px solid ${t.accentBorder}`,
          textDecoration: "none",
          cursor: "pointer",
          transition: "filter 0.12s",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.filter = "brightness(0.95)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.filter = "none"; }}
      >
        <Layers size={10} color={t.accent} />
        <span style={{ fontSize: 10, fontWeight: 600, color: t.accent }}>{id}</span>
      </span>
    </Link>
  );
}

function InjectionSummaryLine({ ig }: { ig: ActivatableIntegration }) {
  const parts: string[] = [];
  if (ig.tools.length > 0) parts.push(`${ig.tools.length} tools`);
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
  if (ig.tools.length === 0 && !ig.has_system_prompt && ig.carapaces.length === 0) return null;

  // Compact single-line summary for the injection metadata
  const meta: string[] = [];
  if (ig.tools.length > 0) meta.push(`${ig.tools.length} tools`);
  if (ig.has_system_prompt) meta.push("system prompt");

  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${t.surfaceBorder}` }}>
      {ig.carapaces.length > 0 && (
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6, flexWrap: "wrap" }}>
          {ig.carapaces.map((id) => (
            <CarapacePill key={id} id={id} t={t} />
          ))}
          {meta.length > 0 && (
            <span style={{ fontSize: 10, color: t.textDim }}>
              {meta.join(" \u00b7 ")}
            </span>
          )}
        </div>
      )}
      {ig.carapaces.length === 0 && meta.length > 0 && (
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
        borderRadius: 8,
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
                borderRadius: 4,
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

        <button
          onClick={() => !disabled && !toggling && onToggle()}
          disabled={disabled || toggling}
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 6,
            padding: "6px 14px",
            borderRadius: 8,
            border: `1px solid ${ig.activated ? t.surfaceBorder : t.accentBorder}`,
            background: ig.activated ? "transparent" : t.accent,
            color: ig.activated ? t.textDim : "#fff",
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
                border: `2px solid ${ig.activated ? t.textDim : "#fff"}`,
                borderTopColor: "transparent",
                borderRadius: "50%",
                display: "inline-block",
                animation: "spin 0.6s linear infinite",
              }}
            />
          ) : ig.activated ? (
            <XIcon size={12} />
          ) : (
            <Plus size={12} />
          )}
          {ig.activated ? "Remove" : "Add"}
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
