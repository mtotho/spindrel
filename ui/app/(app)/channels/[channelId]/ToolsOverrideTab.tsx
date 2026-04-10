import { useState, useCallback, useMemo } from "react";
import {
  Check, Search, X, Shield, Puzzle, Wrench, Server,
  ChevronDown, ChevronRight, Plus,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannelEffectiveTools,
} from "@/src/api/hooks/useChannels";
import { useBotEditorData } from "@/src/api/hooks/useBots";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import { EmptyState } from "@/src/components/shared/FormControls";
import {
  HoverPopover,
  CapabilityPreview,
  SkillPreview,
  ToolPreview,
} from "@/src/components/shared/ItemPreviewPopover";
import type { ChannelSettings, Carapace } from "@/src/types/api";
import { ActivationsSection } from "./integrations/ActivationsSection";
import { buildSkillCarapaceMap, buildToolCarapaceMap } from "@/src/utils/carapaceMapping";

// ---------------------------------------------------------------------------
// Provenance badge — color-coded by source
// ---------------------------------------------------------------------------

type ProvenanceSource = "bot" | "channel" | "activation" | "auto";

function ProvenanceBadge({ source, detail }: { source: ProvenanceSource; detail?: string }) {
  const t = useThemeTokens();
  const cfg: Record<ProvenanceSource, { bg: string; fg: string; label: string }> = {
    bot: { bg: t.surfaceOverlay, fg: t.textMuted, label: "bot" },
    channel: { bg: `${t.accent}15`, fg: t.accent, label: "channel" },
    activation: { bg: t.purpleSubtle, fg: t.purple, label: detail ? `via ${detail}` : "integration" },
    auto: { bg: t.warningSubtle, fg: t.warningMuted, label: "auto-enrolled" },
  };
  const c = cfg[source];
  return (
    <span style={{
      display: "inline-block", fontSize: 9, fontWeight: 600,
      padding: "1px 6px", borderRadius: 4,
      background: c.bg, color: c.fg, whiteSpace: "nowrap",
    }}>
      {c.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Section header
// ---------------------------------------------------------------------------

function SectionLabel({ icon, label, count }: { icon: React.ReactNode; label: string; count?: number }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "14px 0 6px" }}>
      {icon}
      <span style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.8 }}>
        {label}
      </span>
      {count != null && (
        <span style={{
          fontSize: 10, fontWeight: 600, color: t.textDim,
          background: t.surfaceOverlay, borderRadius: 4, padding: "0 6px",
        }}>
          {count}
        </span>
      )}
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Resolved item row — capability, skill, or tool group
// ---------------------------------------------------------------------------

function ResolvedCapabilityRow({
  name, source, sourceDetail, onRemove, carapaceData,
}: {
  id: string; name: string;
  source: ProvenanceSource; sourceDetail?: string;
  onRemove?: () => void;
  carapaceData?: Carapace;
}) {
  const t = useThemeTokens();
  const nameEl = (
    <span style={{
      fontSize: 12, fontWeight: 500, color: t.text,
      cursor: carapaceData ? "help" : undefined,
      borderBottom: carapaceData ? `1px dashed ${t.textDim}` : undefined,
    }}>
      {name}
    </span>
  );
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "6px 8px", borderRadius: 4,
      background: t.purpleSubtle,
      border: `1px solid ${t.purpleBorder}`,
    }}>
      <Shield size={11} color={t.purple} />
      <div style={{ flex: 1 }}>
        {carapaceData ? (
          <HoverPopover content={<CapabilityPreview data={carapaceData} />}>
            {nameEl}
          </HoverPopover>
        ) : nameEl}
      </div>
      <ProvenanceBadge source={source} detail={sourceDetail} />
      {onRemove && (
        <button
          onClick={onRemove}
          title="Remove this capability from the channel"
          style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            width: 20, height: 20, borderRadius: 4,
            cursor: "pointer", border: "none",
            background: "transparent", color: t.textDim,
            transition: "background 0.15s, color 0.15s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = `${t.danger}15`;
            e.currentTarget.style.color = t.danger;
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.color = t.textDim;
          }}
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}

