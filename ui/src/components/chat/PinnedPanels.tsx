/**
 * PinnedPanelsRail — renders pinned workspace-file panels in the channel
 * side rail. Each panel fetches file content, renders it via RichToolResult's
 * mimetype dispatcher, and auto-refetches when a `pinned_file_updated` SSE
 * event invalidates the query key.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "../../theme/tokens";
import { useChannel } from "../../api/hooks/useChannels";
import { apiFetch } from "../../api/client";
import { RichToolResult } from "./RichToolResult";
import { ChevronLeft, ChevronRight, Pin, X } from "lucide-react";
import type { PinnedPanel, ToolResultEnvelope } from "../../types/api";

/** Map file extension to content_type for the RichToolResult dispatcher. */
function mimetypeForPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "md":
    case "mdx":
      return "text/markdown";
    case "json":
      return "application/json";
    case "html":
    case "htm":
      return "text/html";
    default:
      return "text/plain";
  }
}

function fileName(path: string): string {
  return path.split("/").pop() || path;
}

interface PinnedPanelViewProps {
  panel: PinnedPanel;
  workspaceId: string;
  channelId: string;
}

function PinnedPanelView({ panel, workspaceId, channelId }: PinnedPanelViewProps) {
  const t = useThemeTokens();
  const [collapsed, setCollapsed] = useState(false);
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["pinned-panel-content", panel.path],
    queryFn: () =>
      apiFetch<{ path: string; content: string; size: number }>(
        `/api/v1/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(panel.path)}`,
      ),
    enabled: !collapsed,
    refetchInterval: 30_000, // fallback polling in case SSE misses
  });

  const handleUnpin = async () => {
    try {
      await apiFetch(
        `/api/v1/channels/${channelId}/pins?path=${encodeURIComponent(panel.path)}`,
        { method: "DELETE" },
      );
      qc.invalidateQueries({ queryKey: ["channels", channelId] });
    } catch {
      // Silently handle — the panel will disappear on next channel refetch
    }
  };

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        aria-label={`Expand ${fileName(panel.path)}`}
        style={{
          width: 32,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: t.surfaceRaised,
          border: "none",
          borderLeft: `1px solid ${t.surfaceBorder}`,
          cursor: "pointer",
          padding: 0,
          flexShrink: 0,
        }}
      >
        <ChevronLeft size={14} color={t.textDim} />
        <span
          style={{
            fontSize: 10,
            color: t.textDim,
            writingMode: "vertical-lr",
            transform: "rotate(180deg)",
            marginTop: 8,
          }}
        >
          {fileName(panel.path)}
        </span>
      </button>
    );
  }

  const contentType = mimetypeForPath(panel.path);
  const envelope: ToolResultEnvelope | null = data?.content != null
    ? {
        content_type: contentType,
        body: data.content,
        plain_body: `Pinned: ${panel.path}`,
        display: "inline" as const,
        truncated: false,
        record_id: null,
        byte_size: data.size ?? 0,
      }
    : null;

  return (
    <div
      style={{
        width: 320,
        borderLeft: `1px solid ${t.surfaceBorder}`,
        backgroundColor: t.surfaceRaised,
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 12px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          gap: 4,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, flex: 1 }}>
          <Pin size={12} color={t.textDim} style={{ flexShrink: 0 }} />
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: t.text,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={panel.path}
          >
            {fileName(panel.path)}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0 }}>
          <button
            onClick={handleUnpin}
            aria-label="Unpin"
            title="Unpin from channel"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 4,
              borderRadius: 4,
              display: "flex",
              alignItems: "center",
            }}
          >
            <X size={13} color={t.textDim} />
          </button>
          <button
            onClick={() => setCollapsed(true)}
            aria-label="Collapse panel"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 4,
              borderRadius: 4,
              display: "flex",
              alignItems: "center",
            }}
          >
            <ChevronRight size={14} color={t.textDim} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: "auto", padding: 12 }}>
        {isLoading && !data ? (
          <div style={{ padding: 16, display: "flex", justifyContent: "center" }}>
            <div className="chat-spinner" />
          </div>
        ) : error ? (
          <div style={{ fontSize: 12, color: t.danger, padding: 8 }}>
            Failed to load file content
          </div>
        ) : envelope ? (
          <RichToolResult envelope={envelope} t={t} />
        ) : (
          <div style={{ fontSize: 12, color: t.textDim, padding: 8 }}>
            Empty file
          </div>
        )}
      </div>
    </div>
  );
}

interface PinnedPanelsRailProps {
  channelId: string;
  workspaceId?: string | null;
}

export function PinnedPanelsRail({ channelId, workspaceId }: PinnedPanelsRailProps) {
  const { data: channel } = useChannel(channelId);
  const panels = channel?.config?.pinned_panels?.filter((p) => p.position === "right") ?? [];

  if (!workspaceId || panels.length === 0) return null;

  return (
    <>
      {panels.map((panel) => (
        <PinnedPanelView
          key={panel.path}
          panel={panel}
          workspaceId={workspaceId}
          channelId={channelId}
        />
      ))}
    </>
  );
}
