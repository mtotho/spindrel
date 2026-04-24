import { useState } from "react";
import { Link2, Check, Pencil, X } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import type { AvailableIntegration } from "../../api/hooks/useChannels";
import { BindingForm } from "../../../app/(app)/channels/[channelId]/integrations/BindingForm";

export interface PendingBinding {
  clientId: string;
  displayName: string;
  dispatchConfig: Record<string, any>;
}

interface BindableIntegrationsListProps {
  integrations: AvailableIntegration[];
  pending: Record<string, PendingBinding>;
  onSubmit: (type: string, pending: PendingBinding) => void;
  onRemove: (type: string) => void;
}

/** Per-integration binding tiles for the new-channel wizard.
 *
 * Shows one tile per integration that declares ``binding:`` in its manifest.
 * Clicking "Connect" expands the shared ``BindingForm`` (same picker used in
 * channel settings) with the integration type locked. Submitting captures
 * the binding into wizard state; the actual ``POST
 * /channels/:id/integrations`` happens after the channel is created.
 */
export function BindableIntegrationsList({
  integrations,
  pending,
  onSubmit,
  onRemove,
}: BindableIntegrationsListProps) {
  const t = useThemeTokens();
  const [expandedType, setExpandedType] = useState<string | null>(null);

  if (integrations.length === 0) return null;

  return (
    <div className="flex flex-col gap-2.5">
      {integrations.map((integration) => {
        const saved = pending[integration.type];
        const expanded = expandedType === integration.type;
        const hasBinding = !!saved;

        return (
          <div
            key={integration.type}
            className="rounded-[10px] p-3.5 flex flex-col gap-1.5"
            style={{
              border: `1px solid ${hasBinding ? t.accent + "40" : t.surfaceBorder}`,
              backgroundColor: hasBinding ? t.accent + "08" : "transparent",
            }}
          >
            <div className="flex flex-row items-center gap-3">
              <Link2 size={16} color={hasBinding ? t.accent : t.textDim} />
              <div className="flex-1 min-w-0">
                <span
                  className="block text-[14px] font-medium"
                  style={{ color: hasBinding ? t.accent : t.text }}
                >
                  {integration.type.replace(/_/g, " ")}
                </span>
                {saved ? (
                  <span
                    className="block text-[11px] truncate"
                    style={{ color: t.textMuted, fontFamily: "monospace" }}
                  >
                    {saved.clientId}
                  </span>
                ) : (
                  <span
                    className="block text-[12px]"
                    style={{ color: t.textMuted }}
                  >
                    Pick a {integration.type.replace(/_/g, " ")} channel to route to
                  </span>
                )}
              </div>
              {saved && !expanded && (
                <>
                  <button
                    type="button"
                    onClick={() => setExpandedType(integration.type)}
                    className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px]"
                    style={{
                      border: `1px solid ${t.surfaceBorder}`,
                      background: "transparent",
                      color: t.textMuted,
                      cursor: "pointer",
                    }}
                  >
                    <Pencil size={11} />
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => onRemove(integration.type)}
                    className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px]"
                    style={{
                      border: `1px solid ${t.surfaceBorder}`,
                      background: "transparent",
                      color: t.danger,
                      cursor: "pointer",
                    }}
                  >
                    <X size={11} />
                    Remove
                  </button>
                </>
              )}
              {!saved && !expanded && (
                <button
                  type="button"
                  onClick={() => setExpandedType(integration.type)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium"
                  style={{
                    backgroundColor: t.accent,
                    border: "none",
                    color: "#fff",
                    cursor: "pointer",
                  }}
                >
                  <Check size={12} />
                  Connect
                </button>
              )}
            </div>
            {expanded && (
              <div
                className="mt-2 rounded-md p-3"
                style={{
                  border: `1px solid ${t.surfaceBorder}`,
                  background: t.surfaceRaised,
                }}
              >
                <BindingForm
                  availableIntegrations={[integration]}
                  initialType={integration.type}
                  initialClientId={saved?.clientId ?? ""}
                  initialDisplayName={saved?.displayName ?? ""}
                  initialDispatchConfig={saved?.dispatchConfig}
                  onSubmit={(type, clientId, displayName, dispatchConfig) => {
                    onSubmit(type, { clientId, displayName, dispatchConfig });
                    setExpandedType(null);
                  }}
                  onCancel={() => setExpandedType(null)}
                  isPending={false}
                  isError={false}
                  submitLabel={saved ? "Save" : "Connect"}
                  lockType
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
