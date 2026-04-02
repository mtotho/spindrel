import { useState } from "react";
import { Plus, X, Shield } from "lucide-react";
import { Toggle, FormRow } from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

const SKILLS_PATHS = [
  "/workspace/common/skills",
  "/workspace/bots/*/skills",
];

interface WriteProtectionProps {
  paths: string[];
  onChange: (paths: string[]) => void;
}

export function WriteProtection({ paths, onChange }: WriteProtectionProps) {
  const t = useThemeTokens();
  const [newPath, setNewPath] = useState("");

  // Derived toggle: ON if both skills paths are present
  const skillsProtected = SKILLS_PATHS.every((p) => paths.includes(p));

  const handleToggleSkills = (on: boolean) => {
    if (on) {
      const next = [...paths];
      for (const p of SKILLS_PATHS) {
        if (!next.includes(p)) next.push(p);
      }
      onChange(next);
    } else {
      onChange(paths.filter((p) => !SKILLS_PATHS.includes(p)));
    }
  };

  const handleAdd = () => {
    const trimmed = newPath.trim();
    if (!trimmed || paths.includes(trimmed)) return;
    onChange([...paths, trimmed]);
    setNewPath("");
  };

  const handleRemove = (path: string) => {
    onChange(paths.filter((p) => p !== path));
  };

  // Paths that aren't the auto-managed skills paths
  const customPaths = paths.filter((p) => !SKILLS_PATHS.includes(p));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <FormRow label="Protect skills directories">
        <Toggle value={skillsProtected} onChange={handleToggleSkills} label="" />
      </FormRow>
      <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5, marginTop: -4 }}>
        Prevents bots from writing to <code style={{ color: t.accent }}>/workspace/common/skills</code> and{" "}
        <code style={{ color: t.accent }}>/workspace/bots/*/skills</code>.
        Grant per-bot exemptions in the Connected Bots section below.
      </div>

      {/* Current protected paths */}
      {paths.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 4 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted }}>Protected paths:</div>
          {paths.map((p) => (
            <div key={p} style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "4px 8px", background: t.surface, borderRadius: 6,
              border: `1px solid ${t.surfaceRaised}`, fontSize: 12,
            }}>
              <Shield size={11} style={{ color: t.accent, flexShrink: 0 }} />
              <code style={{ flex: 1, color: t.text, fontSize: 11 }}>{p}</code>
              <button
                onClick={() => handleRemove(p)}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: t.textDim, padding: 2, flexShrink: 0,
                }}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add custom path */}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="/workspace/path/to/protect"
          style={{
            flex: 1, background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
            padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
            outline: "none",
          }}
        />
        <button
          onClick={handleAdd}
          disabled={!newPath.trim()}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "5px 10px", fontSize: 11, fontWeight: 600,
            border: "none", borderRadius: 6,
            background: newPath.trim() ? t.accent : t.surfaceBorder,
            color: newPath.trim() ? "#fff" : t.textDim,
            cursor: newPath.trim() ? "pointer" : "not-allowed",
            flexShrink: 0,
          }}
        >
          <Plus size={12} /> Add
        </button>
      </div>
    </div>
  );
}
