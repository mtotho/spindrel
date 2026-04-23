import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent } from "react";
import { ChevronRight, FolderUp, RefreshCw, Upload } from "lucide-react";
import { useMatch, useNavigate, useSearchParams } from "react-router-dom";
import { useChannel, useChannelWorkspaceFiles } from "@/src/api/hooks/useChannels";
import { useUploadWorkspaceFile, useWorkspaceFiles } from "@/src/api/hooks/useWorkspaces";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { formatBytes } from "@/src/utils/format";
import {
  buildChannelFileHref,
  defaultChannelBrowsePath,
  directoryForWorkspaceFile,
} from "@/src/lib/channelFileNavigation";
import type { ToolResultEnvelope, WorkspaceFileEntry } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { PreviewCard, parsePayload } from "./shared";

type FilesMode = "recent" | "browse";

function trimSlashes(value: string): string {
  return value.replace(/^\/+/, "").replace(/\/+$/, "");
}

function withLeadingSlash(value: string): string {
  const trimmed = trimSlashes(value);
  return trimmed ? `/${trimmed}` : "/";
}

function dirForApi(path: string): string {
  return path === "/" ? "/" : withLeadingSlash(path);
}

function fmtModifiedAt(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  const iso = new Date(value * 1000).toISOString();
  const diffMs = Date.now() - Date.parse(iso);
  if (diffMs < 60_000) return "now";
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

function sectionLabel(section: "active" | "archive" | "data"): string {
  if (section === "archive") return "archive";
  if (section === "data") return "data";
  return "active";
}

function displayPath(path: string): string {
  const trimmed = trimSlashes(path);
  return trimmed || "/";
}

function browseRows(entries: WorkspaceFileEntry[] | undefined): WorkspaceFileEntry[] {
  return [...(entries ?? [])].sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
}

function recentRows(
  channelId: string,
  files: { path: string; name: string; section: "active" | "archive" | "data"; modified_at: number; size: number; type?: "folder" }[] | undefined,
) {
  return [...(files ?? [])]
    .filter((file) => file.type !== "folder")
    .sort((a, b) => b.modified_at - a.modified_at)
    .slice(0, 10)
    .map((file) => {
      const fullPath = `${defaultChannelBrowsePath(channelId)}/${trimSlashes(file.path)}`;
      return {
        ...file,
        fullPath,
        directoryPath: directoryForWorkspaceFile(fullPath) || defaultChannelBrowsePath(channelId),
      };
    });
}

function crumbPaths(path: string): Array<{ label: string; value: string }> {
  const trimmed = trimSlashes(path);
  if (!trimmed) return [{ label: "/", value: "/" }];
  const parts = trimmed.split("/");
  return parts.map((part, index) => ({
    label: part,
    value: `/${parts.slice(0, index + 1).join("/")}`,
  }));
}

export function ChannelFilesWidget({
  envelope,
  sessionId,
  channelId,
  t,
}: {
  envelope: ToolResultEnvelope;
  sessionId?: string;
  dashboardPinId?: string;
  channelId?: string;
  t: ThemeTokens;
}) {
  const payload = parsePayload(envelope);
  if (!payload.widget_instance_id) {
    return (
      <PreviewCard
        title="Channel Files"
        description="Compact channel browser with recent file activity and drag-drop uploads."
        t={t}
      />
    );
  }
  if (!channelId) {
    return (
      <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.6 }}>
        Pin this widget on a channel surface so it can bind to that channel workspace.
      </div>
    );
  }

  const navigate = useNavigate();
  const sessionMatch = useMatch("/channels/:channelId/session/:sessionId");
  const dashboardMatch = useMatch("/widgets/channel/:channelId");
  const [searchParams] = useSearchParams();
  const { data: channel } = useChannel(channelId);
  const workspaceId = channel?.resolved_workspace_id ?? channel?.workspace_id ?? undefined;
  const rememberedPath = useFileBrowserStore((s) => s.channelExplorerPaths[channelId]);
  const setRememberedPath = useFileBrowserStore((s) => s.setChannelExplorerPath);
  const [mode, setMode] = useState<FilesMode>(() => (rememberedPath ? "browse" : "recent"));
  const [currentPath, setCurrentPathRaw] = useState<string>(() =>
    rememberedPath ?? `/${defaultChannelBrowsePath(channelId)}`,
  );
  const [osDragging, setOsDragging] = useState(false);
  const [uploadingCount, setUploadingCount] = useState<number | null>(null);
  const dragCounter = useRef(0);
  const uploadWorkspace = useUploadWorkspaceFile(workspaceId ?? "");

  useEffect(() => {
    setCurrentPathRaw(rememberedPath ?? `/${defaultChannelBrowsePath(channelId)}`);
    setMode(rememberedPath ? "browse" : "recent");
  }, [channelId, rememberedPath]);

  const setCurrentPath = useCallback((path: string) => {
    const normalized = withLeadingSlash(path || defaultChannelBrowsePath(channelId));
    setCurrentPathRaw(normalized);
    setRememberedPath(channelId, normalized);
  }, [channelId, setRememberedPath]);

  const { data: recentData, isLoading: recentLoading, refetch: refetchRecent } = useChannelWorkspaceFiles(
    channelId,
    { includeArchive: true, includeData: true },
  );
  const { data: treeData, isLoading: treeLoading, refetch: refetchTree } = useWorkspaceFiles(
    workspaceId,
    dirForApi(currentPath),
  );
  const recent = useMemo(
    () => recentRows(channelId, recentData?.files),
    [channelId, recentData?.files],
  );
  const entries = useMemo(() => browseRows(treeData?.entries), [treeData?.entries]);
  const breadcrumbs = useMemo(() => crumbPaths(currentPath), [currentPath]);
  const parentPath = useMemo(() => {
    const trimmed = trimSlashes(currentPath);
    const slash = trimmed.lastIndexOf("/");
    if (slash <= 0) return "/";
    return `/${trimmed.slice(0, slash)}`;
  }, [currentPath]);

  const routeSessionId =
    sessionMatch?.params.channelId === channelId
      ? sessionMatch.params.sessionId ?? sessionId ?? null
      : sessionId ?? null;
  const scratch =
    searchParams.get("scratch") === "true"
    || (
      dashboardMatch?.params.channelId === channelId
      && !!searchParams.get("scratch_session_id")
      && routeSessionId === searchParams.get("scratch_session_id")
    );

  const openTarget = useCallback((directoryPath: string, openFile?: string | null) => {
    navigate(
      buildChannelFileHref({
        channelId,
        sessionId: routeSessionId,
        scratch,
        directoryPath,
        openFile,
      }),
    );
  }, [channelId, navigate, routeSessionId, scratch]);

  const handleDragEnter = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!workspaceId) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer?.types?.includes("Files")) {
      dragCounter.current += 1;
      setOsDragging(true);
    }
  }, [workspaceId]);

  const handleDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!workspaceId) return;
    event.preventDefault();
    event.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setOsDragging(false);
    }
  }, [workspaceId]);

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!workspaceId) return;
    event.preventDefault();
    if (event.dataTransfer?.types?.includes("Files")) {
      event.dataTransfer.dropEffect = "copy";
    }
  }, [workspaceId]);

  const handleDrop = useCallback(async (event: DragEvent<HTMLDivElement>) => {
    if (!workspaceId) return;
    event.preventDefault();
    event.stopPropagation();
    dragCounter.current = 0;
    setOsDragging(false);
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (!files.length) return;
    setUploadingCount(files.length);
    const targetDir = trimSlashes(currentPath);
    for (const file of files) {
      try {
        // eslint-disable-next-line no-await-in-loop
        await uploadWorkspace.mutateAsync({ file, targetDir });
      } catch {
        // Keep the rest of the drop batch going.
      }
    }
    setUploadingCount(null);
    void refetchTree();
    void refetchRecent();
  }, [currentPath, refetchRecent, refetchTree, uploadWorkspace, workspaceId]);

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: "100%",
        position: "relative",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          alignItems: "baseline",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          paddingBottom: 8,
        }}
      >
        <div style={{ display: "flex", gap: 12, alignItems: "baseline" }}>
          {(["recent", "browse"] as const).map((nextMode) => (
            <button
              key={nextMode}
              type="button"
              onClick={() => setMode(nextMode)}
              style={{
                border: "none",
                background: "transparent",
                padding: 0,
                cursor: "pointer",
                color: mode === nextMode ? t.text : t.textDim,
                fontSize: 10,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              {nextMode}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => {
            if (mode === "browse") {
              void refetchTree();
            } else {
              void refetchRecent();
            }
          }}
          style={{
            border: "none",
            background: "transparent",
            color: t.textDim,
            padding: 0,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
          }}
          title="Refresh"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      {mode === "browse" ? (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", minHeight: 20 }}>
            {breadcrumbs.map((crumb, index) => (
              <div key={crumb.value} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                {index > 0 ? <ChevronRight size={11} color={t.textDim} /> : null}
                <button
                  type="button"
                  onClick={() => setCurrentPath(crumb.value)}
                  style={{
                    border: "none",
                    background: "transparent",
                    padding: 0,
                    cursor: "pointer",
                    color: index === breadcrumbs.length - 1 ? t.text : t.textMuted,
                    fontSize: 11,
                  }}
                >
                  {crumb.label}
                </button>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {currentPath !== "/" ? (
              <button
                type="button"
                onClick={() => setCurrentPath(parentPath)}
                style={{
                  border: "none",
                  borderTop: `1px solid ${t.surfaceBorder}`,
                  background: "transparent",
                  padding: "10px 0",
                  display: "grid",
                  gridTemplateColumns: "18px minmax(0, 1fr) auto",
                  gap: 10,
                  alignItems: "center",
                  cursor: "pointer",
                  textAlign: "left",
                  color: t.textMuted,
                }}
              >
                <FolderUp size={13} />
                <span style={{ fontSize: 12 }}>Up one level</span>
                <span style={{ fontSize: 10, color: t.textDim }}>{displayPath(parentPath)}</span>
              </button>
            ) : null}

            {treeLoading ? (
              <div style={{ color: t.textDim, fontSize: 12, padding: "12px 0" }}>Loading files…</div>
            ) : null}

            {!treeLoading && !entries.length ? (
              <div style={{ color: t.textMuted, fontSize: 12, padding: "12px 0" }}>Empty directory.</div>
            ) : null}

            {entries.map((entry) => (
              <button
                key={entry.path}
                type="button"
                onClick={() => (
                  entry.is_dir
                    ? setCurrentPath(entry.path)
                    : openTarget(directoryForWorkspaceFile(entry.path) || trimSlashes(currentPath), entry.path)
                )}
                style={{
                  border: "none",
                  borderTop: `1px solid ${t.surfaceBorder}`,
                  background: "transparent",
                  padding: "10px 0",
                  display: "grid",
                  gridTemplateColumns: "14px minmax(0, 1fr) auto",
                  gap: 10,
                  alignItems: "center",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <span style={{ color: entry.is_dir ? t.accentMuted : t.textDim, fontSize: 11 }}>
                  {entry.is_dir ? "dir" : "file"}
                </span>
                <span style={{ minWidth: 0 }}>
                  <span
                    style={{
                      display: "block",
                      color: t.text,
                      fontSize: 12,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {entry.display_name || entry.name}
                  </span>
                  <span
                    style={{
                      display: "block",
                      color: t.textDim,
                      fontSize: 10,
                      marginTop: 2,
                    }}
                  >
                    {displayPath(entry.path)}
                  </span>
                </span>
                <span style={{ fontSize: 10, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
                  {entry.is_dir ? "open" : formatBytes(entry.size ?? 0)}
                </span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {recentLoading ? (
            <div style={{ color: t.textDim, fontSize: 12 }}>Loading recent files…</div>
          ) : null}
          {!recentLoading && !recent.length ? (
            <div style={{ color: t.textMuted, fontSize: 12 }}>No recent file updates yet.</div>
          ) : null}
          {recent.map((file) => (
            <button
              key={file.fullPath}
              type="button"
              onClick={() => openTarget(file.directoryPath, file.fullPath)}
              style={{
                border: "none",
                borderTop: `1px solid ${t.surfaceBorder}`,
                background: "transparent",
                padding: "10px 0",
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) auto",
                gap: 10,
                alignItems: "center",
                cursor: "pointer",
                textAlign: "left",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "baseline", minWidth: 0 }}>
                  <span
                    style={{
                      fontSize: 10,
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      color: t.textDim,
                      flexShrink: 0,
                    }}
                  >
                    {sectionLabel(file.section)}
                  </span>
                  <span
                    style={{
                      color: t.text,
                      fontSize: 12,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {file.name}
                  </span>
                </div>
                <div style={{ marginTop: 3, color: t.textMuted, fontSize: 10 }}>
                  {displayPath(file.path)}
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
                <span style={{ fontSize: 10, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
                  {fmtModifiedAt(file.modified_at)}
                </span>
                <span style={{ fontSize: 10, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
                  {formatBytes(file.size ?? 0)}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          borderTop: `1px solid ${t.surfaceBorder}`,
          paddingTop: 8,
          fontSize: 11,
          color: t.textDim,
        }}
      >
        <span>{mode === "browse" ? displayPath(currentPath) : `${recent.length} recent files`}</span>
        <span>{workspaceId ? "drop to upload" : "channel workspace unavailable"}</span>
      </div>

      {(osDragging || uploadingCount) ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            border: `1px solid ${t.accent}`,
            background: `${t.accent}12`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            pointerEvents: "none",
            color: t.accent,
            fontSize: 12,
          }}
        >
          <Upload size={14} />
          <span>
            {uploadingCount ? `Uploading ${uploadingCount} file${uploadingCount === 1 ? "" : "s"}` : `Drop to upload to ${displayPath(currentPath)}`}
          </span>
        </div>
      ) : null}
    </div>
  );
}
