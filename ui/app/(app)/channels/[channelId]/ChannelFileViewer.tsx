import { Spinner } from "@/src/components/shared/Spinner";
import { useState, useEffect, useCallback, useRef } from "react";
import { ArrowLeft, X, Save, RotateCw, Columns2, ChevronRight, History as HistoryIcon } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkspaceFileContent,
  useWriteChannelWorkspaceFile,
  useChannelWorkspaceFileVersions,
  useRestoreChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import {
  useWorkspaceFileContent,
  useWriteWorkspaceFile,
} from "@/src/api/hooks/useWorkspaces";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { CodeEditor } from "./CodeEditor";
import { createPortal } from "react-dom";

const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp"]);

function isImageFile(path: string): boolean {
  const ext = path.includes(".") ? path.substring(path.lastIndexOf(".")).toLowerCase() : "";
  return IMAGE_EXTENSIONS.has(ext);
}

interface ChannelFileViewerProps {
  channelId: string;
  /** Workspace id is required when filePath references files outside the channel scope. */
  workspaceId?: string;
  /**
   * Workspace-relative file path, e.g. "channels/{channelId}/README.md" or
   * "bots/{botId}/memory/notes.md". When the path lives inside the channel
   * scope, channel endpoints are used so the channel's RAG re-index hooks
   * fire on save. Otherwise the workspace endpoints are used.
   */
  filePath: string;
  onBack: () => void;
  splitMode?: boolean;
  onToggleSplit?: () => void;
  /** Called whenever dirty state changes so parent can gate navigation */
  onDirtyChange?: (dirty: boolean) => void;
}

