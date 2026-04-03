import React from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { Link } from "expo-router";
import { Settings, Menu, ArrowLeft, Hash, FolderOpen, Code, PanelLeft } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

export interface ChannelHeaderProps {
  channelId: string;
  displayName: string;
  bot: { id?: string; name?: string; model?: string } | undefined;
  channelModelOverride: string | undefined;
  columns: "single" | "double" | "triple";
  showHamburger: boolean;
  goBack: () => void;
  toggleSidebar: () => void;
  /** Workspace feature flags */
  workspaceEnabled: boolean | undefined;
  workspaceId: string | null | undefined;
  explorerOpen: boolean;
  toggleExplorer: () => void;
  onBrowseWorkspace: () => void;
  onOpenEditor: () => void;
  isMobile: boolean;
}

export function ChannelHeader({
  channelId,
  displayName,
  bot,
  channelModelOverride,
  columns,
  showHamburger,
  goBack,
  toggleSidebar,
  workspaceEnabled,
  workspaceId,
  explorerOpen,
  toggleExplorer,
  onBrowseWorkspace,
  onOpenEditor,
  isMobile,
}: ChannelHeaderProps) {
  const t = useThemeTokens();

  return (
    <View
      className={`flex-row items-center ${isMobile ? "gap-2 px-3" : "gap-3 px-4"} border-b border-surface-border bg-surface`}
      style={{
        flexShrink: 0,
        zIndex: 10,
        minHeight: 52,
      }}
    >
      {columns === "single" && (
        <Pressable
          onPress={goBack}
          className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
        >
          <ArrowLeft size={20} color={t.textMuted} />
        </Pressable>
      )}
      {showHamburger && columns !== "single" && (
        <Pressable
          onPress={toggleSidebar}
          className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
        >
          <Menu size={20} color={t.textMuted} />
        </Pressable>
      )}
      <Hash size={18} color={t.textDim} style={{ marginLeft: 2 }} />
      <View className="flex-1 min-w-0 py-2">
        <Text style={{ fontSize: 16, fontWeight: "700", color: t.text }} numberOfLines={1}>
          {displayName}
        </Text>
        {bot && (
          <View className="flex-row items-center gap-1.5 mt-0.5 min-w-0">
            <Link href={`/admin/bots/${bot.id}` as any}>
              <Text style={{ fontSize: 12, color: t.textMuted }} numberOfLines={1}>{bot.name}</Text>
            </Link>
            <Text style={{ fontSize: 11, color: t.textDim, flexShrink: 1 }} numberOfLines={1}>
              {(channelModelOverride || bot?.model || "").split("/").pop()}
            </Text>
          </View>
        )}
      </View>
      {workspaceEnabled && workspaceId && (
        <>
          <Pressable
            onPress={toggleExplorer}
            className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
            style={{
              width: 36,
              height: 36,
              backgroundColor: explorerOpen ? t.surfaceOverlay : "transparent",
              borderRadius: 6,
            }}
            {...(Platform.OS === "web" ? { title: explorerOpen ? "Hide file explorer" : "Show file explorer" } as any : {})}
          >
            <PanelLeft size={16} color={explorerOpen ? t.accent : t.textDim} />
          </Pressable>
          {!isMobile && (
            <Link href={`/admin/workspaces/${workspaceId}/files` as any} asChild>
              <Pressable
                onPress={onBrowseWorkspace}
                className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
                style={{ width: 36, height: 36 }}
                {...(Platform.OS === "web" ? { title: "Browse workspace" } as any : {})}
              >
                <FolderOpen size={16} color={t.textDim} />
              </Pressable>
            </Link>
          )}
          {!isMobile && Platform.OS === "web" && (
            <Pressable
              onPress={onOpenEditor}
              className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
              style={{ width: 36, height: 36 }}
              {...{ title: "Open in VS Code" } as any}
            >
              <Code size={16} color={t.textDim} />
            </Pressable>
          )}
        </>
      )}
      {channelId && (
        <Link href={`/channels/${channelId}/settings` as any} asChild>
          <Pressable
            className="items-center justify-center rounded-md hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 44, height: 44 }}
          >
            <Settings size={18} color={t.textDim} />
          </Pressable>
        </Link>
      )}
    </View>
  );
}
