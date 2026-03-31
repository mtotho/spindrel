import { useState, useMemo, useRef, useCallback } from "react";
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
import { useMemorySearch, type MemorySearchResult } from "@/src/api/hooks/useSearch";
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
  Sparkles,
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
// Search Results Section
// ---------------------------------------------------------------------------
function SearchResultsView({
  results,
  onClear,
}: {
  results: MemorySearchResult[];
  onClear: () => void;
}) {
  const t = useThemeTokens();

  return (
    <View style={{ gap: 12 }}>
      <View className="flex-row items-center gap-2">
        <Sparkles size={14} color={t.accent} />
        <Text
          className="text-text-dim"
          style={{ fontSize: 10, fontWeight: "700", letterSpacing: 0.8, textTransform: "uppercase" }}
        >
          SEARCH RESULTS
        </Text>
        <Text className="text-text-dim text-xs">
          {results.length} match{results.length !== 1 ? "es" : ""}
        </Text>
        <View style={{ flex: 1 }} />
        <Pressable onPress={onClear} className="flex-row items-center gap-1">
          <X size={12} color={t.textDim} />
          <Text style={{ fontSize: 11, color: t.textDim }}>Clear</Text>
        </Pressable>
      </View>

      {results.map((result, i) => {
        const color = botDotColor(result.bot_id);
        const maxScore = results[0]?.score || 1;
        const barWidth = maxScore > 0 ? (result.score / maxScore) * 100 : 0;

        return (
          <View
            key={`${result.bot_id}-${result.file_path}-${i}`}
            className="rounded-xl border border-surface-border overflow-hidden"
          >
            {/* Header */}
            <View
              className="flex-row items-center gap-2 px-4 py-2.5"
              style={{ backgroundColor: `${color}08` }}
            >
              <View
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: color,
                }}
              />
              <Text className="text-text font-semibold text-xs">
                {result.bot_name}
              </Text>
              <Text className="text-text-dim text-[10px] font-mono">
                {result.file_path}
              </Text>
              <View style={{ flex: 1 }} />
              {/* Score bar */}
              <View style={{ width: 48, gap: 2 }}>
                <View
                  style={{
                    height: 3,
                    borderRadius: 1.5,
                    backgroundColor: t.surfaceBorder,
                    overflow: "hidden",
                  }}
                >
                  <View
                    style={{
                      height: 3,
                      borderRadius: 1.5,
                      backgroundColor: t.accent,
                      width: `${barWidth}%`,
                    }}
                  />
                </View>
              </View>
            </View>

            {/* Content snippet */}
            <View className="p-3">
              <Text
                className="text-text-muted text-xs"
                style={{ fontFamily: "monospace", lineHeight: 17 }}
                numberOfLines={6}
              >
                {result.content}
              </Text>
            </View>
          </View>
        );
      })}
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
  const searchMutation = useMemorySearch();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const sections = data?.sections || [];

  const handleSearchSubmit = useCallback(() => {
    if (search.trim()) {
      searchMutation.mutate({ query: search.trim(), top_k: 15 });
    }
  }, [search, searchMutation]);

  const handleSearchChange = useCallback(
    (text: string) => {
      setSearch(text);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (text.trim()) {
        debounceRef.current = setTimeout(() => {
          searchMutation.mutate({ query: text.trim(), top_k: 15 });
        }, 500);
      }
    },
    [searchMutation]
  );

  const handleClearSearch = useCallback(() => {
    setSearch("");
    searchMutation.reset();
  }, [searchMutation]);

  const searchResults = searchMutation.data?.results;
  const isSearchActive = search.trim().length > 0 && searchResults !== undefined;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Memory" subtitle="MEMORY.md across bots" />

      {/* Search bar */}
      {sections.length >= 1 && (
        <View
          className="flex-row items-center gap-2 border-b border-surface-border"
          style={{ paddingLeft: 24, paddingRight: 16, paddingVertical: 8 }}
        >
          <Brain size={14} color={t.accent} />
          <Text style={{ fontSize: 10, color: t.accent, fontWeight: "600" }}>
            Semantic
          </Text>
          <Search size={14} color={t.textDim} />
          <TextInput
            value={search}
            onChangeText={handleSearchChange}
            onSubmitEditing={handleSearchSubmit}
            placeholder="Search memory semantically..."
            placeholderTextColor={t.textDim}
            className="flex-1 text-text text-sm"
            style={{ backgroundColor: "transparent", outlineStyle: "none" } as any}
          />
          {searchMutation.isPending && (
            <Text style={{ fontSize: 10, color: t.textDim }}>Searching...</Text>
          )}
          {search.length > 0 && (
            <Pressable onPress={handleClearSearch}>
              <X size={14} color={t.textDim} />
            </Pressable>
          )}
        </View>
      )}

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ paddingLeft: 24, paddingRight: 16, paddingTop: 20, gap: 20, paddingBottom: 48, maxWidth: 960 }}
      >
        {isLoading ? (
          <Text className="text-text-muted text-sm">Loading memory...</Text>
        ) : (
          <>
            {/* Search results (above regular sections) */}
            {isSearchActive && searchResults && searchResults.length > 0 && (
              <SearchResultsView results={searchResults} onClear={handleClearSearch} />
            )}
            {isSearchActive && searchResults && searchResults.length === 0 && (
              <View
                className="rounded-xl border border-surface-border p-4"
                style={{ backgroundColor: t.surfaceOverlay }}
              >
                <Text className="text-text-dim text-sm text-center">
                  No semantic matches for "{search}"
                </Text>
              </View>
            )}

            {/* Regular memory sections */}
            {sections.length === 0 ? (
              <MCEmptyState feature="memory">
                <Text className="text-text-muted text-sm">
                  No bots with workspace-files memory scheme found.
                </Text>
              </MCEmptyState>
            ) : (
              sections.map((section) => (
                <MemorySectionView key={section.bot_id} section={section} />
              ))
            )}
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}
