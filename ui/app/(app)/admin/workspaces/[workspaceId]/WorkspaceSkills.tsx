import { useState, useMemo } from "react";
import { useWindowDimensions } from "react-native";
import { Search, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSkills, type SkillItem } from "@/src/api/hooks/useSkills";

type SkillEntry = { id: string; mode?: string; similarity_threshold?: number };

function SectionDivider({ label, count, level }: { label: string; count?: number; level?: number }) {
  const t = useThemeTokens();
  const isSub = (level ?? 0) > 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: `${isSub ? 8 : 12}px 0 4px ${isSub ? 16 : 0}px` }}>
      <span style={{ fontSize: isSub ? 10 : 11, fontWeight: 600, color: isSub ? t.textDim : t.textMuted, textTransform: "uppercase", letterSpacing: 1 }}>
        {label}
      </span>
      {count != null && <span style={{ fontSize: 10, color: t.textDim }}>{count}</span>}
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

function SourceBadge({ type }: { type: string }) {
  const t = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: t.accentSubtle, fg: t.accent, label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    manual: { bg: t.surfaceOverlay, fg: t.textMuted, label: "manual" },
  };
  const c = cfg[type] || cfg.manual;
  return (
    <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600, background: c.bg, color: c.fg }}>
      {c.label}
    </span>
  );
}

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

type GroupedItem =
  | { type: "header"; key: string; label: string; count: number; level: number }
  | { type: "skill"; key: string; skill: SkillItem };

