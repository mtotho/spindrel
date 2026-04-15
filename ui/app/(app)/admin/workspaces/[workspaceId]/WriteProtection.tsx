import { useState } from "react";
import { Plus, X, Shield } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

interface WriteProtectionProps {
  paths: string[];
  onChange: (paths: string[]) => void;
}

export function WriteProtection({ paths, onChange }: WriteProtectionProps) {
  const t = useThemeTokens();
  const [newPath, setNewPath] = useState("");

  const handleAdd = () => {
    const trimmed = newPath.trim();
    if (!trimmed || paths.includes(trimmed)) return;
    onChange([...paths, trimmed]);
    setNewPath("");
  };

  const handleRemove = (path: string) => {
    onChange(paths.filter((p) => p !== path));
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs leading-relaxed" style={{ color: t.textMuted }}>
        Prevent bots from writing to specific directories. Grant per-bot exemptions in the Bots section.
      </div>

      {/* Current protected paths */}
      {paths.length > 0 && (
        <div className="flex flex-col gap-1">
          {paths.map((p) => (
            <div key={p}
              className="flex flex-row items-center gap-2 px-2 py-1 rounded"
              style={{ background: t.surface, border: `1px solid ${t.surfaceRaised}` }}>
              <Shield size={11} className="flex-shrink-0" style={{ color: t.accent }} />
              <code className="flex-1 text-xs font-mono" style={{ color: t.text }}>{p}</code>
              <button
                onClick={() => handleRemove(p)}
                className="flex-shrink-0 bg-transparent border-none cursor-pointer p-0.5"
                style={{ color: t.textDim }}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {paths.length === 0 && (
        <div className="text-xs italic" style={{ color: t.textDim }}>
          No protected paths configured.
        </div>
      )}

      {/* Add custom path */}
      <div className="flex flex-row gap-2 items-center">
        <input
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="/workspace/path/to/protect"
          className="flex-1 font-mono text-xs outline-none"
          style={{
            background: t.inputBg,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            padding: "5px 8px",
            color: t.text,
          }}
        />
        <button
          onClick={handleAdd}
          disabled={!newPath.trim()}
          className="flex flex-row items-center gap-1 text-xs font-semibold flex-shrink-0"
          style={{
            padding: "5px 10px",
            border: "none",
            borderRadius: 6,
            background: newPath.trim() ? t.accent : t.surfaceBorder,
            color: newPath.trim() ? "#fff" : t.textDim,
            cursor: newPath.trim() ? "pointer" : "not-allowed",
          }}
        >
          <Plus size={12} /> Add
        </button>
      </div>
    </div>
  );
}
