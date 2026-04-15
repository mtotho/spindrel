import { useState, useMemo } from "react";
import { Search, Plus, X, Pin } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import { AdvancedSection } from "@/src/components/shared/SettingsControls";
import type { BotConfig, Carapace } from "@/src/types/api";

function SourceBadge({ type, label: customLabel }: { type: string; label?: string }) {
  const t = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: t.accentSubtle, fg: t.accent, label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    tool: { bg: "rgba(168,85,247,0.15)", fg: "#9333ea", label: "bot-created" },
    manual: { bg: t.surfaceOverlay, fg: t.textMuted, label: "manual" },
  };
  const c = cfg[type] || cfg.manual;
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {customLabel || c.label}
    </span>
  );
}

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, padding: "10px 0 4px" }}>
      <span style={{ fontSize: 10, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 1 }}>
        {label}
      </span>
      <span style={{ fontSize: 10, color: t.textDim }}>{count}</span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

type GroupedItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "carapace"; key: string; carapace: Carapace };

function extractIntegrationName(c: Carapace): string | null {
  if (c.source_type !== "integration") return null;
  const fromPath = c.source_path?.match(/integrations\/([^/]+)\//)?.[1];
  if (fromPath) return fromPath;
  return "other";
}

function groupCarapaces(carapaces: Carapace[]): GroupedItem[] {
  const core: Carapace[] = [];
  const integrationMap = new Map<string, Carapace[]>();

  for (const c of carapaces) {
    const intName = extractIntegrationName(c);
    if (intName) {
      const list = integrationMap.get(intName);
      if (list) list.push(c); else integrationMap.set(intName, [c]);
    } else {
      core.push(c);
    }
  }

  const items: GroupedItem[] = [];

  if (core.length > 0) {
    items.push({ type: "header", key: "core", label: "Core", count: core.length });
    for (const c of core) items.push({ type: "carapace", key: c.id, carapace: c });
  }

  const intKeys = [...integrationMap.keys()].sort();
  for (const k of intKeys) {
    const list = integrationMap.get(k)!;
    items.push({ type: "header", key: `int-${k}`, label: fmtIntName(k), count: list.length });
    for (const c of list) items.push({ type: "carapace", key: c.id, carapace: c });
  }

  return items;
}

export function CarapacesSection({
  draft,
  update,
}: {
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
}) {
  const t = useThemeTokens();
  const { data: allCarapaces, isLoading, isError } = useCarapaces();
  const selected = draft.carapaces || [];
  const [filter, setFilter] = useState("");
  const [adding, setAdding] = useState(false);
  const [addSearch, setAddSearch] = useState("");

  const toggle = (id: string) => {
    const next = selected.includes(id)
      ? selected.filter((x) => x !== id)
      : [...selected, id];
    update({ carapaces: next });
  };

  const pinnedCarapaces = useMemo(() => {
    if (!allCarapaces) return [];
    return allCarapaces.filter((c) => selected.includes(c.id));
  }, [allCarapaces, selected]);

  const unpinned = useMemo(() => {
    if (!allCarapaces) return [];
    return allCarapaces.filter((c) => !selected.includes(c.id));
  }, [allCarapaces, selected]);

  const filteredUnpinned = addSearch
    ? unpinned.filter((c) =>
        c.id.toLowerCase().includes(addSearch.toLowerCase()) ||
        c.name.toLowerCase().includes(addSearch.toLowerCase()) ||
        (c.description || "").toLowerCase().includes(addSearch.toLowerCase()))
    : unpinned;

  const filteredAll = useMemo(() => {
    if (!allCarapaces) return [];
    const list = filter
      ? allCarapaces.filter((c) =>
          c.id.toLowerCase().includes(filter.toLowerCase()) ||
          c.name.toLowerCase().includes(filter.toLowerCase()) ||
          (c.description || "").toLowerCase().includes(filter.toLowerCase()))
      : allCarapaces;
    return groupCarapaces(list);
  }, [allCarapaces, filter]);

  if (isLoading || isError) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, color: t.textDim }}>
          Capabilities are auto-discovered per conversation. Pin specific ones to always include them.
        </div>
        <div style={{ color: isError ? t.danger : t.textDim, fontSize: 12, padding: 12, textAlign: "center" }}>
          {isError ? "Failed to load capabilities." : "Loading capabilities..."}
        </div>
      </div>
    );
  }

  if (!allCarapaces || allCarapaces.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, color: t.textDim }}>
          Capabilities are auto-discovered per conversation. Pin specific ones to always include them.
        </div>
        <div style={{ color: t.textDim, fontSize: 12, padding: 12, textAlign: "center" }}>
          No capabilities available. Create one in the Capabilities admin page.
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Capabilities are auto-discovered per conversation. Pin specific ones to always include them.
      </div>

      {/* Pinned Capabilities */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Pinned Capabilities
        </div>
        {pinnedCarapaces.length === 0 && !adding && (
          <div style={{ fontSize: 11, color: t.textDim, padding: "4px 0 8px" }}>
            No pinned capabilities. The bot will auto-discover what it needs.
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {pinnedCarapaces.map((c) => (
            <div key={c.id} style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "4px 8px", borderRadius: 4, fontSize: 11,
              background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
            }}>
              <Pin size={9} color={t.accent} />
              <span style={{ color: t.accent, fontWeight: 500 }}>{c.name}</span>
              <span style={{ fontSize: 9, color: t.textDim, fontFamily: "monospace" }}>{c.id}</span>
              {c.source_type === "integration" && (
                <SourceBadge type="integration" label={fmtIntName(extractIntegrationName(c) || "integration")} />
              )}
              <button
                onClick={() => toggle(c.id)}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex", flexDirection: "row" }}
                title="Unpin"
              >
                <X size={10} color={t.textDim} />
              </button>
            </div>
          ))}
          {!adding && (
            <button
              onClick={() => setAdding(true)}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                padding: "4px 8px", borderRadius: 4, fontSize: 11,
                background: "transparent", border: `1px dashed ${t.surfaceBorder}`,
                color: t.textDim, cursor: "pointer",
              }}
            >
              <Plus size={10} /> Pin a capability
            </button>
          )}
        </div>
        {adding && (
          <div style={{
            padding: 8, borderRadius: 6,
            border: `1px solid ${t.surfaceBorder}`, background: t.inputBg,
            marginBottom: 8,
          }}>
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
              <Search size={12} color={t.textDim} />
              <input
                type="text" value={addSearch}
                onChange={(e) => setAddSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Escape") { setAdding(false); setAddSearch(""); } }}
                placeholder="Search capabilities..."
                autoFocus
                style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
              />
              <button onClick={() => { setAdding(false); setAddSearch(""); }}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                <X size={12} color={t.textDim} />
              </button>
            </div>
            <div style={{ maxHeight: 200, overflow: "auto" }}>
              {filteredUnpinned.map((c) => (
                <button key={c.id} onClick={() => { toggle(c.id); setAddSearch(""); }}
                  style={{
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                    width: "100%", textAlign: "left",
                    padding: "5px 6px", fontSize: 11,
                    color: t.text, background: "transparent", border: "none",
                    cursor: "pointer", borderRadius: 3,
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = t.surfaceOverlay; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
                >
                  <span style={{ fontWeight: 500 }}>{c.name}</span>
                  <span style={{ fontSize: 9, color: t.textDim, fontFamily: "monospace" }}>{c.id}</span>
                  {c.source_type === "integration" && (
                    <SourceBadge type="integration" label={fmtIntName(extractIntegrationName(c) || "integration")} />
                  )}
                </button>
              ))}
              {filteredUnpinned.length === 0 && (
                <span style={{ fontSize: 11, color: t.textDim, padding: 4 }}>No matching capabilities</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Advanced: full capability list */}
      <AdvancedSection title="All Capabilities">
        <div style={{ paddingTop: 8 }}>
          {allCarapaces.length > 6 && (
            <div style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8,
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "4px 8px",
            }}>
              <Search size={12} color={t.textDim} />
              <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter capabilities..." style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }} />
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 0 }}>
            {filteredAll.map((item) => {
              if (item.type === "header") {
                return <SectionHeader key={item.key} label={item.label} count={item.count} />;
              }
              const c = item.carapace;
              const on = selected.includes(c.id);
              const sourceType = c.source_type || "manual";
              return (
                <div key={c.id} style={{
                  padding: "8px 4px", borderRadius: 0,
                  background: on ? t.accentSubtle : "transparent",
                  borderBottom: `1px solid ${on ? t.accentBorder : t.surfaceBorder}`,
                }}>
                  <label style={{ display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                    <input type="checkbox" checked={on} onChange={() => toggle(c.id)} style={{ accentColor: t.accent, marginTop: 2 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12, fontWeight: 500, color: on ? t.accent : t.text }}>{c.name}</span>
                        <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>{c.id}</span>
                        {sourceType !== "integration" && <SourceBadge type={sourceType} />}
                      </div>
                      {c.description && (
                        <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {c.description}
                        </div>
                      )}
                    </div>
                  </label>
                </div>
              );
            })}
          </div>
        </div>
      </AdvancedSection>
    </div>
  );
}
