import { useThemeTokens } from "@/src/theme/tokens";
import { useUpdateActivationConfig } from "@/src/api/hooks/useChannels";
import type { ActivatableIntegration } from "@/src/types/api";

export function HudPresetPicker({
  ig,
  channelId,
}: {
  ig: ActivatableIntegration;
  channelId: string;
}) {
  const t = useThemeTokens();
  const configMut = useUpdateActivationConfig(channelId);
  const presets = ig.chat_hud_presets;
  if (!presets || Object.keys(presets).length < 2) return null;

  const presetEntries = Object.entries(presets);
  const currentPreset = ig.activation_config?.hud_preset as string | undefined;
  const selectedKey = (currentPreset && presets[currentPreset]) ? currentPreset : presetEntries[0][0];

  const widgetLabels: Record<string, string> = {};
  for (const w of ig.chat_hud ?? []) {
    widgetLabels[w.id] = w.label ?? w.id;
  }

  const handleSelect = (key: string) => {
    if (key === selectedKey) return;
    configMut.mutate({
      integrationType: ig.integration_type,
      config: { hud_preset: key },
    });
  };

  return (
    <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${t.surfaceBorder}` }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: t.textDim, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>
        HUD Layout
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {presetEntries.map(([key, preset]) => {
          const isSelected = key === selectedKey;
          return (
            <button
              key={key}
              onClick={() => handleSelect(key)}
              disabled={configMut.isPending}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "8px 10px",
                borderRadius: 8,
                border: `1.5px solid ${isSelected ? t.accent : t.surfaceBorder}`,
                background: isSelected ? t.accentSubtle : "transparent",
                cursor: configMut.isPending ? "wait" : "pointer",
                textAlign: "left",
                transition: "all 0.12s",
              }}
            >
              <div style={{
                width: 16, height: 16, borderRadius: 8, flexShrink: 0, marginTop: 1,
                border: `2px solid ${isSelected ? t.accent : t.surfaceBorder}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                transition: "border-color 0.12s",
              }}>
                {isSelected && (
                  <div style={{ width: 8, height: 8, borderRadius: 4, background: t.accent }} />
                )}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
                    {preset.label}
                  </span>
                  <span style={{ fontSize: 10, color: t.textDim }}>
                    {preset.widgets.length} widget{preset.widgets.length !== 1 ? "s" : ""}
                  </span>
                </div>
                {preset.description && (
                  <div style={{ fontSize: 11, color: t.textDim, marginTop: 2, lineHeight: "1.35" }}>
                    {preset.description}
                  </div>
                )}
                {preset.widgets.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 5 }}>
                    {preset.widgets.map((wid: string) => (
                      <span
                        key={wid}
                        style={{
                          fontSize: 10,
                          fontWeight: 500,
                          color: isSelected ? t.accent : t.textDim,
                          padding: "1px 6px",
                          borderRadius: 4,
                          background: isSelected ? `${t.accent}18` : t.surfaceOverlay,
                          border: `1px solid ${isSelected ? `${t.accent}33` : t.surfaceBorder}`,
                        }}
                      >
                        {widgetLabels[wid] ?? wid}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
