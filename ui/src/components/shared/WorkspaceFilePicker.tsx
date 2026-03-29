import { useState } from "react";
import { Folder, FileText, ChevronRight } from "lucide-react";
import { useWorkspaceFiles } from "../../api/hooks/useWorkspaces";
import { useThemeTokens } from "../../theme/tokens";
import type { WorkspaceFileEntry } from "../../types/api";

interface WorkspaceFilePickerProps {
  workspaceId: string;
  value: string;
  onChange: (path: string) => void;
  fileFilter?: string; // e.g. ".md"
}

export function WorkspaceFilePicker({ workspaceId, value, onChange, fileFilter }: WorkspaceFilePickerProps) {
  const t = useThemeTokens();
  const [path, setPath] = useState(() => {
    // Start in the directory of the current value if set
    if (value) {
      const dir = value.replace(/\/[^/]+$/, "") || "/";
      return dir.startsWith("/") ? dir : "/" + dir;
    }
    return "/";
  });

  const { data, isLoading } = useWorkspaceFiles(workspaceId, path);

  const navigateTo = (entryPath: string) => setPath(entryPath);
  const navigateUp = () => {
    const parent = path.replace(/\/[^/]+\/?$/, "") || "/";
    navigateTo(parent);
  };

  const matchesFilter = (entry: WorkspaceFileEntry) => {
    if (entry.is_dir || !fileFilter) return true;
    return entry.name.endsWith(fileFilter);
  };

  const normalizedValue = value.startsWith("/") ? value : "/" + value;

  const formatSize = (size: number | null | undefined) => {
    if (size == null) return "";
    if (size > 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)}M`;
    if (size > 1024) return `${(size / 1024).toFixed(1)}K`;
    return `${size}B`;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {/* Breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 0, fontSize: 12, flexWrap: "wrap" }}>
        <button
          onClick={() => navigateTo("/")}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: path === "/" ? t.text : t.accent, fontSize: 12, padding: 0,
            fontFamily: "monospace",
          }}
        >
          /workspace
        </button>
        {path !== "/" && (() => {
          const segments = path.replace(/^\//, "").split("/").filter(Boolean);
          return segments.map((seg, i) => {
            const segPath = "/" + segments.slice(0, i + 1).join("/");
            const isLast = i === segments.length - 1;
            return (
              <span key={segPath} style={{ display: "inline-flex", alignItems: "center" }}>
                <span style={{ color: t.textDim, margin: "0 1px" }}>/</span>
                <button
                  onClick={() => navigateTo(segPath)}
                  style={{
                    background: "none", border: "none", cursor: "pointer",
                    color: isLast ? t.text : t.accent, fontSize: 12, padding: 0,
                    fontFamily: "monospace",
                  }}
                >
                  {seg}
                </button>
              </span>
            );
          });
        })()}
      </div>

      {/* Entries */}
      {isLoading ? (
        <div style={{ color: t.textDim, fontSize: 12, padding: 12 }}>Loading...</div>
      ) : (
        <div style={{
          background: t.inputBg, borderRadius: 8, border: `1px solid ${t.surfaceBorder}`,
          overflow: "hidden", maxHeight: 250, overflowY: "auto",
        }}>
          {(!data?.entries || data.entries.length === 0) && (
            <div style={{ color: t.textDim, fontSize: 12, padding: 12 }}>Empty directory</div>
          )}
          {data?.entries?.map((entry) => {
            const matches = matchesFilter(entry);
            const isSelected = !entry.is_dir && entry.path === normalizedValue;
            return (
              <button
                key={entry.path}
                onClick={() => {
                  if (entry.is_dir) {
                    navigateTo(entry.path);
                  } else if (matches) {
                    // Strip leading slash for the value
                    const cleanPath = entry.path.startsWith("/") ? entry.path.slice(1) : entry.path;
                    onChange(cleanPath);
                  }
                }}
                disabled={!entry.is_dir && !matches}
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%",
                  padding: "6px 12px",
                  background: isSelected ? t.accentSubtle : "transparent",
                  borderBottom: `1px solid ${t.surfaceBorder}`,
                  border: "none", borderBlockEnd: `1px solid ${t.surfaceBorder}`,
                  cursor: (entry.is_dir || matches) ? "pointer" : "default",
                  textAlign: "left",
                  opacity: matches ? 1 : 0.35,
                }}
                onMouseEnter={(e) => {
                  if ((entry.is_dir || matches) && !isSelected) {
                    e.currentTarget.style.background = "rgba(255,255,255,0.03)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) e.currentTarget.style.background = "transparent";
                }}
              >
                {entry.is_dir ? (
                  <Folder size={13} color={t.accent} />
                ) : (
                  <FileText size={13} color={isSelected ? t.accent : t.textDim} />
                )}
                <span style={{
                  flex: 1, fontSize: 12,
                  color: isSelected ? t.accent : entry.is_dir ? t.text : t.textMuted,
                  fontFamily: "monospace",
                  fontWeight: isSelected ? 600 : 400,
                }}>
                  {entry.name}
                </span>
                {!entry.is_dir && entry.size != null && (
                  <span style={{ fontSize: 10, color: t.textDim }}>{formatSize(entry.size)}</span>
                )}
                {entry.is_dir && <ChevronRight size={12} color={t.textDim} />}
              </button>
            );
          })}
        </div>
      )}

      {/* Selected path display */}
      {value && (
        <div style={{
          fontSize: 11, color: t.success, fontFamily: "monospace",
          padding: "4px 8px", background: t.successSubtle,
          borderRadius: 4, border: `1px solid ${t.successBorder}`,
        }}>
          Selected: {value}
        </div>
      )}
    </div>
  );
}
