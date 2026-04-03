import { useState, useMemo } from "react";
import { Search, Zap } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import type { BotConfig, Carapace } from "@/src/types/api";

function SourceBadge({ type }: { type: string }) {
  const t = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: t.accentSubtle, fg: t.accent, label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    manual: { bg: t.surfaceOverlay, fg: t.textMuted, label: "manual" },
  };
  const c = cfg[type] || cfg.manual;
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {c.label}
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
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 0 4px" }}>
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

const AUTO_INJECTED_CARAPACES: Record<string, string> = {
  "mission-control": "Auto-injected for workspace-enabled channels",
};

export function CarapacesSection({
  draft,
  update,
}: {
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
}) {
  const t = useThemeTokens();
  const { data: allCarapaces } = useCarapaces();
  const selected = draft.carapaces || [];
  const [filter, setFilter] = useState("");

  const toggle = (id: string) => {
    const next = selected.includes(id)
      ? selected.filter((x) => x !== id)
      : [...selected, id];
    update({ carapaces: next });
  };

  const filtered = useMemo(() => {
    if (!allCarapaces) return [];
    const list = filter
      ? allCarapaces.filter((c) =>
          c.id.toLowerCase().includes(filter.toLowerCase()) ||
          c.name.toLowerCase().includes(filter.toLowerCase()) ||
          (c.description || "").toLowerCase().includes(filter.toLowerCase()))
      : allCarapaces;
    return groupCarapaces(list);
  }, [allCarapaces, filter]);

  if (!allCarapaces || allCarapaces.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, color: t.textDim }}>
          Composable skill+tool bundles. Select carapaces to equip this bot with pre-configured expertise.
        </div>
        <div style={{ color: t.textDim, fontSize: 12, padding: 12, textAlign: "center" }}>
          No carapaces available. Create one in the Carapaces admin page.
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Composable skill+tool bundles. Select carapaces to equip this bot with pre-configured expertise.
      </div>
      {allCarapaces.length > 6 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "4px 8px",
        }}>
          <Search size={12} color={t.textDim} />
          <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter carapaces..." style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }} />
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 0 }}>
        {filtered.map((item) => {
          if (item.type === "header") {
            return <SectionHeader key={item.key} label={item.label} count={item.count} />;
          }
          const c = item.carapace;
          const on = selected.includes(c.id);
          const autoNote = AUTO_INJECTED_CARAPACES[c.id];
          const sourceType = c.source_type || "manual";
          return (
            <div key={c.id} style={{
              padding: "8px 4px", borderRadius: 0,
              background: on ? t.accentSubtle : autoNote && !on ? t.surfaceOverlay : "transparent",
              borderBottom: `1px solid ${on ? t.accentBorder : t.surfaceBorder}`,
              opacity: autoNote && !on ? 0.7 : 1,
            }}>
              <label style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                <input type="checkbox" checked={on} onChange={() => toggle(c.id)} style={{ accentColor: t.accent, marginTop: 2 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: on ? t.accent : t.text }}>{c.name}</span>
                    <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>{c.id}</span>
                    {sourceType !== "integration" && <SourceBadge type={sourceType} />}
                    {autoNote && !on && (
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 3,
                        fontSize: 9, fontWeight: 600, color: t.accent,
                        background: `${t.accent}15`, borderRadius: 4, padding: "1px 5px",
                      }}>
                        <Zap size={8} />
                        AUTO
                      </span>
                    )}
                  </div>
                  {autoNote && !on ? (
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                      {autoNote}
                    </div>
                  ) : c.description ? (
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {c.description}
                    </div>
                  ) : null}
                </div>
              </label>
            </div>
          );
        })}
      </div>
    </div>
  );
}
