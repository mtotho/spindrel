import { useState } from "react";
import { Search } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSkills } from "@/src/api/hooks/useSkills";

type SkillEntry = { id: string; mode?: string; similarity_threshold?: number };

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

  // Filter to non-workspace skills (only global/file-sourced skills)
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

  const filtered = filter
    ? globalSkills.filter(
        (s) =>
          s.id.toLowerCase().includes(filter.toLowerCase()) ||
          s.name.toLowerCase().includes(filter.toLowerCase()),
      )
    : globalSkills;

  if (!globalSkills.length) {
    return (
      <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
        No global skills available. Create skills in the Skills admin page first.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Assign global DB skills to all bots in this workspace.{" "}
        <strong style={{ color: t.textMuted }}>on_demand</strong>: index + get_skill.{" "}
        <strong style={{ color: t.textMuted }}>pinned</strong>: full content every turn.{" "}
        <strong style={{ color: t.textMuted }}>rag</strong>: similarity per turn.
      </div>
      {globalSkills.length > 6 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: t.inputBg,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            padding: "4px 8px",
          }}
        >
          <Search size={12} color={t.textDim} />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter skills..."
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: t.text,
              fontSize: 12,
            }}
          />
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 6 }}>
        {filtered.map((skill) => {
          const sel = isSelected(skill.id);
          const entry = getEntry(skill.id);
          return (
            <div
              key={skill.id}
              style={{
                padding: 8,
                borderRadius: 6,
                background: sel ? t.accentSubtle : t.surface,
                border: `1px solid ${sel ? t.accentBorder : t.surfaceRaised}`,
              }}
            >
              <label style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={sel}
                  onChange={() => toggle(skill.id)}
                  style={{ accentColor: t.accent, marginTop: 2 }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: sel ? t.accent : t.textMuted }}>
                      {skill.name}
                    </span>
                    <span style={{ fontSize: 10, color: t.surfaceBorder, fontFamily: "monospace" }}>{skill.id}</span>
                  </div>
                </div>
              </label>
              {sel && entry && (
                <div style={{ marginTop: 6, marginLeft: 22 }}>
                  <select
                    value={entry.mode || "on_demand"}
                    onChange={(e) => setMode(skill.id, e.target.value)}
                    style={{
                      background: t.inputBg,
                      border: `1px solid ${t.surfaceBorder}`,
                      borderRadius: 4,
                      padding: "2px 8px",
                      fontSize: 11,
                      color: t.text,
                    }}
                  >
                    <option value="on_demand">on_demand</option>
                    <option value="pinned">pinned</option>
                    <option value="rag">rag</option>
                  </select>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
