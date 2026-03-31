import { useState, useMemo } from "react";
import { View, Text, Pressable, TextInput, Platform } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCMemory,
  useMCPrefs,
  useMCReferenceFile,
  type MCMemorySection,
} from "@/src/api/hooks/useMissionControl";
import { MCEmptyState } from "@/src/components/mission-control/MCEmptyState";
import { botDotColor } from "@/src/components/mission-control/botColors";
import {
  Brain,
  FileText,
  ChevronDown,
  ChevronRight,
  Search,
  Eye,
  X,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Lazy markdown import (web only)
// ---------------------------------------------------------------------------
let MarkdownViewer: React.ComponentType<{ content: string }> | null = null;
try {
  if (Platform.OS === "web") {
    MarkdownViewer =
      require("@/src/components/workspace/MarkdownViewer").MarkdownViewer;
  }
} catch {
  // Not available — fallback to monospace
}

// ---------------------------------------------------------------------------
// Reference file preview (inline)
// ---------------------------------------------------------------------------
function ReferenceFilePreview({
  botId,
  filename,
  onClose,
}: {
  botId: string;
  filename: string;
  onClose: () => void;
}) {
  const t = useThemeTokens();
  const { data, isLoading } = useMCReferenceFile(botId, filename);

  return (
    <View
      className="rounded-lg border border-surface-border mt-2 overflow-hidden"
      style={{ backgroundColor: t.codeBg || "rgba(0,0,0,0.03)" }}
    >
      <View className="flex-row items-center justify-between px-3 py-2 border-b border-surface-border">
        <Text className="text-text-dim text-xs font-semibold">{filename}</Text>
        <Pressable onPress={onClose}>
          <X size={14} color={t.textDim} />
        </Pressable>
      </View>
      <View className="p-3">
        {isLoading ? (
          <Text className="text-text-muted text-xs">Loading...</Text>
        ) : data?.content && MarkdownViewer ? (
          <MarkdownViewer content={data.content} />
        ) : (
          <Text
            className="text-text-muted text-xs"
            style={{ fontFamily: "monospace", lineHeight: 18 }}
          >
            {data?.content || "Empty file"}
          </Text>
        )}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Memory Section component (collapsible)
// ---------------------------------------------------------------------------
function MemorySectionView({ section }: { section: MCMemorySection }) {
  const t = useThemeTokens();
  const color = botDotColor(section.bot_id);
  const [expanded, setExpanded] = useState(true);
  const [previewFile, setPreviewFile] = useState<string | null>(null);

  return (
    <View className="rounded-xl border border-surface-border overflow-hidden">
      {/* Header — collapsible */}
      <Pressable
        onPress={() => setExpanded(!expanded)}
        className="flex-row items-center gap-3 px-4 py-3.5 border-b border-surface-border hover:bg-surface-overlay"
        style={{ backgroundColor: `${color}08` }}
      >
        {expanded ? (
          <ChevronDown size={14} color={t.textDim} />
        ) : (
          <ChevronRight size={14} color={t.textDim} />
        )}
        <View
          style={{
            width: 10,
            height: 10,
            borderRadius: 5,
            backgroundColor: color,
          }}
        />
        <Text className="text-text font-semibold text-sm flex-1">
          {section.bot_name}
        </Text>
        {section.reference_files.length > 0 && (
          <View className="flex-row items-center gap-1">
            <FileText size={12} color={t.textDim} />
            <Text className="text-text-dim text-xs">
              {section.reference_files.length} ref
            </Text>
          </View>
        )}
      </Pressable>

      {expanded && (
        <>
          {/* MEMORY.md content */}
          <View className="p-4">
            {section.memory_content ? (
              MarkdownViewer ? (
                <MarkdownViewer content={section.memory_content} />
              ) : (
                <Text
                  className="text-text-muted text-xs"
                  style={{ fontFamily: "monospace", lineHeight: 18 }}
                >
                  {section.memory_content}
                </Text>
              )
            ) : (
              <Text className="text-text-dim text-xs italic">
                No MEMORY.md found
              </Text>
            )}
          </View>

          {/* Reference files */}
          {section.reference_files.length > 0 && (
            <View className="px-4 pb-4" style={{ borderTopWidth: 1, borderTopColor: 'rgba(107,114,128,0.1)', paddingTop: 12 }}>
              <Text className="text-text-dim text-[10px] font-semibold tracking-wider mb-3">
                REFERENCE FILES
              </Text>
              <View style={{ gap: 6 }}>
                {section.reference_files.map((file) => (
                  <View key={file}>
                    <View className="flex-row items-center gap-2">
                      <FileText size={12} color={t.textDim} />
                      <Text className="text-text-muted text-xs flex-1">
                        {file}
                      </Text>
                      <Pressable
                        onPress={() =>
                          setPreviewFile(previewFile === file ? null : file)
                        }
                        className="flex-row items-center gap-1 px-2 py-0.5 rounded border border-surface-border hover:bg-surface-overlay"
                      >
                        <Eye size={10} color={t.textDim} />
                        <Text className="text-text-dim text-[10px]">
                          {previewFile === file ? "Hide" : "View"}
                        </Text>
                      </Pressable>
                    </View>
                    {previewFile === file && (
                      <ReferenceFilePreview
                        botId={section.bot_id}
                        filename={file}
                        onClose={() => setPreviewFile(null)}
                      />
                    )}
                  </View>
                ))}
              </View>
            </View>
          )}
        </>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCMemory() {
  const { data: prefs } = useMCPrefs();
  const scope =
    ((prefs?.layout_prefs as any)?.scope as "fleet" | "personal") || "fleet";
  const { data, isLoading } = useMCMemory(scope);
  const { refreshing, onRefresh } = usePageRefresh([["mc-memory"]]);
  const t = useThemeTokens();
  const [search, setSearch] = useState("");

  const sections = data?.sections || [];

  // Client-side search filter
  const filtered = useMemo(() => {
    if (!search.trim()) return sections;
    const q = search.toLowerCase();
    return sections.filter(
      (s) =>
        s.bot_name.toLowerCase().includes(q) ||
        (s.memory_content && s.memory_content.toLowerCase().includes(q)) ||
        s.reference_files.some((f) => f.toLowerCase().includes(q))
    );
  }, [sections, search]);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Memory" subtitle="MEMORY.md across bots" />

      {/* Search bar */}
      {sections.length >= 1 && (
        <View className="flex-row items-center gap-2 px-4 py-2 border-b border-surface-border">
          <Search size={14} color={t.textDim} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Search bots, content, files..."
            placeholderTextColor={t.textDim}
            className="flex-1 text-text text-sm"
            style={{ backgroundColor: "transparent", outlineStyle: "none" } as any}
          />
          {search.length > 0 && (
            <Pressable onPress={() => setSearch("")}>
              <X size={14} color={t.textDim} />
            </Pressable>
          )}
        </View>
      )}

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ paddingHorizontal: 20, paddingTop: 24, gap: 24, paddingBottom: 40, maxWidth: 960 }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading memory...</Text>
        ) : filtered.length === 0 ? (
          <MCEmptyState feature="memory">
            <Text className="text-text-muted text-sm">
              {search
                ? "No matching bots or content found."
                : "No bots with workspace-files memory scheme found."}
            </Text>
          </MCEmptyState>
        ) : (
          filtered.map((section) => (
            <MemorySectionView key={section.bot_id} section={section} />
          ))
        )}
      </RefreshableScrollView>
    </View>
  );
}
