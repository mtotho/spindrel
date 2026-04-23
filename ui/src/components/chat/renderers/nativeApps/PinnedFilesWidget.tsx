import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, ExternalLink, PinOff } from "lucide-react";
import { useMatch, useNavigate, useSearchParams } from "react-router-dom";
import { apiFetch } from "@/src/api/client";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import {
  buildChannelFileHref,
  directoryForWorkspaceFile,
} from "@/src/lib/channelFileNavigation";
import type { ToolResultEnvelope } from "@/src/types/api";
import { PreviewCard, parsePayload, useNativeEnvelopeState, type NativeAppRendererProps } from "./shared";

type PinnedFileEntry = {
  path: string;
  pinned_at: string;
  pinned_by: string;
};

function fileName(path: string): string {
  return path.split("/").pop() || path;
}

function mimetypeForPath(path: string): string | null {
  const ext = path.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "md":
    case "mdx":
      return "text/markdown";
    case "txt":
    case "log":
    case "py":
    case "js":
    case "ts":
    case "tsx":
    case "json":
    case "yaml":
    case "yml":
    case "html":
    case "htm":
      return ext === "json"
        ? "application/json"
        : ext === "html" || ext === "htm"
          ? "text/html"
          : "text/plain";
    default:
      return null;
  }
}

export function PinnedFilesWidget({
  envelope,
  sessionId,
  dashboardPinId,
  channelId,
  t,
}: NativeAppRendererProps) {
  const payload = parsePayload(envelope);
  const { currentPayload, dispatchNativeAction } = useNativeEnvelopeState(
    envelope,
    "core/pinned_files_native",
    channelId,
    dashboardPinId,
  );
  const navigate = useNavigate();
  const sessionMatch = useMatch("/channels/:channelId/session/:sessionId");
  const dashboardMatch = useMatch("/widgets/channel/:channelId");
  const [searchParams] = useSearchParams();
  const pinnedFiles = useMemo<PinnedFileEntry[]>(
    () => ((currentPayload.state?.pinned_files as PinnedFileEntry[] | undefined) ?? []).filter((item) => !!item?.path),
    [currentPayload.state],
  );
  const activePath = typeof currentPayload.state?.active_path === "string"
    ? currentPayload.state.active_path
    : pinnedFiles[0]?.path ?? null;
  const previewContentType = activePath ? mimetypeForPath(activePath) : null;
  const routeSessionId =
    sessionMatch?.params.channelId === channelId
      ? sessionMatch?.params.sessionId ?? sessionId ?? null
      : sessionId ?? null;
  const scratch =
    searchParams.get("scratch") === "true"
    || (
      dashboardMatch?.params.channelId === channelId
      && !!searchParams.get("scratch_session_id")
      && routeSessionId === searchParams.get("scratch_session_id")
    );
  const previewQuery = useQuery({
    queryKey: ["pinned-files-preview", channelId, activePath],
    queryFn: () =>
      apiFetch<{ path: string; content: string }>(
        `/api/v1/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(activePath!)}`,
      ),
    enabled: !!channelId && !!activePath && !!previewContentType,
  });
  const handleOpenFile = useCallback((path: string) => {
    if (!channelId) return;
    navigate(
      buildChannelFileHref({
        channelId,
        sessionId: routeSessionId,
        scratch,
        directoryPath: directoryForWorkspaceFile(path),
        openFile: path,
      }),
    );
  }, [channelId, navigate, routeSessionId, scratch]);
  const previewEnvelope = useMemo<ToolResultEnvelope | null>(() => {
    if (!activePath || !previewContentType || !previewQuery.data?.content) return null;
    return {
      content_type: previewContentType,
      body: previewQuery.data.content,
      plain_body: previewQuery.data.content,
      display: "inline",
      truncated: false,
      record_id: null,
      byte_size: previewQuery.data.content.length,
      display_label: fileName(activePath),
    };
  }, [activePath, previewContentType, previewQuery.data]);

  if (!payload.widget_instance_id) {
    return (
      <PreviewCard
        title="Pinned files"
        description="Channel-scoped pinned file previews for reports, notes, and scratch artifacts."
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, minHeight: "100%" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {pinnedFiles.length === 0 ? (
          <div
            style={{
              border: `1px solid ${t.surfaceBorder}`,
              background: t.surface,
              borderRadius: 12,
              padding: 14,
              color: t.textMuted,
              fontSize: 12,
              lineHeight: 1.6,
            }}
          >
            No files pinned yet. Use the Files tab to pin a channel file into this widget.
          </div>
        ) : (
          pinnedFiles.map((item) => {
            const isActive = item.path === activePath;
            return (
              <div
                key={item.path}
                style={{
                  border: `1px solid ${isActive ? t.accent : t.surfaceBorder}`,
                  background: isActive ? t.surfaceRaised : t.surface,
                  borderRadius: 12,
                  padding: 10,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <button
                  type="button"
                  onClick={() => void dispatchNativeAction("set_active_path", { path: item.path })}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    border: "none",
                    background: "transparent",
                    padding: 0,
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  <FileText size={14} color={isActive ? t.accent : t.textDim} />
                  <span style={{ color: t.text, fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {fileName(item.path)}
                  </span>
                </button>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <div
                    style={{
                      color: t.textDim,
                      fontSize: 11,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={item.path}
                  >
                    {item.path}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      onClick={() => handleOpenFile(item.path)}
                      title="Open file"
                      aria-label={`Open ${fileName(item.path)}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        border: `1px solid ${t.surfaceBorder}`,
                        background: t.surfaceRaised,
                        color: t.text,
                        width: 30,
                        height: 30,
                        borderRadius: 8,
                        cursor: "pointer",
                      }}
                    >
                      <ExternalLink size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void dispatchNativeAction("unpin_path", { path: item.path })}
                      title="Unpin file"
                      aria-label={`Unpin ${fileName(item.path)}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        border: `1px solid ${t.surfaceBorder}`,
                        background: t.surfaceRaised,
                        color: t.textDim,
                        width: 30,
                        height: 30,
                        borderRadius: 8,
                        cursor: "pointer",
                      }}
                    >
                      <PinOff size={14} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {activePath ? (
        <div
          style={{
            flex: 1,
            minHeight: 180,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surface,
            borderRadius: 12,
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
            <div style={{ color: t.text, fontSize: 13, fontWeight: 600 }}>{fileName(activePath)}</div>
            <div style={{ color: t.textDim, fontSize: 11 }} title={activePath}>{activePath}</div>
          </div>
          {previewContentType == null ? (
            <div style={{ color: t.textMuted, fontSize: 12, lineHeight: 1.6 }}>
              Preview isn’t available for this file type here. Use Open file for the full viewer.
            </div>
          ) : previewQuery.isLoading && !previewEnvelope ? (
            <div style={{ color: t.textMuted, fontSize: 12 }}>Loading preview…</div>
          ) : previewQuery.isError ? (
            <div style={{ color: t.danger, fontSize: 12 }}>Failed to load preview.</div>
          ) : previewEnvelope ? (
            <div style={{ minHeight: 0, flex: 1, overflow: "auto" }}>
              <RichToolResult envelope={previewEnvelope} t={t} />
            </div>
          ) : (
            <div style={{ color: t.textMuted, fontSize: 12 }}>Empty file.</div>
          )}
        </div>
      ) : null}
    </div>
  );
}
