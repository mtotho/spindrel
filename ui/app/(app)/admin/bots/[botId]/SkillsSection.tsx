import { useState } from "react";
import { Search } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { BotConfig, BotEditorData } from "@/src/types/api";

export function SkillsSection({
  editorData, draft, update,
}: { editorData: BotEditorData; draft: BotConfig; update: (p: Partial<BotConfig>) => void }) {
  const t = useThemeTokens();
  const [filter, setFilter] = useState("");
  const skills = draft.skills || [];
  const isSelected = (id: string) => skills.some((s) => s.id === id);
  const getEntry = (id: string) => skills.find((s) => s.id === id);

  const toggle = (id: string) => {
    update({
      skills: isSelected(id)
        ? skills.filter((s) => s.id !== id)
        : [...skills, { id, mode: "on_demand" }],
    });
  };

  const setMode = (id: string, mode: string) => {
    update({
      skills: skills.map((s) =>
        s.id === id ? { ...s, mode, similarity_threshold: mode === "rag" ? s.similarity_threshold : null } : s
      ),
    });
  };

  const filtered = filter
    ? editorData.all_skills.filter((s) =>
        s.id.toLowerCase().includes(filter.toLowerCase()) ||
        s.name.toLowerCase().includes(filter.toLowerCase()) ||
        (s.description || "").toLowerCase().includes(filter.toLowerCase()))
    : editorData.all_skills;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: t.textDim }}>
        <strong style={{ color: t.textMuted }}>on_demand</strong>: index injected, agent calls get_skill.{" "}
        <strong style={{ color: t.textMuted }}>pinned</strong>: full content every turn.{" "}
        <strong style={{ color: t.textMuted }}>rag</strong>: semantic similarity per turn.
      </div>
      {editorData.all_skills.length > 6 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6, padding: "4px 8px",
        }}>
          <Search size={12} color={t.textDim} />
          <input type="text" value={filter} onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter skills..." style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }} />
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 6 }}>
        {filtered.map((skill) => {
          const sel = isSelected(skill.id);
          const entry = getEntry(skill.id);
          return (
            <div key={skill.id} style={{
              padding: 8, borderRadius: 6,
              background: sel ? t.accentSubtle : t.surface,
              border: `1px solid ${sel ? t.accentBorder : t.surfaceRaised}`,
            }}>
              <label style={{ display: "flex", alignItems: "flex-start", gap: 6, cursor: "pointer" }}>
                <input type="checkbox" checked={sel} onChange={() => toggle(skill.id)} style={{ accentColor: t.accent, marginTop: 2 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 500, color: sel ? t.accent : t.textMuted }}>{skill.name}</span>
                    <span style={{ fontSize: 10, color: t.surfaceBorder, fontFamily: "monospace" }}>{skill.id}</span>
                  </div>
                  {skill.description && (
                    <div style={{ fontSize: 10, color: t.textDim, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {skill.description}
                    </div>
                  )}
                </div>
              </label>
              {sel && entry && (
                <div style={{ marginTop: 6, marginLeft: 22 }}>
                  <select value={entry.mode || "on_demand"} onChange={(e) => setMode(skill.id, e.target.value)}
                    style={{ background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4, padding: "2px 8px", fontSize: 11, color: t.text }}>
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
