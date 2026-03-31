import { useState, useEffect, useCallback, useRef } from "react";
import { View, Text, Pressable, ActivityIndicator, Platform } from "react-native";
import { ArrowLeft, Save, RotateCw, Columns2 } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkspaceFileContent,
  useWriteChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";

interface ChannelFileViewerProps {
  channelId: string;
  filePath: string;
  onBack: () => void;
  splitMode?: boolean;
  onToggleSplit?: () => void;
  /** Called whenever dirty state changes so parent can gate navigation */
  onDirtyChange?: (dirty: boolean) => void;
}

export function ChannelFileViewer({ channelId, filePath, onBack, splitMode, onToggleSplit, onDirtyChange }: ChannelFileViewerProps) {
  const t = useThemeTokens();
  const { data, isLoading, refetch } = useChannelWorkspaceFileContent(channelId, filePath);
  const writeMutation = useWriteChannelWorkspaceFile(channelId);

  const [editContent, setEditContent] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
    writeMutation.mutate(
      { path: filePath, content: editContent },
      {
        onSuccess: () => {
          setSavedAt(new Date().toLocaleTimeString());
          // Refetch to sync originalContent, then clear edit state
          refetch().then(() => setEditContent(null));
        },
      },
    );
  }, [filePath, editContent, isDirty, writeMutation, refetch]);

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
          {...(Platform.OS === "web" ? { title: "Back to chat" } as any : {})}
        >
          <ArrowLeft size={16} color={t.textMuted} />
        </Pressable>

        <View style={{ flex: 1, minWidth: 0 }}>
          <Text
            style={{ color: t.text, fontSize: 13, fontWeight: "600", fontFamily: "monospace" }}
            numberOfLines={1}
          >
            {fileName}
            {isDirty && (
              <Text style={{ color: t.accent }}> *</Text>
            )}
          </Text>
          <Text style={{ color: t.textDim, fontSize: 10 }} numberOfLines={1}>
            {filePath}
          </Text>
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
      </View>

      {/* Editor area */}
      {isLoading ? (
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
          <ActivityIndicator color={t.accent} />
        </View>
      ) : Platform.OS === "web" ? (
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          <textarea
            ref={textareaRef as any}
            value={displayContent}
            onChange={(e) => setEditContent(e.target.value)}
            spellCheck={false}
            style={{
              flex: 1,
              width: "100%",
              padding: 16,
              backgroundColor: t.surfaceRaised,
              color: t.text,
              fontSize: 13,
              lineHeight: "1.6",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              border: "none",
              outline: "none",
              resize: "none",
              tabSize: 2,
            }}
          />
        </div>
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