export function ChannelFileViewer({ channelId, workspaceId, filePath, onBack, splitMode, onToggleSplit, onDirtyChange }: ChannelFileViewerProps) {
  const t = useThemeTokens();
  const isImage = isImageFile(filePath);

  // Decide which API to use based on path scope.
  // Workspace-relative path inside the channel → use channel endpoints (preserves re-indexing).
  // Anything else → use workspace endpoints.
  const channelPrefix = `channels/${channelId}/`;
  const useChannelEndpoint = filePath.startsWith(channelPrefix);
  const channelRelPath = useChannelEndpoint ? filePath.slice(channelPrefix.length) : null;

  // Channel hooks (only enabled when scope matches)
  const channelContent = useChannelWorkspaceFileContent(
    useChannelEndpoint ? channelId : undefined,
    useChannelEndpoint && !isImage ? channelRelPath : null,
  );
  const channelWrite = useWriteChannelWorkspaceFile(channelId);

  // Workspace hooks (only enabled when scope is outside the channel)
  const workspaceContent = useWorkspaceFileContent(
    !useChannelEndpoint ? workspaceId : undefined,
    !useChannelEndpoint && !isImage ? filePath : null,
  );
  const workspaceWrite = useWriteWorkspaceFile(workspaceId ?? "");

  const data = useChannelEndpoint ? channelContent.data : workspaceContent.data;
  const isLoading = useChannelEndpoint ? channelContent.isLoading : workspaceContent.isLoading;
  const refetch = useChannelEndpoint ? channelContent.refetch : workspaceContent.refetch;
  const writeMutation = useChannelEndpoint ? channelWrite : workspaceWrite;

  const { serverUrl } = useAuthStore();

  // For image files, fetch raw bytes and create a blob URL.
  // Route to channel or workspace raw endpoint based on scope, mirroring the
  // text-content path detection above so re-indexing hooks stay consistent.
  const [imageBlobUrl, setImageBlobUrl] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(false);
  useEffect(() => {
    if (!isImage) { setImageBlobUrl(null); return; }
    let revoke: string | null = null;
    setImageLoading(true);
    const token = getAuthToken();
    const url = useChannelEndpoint
      ? `${serverUrl}/api/v1/channels/${channelId}/workspace/files/raw?path=${encodeURIComponent(channelRelPath!)}`
      : workspaceId
        ? `${serverUrl}/api/v1/workspaces/${workspaceId}/files/raw?path=${encodeURIComponent(filePath)}`
        : null;
    if (!url) { setImageLoading(false); return; }
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((res) => { if (!res.ok) throw new Error("fetch failed"); return res.blob(); })
      .then((blob) => {
        revoke = URL.createObjectURL(blob);
        setImageBlobUrl(revoke);
      })
      .catch(() => setImageBlobUrl(null))
      .finally(() => setImageLoading(false));
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [isImage, serverUrl, channelId, workspaceId, useChannelEndpoint, channelRelPath, filePath]);

  const [editContent, setEditContent] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  // Reset edit state when file changes or data loads
  useEffect(() => {
    setEditContent(null);
    setSavedAt(null);
    setHistoryOpen(false);
  }, [filePath]);

  // Versions + restore — only wired up for channel-scoped files for now.
  const versionsPath = useChannelEndpoint ? channelRelPath : null;
  const versionsQuery = useChannelWorkspaceFileVersions(
    useChannelEndpoint ? channelId : undefined,
    versionsPath,
    historyOpen,
  );
  const restoreMutation = useRestoreChannelWorkspaceFile(channelId);

  const originalContent = data?.content ?? "";
  const displayContent = editContent ?? originalContent;
  const isDirty = editContent !== null && editContent !== originalContent;

  // Notify parent of dirty state changes
  const prevDirtyRef = useRef(false);
  useEffect(() => {
    if (isDirty !== prevDirtyRef.current) {
      prevDirtyRef.current = isDirty;
      onDirtyChange?.(isDirty);
    }
  }, [isDirty, onDirtyChange]);

  const handleSave = useCallback(() => {
    if (!isDirty || editContent == null) return;
    const writePath = useChannelEndpoint ? channelRelPath! : filePath;
    writeMutation.mutate(
      { path: writePath, content: editContent },
      {
        onSuccess: () => {
          setSavedAt(new Date().toLocaleTimeString());
          // Refetch to sync originalContent, then clear edit state
          refetch().then(() => setEditContent(null));
        },
      },
    );
  }, [filePath, useChannelEndpoint, channelRelPath, editContent, isDirty, writeMutation, refetch]);

  // Keyboard shortcut: Ctrl/Cmd+S to save
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleSave]);

  const handleBack = useCallback(() => {
    if (isDirty && !confirm("You have unsaved changes. Discard them?")) return;
    onBack();
  }, [isDirty, onBack]);

  const fileName = filePath.split("/").pop() ?? filePath;
  const pathSegments = filePath.split("/");

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", backgroundColor: t.surface, minHeight: 0 }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingLeft: 12, paddingRight: 12,
          paddingTop: 8, paddingBottom: 8,
          borderBottom: `1px solid ${t.surfaceBorder}`,
          minHeight: 42,
        }}
      >
        <button type="button"
          onClick={handleBack}
          style={{ padding: 6, borderRadius: 4 }}
          className="hover:bg-surface-overlay active:bg-surface-overlay"
          {...{ title: splitMode ? "Close file" : "Back (Esc)" }}
        >
          {splitMode ? <X size={16} color={t.textMuted} /> : <ArrowLeft size={16} color={t.textMuted} />}
        </button>

        {/* Breadcrumb path */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {true ? (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 2, minWidth: 0, overflow: "hidden" }}>
              {pathSegments.map((seg, i) => {
                const isLast = i === pathSegments.length - 1;
                return (
                  <div key={i} style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 2, flexShrink: isLast ? 1 : 0, minWidth: 0 }}>
                    {i > 0 && <ChevronRight size={10} color={t.textDim} style={{ flexShrink: 0 }} />}
                    <span
                      style={{
                        fontSize: 13,
                        fontWeight: isLast ? 600 : 400,
                        color: isLast ? t.text : t.textDim,
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {seg}
                    </span>
                  </div>
                );
              })}
              {isDirty && <span style={{ color: t.accent, fontWeight: 600, marginLeft: 2 }}>*</span>}
            </div>
          ) : (
            <>
              <span
                style={{ color: t.text, fontSize: 13, fontWeight: "600", fontFamily: "monospace" }}
              >
                {fileName}
                {isDirty && <span style={{ color: t.accent }}> *</span>}
              </span>
              <span style={{ color: t.textDim, fontSize: 10 }}>
                {filePath}
              </span>
            </>
          )}
        </div>

        {savedAt && !isDirty && (
          <span style={{ color: t.success, fontSize: 10 }}>Saved {savedAt}</span>
        )}

        <button type="button"
          onClick={() => refetch()}
          style={{ padding: 6, borderRadius: 4 }}
          className="hover:bg-surface-overlay active:bg-surface-overlay"
          {...{ title: "Refresh file" }}
        >
          <RotateCw size={13} color={t.textDim} />
        </button>

        {useChannelEndpoint && !isImage && (
          <button type="button"
            onClick={() => setHistoryOpen(true)}
            style={{ padding: 6, borderRadius: 4 }}
            className="hover:bg-surface-overlay active:bg-surface-overlay"
            {...{ title: "File history — view and restore earlier versions" }}
          >
            <HistoryIcon size={13} color={t.textDim} />
          </button>
        )}

        {onToggleSplit && (
          <button type="button"
            onClick={onToggleSplit}
            style={{
              padding: 6,
              borderRadius: 4,
              backgroundColor: splitMode ? t.surfaceOverlay : "transparent",
            }}
            className="hover:bg-surface-overlay active:bg-surface-overlay"
            {...{ title: splitMode ? "Exit split view" : "Split view" }}
          >
            <Columns2 size={13} color={splitMode ? t.accent : t.textDim} />
          </button>
        )}

        {!isImage && (
          <button type="button"
            onClick={handleSave}
            disabled={!isDirty || writeMutation.isPending}
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 5,
              paddingLeft: 10, paddingRight: 10,
              paddingTop: 5, paddingBottom: 5,
              borderRadius: 5,
              backgroundColor: isDirty ? t.accent : t.surfaceOverlay,
              opacity: isDirty ? 1 : 0.4,
            }}
            {...{ title: "Save (Ctrl+S)" }}
          >
            <Save size={12} color={isDirty ? "#fff" : t.textDim} />
            <span style={{ color: isDirty ? "#fff" : t.textDim, fontSize: 11, fontWeight: "600" }}>
              {writeMutation.isPending ? "Saving..." : "Save"}
            </span>
          </button>
        )}
      </div>

      {/* Editor / Preview area */}
      {isImage ? (
        imageLoading ? (
          <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center" }}>
            <Spinner color={t.accent} />
          </div>
        ) : imageBlobUrl ? (
          <div style={{
            flex: 1,
            display: "flex", flexDirection: "row",
            alignItems: "center",
            justifyContent: "center",
            overflow: "auto",
            padding: 16,
            backgroundColor: t.surfaceRaised,
          }}>
            <img
              src={imageBlobUrl}
              alt={fileName}
              style={{ maxWidth: "100%", maxHeight: "80vh", objectFit: "contain", borderRadius: 4 }}
            />
          </div>
        ) : (
          <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center" }}>
            <span style={{ color: t.textDim, fontSize: 12 }}>Failed to load image</span>
          </div>
        )
      ) : isLoading ? (
        <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center" }}>
          <Spinner color={t.accent} />
        </div>
      ) : true ? (
        <CodeEditor
          content={displayContent}
          onChange={setEditContent}
          filePath={filePath}
          t={t}
        />
      ) : (
        <div style={{ flex: 1, padding: 16 }}>
          <span style={{ color: t.textDim, fontSize: 12 }}>
            Editing not supported on this platform
          </span>
        </div>
      )}

      {/* Status bar */}
      {writeMutation.isError && (
        <div style={{ paddingLeft: 12, paddingRight: 12, paddingTop: 6, paddingBottom: 6, backgroundColor: "rgba(239,68,68,0.1)" }}>
          <span style={{ color: t.danger, fontSize: 11 }}>
            Save failed: {(writeMutation.error as Error)?.message || "Unknown error"}
          </span>
        </div>
      )}

      {historyOpen && versionsPath && typeof document !== "undefined" && createPortal(
        <FileHistoryModal
          fileName={fileName}
          versions={versionsQuery.data?.versions ?? []}
          loading={versionsQuery.isLoading}
          restoring={restoreMutation.isPending}
          onClose={() => setHistoryOpen(false)}
          onRestore={(version) => {
            if (!confirm(`Restore "${fileName}" to version ${version}? Your current file will be backed up first.`)) return;
            restoreMutation.mutate(
              { path: versionsPath, version },
              {
                onSuccess: () => {
                  setEditContent(null);
                  refetch();
                  setHistoryOpen(false);
                },
              },
            );
          }}
        />,
        document.body,
      )}
    </div>
  );
}


