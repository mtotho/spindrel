import { useState, useCallback, useMemo } from "react";
import { ActivityIndicator, useWindowDimensions } from "react-native";
import { Check, Search, X, RotateCcw, ShieldOff } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannelEffectiveTools,
} from "@/src/api/hooks/useChannels";
import { useBotEditorData } from "@/src/api/hooks/useBots";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import { EmptyState } from "@/src/components/shared/FormControls";
import { StatusBadge, AdvancedSection } from "@/src/components/shared/SettingsControls";
import type { ChannelSettings } from "@/src/types/api";
import { EffectiveToolsList } from "./EffectiveToolsList";
import { EffectiveSkillsList } from "./EffectiveSkillsList";

function SectionDivider({ label, count }: { label: string; count?: number }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 0 4px" }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 1 }}>
        {label}
      </span>
      {count != null && (
        <span style={{ fontSize: 10, color: t.textDim }}>{count}</span>
      )}
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

export function ToolsOverrideTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const t = useThemeTokens();
  const { data: editorData, isLoading: editorLoading } = useBotEditorData(botId);
  const { data: settings } = useChannelSettings(channelId);
  const { data: effective } = useChannelEffectiveTools(channelId);
  const { data: allCarapaces } = useCarapaces();
  const updateMutation = useUpdateChannelSettings(channelId);
  const [filter, setFilter] = useState("");
  const [saved, setSaved] = useState(false);
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const save = useCallback(
    async (patch: Partial<ChannelSettings>) => {
      setSaved(false);
      await updateMutation.mutateAsync(patch);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    },
    [updateMutation],
  );

  const handleResetAll = useCallback(() => {
    if (!confirm("Reset all channel overrides? This will re-enable all disabled items and remove all extras.")) return;
    save({
      local_tools_disabled: null,
      mcp_servers_disabled: null,
      client_tools_disabled: null,
      skills_disabled: null,
      skills_extra: null,
      carapaces_extra: null,
      carapaces_disabled: null,
    } as any);
  }, [save]);

  const toggleCarapaceExtra = useCallback(
    (carapaceId: string) => {
      const current = settings?.carapaces_extra ?? [];
      const next = current.includes(carapaceId)
        ? current.filter((c) => c !== carapaceId)
        : [...current, carapaceId];
      const updates: any = { carapaces_extra: next.length > 0 ? next : null };
      if (!current.includes(carapaceId)) {
        const disabled = settings?.carapaces_disabled ?? [];
        if (disabled.includes(carapaceId)) {
          const nextDisabled = disabled.filter((c) => c !== carapaceId);
          updates.carapaces_disabled = nextDisabled.length > 0 ? nextDisabled : null;
        }
      }
      save(updates);
    },
    [settings, save],
  );

  const toggleCarapaceDisabled = useCallback(
    (carapaceId: string) => {
      const current = settings?.carapaces_disabled ?? [];
      const next = current.includes(carapaceId)
        ? current.filter((c) => c !== carapaceId)
        : [...current, carapaceId];
      const updates: any = { carapaces_disabled: next.length > 0 ? next : null };
      if (!current.includes(carapaceId)) {
        const extra = settings?.carapaces_extra ?? [];
        if (extra.includes(carapaceId)) {
          const nextExtra = extra.filter((c) => c !== carapaceId);
          updates.carapaces_extra = nextExtra.length > 0 ? nextExtra : null;
        }
      }
      save(updates);
    },
    [settings, save],
  );

  // Build skill -> carapace mapping for active carapaces (walks includes)
  const skillFromCarapace = useMemo(() => {
    const map = new Map<string, { carapaceId: string; carapaceName: string; mode: string }>();
    if (!allCarapaces || !effective?.carapaces) return map;

    const carapaceById = new Map(allCarapaces.map((c) => [c.id, c]));
    const activeIds = new Set(effective.carapaces);
    const visited = new Set<string>();

    function walk(id: string, rootId: string, rootName: string) {
      const key = `${rootId}:${id}`;
      if (visited.has(key)) return;
      visited.add(key);
      const c = carapaceById.get(id);
      if (!c) return;
      for (const s of c.skills) {
        if (!map.has(s.id)) {
          map.set(s.id, { carapaceId: rootId, carapaceName: rootName, mode: s.mode || "on_demand" });
        }
      }
      for (const inc of c.includes) {
        walk(inc, rootId, rootName);
      }
    }

    for (const cId of activeIds) {
      const c = carapaceById.get(cId);
      if (c) walk(cId, cId, c.name);
    }
    return map;
  }, [allCarapaces, effective]);

  if (editorLoading) {
    return <ActivityIndicator size="small" color={t.textDim} />;
  }

  if (!editorData || !settings) {
    return <EmptyState message="Loading..." />;
  }

  const hasOverrides =
    settings.local_tools_disabled != null ||
    settings.mcp_servers_disabled != null ||
    settings.client_tools_disabled != null ||
    settings.skills_disabled != null ||
    settings.skills_extra != null ||
    settings.carapaces_extra != null ||
    settings.carapaces_disabled != null;

  const extras = new Set(settings.carapaces_extra ?? []);
  const disabled = new Set(settings.carapaces_disabled ?? []);
  // Unfiltered list for the main (non-advanced) view
  const allCapabilities = allCarapaces ?? [];
  // Filtered list only for the advanced section
  const filteredCarapaces = allCapabilities.filter(
    (c) => !filter || c.id.includes(filter.toLowerCase()) || c.name.toLowerCase().includes(filter.toLowerCase()),
  );

  // Gather all disabled items for the "Disabled" section
  const disabledCapabilities = (settings.carapaces_disabled ?? []).map((id) => {
    const c = allCarapaces?.find((cap) => cap.id === id);
    return { id, name: c?.name || id, type: "capability" as const };
  });
  const disabledSkills = (settings.skills_disabled ?? []).map((id) => ({
    id, name: id, type: "skill" as const,
  }));
  const disabledTools = [
    ...(settings.local_tools_disabled ?? []).map((id) => ({ id, name: id, type: "tool" as const })),
    ...(settings.mcp_servers_disabled ?? []).map((id) => ({ id, name: id, type: "mcp" as const })),
    ...(settings.client_tools_disabled ?? []).map((id) => ({ id, name: id, type: "client_tool" as const })),
  ];
  const allDisabled = [...disabledCapabilities, ...disabledSkills, ...disabledTools];

  return (
    <>
      {/* Controls bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        {saved && (
          <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.success, whiteSpace: "nowrap" }}>
            <Check size={12} /> Saved
          </span>
        )}
        <div style={{ flex: 1 }} />
        {hasOverrides && (
          <button
            onClick={handleResetAll}
            style={{
              display: "flex", alignItems: "center", gap: 4, padding: "5px 10px",
              borderRadius: 4, border: `1px solid ${t.surfaceBorder}`,
              background: "transparent", color: t.textDim, cursor: "pointer",
              fontSize: 11, whiteSpace: "nowrap",
            }}
          >
            <RotateCcw size={10} /> Reset All
          </button>
        )}
      </div>

      {/* Active Capabilities — read-only with disable buttons */}
      {allCapabilities.length > 0 && (
        <>
          <SectionDivider label="Active Capabilities" count={effective?.carapaces.length ?? 0} />
          <div style={{ fontSize: 11, color: t.textDim, marginBottom: 8 }}>
            Capabilities active for this channel. Disable any you don't need.
          </div>
          {allCapabilities
            .filter((c) => {
              // Show capabilities that are active (from bot, activation, or extras) and not disabled
              const source = effective?.carapace_sources?.[c.id];
              const isExtra = extras.has(c.id);
              return (source || isExtra) && !disabled.has(c.id);
            })
            .map((c) => {
              const source = effective?.carapace_sources?.[c.id];
              const isActivation = source?.startsWith("activation:");
              const activationLabel = isActivation
                ? `via ${source!.replace("activation:", "")} activation`
                : null;
              const isExtra = extras.has(c.id);

              return (
                <div
                  key={c.id}
                  style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "6px 4px",
                    borderBottom: `1px solid ${t.surfaceBorder}`,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12, fontWeight: 500, color: t.text }}>{c.name}</span>
                      <span style={{ fontSize: 10, fontFamily: "monospace", color: t.textDim }}>{c.id}</span>
                      {isActivation && <StatusBadge label={activationLabel!} variant="purple" />}
                      {source === "bot" && <StatusBadge label="bot default" variant="neutral" />}
                      {isExtra && <StatusBadge label="added" variant="success" />}
                    </div>
                  </div>
                  <button
                    onClick={() => toggleCarapaceDisabled(c.id)}
                    style={{
                      padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 500, cursor: "pointer",
                      border: `1px solid ${t.surfaceBorder}`,
                      background: "transparent",
                      color: t.textDim,
                    }}
                  >
                    Disable
                  </button>
                </div>
              );
            })}
        </>
      )}

      {/* Disabled Items — consolidated view */}
      {allDisabled.length > 0 && (
        <>
          <SectionDivider label="Disabled Items" count={allDisabled.length} />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {allDisabled.map((item) => (
              <div key={`${item.type}-${item.id}`} style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "3px 8px", borderRadius: 4, fontSize: 11,
                background: `${t.danger}10`, border: `1px solid ${t.danger}30`,
              }}>
                <ShieldOff size={9} color={t.danger} />
                <span style={{ color: t.danger }}>{item.name}</span>
                <span style={{ fontSize: 9, color: t.textDim }}>({item.type})</span>
                <button
                  onClick={() => {
                    if (item.type === "capability") toggleCarapaceDisabled(item.id);
                    else if (item.type === "skill") {
                      const next = (settings.skills_disabled ?? []).filter((s) => s !== item.id);
                      save({ skills_disabled: next.length ? next : null } as any);
                    } else if (item.type === "tool") {
                      const next = (settings.local_tools_disabled ?? []).filter((s) => s !== item.id);
                      save({ local_tools_disabled: next.length ? next : null } as any);
                    } else if (item.type === "mcp") {
                      const next = (settings.mcp_servers_disabled ?? []).filter((s) => s !== item.id);
                      save({ mcp_servers_disabled: next.length ? next : null } as any);
                    } else if (item.type === "client_tool") {
                      const next = (settings.client_tools_disabled ?? []).filter((s) => s !== item.id);
                      save({ client_tools_disabled: next.length ? next : null } as any);
                    }
                  }}
                  style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex" }}
                  title="Re-enable"
                >
                  <X size={10} color={t.textDim} />
                </button>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Summary */}
      {effective && (
        <>
          <SectionDivider label="Summary" />
          <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {effective.local_tools.length} local, {effective.mcp_servers.length} MCP, {effective.client_tools.length} client, {effective.pinned_tools.length} pinned, {effective.skills.length} skills, {effective.carapaces.length} capabilities
          </span>
        </>
      )}

      {/* Advanced: full override controls */}
      <AdvancedSection title="Advanced Overrides">
        <div style={{ paddingTop: 8 }}>
          {/* Search filter */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 6, flex: 1,
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6, padding: "6px 10px",
            }}>
              <Search size={13} color={t.textDim} />
              <input
                type="text"
                value={filter}
                onChange={(e: any) => setFilter(e.target.value)}
                placeholder="Filter tools, skills & capabilities..."
                style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
              />
              {filter && (
                <button onClick={() => setFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex" }}>
                  <X size={10} color={t.textDim} />
                </button>
              )}
            </div>
          </div>

          {/* All Capabilities (add/disable) */}
          {filteredCarapaces.length > 0 && (
            <>
              <SectionDivider label="All Capabilities" count={filteredCarapaces.length} />
              {filteredCarapaces.map((c) => {
                const isExtra = extras.has(c.id);
                const isDisabled = disabled.has(c.id);
                const source = effective?.carapace_sources?.[c.id];
                const isActivation = source?.startsWith("activation:");
                const activationLabel = isActivation
                  ? `via ${source!.replace("activation:", "")} activation`
                  : null;

                if (!isWide) {
                  return (
                    <div
                      key={c.id}
                      style={{
                        display: "flex", flexDirection: "column", gap: 4,
                        padding: "10px 12px", background: t.inputBg, borderRadius: 8,
                        border: `1px solid ${t.surfaceBorder}`, marginBottom: 6,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
                          {c.name}
                        </span>
                        {isActivation && <StatusBadge label={activationLabel!} variant="purple" />}
                        {source === "bot" && <StatusBadge label="bot default" variant="neutral" />}
                      </div>
                      <span style={{ fontSize: 10, fontFamily: "monospace", color: t.textMuted }}>
                        {c.id}
                      </span>
                      <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
                        {!isActivation && (
                          <button
                            onClick={() => toggleCarapaceExtra(c.id)}
                            style={{
                              padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 500, cursor: "pointer",
                              border: `1px solid ${isExtra ? t.success : t.surfaceBorder}`,
                              background: isExtra ? `${t.success}18` : "transparent",
                              color: isExtra ? t.success : t.textDim,
                            }}
                          >
                            {isExtra ? "Added" : "Add"}
                          </button>
                        )}
                        <button
                          onClick={() => toggleCarapaceDisabled(c.id)}
                          style={{
                            padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 500, cursor: "pointer",
                            border: `1px solid ${isDisabled ? t.danger : t.surfaceBorder}`,
                            background: isDisabled ? `${t.danger}18` : "transparent",
                            color: isDisabled ? t.danger : t.textDim,
                          }}
                        >
                          {isDisabled ? "Disabled" : "Disable"}
                        </button>
                      </div>
                    </div>
                  );
                }

                return (
                  <div
                    key={c.id}
                    style={{
                      display: "grid", gridTemplateColumns: "160px 1fr auto auto auto",
                      alignItems: "center", gap: 12,
                      padding: "6px 4px", background: "transparent",
                      borderBottom: `1px solid ${t.surfaceBorder}`,
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = t.inputBg; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                  >
                    <span style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {c.id}
                    </span>
                    <div style={{ overflow: "hidden" }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{c.name}</span>
                      {c.description && (
                        <div style={{ fontSize: 11, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>
                          {c.description}
                        </div>
                      )}
                    </div>
                    <div style={{ display: "flex", gap: 4 }}>
                      {isActivation && <StatusBadge label={activationLabel!} variant="purple" />}
                      {source === "bot" && <StatusBadge label="bot default" variant="neutral" />}
                    </div>
                    {!isActivation ? (
                      <button
                        onClick={() => toggleCarapaceExtra(c.id)}
                        style={{
                          padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 500, cursor: "pointer",
                          border: `1px solid ${isExtra ? t.success : t.surfaceBorder}`,
                          background: isExtra ? `${t.success}18` : "transparent",
                          color: isExtra ? t.success : t.textDim,
                        }}
                      >
                        {isExtra ? "Added" : "Add"}
                      </button>
                    ) : <span />}
                    <button
                      onClick={() => toggleCarapaceDisabled(c.id)}
                      style={{
                        padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 500, cursor: "pointer",
                        border: `1px solid ${isDisabled ? t.danger : t.surfaceBorder}`,
                        background: isDisabled ? `${t.danger}18` : "transparent",
                        color: isDisabled ? t.danger : t.textDim,
                      }}
                    >
                      {isDisabled ? "Disabled" : "Disable"}
                    </button>
                  </div>
                );
              })}
            </>
          )}

          {/* Skills */}
          <SectionDivider label="Skills" />
          <EffectiveSkillsList
            editorData={editorData}
            settings={settings}
            filter={filter}
            onSave={save}
            isWide={isWide}
            skillFromCarapace={skillFromCarapace}
          />

          {/* Tool Overrides */}
          <SectionDivider label="Tool Overrides" />
          <EffectiveToolsList
            editorData={editorData}
            settings={settings}
            filter={filter}
            onSave={save}
          />
        </div>
      </AdvancedSection>
    </>
  );
}
