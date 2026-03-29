import { useState, useEffect, useCallback, useMemo } from "react";
import {
  View,
  Text,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Switch,
  useWindowDimensions,
} from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { Link, useRouter } from "expo-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, RotateCcw, Check, Eye, ChevronRight, Server, KeyRound, Sun, Moon, AlertTriangle } from "lucide-react";
import { MemorySchemeSection } from "@/src/components/settings/MemorySchemeSection";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { apiFetch } from "@/src/api/client";
import { useThemeStore } from "@/src/stores/theme";
import { useThemeTokens } from "@/src/theme/tokens";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList, type FallbackModelEntry } from "@/src/components/shared/FallbackModelList";
import { Section } from "@/src/components/shared/FormControls";
import {
  useSettings,
  useUpdateSettings,
  useResetSetting,
  SettingItem,
  SettingsGroup,
} from "@/src/api/hooks/useSettings";

// ---------------------------------------------------------------------------
// Field renderers
// ---------------------------------------------------------------------------

function BoolField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <Switch
      value={value}
      onValueChange={onChange}
      disabled={item.read_only}
      trackColor={{ false: "#374151", true: "#3b82f6" }}
      thumbColor="#e5e5e5"
    />
  );
}

function SelectField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <View className="flex-row flex-wrap gap-1.5">
      {item.options!.map((opt) => (
        <Pressable
          key={opt}
          onPress={() => !item.read_only && onChange(opt)}
          className={`px-3 py-1.5 rounded border ${
            value === opt
              ? "bg-accent/20 border-accent"
              : "bg-surface border-surface-border"
          }`}
        >
          <Text
            className={`text-xs ${
              value === opt ? "text-accent font-medium" : "text-text-muted"
            }`}
          >
            {opt}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

function NumberField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <TextInput
      className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
      style={{ maxWidth: 200 }}
      value={value}
      onChangeText={onChange}
      editable={!item.read_only}
      keyboardType="numeric"
      placeholder={item.nullable ? "(none)" : undefined}
      placeholderTextColor="#737373"
    />
  );
}

function StringField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <TextInput
      className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm flex-1"
      value={value}
      onChangeText={onChange}
      editable={!item.read_only}
      placeholder="(empty)"
      placeholderTextColor="#737373"
    />
  );
}

function TextareaField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <TextInput
      className="bg-surface border border-surface-border rounded px-3 py-3 text-text text-sm"
      value={value}
      onChangeText={onChange}
      editable={!item.read_only}
      placeholder="(empty)"
      placeholderTextColor="#737373"
      multiline
      numberOfLines={16}
      style={{
        minHeight: 300,
        width: "100%",
        textAlignVertical: "top",
        fontFamily: "monospace",
        lineHeight: 20,
        // @ts-ignore — web-only resize property
        resize: "vertical",
      }}
    />
  );
}

function ModelField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <View style={{ maxWidth: 400 }}>
      <LlmModelDropdown
        value={value}
        onChange={onChange}
        placeholder="Select model..."
        allowClear
      />
    </View>
  );
}

