import { useState, useCallback } from "react";
import { RefreshCw, X, FileText, Folder, ChevronRight, Edit3, Save, Trash2, FolderPlus, FilePlus } from "lucide-react";
import {
  useWorkspaceFiles, useReindexWorkspace,
  useWorkspaceFileContent, useWriteWorkspaceFile, useMkdirWorkspace, useDeleteWorkspaceFile,
} from "@/src/api/hooks/useWorkspaces";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section } from "@/src/components/shared/FormControls";
import { CronJobs } from "./CronJobs";

// ---------------------------------------------------------------------------
// URL-persisted file browser params
// ---------------------------------------------------------------------------
function useFileBrowserParams() {
  const readParams = () => {
    if (typeof window === "undefined") return { path: "/", file: null as string | null };
    const sp = new URLSearchParams(window.location.search);
    return { path: sp.get("fp") || "/", file: sp.get("ff") || null };
  };
  const [state, setState] = useState(readParams);

  const update = useCallback((path: string, file: string | null) => {
    setState({ path, file });
    if (typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    if (path && path !== "/") sp.set("fp", path); else sp.delete("fp");
    if (file) sp.set("ff", file); else sp.delete("ff");
    const qs = sp.toString();
    const url = window.location.pathname + (qs ? `?${qs}` : "");
    window.history.replaceState(null, "", url);
  }, []);

  return { browserPath: state.path, browserFile: state.file, updateBrowserParams: update };
}

// ---------------------------------------------------------------------------
// Inline file browser
// ---------------------------------------------------------------------------
function FileBrowser({ workspaceId }: { workspaceId: string }) {
  const t = useThemeTokens();
  const { browserPath, browserFile, updateBrowserParams } = useFileBrowserParams();
  const [path, setPathRaw] = useState(browserPath);
  const [viewingFile, setViewingFileRaw] = useState<string | null>(browserFile);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [creating, setCreating] = useState<"file" | "folder" | null>(null);
  const [newName, setNewName] = useState("");

  const setPath = useCallback((p: string) => {
    setPathRaw(p);
    updateBrowserParams(p, null);
  }, [updateBrowserParams]);
  const setViewingFile = useCallback((f: string | null) => {
    setViewingFileRaw(f);
    updateBrowserParams(path, f);
  }, [updateBrowserParams, path]);

  const { data, isLoading, refetch } = useWorkspaceFiles(workspaceId, path);
  const { data: fileData, isLoading: fileLoading, error: fileError } = useWorkspaceFileContent(
    workspaceId, viewingFile
  );
  const writeMut = useWriteWorkspaceFile(workspaceId);
  const mkdirMut = useMkdirWorkspace(workspaceId);
  const deleteMut = useDeleteWorkspaceFile(workspaceId);

  const navigateTo = (entryPath: string) => {
    setViewingFileRaw(null);
    setEditing(false);
    setPathRaw(entryPath);
    updateBrowserParams(entryPath, null);
  };

  const handleSaveFile = () => {
    if (!viewingFile) return;
    writeMut.mutate({ path: viewingFile, content: editContent }, {
      onSuccess: () => { setEditing(false); refetch(); },
    });
  };

  const handleCreate = () => {
    if (!newName.trim()) return;
    const newPath = path === "/" ? newName.trim() : `${path.replace(/^\//, "")}/${newName.trim()}`;
    if (creating === "folder") {
      mkdirMut.mutate(newPath, { onSuccess: () => { setCreating(null); setNewName(""); refetch(); } });
    } else {
      writeMut.mutate({ path: newPath, content: "" }, {
        onSuccess: () => { setCreating(null); setNewName(""); refetch(); },
      });
    }
  };

  const handleDelete = (entryPath: string, entryName: string, isDir: boolean) => {
    if (!confirm(`Delete ${isDir ? "directory" : "file"} "${entryName}"?`)) return;
    deleteMut.mutate(entryPath, {
      onSuccess: () => {
        if (viewingFile === entryPath) { setViewingFile(null); setEditing(false); }
        refetch();
      },
    });
  };

  const formatSize = (size: number | null | undefined) => {
    if (size == null) return "";
    if (size > 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)}M`;
    if (size > 1024) return `${(size / 1024).toFixed(1)}K`;
    return `${size}B`;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Breadcrumb + toolbar */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 0, fontSize: 12, flexWrap: "wrap" }}>
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
              <span key={segPath} style={{ display: "inline-flex", flexDirection: "row", alignItems: "center" }}>
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
        <div style={{ flex: 1 }} />
        <button
          onClick={() => { setCreating("file"); setNewName(""); }}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 3,
            background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            cursor: "pointer", color: t.textMuted, fontSize: 10, padding: "2px 8px",
          }}
        >
          <FilePlus size={11} /> New File
        </button>
        <button
          onClick={() => { setCreating("folder"); setNewName(""); }}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 3,
            background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            cursor: "pointer", color: t.textMuted, fontSize: 10, padding: "2px 8px",
          }}
        >
          <FolderPlus size={11} /> New Folder
        </button>
        <button
          onClick={() => refetch()}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 3,
            background: "none", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
            cursor: "pointer", color: t.textMuted, fontSize: 10, padding: "2px 8px",
          }}
        >
          <RefreshCw size={10} />
        </button>
      </div>

      {/* Create inline form */}
      {creating && (
        <div style={{
          display: "flex", flexDirection: "row", gap: 6, alignItems: "center",
          padding: "6px 10px", background: t.inputBg, borderRadius: 6, border: `1px solid ${t.surfaceBorder}`,
        }}>
          <span style={{ fontSize: 11, color: t.textMuted }}>
            {creating === "folder" ? "Folder:" : "File:"}
          </span>
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); if (e.key === "Escape") setCreating(null); }}
            placeholder={creating === "folder" ? "folder-name" : "filename.txt"}
            style={{
              flex: 1, background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
              padding: "3px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <button
            onClick={handleCreate}
            disabled={!newName.trim() || mkdirMut.isPending || writeMut.isPending}
            style={{
              padding: "3px 10px", fontSize: 11, fontWeight: 600,
              background: newName.trim() ? t.accent : t.surfaceBorder,
              color: newName.trim() ? "#fff" : t.textDim,
              border: "none", borderRadius: 4, cursor: newName.trim() ? "pointer" : "not-allowed",
            }}
          >
            Create
          </button>
          <button
            onClick={() => setCreating(null)}
            style={{ background: "none", border: "none", cursor: "pointer", color: t.textDim, padding: 2 }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Entries */}
      {isLoading ? (
        <div style={{ color: t.textDim, fontSize: 12, padding: 12 }}>Loading...</div>
      ) : (
        <div style={{
          background: t.surface, borderRadius: 8, border: `1px solid ${t.surfaceRaised}`,
          overflow: "hidden",
        }}>
          {(!data?.entries || data.entries.length === 0) && (
            <div style={{ color: t.textDim, fontSize: 12, padding: 12 }}>Empty directory</div>
          )}
          {data?.entries?.map((entry) => (
            <div
              key={entry.path}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
                padding: "6px 12px",
                background: viewingFile === entry.path ? t.accentSubtle : "transparent",
                borderBottom: `1px solid ${t.inputBg}`,
              }}
            >
              <button
                onClick={() => {
                  if (entry.is_dir) {
                    navigateTo(entry.path);
                  } else {
                    setViewingFile(entry.path);
                    setEditing(false);
                  }
                }}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flex: 1,
                  background: "none", border: "none", cursor: "pointer",
                  textAlign: "left", padding: 0,
                }}
              >
                {entry.is_dir ? (
                  <Folder size={13} color={t.accent} />
                ) : (
                  <FileText size={13} color={t.textDim} />
                )}
                <span style={{
                  flex: 1, fontSize: 12, color: entry.is_dir ? t.text : t.textMuted,
                  fontFamily: "monospace",
                }}>
                  {entry.name}
                </span>
                {!entry.is_dir && entry.size != null && (
                  <span style={{ fontSize: 10, color: t.textDim }}>{formatSize(entry.size)}</span>
                )}
                {entry.is_dir && <ChevronRight size={12} color={t.textDim} />}
              </button>
              <button
                onClick={() => handleDelete(entry.path, entry.name, entry.is_dir)}
                disabled={deleteMut.isPending}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: t.textDim, padding: 2, flexShrink: 0,
                }}
                title="Delete"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* File viewer/editor panel */}
      {viewingFile && (
        <div style={{
          background: t.surface, borderRadius: 8, border: `1px solid ${t.surfaceRaised}`,
          overflow: "hidden",
        }}>
          {/* File header */}
          <div style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
            padding: "8px 12px", borderBottom: `1px solid ${t.surfaceRaised}`,
            background: t.inputBg,
          }}>
            <FileText size={13} color={t.accent} />
            <span style={{ flex: 1, fontSize: 12, color: t.text, fontFamily: "monospace" }}>
              {viewingFile}
            </span>
            {fileData && !editing && (
              <button
                onClick={() => { setEditing(true); setEditContent(fileData.content); }}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  padding: "3px 10px", fontSize: 11, fontWeight: 600,
                  background: "transparent", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                  color: t.textMuted, cursor: "pointer",
                }}
              >
                <Edit3 size={11} /> Edit
              </button>
            )}
            {editing && (
              <>
                <button
                  onClick={handleSaveFile}
                  disabled={writeMut.isPending}
                  style={{
                    display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                    padding: "3px 10px", fontSize: 11, fontWeight: 600,
                    background: t.accent, border: "none", borderRadius: 4,
                    color: "#fff", cursor: "pointer",
                  }}
                >
                  <Save size={11} /> {writeMut.isPending ? "Saving..." : "Save"}
                </button>
                <button
                  onClick={() => setEditing(false)}
                  style={{
                    padding: "3px 10px", fontSize: 11,
                    background: "transparent", border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
                    color: t.textMuted, cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </>
            )}
            <button
              onClick={() => { setViewingFile(null); setEditing(false); }}
              style={{ background: "none", border: "none", cursor: "pointer", color: t.textDim, padding: 2 }}
            >
              <X size={14} />
            </button>
          </div>

          {/* File content */}
          <div style={{ padding: 12, maxHeight: 400, overflowY: "auto" }}>
            {fileLoading && (
              <div style={{ color: t.textDim, fontSize: 12 }}>Loading file...</div>
            )}
            {fileError && (
              <div style={{ color: t.danger, fontSize: 12 }}>
                {(fileError as any)?.message || "Failed to load file"}
              </div>
            )}
            {fileData && !editing && (
              <pre style={{
                color: t.text, fontSize: 12, fontFamily: "monospace",
                whiteSpace: "pre-wrap", margin: 0, lineHeight: 1.5,
                wordBreak: "break-all",
              }}>
                {fileData.content || <span style={{ color: t.textDim }}>(empty file)</span>}
              </pre>
            )}
            {editing && (
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                style={{
                  width: "100%", minHeight: 200, background: t.surface,
                  border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                  padding: 10, color: t.text, fontSize: 12, fontFamily: "monospace",
                  lineHeight: 1.5, resize: "vertical", outline: "none",
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
export interface FilesTabProps {
  workspaceId: string;
  currentStatus: string;
}

// ---------------------------------------------------------------------------
// Files tab: file browser + cron jobs
// ---------------------------------------------------------------------------
export function FilesTab({ workspaceId, currentStatus }: FilesTabProps) {
  const t = useThemeTokens();
  const reindexMut = useReindexWorkspace(workspaceId);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {currentStatus === "running" ? (
        <Section
          title="File Browser"
          action={
            <button
              onClick={() => reindexMut.mutate()}
              disabled={reindexMut.isPending}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                padding: "4px 10px", fontSize: 11, fontWeight: 600,
                border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                background: "transparent", color: t.textMuted, cursor: "pointer",
              }}
            >
              <RefreshCw size={11} />
              {reindexMut.isPending ? "Reindexing..." : "Reindex"}
            </button>
          }
        >
          <FileBrowser workspaceId={workspaceId} />
        </Section>
      ) : (
        <Section title="File Browser">
          <div style={{ color: t.textDim, fontSize: 12 }}>
            Start the workspace to browse files.
          </div>
        </Section>
      )}

      <Section title="Cron Jobs" description="Cron jobs scheduled inside this workspace container.">
        <CronJobs workspaceId={workspaceId} status={currentStatus} />
      </Section>
    </div>
  );
}