function ResolvedSkillRow({
  id, name, source, sourceDetail, mode,
  skillPreview,
}: {
  id: string; name: string; mode?: string;
  source: ProvenanceSource; sourceDetail?: string;
  skillPreview?: { id: string; name: string; description?: string | null; source_type?: string; chunk_count?: number };
}) {
  const t = useThemeTokens();
  const nameEl = (
    <span style={{
      fontSize: 11, color: t.accent, fontWeight: 500,
      cursor: skillPreview ? "help" : undefined,
      borderBottom: skillPreview ? `1px dashed ${t.accent}40` : undefined,
    }}>
      {name || id}
    </span>
  );
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      padding: "4px 8px", borderRadius: 4,
      background: t.accentSubtle,
    }}>
      <div style={{ flex: 1 }}>
        {skillPreview ? (
          <HoverPopover content={<SkillPreview data={skillPreview} />}>
            {nameEl}
          </HoverPopover>
        ) : nameEl}
      </div>
      {mode && (
        <span style={{ fontSize: 9, color: t.textDim, fontFamily: "monospace" }}>{mode}</span>
      )}
      <ProvenanceBadge source={source} detail={sourceDetail} />
    </div>
  );
}

function ToolGroupRow({
  label, tools, accent, toolCapName,
}: {
  label: string; tools: string[]; accent?: string; toolCapName?: string;
}) {
  const t = useThemeTokens();
  if (tools.length === 0) return null;
  return (
    <div style={{ padding: "4px 0" }}>
      <div style={{
        fontSize: 9, fontWeight: 700, color: accent || t.textDim,
        textTransform: "uppercase", letterSpacing: 0.8, marginBottom: 3,
      }}>
        {label} ({tools.length})
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
        {tools.map((name) => (
          <ToolChipWithPreview key={name} name={name} fromCapability={toolCapName} />
        ))}
      </div>
    </div>
  );
}

function ToolChipWithPreview({ name, fromCapability }: { name: string; fromCapability?: string }) {
  const t = useThemeTokens();
  return (
    <HoverPopover content={<ToolPreview data={{ name, fromCapability }} />}>
      <span style={{
        fontSize: 10, fontFamily: "monospace",
        padding: "1px 6px", borderRadius: 4,
        background: t.surfaceOverlay, color: t.textMuted,
        cursor: "help",
        borderBottom: `1px dashed ${t.textDim}40`,
        transition: "background 0.15s",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = t.surfaceBorder; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = t.surfaceOverlay; }}
      >
        {name}
      </span>
    </HoverPopover>
  );
}

// ---------------------------------------------------------------------------
// "Add more" pool row
// ---------------------------------------------------------------------------

