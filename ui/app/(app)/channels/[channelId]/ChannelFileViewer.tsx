import { useState, useEffect, useCallback, useRef } from "react";
import { View, Text, Pressable, ActivityIndicator, Platform } from "react-native";
import { ArrowLeft, Save, RotateCw, Columns2, ChevronRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkspaceFileContent,
  useWriteChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import {
  useWorkspaceFileContent,
  useWriteWorkspaceFile,
} from "@/src/api/hooks/useWorkspaces";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { CodeEditor } from "./CodeEditor";

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

  // Reset edit state when file changes or data loads
  useEffect(() => {
    setEditContent(null);
    setSavedAt(null);
  }, [filePath]);

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
    if (!isDirty || !editContent) return;
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
    if (Platform.OS !== "web") return;
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
    <View style={{ flex: 1, backgroundColor: t.surface }}>
      {/* Header */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          paddingHorizontal: 12,
          paddingVertical: 8,
          borderBottomWidth: 1,
          borderBottomColor: t.surfaceBorder,
          minHeight: 42,
        }}
      >
        <Pressable
          onPress={handleBack}
          style={{ padding: 6, borderRadius: 4 }}
          className="hover:bg-surface-overlay active:bg-surface-overlay"
          {...(Platform.OS === "web" ? { title: "Back (Esc)" } as any : {})}
        >
          <ArrowLeft size={16} color={t.textMuted} />
        </Pressable>

        {/* Breadcrumb path */}
        <View style={{ flex: 1, minWidth: 0 }}>
          {Platform.OS === "web" ? (
            <div style={{ display: "flex", alignItems: "center", gap: 2, minWidth: 0, overflow: "hidden" }}>
              {pathSegments.map((seg, i) => {
                const isLast = i === pathSegments.length - 1;
                return (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: isLast ? 1 : 0, minWidth: 0 }}>
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
              <Text
                style={{ color: t.text, fontSize: 13, fontWeight: "600", fontFamily: "monospace" }}
                numberOfLines={1}
              >
                {fileName}
                {isDirty && <Text style={{ color: t.accent }}> *</Text>}
              </Text>
              <Text style={{ color: t.textDim, fontSize: 10 }} numberOfLines={1}>
                {filePath}
              </Text>
            </>
          )}
        </View>

        {savedAt && !isDirty && (
          <Text style={{ color: t.success, fontSize: 10 }}>Saved {savedAt}</Text>
        )}

        <Pressable
          onPress={() => refetch()}
          style={{ padding: 6, borderRadius: 4 }}
          className="hover:bg-surface-overlay active:bg-surface-overlay"
          {...(Platform.OS === "web" ? { title: "Refresh file" } as any : {})}
        >
          <RotateCw size={13} color={t.textDim} />
        </Pressable>

        {onToggleSplit && (
          <Pressable
            onPress={onToggleSplit}
            style={{
              padding: 6,
              borderRadius: 4,
              backgroundColor: splitMode ? t.surfaceOverlay : "transparent",
            }}
            className="hover:bg-surface-overlay active:bg-surface-overlay"
            {...(Platform.OS === "web" ? { title: splitMode ? "Exit split view" : "Split view" } as any : {})}
          >
            <Columns2 size={13} color={splitMode ? t.accent : t.textDim} />
          </Pressable>
        )}

        {!isImage && (
          <Pressable
            onPress={handleSave}
            disabled={!isDirty || writeMutation.isPending}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 5,
              paddingHorizontal: 10,
              paddingVertical: 5,
              borderRadius: 5,
              backgroundColor: isDirty ? t.accent : t.surfaceOverlay,
              opacity: isDirty ? 1 : 0.4,
            }}
            {...(Platform.OS === "web" ? { title: "Save (Ctrl+S)" } as any : {})}
          >
            <Save size={12} color={isDirty ? "#fff" : t.textDim} />
            <Text style={{ color: isDirty ? "#fff" : t.textDim, fontSize: 11, fontWeight: "600" }}>
              {writeMutation.isPending ? "Saving..." : "Save"}
            </Text>
          </Pressable>
        )}
      </View>

      {/* Editor / Preview area */}
      {isImage ? (
        imageLoading ? (
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
            <ActivityIndicator color={t.accent} />
          </View>
        ) : imageBlobUrl ? (
          <div style={{
            flex: 1,
            display: "flex",
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
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
            <Text style={{ color: t.textDim, fontSize: 12 }}>Failed to load image</Text>
          </View>
        )
      ) : isLoading ? (
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator color={t.accent} />
        </View>
      ) : Platform.OS === "web" ? (
        <CodeEditor
          content={displayContent}
          onChange={setEditContent}
          filePath={filePath}
          t={t}
        />
      ) : (
        <View style={{ flex: 1, padding: 16 }}>
          <Text style={{ color: t.textDim, fontSize: 12 }}>
            Editing not supported on this platform
          </Text>
        </View>
      )}

      {/* Status bar */}
      {writeMutation.isError && (
        <View style={{ paddingHorizontal: 12, paddingVertical: 6, backgroundColor: "rgba(239,68,68,0.1)" }}>
          <Text style={{ color: t.danger, fontSize: 11 }}>
            Save failed: {(writeMutation.error as Error)?.message || "Unknown error"}
          </Text>
        </View>
      )}
    </View>
  );
}
