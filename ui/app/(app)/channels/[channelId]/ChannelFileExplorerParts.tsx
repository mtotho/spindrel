/**
 * Visual subcomponents for ChannelFileExplorer.
 * Extracted to keep the main file under the 1000-line split rule.
 */
import { useState, useEffect, useMemo } from "react";
import { View, Text, Pressable, Platform } from "react-native";
import { Plus, Trash2, Archive, ChevronRight, Folder } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useChannelWorkspaceFiles,
  useWriteChannelWorkspaceFile,
  type ChannelWorkspaceFile,
} from "@/src/api/hooks/useChannels";
import { useChatStore } from "@/src/stores/chat";
import {
  formatRelativeTime,
  formatSize,
  estimateTokens,
  getFileIcon,
  getArchiveIcon,
} from "./ChannelFileExplorerData";

// ---------------------------------------------------------------------------
// Path helper used by multiple components
// ---------------------------------------------------------------------------

export function stripSlashes(p: string): string {
  return p.replace(/^\/+/, "").replace(/\/+$/, "");
}

// ---------------------------------------------------------------------------
// IN CONTEXT card — pinned active section
// ---------------------------------------------------------------------------

const TOKEN_BUDGET = 8000;

export function InContextCard({
  channelId,
  activeFile,
  onSelectFile,
  onArchive,
  onDelete,
}: {
  channelId: string;
  activeFile: string | null;
  onSelectFile: (workspaceRelativePath: string) => void;
  onArchive: (file: ChannelWorkspaceFile) => void;
  onDelete: (file: ChannelWorkspaceFile) => void;
}) {
  const t = useThemeTokens();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const writeMutation = useWriteChannelWorkspaceFile(channelId);

  const { data: filesData, isLoading } = useChannelWorkspaceFiles(channelId, {
    includeArchive: false,
    includeData: false,
  });

  // Auto-refresh while bot is streaming so newly written active files appear.
  const queryClient = useQueryClient();
  const isStreaming = useChatStore((s) => s.getChannel(channelId).isStreaming);
  useEffect(() => {
    if (!isStreaming) return;
    const interval = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
    }, 3000);
    return () => clearInterval(interval);
  }, [isStreaming, channelId, queryClient]);

  const activeFiles = useMemo(
    () => (filesData?.files ?? []).filter((f) => f.section === "active" && f.type !== "folder"),
    [filesData],
  );

  const totalSize = activeFiles.reduce((s, f) => s + (f.size || 0), 0);
  const tokenStr = estimateTokens(totalSize);
  const tokenNum = Math.round(totalSize / 4);
  const tokenPct = Math.min(1, tokenNum / TOKEN_BUDGET);
  const tokenColor =
    tokenPct > 0.85 ? t.danger : tokenPct > 0.6 ? t.warning : t.accent;

  const channelPathFor = (f: ChannelWorkspaceFile) => `channels/${channelId}/${f.path}`;

  const handleCreate = () => {
    let filename = newName.trim();
    if (!filename) {
      setCreating(false);
      return;
    }
    if (!filename.endsWith(".md")) filename += ".md";
    writeMutation.mutate(
      { path: filename, content: `# ${filename.replace(/\.md$/, "")}\n` },
      {
        onSuccess: () => {
          onSelectFile(`channels/${channelId}/${filename}`);
          setCreating(false);
          setNewName("");
        },
      },
    );
  };

  // Note: we intentionally render the card even on first load (no early return).
  // Hiding it during the initial fetch makes the entire affordance disappear,
  // so the user can't see the "Add active file" button until the network
  // round-trip completes. Render the chrome immediately and let the body show
  // a placeholder while loading.

  return (
    <View
      style={{
        marginTop: 6,
        marginHorizontal: 6,
        marginBottom: 4,
        backgroundColor: t.accentSubtle,
        borderRadius: 6,
        borderLeftWidth: 2,
        borderLeftColor: t.accent,
        overflow: "hidden",
      }}
    >
      {/* Title row */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: 8,
          paddingTop: 6,
          paddingBottom: 4,
          gap: 6,
        }}
      >
        <View style={{
          width: 6, height: 6, borderRadius: 3,
          backgroundColor: isStreaming ? "#14b8a6" : t.accent,
          opacity: isStreaming ? 1 : 0.5,
        }} />
        <Text
          style={{
            flex: 1,
            color: t.textMuted,
            fontSize: 10,
            fontWeight: "700",
            textTransform: "uppercase",
            letterSpacing: 0.8,
          }}
        >
          In Context
        </Text>
        <Text
          style={{
            color: tokenColor,
            fontSize: 10,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
          }}
        >
          {tokenStr} tok
        </Text>
      </View>

      {/* Token bar */}
      <View style={{ height: 2, backgroundColor: `${t.text}10`, marginHorizontal: 8, borderRadius: 1 }}>
        <View
          style={{
            width: `${Math.round(tokenPct * 100)}%` as any,
            height: 2,
            backgroundColor: tokenColor,
            borderRadius: 1,
          }}
        />
      </View>

      {/* File rows */}
      <View style={{ paddingVertical: 4 }}>
        {activeFiles.length === 0 && !creating && (
          <Text
            style={{
              color: t.textDim,
              fontSize: 11,
              fontStyle: "italic",
              paddingHorizontal: 10,
              paddingVertical: 4,
            }}
          >
            {isLoading ? "Loading…" : "No active files yet"}
          </Text>
        )}
        {activeFiles.map((f) => (
          <ActiveFileRow
            key={f.path}
            file={f}
            selected={activeFile === channelPathFor(f)}
            onSelect={() => onSelectFile(channelPathFor(f))}
            onArchive={() => onArchive(f)}
            onDelete={() => onDelete(f)}
          />
        ))}

        {creating ? (
          <View style={{ paddingHorizontal: 10, paddingVertical: 2 }}>
            <input
              autoFocus
              value={newName}
              onChange={(e: any) => setNewName(e.target.value)}
              onKeyDown={(e: any) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") { setCreating(false); setNewName(""); }
              }}
              onBlur={() => {
                if (!newName.trim()) { setCreating(false); setNewName(""); }
              }}
              placeholder="filename.md"
              style={{
                width: "100%",
                background: t.inputBg,
                border: `1px solid ${t.accent}`,
                borderRadius: 3,
                padding: "1px 6px",
                fontSize: 11,
                color: t.text,
                outline: "none",
                height: 18,
                fontFamily: "inherit",
              }}
            />
          </View>
        ) : (
          <Pressable
            onPress={() => setCreating(true)}
            style={({ hovered }: any) => ({
              flexDirection: "row",
              alignItems: "center",
              gap: 5,
              paddingHorizontal: 10,
              paddingVertical: 3,
              opacity: hovered ? 1 : 0.55,
              cursor: "pointer",
            } as any)}
          >
            <Plus size={11} color={t.accent} />
            <Text
              style={{
                color: t.accent,
                fontSize: 10.5,
                fontWeight: "500",
              }}
            >
              Add active file
            </Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

function ActiveFileRow({
  file,
  selected,
  onSelect,
  onArchive,
  onDelete,
}: {
  file: ChannelWorkspaceFile;
  selected: boolean;
  onSelect: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);

  const displayName = file.name.includes("/")
    ? file.name.substring(file.name.lastIndexOf("/") + 1)
    : file.name;

  // Use accent-tinted icon to mark as "live"
  const icon = getFileIcon(displayName, t.accent, t.textDim);
  const modified = formatRelativeTime(file.modified_at);

  return (
    <Pressable
      onPress={onSelect}
      onHoverIn={() => setHovered(true)}
      onHoverOut={() => setHovered(false)}
      style={{
        flexDirection: "row",
        alignItems: "center",
        height: 22,
        paddingLeft: 10,
        paddingRight: 8,
        gap: 6,
        backgroundColor: selected ? `${t.accent}25` : hovered ? `${t.accent}12` : "transparent",
        cursor: "pointer",
      } as any}
    >
      {icon}
      <Text
        style={{
          flex: 1,
          color: selected ? t.text : t.accent,
          fontSize: 11.5,
          lineHeight: 22,
          minWidth: 0,
        }}
        numberOfLines={1}
      >
        {displayName}
      </Text>
      {hovered ? (
        <View style={{ flexDirection: "row", alignItems: "center", gap: 1 }}>
          <Pressable
            onPress={(e) => { e.stopPropagation(); onArchive(); }}
            style={{ padding: 2, opacity: 0.7 }}
            {...(Platform.OS === "web" ? { title: "Archive" } as any : {})}
          >
            <Archive size={11} color={t.textMuted} />
          </Pressable>
          <Pressable
            onPress={(e) => { e.stopPropagation(); onDelete(); }}
            style={{ padding: 2, opacity: 0.7 }}
            {...(Platform.OS === "web" ? { title: "Delete" } as any : {})}
          >
            <Trash2 size={11} color={t.textMuted} />
          </Pressable>
        </View>
      ) : (
        modified ? (
          <Text style={{ color: t.textDim, fontSize: 9, flexShrink: 0 }}>{modified}</Text>
        ) : null
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Scope strip — quick-jump chips
// ---------------------------------------------------------------------------

export function ScopeStrip({
  currentPath,
  channelTarget,
  memoryTarget,
  rootTarget,
  onJump,
}: {
  currentPath: string;
  channelTarget: string | null;
  memoryTarget: string | null;
  rootTarget: string;
  onJump: (path: string) => void;
}) {
  const t = useThemeTokens();
  const chips: { label: string; path: string }[] = [];
  if (channelTarget) chips.push({ label: "Channel", path: channelTarget });
  if (memoryTarget) chips.push({ label: "Memory", path: memoryTarget });
  chips.push({ label: "Workspace", path: rootTarget });

  return (
    <View
      style={{
        flexDirection: "row",
        gap: 4,
        paddingHorizontal: 8,
        paddingTop: 4,
        paddingBottom: 4,
      }}
    >
      {chips.map((c) => {
        const active =
          currentPath === c.path ||
          (c.path !== "/" && currentPath.startsWith(c.path + "/"));
        return (
          <Pressable
            key={c.label}
            onPress={() => onJump(c.path)}
            style={({ hovered }: any) => ({
              paddingHorizontal: 8,
              paddingVertical: 2,
              borderRadius: 10,
              backgroundColor: active
                ? t.accentSubtle
                : hovered
                  ? `${t.text}08`
                  : "transparent",
              borderWidth: 1,
              borderColor: active ? t.accentBorder : "transparent",
              cursor: "pointer",
            } as any)}
          >
            <Text
              style={{
                color: active ? t.accent : t.textMuted,
                fontSize: 10,
                fontWeight: active ? "600" : "500",
                letterSpacing: 0.2,
              }}
            >
              {c.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Breadcrumb — clickable path segments
// ---------------------------------------------------------------------------

export function Breadcrumb({
  path,
  channelId,
  channelDisplayName,
  onNavigate,
}: {
  path: string;
  channelId: string;
  channelDisplayName: string | null | undefined;
  onNavigate: (p: string) => void;
}) {
  const t = useThemeTokens();
  const segments = path === "/" ? [] : stripSlashes(path).split("/");

  // Replace channel UUID segments with display name
  const labelFor = (seg: string, i: number) => {
    if (i > 0 && segments[i - 1] === "channels" && seg === channelId && channelDisplayName) {
      return channelDisplayName;
    }
    return seg;
  };

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: 10,
        paddingVertical: 3,
        flexWrap: "nowrap",
        minHeight: 20,
      }}
    >
      <Pressable
        onPress={() => onNavigate("/")}
        style={({ hovered }: any) => ({ cursor: "pointer", opacity: hovered ? 1 : 0.85 } as any)}
      >
        <Text
          style={{
            color: path === "/" ? t.text : t.accent,
            fontSize: 10.5,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
          }}
        >
          /ws
        </Text>
      </Pressable>
      {segments.map((seg, i) => {
        const segPath = "/" + segments.slice(0, i + 1).join("/");
        const isLast = i === segments.length - 1;
        const label = labelFor(seg, i);
        return (
          <View key={segPath} style={{ flexDirection: "row", alignItems: "center", minWidth: 0 }}>
            <Text style={{ color: t.textDim, fontSize: 10.5, marginHorizontal: 3 }}>
              ›
            </Text>
            <Pressable
              onPress={() => !isLast && onNavigate(segPath)}
              style={({ hovered }: any) => ({
                cursor: isLast ? "default" : "pointer",
                opacity: hovered && !isLast ? 1 : 0.85,
                minWidth: 0,
              } as any)}
            >
              <Text
                numberOfLines={1}
                style={{
                  color: isLast ? t.text : t.accent,
                  fontSize: 10.5,
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                  maxWidth: 140,
                }}
              >
                {label}
              </Text>
            </Pressable>
          </View>
        );
      })}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Tree row — folder or file in current directory
// ---------------------------------------------------------------------------

export function TreeFolderRow({
  name,
  fullPath,
  onNavigate,
  onContextMenu,
  focused,
}: {
  name: string;
  fullPath: string;
  onNavigate: (p: string) => void;
  onContextMenu?: (e: any) => void;
  focused?: boolean;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  return (
    <Pressable
      onPress={() => onNavigate(fullPath)}
      onHoverIn={() => setHovered(true)}
      onHoverOut={() => setHovered(false)}
      style={{
        flexDirection: "row",
        alignItems: "center",
        height: 22,
        paddingLeft: 12,
        paddingRight: 8,
        gap: 6,
        backgroundColor: hovered || focused ? `${t.text}08` : "transparent",
        outline: focused ? `1px dotted ${t.textDim}` : "none",
        outlineOffset: -1,
        cursor: "pointer",
      } as any}
      {...(Platform.OS === "web" && onContextMenu ? { onContextMenu } as any : {})}
    >
      <Folder size={13} color="#dcb67a" />
      <Text
        style={{
          flex: 1,
          color: t.text,
          fontSize: 12,
          lineHeight: 22,
          minWidth: 0,
        }}
        numberOfLines={1}
      >
        {name}
      </Text>
      <ChevronRight size={11} color={t.textDim} />
    </Pressable>
  );
}

export function TreeFileRow({
  name,
  fullPath,
  size,
  modifiedAt,
  selected,
  focused,
  onSelect,
  onContextMenu,
  onDelete,
}: {
  name: string;
  fullPath: string;
  size: number | null | undefined;
  modifiedAt: number | null | undefined;
  selected: boolean;
  focused?: boolean;
  onSelect: () => void;
  onContextMenu?: (e: any) => void;
  onDelete: () => void;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);

  const icon = name === "MEMORY.md" || fullPath.endsWith("/archive")
    ? getArchiveIcon(t.textDim)
    : getFileIcon(name, null, t.textDim);
  const sizeStr = formatSize(size);
  const modified = formatRelativeTime(modifiedAt);

  return (
    <Pressable
      onPress={onSelect}
      onHoverIn={() => setHovered(true)}
      onHoverOut={() => setHovered(false)}
      style={{
        flexDirection: "row",
        alignItems: "center",
        height: 22,
        paddingLeft: 12,
        paddingRight: 8,
        gap: 6,
        backgroundColor: selected
          ? t.accentSubtle
          : hovered || focused
            ? `${t.text}08`
            : "transparent",
        outline: focused && !selected ? `1px dotted ${t.textDim}` : "none",
        outlineOffset: -1,
        cursor: "pointer",
      } as any}
      {...(Platform.OS === "web" && onContextMenu ? { onContextMenu } as any : {})}
    >
      {icon}
      <Text
        style={{
          flex: 1,
          color: t.text,
          fontSize: 12,
          lineHeight: 22,
          minWidth: 0,
        }}
        numberOfLines={1}
      >
        {name}
      </Text>
      {hovered ? (
        <Pressable
          onPress={(e) => { e.stopPropagation(); onDelete(); }}
          style={{ padding: 2, opacity: 0.7 }}
          {...(Platform.OS === "web" ? { title: "Delete" } as any : {})}
        >
          <Trash2 size={11} color={t.textMuted} />
        </Pressable>
      ) : (
        <Text style={{ color: t.textDim, fontSize: 9, flexShrink: 0 }}>
          {modified || sizeStr}
        </Text>
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Inline new-item row (file or folder)
// ---------------------------------------------------------------------------

export function NewItemRow({
  kind,
  onSubmit,
  onCancel,
}: {
  kind: "file" | "folder";
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const t = useThemeTokens();
  const [name, setName] = useState("");

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        height: 24,
        paddingLeft: 12,
        paddingRight: 8,
        gap: 6,
      }}
    >
      {kind === "folder"
        ? <Folder size={13} color="#dcb67a" />
        : <Plus size={13} color={t.accent} />}
      <input
        autoFocus
        value={name}
        onChange={(e: any) => setName(e.target.value)}
        onKeyDown={(e: any) => {
          if (e.key === "Enter" && name.trim()) onSubmit(name.trim());
          if (e.key === "Escape") onCancel();
        }}
        onBlur={() => { if (!name.trim()) onCancel(); else onSubmit(name.trim()); }}
        placeholder={kind === "folder" ? "folder-name" : "filename.md"}
        style={{
          flex: 1,
          background: t.inputBg,
          border: `1px solid ${t.accent}`,
          borderRadius: 3,
          padding: "0px 6px",
          fontSize: 12,
          color: t.text,
          outline: "none",
          height: 20,
          fontFamily: "inherit",
          minWidth: 0,
        }}
      />
    </View>
  );
}