function AddCapabilityRow({
  id, name, description, onAdd,
}: {
  id: string; name: string; description?: string; onAdd: () => void;
}) {
  const t = useThemeTokens();
  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 8px", borderRadius: 4,
        border: `1px dashed ${t.surfaceBorder}`,
        transition: "background 0.15s, border-color 0.15s",
        cursor: "pointer",
      }}
      onClick={onAdd}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = t.surfaceOverlay;
        e.currentTarget.style.borderColor = t.accentBorder;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
        e.currentTarget.style.borderColor = t.surfaceBorder;
      }}
    >
      <Plus size={12} color={t.accent} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: t.text }}>{name}</span>
        {description && (
          <div style={{ fontSize: 10, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>
            {description}
          </div>
        )}
      </div>
      <span style={{ fontSize: 10, fontFamily: "monospace", color: t.textDim }}>{id}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible section
// ---------------------------------------------------------------------------

function CollapsibleSection({
  title, defaultOpen = false, count, children,
}: {
  title: string; defaultOpen?: boolean; count?: number; children: React.ReactNode;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "none", border: "none", cursor: "pointer",
          padding: "6px 0", width: "100%",
        }}
      >
        {open ? <ChevronDown size={12} color={t.textMuted} /> : <ChevronRight size={12} color={t.textMuted} />}
        <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted }}>{title}</span>
        {count != null && (
          <span style={{ fontSize: 10, color: t.textDim }}>{count}</span>
        )}
      </button>
      {open && children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ToolsOverrideTab({ channelId, botId, workspaceEnabled }: { channelId: string; botId?: string; workspaceEnabled?: boolean }) {
  const t = useThemeTokens();
  const { data: editorData, isLoading: editorLoading } = useBotEditorData(botId);
  const { data: settings } = useChannelSettings(channelId);
  const { data: effective } = useChannelEffectiveTools(channelId);
  const { data: allCarapaces } = useCarapaces();
  const updateMutation = useUpdateChannelSettings(channelId);
  const [filter, setFilter] = useState("");
  const [saved, setSaved] = useState(false);

  const save = useCallback(
    async (patch: Partial<ChannelSettings>) => {
      setSaved(false);
      await updateMutation.mutateAsync(patch);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    },
    [updateMutation],
  );

  // --- Capability mutations (only carapaces_extra remains; channel-level
  // add/remove is the only override that survives the simplification). ---
  const toggleCarapaceExtra = useCallback(
    (carapaceId: string) => {
      const current = settings?.carapaces_extra ?? [];
      const next = current.includes(carapaceId)
        ? current.filter((c) => c !== carapaceId)
        : [...current, carapaceId];
      save({ carapaces_extra: next.length > 0 ? next : null } as any);
    },
    [settings, save],
  );

  // --- Provenance maps ---
  const skillCapMap = useMemo(() => {
    if (!allCarapaces || !effective?.carapaces) return new Map();
    return buildSkillCarapaceMap(allCarapaces, effective.carapaces);
  }, [allCarapaces, effective]);

  const toolCapMap = useMemo(() => {
    if (!allCarapaces || !effective?.carapaces) return new Map();
    return buildToolCarapaceMap(allCarapaces, effective.carapaces);
  }, [allCarapaces, effective]);

  // --- Tool grouping ---
  const toolGroups = useMemo(() => {
    if (!effective) return [];
    const groups = new Map<string, { name: string; tools: string[] }>();
    const ungrouped: string[] = [];
    for (const tool of effective.local_tools) {
      const cap = toolCapMap.get(tool);
      if (cap) {
        const g = groups.get(cap.carapaceId);
        if (g) g.tools.push(tool);
        else groups.set(cap.carapaceId, { name: cap.carapaceName, tools: [tool] });
      } else {
        ungrouped.push(tool);
      }
    }
    const result: { label: string; tools: string[] }[] = [];
    for (const [, g] of groups) result.push({ label: g.name, tools: g.tools });
    if (ungrouped.length > 0) result.push({ label: "Other tools", tools: ungrouped });
    return result;
  }, [effective, toolCapMap]);

  // --- Lookup maps ---
  const carapaceById = useMemo(() => {
    if (!allCarapaces) return new Map<string, Carapace>();
    return new Map(allCarapaces.map((c) => [c.id, c]));
  }, [allCarapaces]);

  const allSkillsMap = useMemo(() => {
    const m = new Map<string, { id: string; name: string; description?: string | null; source_type?: string }>();
    for (const s of editorData?.all_skills ?? []) {
      m.set(s.id, { id: s.id, name: s.name, description: s.description, source_type: s.source_type });
    }
    return m;
  }, [editorData]);

  // --- Resolved capabilities with provenance ---
  const resolvedCapabilities = useMemo(() => {
    if (!effective || !allCarapaces) return [];
    const extras = new Set(settings?.carapaces_extra ?? []);
    return effective.carapaces.map((id) => {
      const cap = allCarapaces.find((c) => c.id === id);
      const rawSource = effective.carapace_sources?.[id];
      let source: ProvenanceSource = "channel";
      let sourceDetail: string | undefined;
      if (rawSource === "bot") source = "bot";
      else if (rawSource?.startsWith("activation:")) {
        source = "activation";
        sourceDetail = rawSource.replace("activation:", "");
      } else if (extras.has(id)) source = "channel";
      return { id, name: cap?.name || id, source, sourceDetail };
    });
  }, [effective, allCarapaces, settings]);

  // --- Resolved skills with provenance ---
  const resolvedSkills = useMemo(() => {
    if (!effective) return [];
    return effective.skills.map((s) => {
      const capInfo = skillCapMap.get(s.id);
      let source: ProvenanceSource = "auto";
      let sourceDetail: string | undefined;
      if (capInfo) {
        source = "activation";
        sourceDetail = capInfo.carapaceName;
      }
      return {
        id: s.id,
        name: s.name || s.id,
        mode: s.mode,
        source,
        sourceDetail,
      };
    });
  }, [effective, skillCapMap]);

  // --- Available capabilities (not currently active) ---
  const availableCapabilities = useMemo(() => {
    if (!allCarapaces || !effective) return [];
    const activeSet = new Set(effective.carapaces);
    const q = filter.toLowerCase();
    return allCarapaces.filter((c) => {
      if (activeSet.has(c.id)) return false;
      if (q && !c.id.includes(q) && !c.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [allCarapaces, effective, filter]);

  // --- Loading states ---
  if (editorLoading) {
    return <EmptyState message="Loading..." />;
  }
  if (!editorData || !settings) {
    return <EmptyState message="Loading..." />;
  }

  return (
    <>
      {/* Top bar — resolved counts + save indicator */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        {effective && (
          <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {effective.local_tools.length} tools &middot; {effective.carapaces.length} capabilities &middot; {effective.skills.length} skills
          </span>
        )}
        <div style={{ flex: 1 }} />
        {saved && (
          <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.success, whiteSpace: "nowrap" }}>
            <Check size={12} /> Saved
          </span>
        )}
      </div>

      {/* Integration activations */}
      <ActivationsSection channelId={channelId} workspaceEnabled={!!workspaceEnabled} />

      {/* ================================================================= */}
      {/* RESOLVED VIEW — what the bot actually gets                        */}
      {/* ================================================================= */}

      {/* Capabilities */}
      {resolvedCapabilities.length > 0 && (
        <>
          <SectionLabel
            icon={<Shield size={12} color={t.purple} />}
            label="Capabilities"
            count={resolvedCapabilities.length}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {resolvedCapabilities.map((cap) => (
              <ResolvedCapabilityRow
                key={cap.id}
                id={cap.id}
                name={cap.name}
                source={cap.source}
                sourceDetail={cap.sourceDetail}
                onRemove={cap.source === "channel" ? () => toggleCarapaceExtra(cap.id) : undefined}
                carapaceData={carapaceById.get(cap.id)}
              />
            ))}
          </div>
        </>
      )}

      {/* Tools (grouped by capability, read-only) */}
      {toolGroups.length > 0 && (
        <>
          <SectionLabel
            icon={<Wrench size={12} color={t.textDim} />}
            label="Tools"
            count={effective?.local_tools.length}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {toolGroups.map((g) => (
              <ToolGroupRow key={g.label} label={g.label} tools={g.tools} toolCapName={g.label !== "Other tools" ? g.label : undefined} />
            ))}
          </div>
        </>
      )}

      {/* Skills */}
      {resolvedSkills.length > 0 && (
        <>
          <SectionLabel
            icon={<Puzzle size={12} color={t.accent} />}
            label="Skills"
            count={resolvedSkills.length}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {resolvedSkills.map((skill) => (
              <ResolvedSkillRow
                key={skill.id}
                id={skill.id}
                name={skill.name}
                mode={skill.mode}
                source={skill.source}
                sourceDetail={skill.sourceDetail}
                skillPreview={allSkillsMap.get(skill.id)}
              />
            ))}
          </div>
        </>
      )}

      {/* MCP servers */}
      {effective && effective.mcp_servers.length > 0 && (
        <>
          <SectionLabel
            icon={<Server size={12} color={t.textDim} />}
            label="MCP Servers"
            count={effective.mcp_servers.length}
          />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
            {effective.mcp_servers.map((name) => (
              <span key={name} style={{
                fontSize: 10, fontFamily: "monospace",
                padding: "1px 6px", borderRadius: 4,
                background: t.surfaceOverlay, color: t.textMuted,
              }}>
                {name}
              </span>
            ))}
          </div>
        </>
      )}

      {/* ================================================================= */}
      {/* ADD MORE — capabilities not currently active                      */}
      {/* ================================================================= */}

      <CollapsibleSection title="Add Capability" count={availableCapabilities.length}>
        <div style={{ paddingTop: 4 }}>
          {/* Filter */}
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6, padding: "6px 10px", marginBottom: 8,
          }}>
            <Search size={13} color={t.textDim} />
            <input
              type="text"
              value={filter}
              onChange={(e: any) => setFilter(e.target.value)}
              placeholder="Filter capabilities..."
              style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
            />
            {filter && (
              <button onClick={() => setFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex" }}>
                <X size={10} color={t.textDim} />
              </button>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {availableCapabilities.map((c) => (
              <AddCapabilityRow
                key={c.id}
                id={c.id}
                name={c.name}
                description={c.description ?? undefined}
                onAdd={() => toggleCarapaceExtra(c.id)}
              />
            ))}
            {availableCapabilities.length === 0 && (
              <span style={{ fontSize: 11, color: t.textDim, fontStyle: "italic", padding: "8px 0" }}>
                {filter ? "No matching capabilities." : "All capabilities are active."}
              </span>
            )}
          </div>
        </div>
      </CollapsibleSection>

    </>
  );
}
