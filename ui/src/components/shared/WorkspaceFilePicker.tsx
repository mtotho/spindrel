import { useState } from "react";
import { Folder, FileText, ChevronRight } from "lucide-react";
import { useWorkspaceFiles } from "../../api/hooks/useWorkspaces";
import type { WorkspaceFileEntry } from "../../types/api";

interface WorkspaceFilePickerProps {
  workspaceId: string;
  value: string;
  onChange: (path: string) => void;
  fileFilter?: string; // e.g. ".md"
}

export function WorkspaceFilePicker({ workspaceId, value, onChange, fileFilter }: WorkspaceFilePickerProps) {
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
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, flexWrap: "wrap" }}>
        <button
          onClick={() => navigateTo("/")}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: "#93c5fd", fontSize: 12, padding: 0,
          }}
        >
          /workspace
        </button>
        {path !== "/" && (
          <>
            <span style={{ color: "#555" }}>/</span>
            <span style={{ color: "#999", fontFamily: "monospace" }}>
              {path.replace(/^\//, "")}
            </span>
            <button
              onClick={navigateUp}
              style={{
                background: "none", border: "1px solid #333", borderRadius: 4,
                cursor: "pointer", color: "#999", fontSize: 10, padding: "1px 6px",
                marginLeft: 4,
              }}
            >
              Up
            </button>
          </>
        )}
      </div>

      {/* Entries */}
      {isLoading ? (
        <div style={{ color: "#555", fontSize: 12, padding: 12 }}>Loading...</div>
      ) : (
        <div style={{
          background: "#0a0a0a", borderRadius: 8, border: "1px solid #1a1a1a",
          overflow: "hidden", maxHeight: 250, overflowY: "auto",
        }}>
          {(!data?.entries || data.entries.length === 0) && (
            <div style={{ color: "#555", fontSize: 12, padding: 12 }}>Empty directory</div>
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
                  background: isSelected ? "rgba(59,130,246,0.12)" : "transparent",
                  borderBottom: "1px solid #111",
                  border: "none", borderBlockEnd: "1px solid #111",
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
                  <Folder size={13} color="#93c5fd" />
                ) : (
                  <FileText size={13} color={isSelected ? "#93c5fd" : "#666"} />
                )}
                <span style={{
                  flex: 1, fontSize: 12,
                  color: isSelected ? "#93c5fd" : entry.is_dir ? "#e5e5e5" : "#999",
                  fontFamily: "monospace",
                  fontWeight: isSelected ? 600 : 400,
                }}>
                  {entry.name}
                </span>
                {!entry.is_dir && entry.size != null && (
                  <span style={{ fontSize: 10, color: "#555" }}>{formatSize(entry.size)}</span>
                )}
                {entry.is_dir && <ChevronRight size={12} color="#555" />}
              </button>
            );
          })}
        </div>
      )}

      {/* Selected path display */}
      {value && (
        <div style={{
          fontSize: 11, color: "#86efac", fontFamily: "monospace",
          padding: "4px 8px", background: "rgba(34,197,94,0.08)",
          borderRadius: 4, border: "1px solid rgba(34,197,94,0.15)",
        }}>
          Selected: {value}
        </div>
      )}
    </div>
  );
}
