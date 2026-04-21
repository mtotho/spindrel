import { Plug } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import type { ActivatableIntegration } from "../../types/api";

interface IntegrationActivationListProps {
  integrations: ActivatableIntegration[];
  enabled: string[];
  onToggle: (integrationType: string) => void;
}

export function IntegrationActivationList({
  integrations,
  enabled,
  onToggle,
}: IntegrationActivationListProps) {
  const t = useThemeTokens();

  if (integrations.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {integrations.map((integration) => {
        const isEnabled = enabled.includes(integration.integration_type);

        return (
          <div
            key={integration.integration_type}
            style={{
              border: `1px solid ${isEnabled ? t.accent + "40" : t.surfaceBorder}`,
              backgroundColor: isEnabled ? t.accent + "08" : "transparent",
              borderRadius: 10,
              padding: 14,
              display: "flex",
              flexDirection: "column",
              gap: 6,
            }}
          >
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 12 }}>
              <Plug size={16} color={isEnabled ? t.accent : t.textDim} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <span style={{
                  display: "block",
                  fontSize: 14,
                  fontWeight: 500,
                  color: isEnabled ? t.accent : t.text,
                }}>
                  {integration.integration_type.replace(/_/g, " ")}
                </span>
                {integration.description && (
                  <span style={{
                    display: "block",
                    fontSize: 12,
                    color: t.textMuted,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {integration.description}
                  </span>
                )}
              </div>
              {/* Toggle switch */}
              <button
                onClick={() => onToggle(integration.integration_type)}
                style={{
                  width: 44,
                  height: 24,
                  borderRadius: 12,
                  backgroundColor: isEnabled ? t.accent : t.surfaceBorder,
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                  position: "relative",
                  transition: "background-color 0.2s",
                  flexShrink: 0,
                }}
              >
                <div
                  style={{
                    width: 20,
                    height: 20,
                    borderRadius: 10,
                    backgroundColor: "white",
                    position: "absolute",
                    top: 2,
                    left: isEnabled ? 22 : 2,
                    transition: "left 0.2s",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                  }}
                />
              </button>
            </div>

            {/* What it provides */}
            <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6, marginLeft: 28 }}>
              {integration.tools.length > 0 && (
                <span style={{
                  backgroundColor: t.surfaceBorder,
                  padding: "2px 6px",
                  borderRadius: 4,
                  fontSize: 10,
                  color: t.textDim,
                }}>
                  {integration.tools.length} tool{integration.tools.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