function FileHistoryModal({
  fileName,
  versions,
  loading,
  restoring,
  onClose,
  onRestore,
}: {
  fileName: string;
  versions: Array<{ version: string; bytes: number; modified_at: string }>;
  loading: boolean;
  restoring: boolean;
  onClose: () => void;
  onRestore: (version: string) => void;
}) {
  const t = useThemeTokens();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 60000,
        }}
      />
      <div
        style={{
          position: "fixed",
          top: "10vh",
          left: "50%",
          transform: "translateX(-50%)",
          width: "min(640px, 90vw)",
          maxHeight: "80vh",
          background: t.surface,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 8,
          zIndex: 60001,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "12px 16px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <div style={{ color: t.text, fontSize: 14, fontWeight: 600 }}>File history</div>
            <div style={{ color: t.textDim, fontSize: 11, fontFamily: "monospace", marginTop: 2 }}>
              {fileName}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{ padding: 6, borderRadius: 4 }}
            className="hover:bg-surface-overlay active:bg-surface-overlay"
          >
            <X size={16} color={t.textMuted} />
          </button>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: 8 }}>
          {loading ? (
            <div style={{ padding: 24, display: "flex", justifyContent: "center" }}>
              <Spinner color={t.accent} />
            </div>
          ) : versions.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: t.textDim, fontSize: 12 }}>
              No prior versions of this file. Backups are created automatically on overwrite.
            </div>
          ) : (
            versions.map((v) => (
              <div
                key={v.version}
                style={{
                  display: "flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 12,
                  padding: "8px 12px",
                  borderBottom: `1px solid ${t.surfaceBorder}`,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: t.text, fontSize: 12, fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {v.version}
                  </div>
                  <div style={{ color: t.textDim, fontSize: 11, marginTop: 2 }}>
                    {v.modified_at} · {v.bytes} bytes
                  </div>
                </div>
                <button
                  type="button"
                  disabled={restoring}
                  onClick={() => onRestore(v.version)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 4,
                    fontSize: 12,
                    fontWeight: 600,
                    background: t.surfaceOverlay,
                    color: t.text,
                    opacity: restoring ? 0.5 : 1,
                  }}
                  className="hover:bg-accent-dim"
                >
                  Restore
                </button>
              </div>
            ))
          )}
        </div>
        <div
          style={{
            padding: "8px 16px",
            borderTop: `1px solid ${t.surfaceBorder}`,
            color: t.textDim,
            fontSize: 11,
          }}
        >
          Restoring creates a new backup of the current file first, so restore is itself undoable.
        </div>
      </div>
    </>
  );
}