function EmbeddingModelField({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <View style={{ maxWidth: 400 }}>
      <LlmModelDropdown
        value={value}
        onChange={onChange}
        placeholder="Select embedding model..."
        allowClear
        variant="embedding"
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Single setting row
// ---------------------------------------------------------------------------

function SettingRow({
  item,
  localValue,
  onLocalChange,
  onReset,
  isResetting,
}: {
  item: SettingItem;
  localValue: any;
  onLocalChange: (key: string, value: any) => void;
  onReset: (key: string) => void;
  isResetting: boolean;
}) {
  const renderField = () => {
    if (item.type === "bool") {
      return (
        <BoolField
          item={item}
          value={!!localValue}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    if (item.options && item.options.length > 0) {
      return (
        <SelectField
          item={item}
          value={String(localValue ?? "")}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    if (item.type === "int" || item.type === "float") {
      return (
        <NumberField
          item={item}
          value={localValue === null || localValue === undefined ? "" : String(localValue)}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    if (item.widget === "textarea") {
      return (
        <TextareaField
          item={item}
          value={String(localValue ?? "")}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    if (item.widget === "model") {
      return (
        <ModelField
          item={item}
          value={String(localValue ?? "")}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    if (item.widget === "embedding_model") {
      return (
        <EmbeddingModelField
          item={item}
          value={String(localValue ?? "")}
          onChange={(v) => onLocalChange(item.key, v)}
        />
      );
    }
    return (
      <StringField
        item={item}
        value={String(localValue ?? "")}
        onChange={(v) => onLocalChange(item.key, v)}
      />
    );
  };

  return (
    <View className="py-3 gap-2">
      <View className="flex-row items-center gap-2 flex-wrap">
        <Text className="text-text text-sm font-medium">{item.label}</Text>
        {item.overridden && (
          <View className="bg-accent/20 px-1.5 py-0.5 rounded">
            <Text className="text-accent text-[10px] font-medium">overridden</Text>
          </View>
        )}
        {item.read_only && (
          <View className="bg-surface-overlay px-1.5 py-0.5 rounded">
            <Text className="text-text-dim text-[10px]">read-only</Text>
          </View>
        )}
      </View>
      <Text className="text-text-dim text-xs">{item.description}</Text>
      <View className="flex-row items-center gap-2">
        {renderField()}
        {item.overridden && !item.read_only && (
          <Pressable
            onPress={() => onReset(item.key)}
            disabled={isResetting}
            className="flex-row items-center gap-1 px-2 py-1.5 rounded border border-surface-border hover:bg-surface-overlay"
          >
            {isResetting ? (
              <ActivityIndicator size="small" color="#9ca3af" />
            ) : (
              <RotateCcw size={12} color="#9ca3af" />
            )}
            <Text className="text-text-muted text-xs">Reset</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Group section nav
// ---------------------------------------------------------------------------

function GroupNav({
  groups,
  activeGroup,
  onSelect,
}: {
  groups: SettingsGroup[];
  activeGroup: string;
  onSelect: (g: string) => void;
}) {
  return (
    <View className="gap-0.5">
      {groups.map((g) => (
        <Pressable
          key={g.group}
          onPress={() => onSelect(g.group)}
          className={`px-3 py-2 rounded ${
            activeGroup === g.group ? "bg-accent/15" : "hover:bg-surface-overlay"
          }`}
        >
          <Text
            className={`text-sm ${
              activeGroup === g.group
                ? "text-accent font-medium"
                : "text-text-muted"
            }`}
          >
            {g.group}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Global Fallback Models hooks
// ---------------------------------------------------------------------------

function useGlobalFallbackModels() {
  return useQuery({
    queryKey: ["global-fallback-models"],
    queryFn: () =>
      apiFetch<{ models: FallbackModelEntry[] }>("/api/v1/admin/global-fallback-models"),
  });
}

function useUpdateGlobalFallbackModels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (models: FallbackModelEntry[]) =>
      apiFetch("/api/v1/admin/global-fallback-models", {
        method: "PUT",
        body: JSON.stringify({ models }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["global-fallback-models"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Global Fallback Models section
// ---------------------------------------------------------------------------

const GLOBAL_GROUP = "Global";

function GlobalSection({
  fbModels,
  onFbChange,
  onFbSave,
  fbDirty,
  fbSaving,
  fbSaved,
  fbError,
  fbLoading,
}: {
  fbModels: FallbackModelEntry[];
  onFbChange: (v: FallbackModelEntry[]) => void;
  onFbSave: () => void;
  fbDirty: boolean;
  fbSaving: boolean;
  fbSaved: boolean;
  fbError: boolean;
  fbLoading: boolean;
}) {
  return (
    <View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        <Link href={"/admin/providers" as any} asChild>
          <Pressable className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay border border-surface-border">
            <Server size={14} color="#3b82f6" />
            <Text className="text-accent" style={{ fontSize: 13 }}>Providers</Text>
          </Pressable>
        </Link>
        <Link href={"/admin/api-keys" as any} asChild>
          <Pressable className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay border border-surface-border">
            <KeyRound size={14} color="#3b82f6" />
            <Text className="text-accent" style={{ fontSize: 13 }}>API Keys</Text>
          </Pressable>
        </Link>
        <Link href={"/admin/config-state" as any} asChild>
          <Pressable className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay border border-surface-border">
            <Eye size={14} color="#3b82f6" />
            <Text className="text-accent" style={{ fontSize: 13 }}>Config State</Text>
          </Pressable>
        </Link>
      </View>

      <Section title="Global Fallback Models">
        <Text className="text-text-dim text-xs" style={{ marginBottom: 12 }}>
          Catch-all fallback chain appended after channel/bot fallbacks. When all per-channel
          and per-bot fallbacks are exhausted, these models are tried in order.
        </Text>

        {fbLoading ? (
          <ActivityIndicator color="#3b82f6" />
        ) : (
          <FallbackModelList value={fbModels} onChange={onFbChange} />
        )}
      </Section>

      <View style={{ marginTop: 20, flexDirection: "row", gap: 12, alignItems: "center" }}>
        <Pressable
          onPress={onFbSave}
          disabled={!fbDirty || fbSaving}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            backgroundColor: fbDirty ? "#3b82f6" : "rgba(128,128,128,0.3)",
            paddingHorizontal: 16,
            paddingVertical: 8,
            borderRadius: 8,
            opacity: fbDirty ? 1 : 0.5,
          }}
        >
          {fbSaving ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : fbSaved ? (
            <Check size={14} color="#fff" />
          ) : (
            <Save size={14} color="#fff" />
          )}
          <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>
            {fbSaved ? "Saved" : "Save"}
          </Text>
        </Pressable>
        {fbError && (
          <Text style={{ color: "#ef4444", fontSize: 12 }}>Failed to save</Text>
        )}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Appearance section
// ---------------------------------------------------------------------------

function AppearanceSection() {
  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);
  const t = useThemeTokens();
  return (
    <Section title="Appearance" description="UI theme and display preferences">
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingVertical: 8,
          paddingHorizontal: 4,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          {mode === "dark" ? (
            <Moon size={18} color={t.textMuted} />
          ) : (
            <Sun size={18} color={t.textMuted} />
          )}
          <Text className="text-text text-sm">
            {mode === "dark" ? "Dark mode" : "Light mode"}
          </Text>
        </View>
        <Switch
          value={mode === "dark"}
          onValueChange={toggle}
          trackColor={{ false: "#d1d5db", true: "#3b82f6" }}
          thumbColor="#fff"
        />
      </View>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Chat History extras (section index preview + deviations)
// ---------------------------------------------------------------------------

const SECTION_INDEX_HEADER = `Archived conversation history — use read_conversation_history with:
  - A section number (e.g. '3') to read a full transcript
  - 'search:<query>' to find sections by topic
  - 'messages:<query>' to grep raw messages across ALL history
  - 'tool:<id>' to retrieve full output of a summarized tool call`;

const SECTION_INDEX_PREVIEW: Record<string, string> = {
  compact: `${SECTION_INDEX_HEADER}
- #3: Deploy Pipeline (Mar 5) [deploy, ci-cd]
- #2: API Design (Mar 3) [api, design]
- #1: Database Migration (Mar 1) [database, migration]`,
  standard: `${SECTION_INDEX_HEADER}

#3: Deploy Pipeline (Mar 5) [deploy, ci-cd]
  Set up GitHub Actions workflow with staging and production targets.

#2: API Design (Mar 3) [api, design]
  Discussed REST endpoint structure for v2 and auth middleware.

#1: Database Migration (Mar 1) [database, migration]
  Fixed PostgreSQL schema issues and updated indexes for vector search.`,
  detailed: `${SECTION_INDEX_HEADER}

#3: Deploy Pipeline (12 msgs, mar 5, 8:30am — 11:15am) [deploy, ci-cd]
  Set up GitHub Actions workflow with staging and production targets.

#2: API Design (18 msgs, mar 3, 10:00am — 2:45pm) [api, design]
  Discussed REST endpoint structure for v2 and auth middleware.

#1: Database Migration (32 msgs, mar 1, 9:15am — 4:30pm) [database, migration]
  Fixed PostgreSQL schema issues and updated indexes for vector search.`,
};

interface ChatHistoryDeviation {
  channel_id: string;
  channel_name: string;
  deviations: { field: string; global_value: any; channel_value: any }[];
}

function ChatHistoryExtras({ verbosity }: { verbosity: string }) {
  const router = useRouter();
  const t = useThemeTokens();
  const [showDeviations, setShowDeviations] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["chat-history-deviations"],
    queryFn: () => apiFetch<{ channels: ChatHistoryDeviation[] }>("/api/v1/admin/settings/chat-history-deviations"),
    enabled: showDeviations,
  });

  const preview = SECTION_INDEX_PREVIEW[verbosity] || SECTION_INDEX_PREVIEW.standard;

  return (
    <View style={{ marginTop: 16, gap: 16 }}>
      {/* Section Index Preview */}
      <Section title="Section Index Preview" description={`System message injected into the bot's context each turn ("${verbosity}" verbosity)`}>
        <View style={{
          backgroundColor: t.surface,
          borderRadius: 8,
          border: `1px solid ${t.surfaceOverlay}`,
          padding: 14,
        }}>
          <Text style={{
            fontFamily: "monospace",
            fontSize: 11,
            lineHeight: 18,
            color: t.textMuted,
            whiteSpace: "pre-wrap",
          }}>
            {preview}
          </Text>
        </View>
      </Section>

      {/* Show Deviations */}
      <Section title="Channel Deviations" description="Channels with chat history settings that differ from these global defaults">
        {!showDeviations ? (
          <Pressable
            onPress={() => setShowDeviations(true)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              backgroundColor: t.surfaceRaised,
              paddingHorizontal: 14,
              paddingVertical: 10,
              borderRadius: 8,
              border: `1px solid ${t.surfaceBorder}`,
              alignSelf: "flex-start",
            }}
          >
            <Eye size={14} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 13 }}>Show Deviations</Text>
          </Pressable>
        ) : isLoading ? (
          <ActivityIndicator color="#3b82f6" />
        ) : !data?.channels?.length ? (
          <Text style={{ color: t.textDim, fontSize: 12 }}>All channels use global defaults.</Text>
        ) : (
          <View style={{ gap: 8 }}>
            {data.channels.map((ch) => (
              <Pressable
                key={ch.channel_id}
                onPress={() => router.push(`/channels/${ch.channel_id}/settings` as any)}
                style={{
                  backgroundColor: t.surfaceRaised,
                  borderRadius: 8,
                  border: `1px solid ${t.surfaceOverlay}`,
                  padding: 12,
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ color: t.text, fontSize: 13, fontWeight: "500", marginBottom: 4 }}>
                    {ch.channel_name}
                  </Text>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                    {ch.deviations.map((d) => (
                      <Text key={d.field} style={{ fontSize: 11, color: t.textMuted }}>
                        {d.field}: <Text style={{ color: "#f59e0b" }}>{String(d.channel_value)}</Text>
                        {" "}(global: {String(d.global_value)})
                      </Text>
                    ))}
                  </View>
                </View>
                <ChevronRight size={14} color={t.textDim} />
              </Pressable>
            ))}
          </View>
        )}
      </Section>
    </View>
  );
}

// ---------------------------------------------------------------------------
// File-mode-only indicator for section index settings
// ---------------------------------------------------------------------------

function FileModeOnlyBanner({ historyMode }: { historyMode: string }) {
  const t = useThemeTokens();
  const isFileMode = historyMode === "file";

  return (
    <View style={{ marginTop: 8, marginBottom: 4 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <Text style={{ fontSize: 13, fontWeight: "600", color: t.text }}>
          Section Index
        </Text>
        <View
          style={{
            backgroundColor: isFileMode ? "rgba(59,130,246,0.1)" : "rgba(100,100,100,0.15)",
            paddingHorizontal: 7,
            paddingVertical: 2,
            borderRadius: 4,
          }}
        >
          <Text
            style={{
              fontSize: 9,
              fontWeight: "700",
              color: isFileMode ? "#3b82f6" : t.textDim,
            }}
          >
            file mode only
          </Text>
        </View>
      </View>
      {!isFileMode && (
        <Text style={{ fontSize: 11, color: t.textDim, lineHeight: 17 }}>
          These settings only apply when History Mode is "file". Current mode: "{historyMode}".
        </Text>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Flush prompt override warning (workspace-files bots ignore this setting)
// ---------------------------------------------------------------------------

function FlushPromptOverrideWarning() {
  const t = useThemeTokens();
  const { data: bots } = useAdminBots();
  const wsFileBots = bots?.filter((b) => b.memory_scheme === "workspace-files") ?? [];
  if (!wsFileBots.length) return null;

  return (
    <View
      style={{
        flexDirection: "row",
        gap: 10,
        backgroundColor: "rgba(245,158,11,0.08)",
        borderWidth: 1,
        borderColor: "rgba(245,158,11,0.25)",
        borderRadius: 8,
        padding: 12,
        marginBottom: 4,
      }}
    >
      <AlertTriangle size={15} color="#f59e0b" style={{ marginTop: 1, flexShrink: 0 } as any} />
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={{ fontSize: 12, fontWeight: "600", color: "#f59e0b" }}>
          Ignored by workspace-files bots
        </Text>
        <Text style={{ fontSize: 11, color: t.textMuted, lineHeight: 17 }}>
          {wsFileBots.length === bots?.length
            ? "All bots use workspace-files memory — this prompt is never used. "
            : `This prompt is ignored for ${wsFileBots.length} bot${wsFileBots.length > 1 ? "s" : ""} using workspace-files memory. `}
          Those bots use a built-in flush prompt that writes to disk instead.
        </Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 2 }}>
          {wsFileBots.map((b) => (
            <View
              key={b.id}
              style={{
                backgroundColor: "rgba(245,158,11,0.1)",
                paddingHorizontal: 7,
                paddingVertical: 2,
                borderRadius: 4,
              }}
            >
              <Text style={{ fontSize: 10, fontWeight: "600", color: "#f59e0b" }}>{b.name}</Text>
            </View>
          ))}
        </View>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Settings screen
// ---------------------------------------------------------------------------

export default function SettingsScreen() {
  const { data, isLoading, error } = useSettings();
  const { refreshing, onRefresh } = usePageRefresh();
  const updateMutation = useUpdateSettings();
  const resetMutation = useResetSetting();
  const { width } = useWindowDimensions();
  const isDesktop = width >= 768;

  // Fallback models state
  const fbQuery = useGlobalFallbackModels();
  const fbUpdateMut = useUpdateGlobalFallbackModels();
  const [fbModels, setFbModels] = useState<FallbackModelEntry[]>([]);
  const [fbDirty, setFbDirty] = useState(false);
  const [fbSaved, setFbSaved] = useState(false);

  useEffect(() => {
    if (fbQuery.data?.models) {
      setFbModels(fbQuery.data.models);
      setFbDirty(false);
    }
  }, [fbQuery.data]);

  const handleFbChange = useCallback((v: FallbackModelEntry[]) => {
    setFbModels(v);
    setFbDirty(true);
    setFbSaved(false);
  }, []);

  const handleFbSave = useCallback(async () => {
    const clean = fbModels.filter((m) => m.model);
    await fbUpdateMut.mutateAsync(clean);
    setFbDirty(false);
    setFbSaved(true);
    setTimeout(() => setFbSaved(false), 2000);
  }, [fbModels, fbUpdateMut]);

  // Settings state
  const groups = data?.groups ?? [];
  const allGroups = useMemo(
    () => [{ group: GLOBAL_GROUP, settings: [] as SettingItem[] }, ...groups],
    [groups]
  );
  const [activeGroup, setActiveGroup] = useState<string>(GLOBAL_GROUP);
  const [localValues, setLocalValues] = useState<Record<string, any>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);
  const [resettingKey, setResettingKey] = useState<string | null>(null);

  // Initialize local values from server data
  useEffect(() => {
    if (!groups.length) return;
    const vals: Record<string, any> = {};
    for (const g of groups) {
      for (const s of g.settings) {
        vals[s.key] = s.value;
      }
    }
    setLocalValues(vals);
    setDirty({});
  }, [data]);

  const handleLocalChange = useCallback(
    (key: string, value: any) => {
      setLocalValues((prev) => ({ ...prev, [key]: value }));
      // Find original value
      for (const g of groups) {
        const item = g.settings.find((s) => s.key === key);
        if (item) {
          const changed = value !== item.value && String(value) !== String(item.value);
          setDirty((prev) => ({ ...prev, [key]: changed }));
          break;
        }
      }
      setSaved(false);
    },
    [groups]
  );

  const changedKeys = useMemo(
    () => Object.entries(dirty).filter(([, v]) => v).map(([k]) => k),
    [dirty]
  );

  const handleSave = useCallback(() => {
    if (!changedKeys.length) return;
    const updates: Record<string, any> = {};
    for (const key of changedKeys) {
      const schema = groups
        .flatMap((g) => g.settings)
        .find((s) => s.key === key);
      let val = localValues[key];
      // Coerce types before sending
      if (schema?.type === "int") {
        val = val === "" && schema.nullable ? null : parseInt(val, 10);
        if (!schema.nullable && isNaN(val)) continue;
      } else if (schema?.type === "float") {
        val = parseFloat(val);
        if (isNaN(val)) continue;
      }
      updates[key] = val;
    }
    updateMutation.mutate(updates, {
      onSuccess: () => {
        setDirty({});
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      },
    });
  }, [changedKeys, localValues, groups, updateMutation]);

  const handleReset = useCallback(
    (key: string) => {
      setResettingKey(key);
      resetMutation.mutate(key, {
        onSettled: () => setResettingKey(null),
      });
    },
    [resetMutation]
  );

  const isGlobal = activeGroup === GLOBAL_GROUP;
  const activeSettings = groups.find((g) => g.group === activeGroup)?.settings ?? [];

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator size="large" color="#3b82f6" />
      </View>
    );
  }

  if (error) {
    return (
      <View className="flex-1 bg-surface items-center justify-center p-4">
        <Text className="text-red-400 text-sm">
          Failed to load settings: {error instanceof Error ? error.message : "Unknown error"}
        </Text>
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Settings"
        right={
          <View className="flex-row items-center gap-2">
            {saved && (
              <View className="flex-row items-center gap-1">
                <Check size={14} color="#22c55e" />
                <Text className="text-green-400 text-xs">Saved</Text>
              </View>
            )}
            {changedKeys.length > 0 && (
              <Pressable
                onPress={handleSave}
                disabled={updateMutation.isPending}
                className="bg-accent rounded px-3 py-1.5 flex-row items-center gap-1.5"
              >
                {updateMutation.isPending ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Save size={14} color="#fff" />
                )}
                <Text className="text-white text-sm font-medium">Save</Text>
              </Pressable>
            )}
          </View>
        }
      />

      <View className="flex-1 flex-row">
        {/* Desktop group nav */}
        {isDesktop && (
          <View
            className="border-r border-surface-border p-3"
            style={{ width: 200 }}
          >
            <GroupNav
              groups={allGroups}
              activeGroup={activeGroup}
              onSelect={setActiveGroup}
            />
          </View>
        )}

        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1 p-4" contentContainerStyle={{ maxWidth: 640 }}>
          {/* Mobile group selector */}
          {!isDesktop && (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              className="mb-4"
              contentContainerStyle={{ gap: 6 }}
            >
              {allGroups.map((g) => (
                <Pressable
                  key={g.group}
                  onPress={() => setActiveGroup(g.group)}
                  className={`px-3 py-1.5 rounded-full border ${
                    activeGroup === g.group
                      ? "bg-accent/20 border-accent"
                      : "border-surface-border"
                  }`}
                >
                  <Text
                    className={`text-xs ${
                      activeGroup === g.group
                        ? "text-accent font-medium"
                        : "text-text-muted"
                    }`}
                  >
                    {g.group}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          )}

          {/* Group title */}
          <Text className="text-text font-semibold text-lg mb-2">
            {activeGroup}
          </Text>

          {/* Appearance section — shown in Global group */}
          {isGlobal && <AppearanceSection />}

          {/* Global section (fallback models + config state link) */}
          {isGlobal && (
            <GlobalSection
              fbModels={fbModels}
              onFbChange={handleFbChange}
              onFbSave={handleFbSave}
              fbDirty={fbDirty}
              fbSaving={fbUpdateMut.isPending}
              fbSaved={fbSaved}
              fbError={fbUpdateMut.isError}
              fbLoading={fbQuery.isLoading}
            />
          )}

          {/* Settings */}
          {!isGlobal && activeSettings.filter((s: any) => !s.ui_hidden).map((item, idx) => {
            const FILE_MODE_KEYS = new Set(["SECTION_INDEX_COUNT", "SECTION_INDEX_VERBOSITY"]);
            const historyMode = String(localValues["DEFAULT_HISTORY_MODE"] ?? "file");
            const isFileModeOnly = FILE_MODE_KEYS.has(item.key);
            const dimmed = isFileModeOnly && historyMode !== "file";

            return (
              <View key={item.key} style={dimmed ? { opacity: 0.4 } : undefined}>
                {idx > 0 && <View className="h-px bg-surface-border" />}
                {item.key === "MEMORY_FLUSH_DEFAULT_PROMPT" && <FlushPromptOverrideWarning />}
                {item.key === "SECTION_INDEX_COUNT" && (
                  <FileModeOnlyBanner historyMode={historyMode} />
                )}
                <SettingRow
                  item={item}
                  localValue={localValues[item.key]}
                  onLocalChange={handleLocalChange}
                  onReset={handleReset}
                  isResetting={resettingKey === item.key}
                />
              </View>
            );
          })}

          {/* Chat History extras: section index preview + deviations (file mode only) + memory scheme */}
          {activeGroup === "Chat History" && (
            <>
              {String(localValues["DEFAULT_HISTORY_MODE"] ?? "file") === "file" && (
                <ChatHistoryExtras
                  verbosity={String(localValues["SECTION_INDEX_VERBOSITY"] ?? "standard")}
                />
              )}
              <MemorySchemeSection />
            </>
          )}
        </RefreshableScrollView>
      </View>
    </View>
  );
}