export function WorkspaceSkills({
  skills,
  onChange,
}: {
  skills: SkillEntry[];
  onChange: (skills: SkillEntry[]) => void;
}) {
  const t = useThemeTokens();
  const { data: allSkills } = useSkills();
  const [filter, setFilter] = useState("");
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const globalSkills = (allSkills || []).filter((s) => s.source_type !== "workspace");
  const isSelected = (id: string) => skills.some((s) => s.id === id);
  const getEntry = (id: string) => skills.find((s) => s.id === id);

  const toggle = (id: string) => {
    onChange(
      isSelected(id)
        ? skills.filter((s) => s.id !== id)
        : [...skills, { id, mode: "on_demand" }],
    );
  };

  const setMode = (id: string, mode: string) => {
    onChange(
      skills.map((s) =>
        s.id === id ? { ...s, mode, similarity_threshold: mode === "rag" ? s.similarity_threshold : undefined } : s,
      ),
    );
  };

  const filtered = useMemo(() => {
    if (!filter.trim()) return globalSkills;
    const q = filter.toLowerCase();
    return globalSkills.filter(
      (s) =>
        s.id.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q),
    );
  }, [globalSkills, filter]);

  const groupedItems = useMemo((): GroupedItem[] => {
    if (!filtered.length) return [];

    const manual: SkillItem[] = [];
    const core: SkillItem[] = [];
    const integrationMap = new Map<string, SkillItem[]>();

    for (const s of filtered) {
      if (s.source_type === "manual") manual.push(s);
      else if (s.source_type === "integration") {
        const name = s.id.match(/^integrations\/([^/]+)\//)?.[1] ?? "other";
        const list = integrationMap.get(name);
        if (list) list.push(s); else integrationMap.set(name, [s]);
      } else core.push(s);
    }

    const items: GroupedItem[] = [];

    const addGroup = (key: string, label: string, list: SkillItem[], level = 0) => {
      if (!list.length) return;
      items.push({ type: "header", key, label, count: list.length, level });
      for (const s of list) items.push({ type: "skill", key: s.id, skill: s });
    };

    addGroup("manual", "User Added", manual);
    addGroup("core", "Core", core);

    const intKeys = [...integrationMap.keys()].sort();
    if (intKeys.length) {
      const totalInt = intKeys.reduce((n, k) => n + integrationMap.get(k)!.length, 0);
      items.push({ type: "header", key: "integrations", label: "Integrations", count: totalInt, level: 0 });
      for (const k of intKeys) {
        const list = integrationMap.get(k)!;
        items.push({ type: "header", key: `int-${k}`, label: fmtIntName(k), count: list.length, level: 1 });
        for (const s of list) items.push({ type: "skill", key: s.id, skill: s });
      }
    }

    return items;
  }, [filtered]);

  if (!globalSkills.length) {
    return (
      <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
        No global skills available. Create skills in the Skills admin page first.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <div style={{ fontSize: 11, color: t.textDim, marginBottom: 8 }}>
        Check to assign skills to all bots in this workspace.{" "}
        <strong style={{ color: t.textMuted }}>on_demand</strong>: index + get_skill.{" "}
        <strong style={{ color: t.textMuted }}>pinned</strong>: full content every turn.{" "}
        <strong style={{ color: t.textMuted }}>rag</strong>: similarity per turn.
      </div>

      {/* Search */}
      {globalSkills.length > 6 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6, flex: 1,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "6px 10px", marginBottom: 4,
        }}>
          <Search size={13} color={t.textDim} />
          <input
            type="text"
            value={filter}
            onChange={(e: any) => setFilter(e.target.value)}
            placeholder="Filter skills..."
            style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
          />
          {filter && (
            <button onClick={() => setFilter("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex" }}>
              <X size={10} color={t.textDim} />
            </button>
          )}
        </div>
      )}

      {/* Grouped skill rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: isWide ? 0 : 6 }}>
        {groupedItems.map((item) => {
          if (item.type === "header") {
            return <SectionDivider key={item.key} label={item.label} count={item.count} level={item.level} />;
          }

          const { skill } = item;
          const sel = isSelected(skill.id);
          const entry = getEntry(skill.id);
          const firstLine = (skill.content || "").split("\n").find((l) => l.trim() && !l.startsWith("#"))?.trim() || "";
          const desc = firstLine && firstLine !== "---" ? firstLine.slice(0, 120) : null;

          if (!isWide) {
            return (
              <div
                key={skill.id}
                style={{
                  display: "flex", flexDirection: "column", gap: 4,
                  padding: "10px 12px", background: t.inputBg, borderRadius: 8,
                  border: `1px solid ${sel ? t.accentBorder : t.surfaceBorder}`,
                }}
              >
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input type="checkbox" checked={sel} onChange={() => toggle(skill.id)} style={{ accentColor: t.accent }} />
                  <span style={{ fontSize: 13, fontWeight: 500, color: sel ? t.accent : t.text, flex: 1 }}>{skill.name}</span>
                  <SourceBadge type={skill.source_type} />
                </label>
                <span style={{ fontSize: 10, fontFamily: "monospace", color: t.textMuted, marginLeft: 28 }}>{skill.id}</span>
                {desc && (
                  <div style={{ fontSize: 11, color: t.textDim, marginLeft: 28, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {desc}
                  </div>
                )}
                {sel && entry && (
                  <div style={{ marginLeft: 28 }}>
                    <select value={entry.mode || "on_demand"} onChange={(e: any) => setMode(skill.id, e.target.value)}
                      style={{ background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4, padding: "2px 8px", fontSize: 11, color: t.text }}>
                      <option value="on_demand">on_demand</option>
                      <option value="pinned">pinned</option>
                      <option value="rag">rag</option>
                    </select>
                  </div>
                )}
              </div>
            );
          }

          // Desktop: grid row
          return (
            <label
              key={skill.id}
              style={{
                display: "grid", gridTemplateColumns: "24px 160px 1fr auto auto",
                alignItems: "center", gap: 12,
                padding: "6px 4px", background: "transparent",
                borderBottom: `1px solid ${sel ? t.accentBorder : t.surfaceBorder}`,
                cursor: "pointer",
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = t.inputBg; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
            >
              <input type="checkbox" checked={sel} onChange={() => toggle(skill.id)} style={{ accentColor: t.accent }} />
              <span style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {skill.id}
              </span>
              <div style={{ overflow: "hidden" }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: sel ? t.accent : t.text }}>{skill.name}</span>
                {desc && (
                  <div style={{ fontSize: 11, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 1 }}>
                    {desc}
                  </div>
                )}
              </div>
              <SourceBadge type={skill.source_type} />
              {sel && entry ? (
                <select
                  value={entry.mode || "on_demand"}
                  onChange={(e: any) => setMode(skill.id, e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  style={{ background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4, padding: "2px 8px", fontSize: 11, color: t.text }}
                >
                  <option value="on_demand">on_demand</option>
                  <option value="pinned">pinned</option>
                  <option value="rag">rag</option>
                </select>
              ) : <span />}
            </label>
          );
        })}
      </div>

      {filter && filtered.length === 0 && (
        <div style={{ padding: 20, textAlign: "center", color: t.textDim, fontSize: 12 }}>
          No skills match "{filter}"
        </div>
      )}
    </div>
  );
}
