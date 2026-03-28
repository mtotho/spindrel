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
import { Save, RotateCcw, Check, Eye, ChevronRight, Server, KeyRound } from "lucide-react";
import { MemorySchemeSection } from "@/src/components/settings/MemorySchemeSection";
import { apiFetch } from "@/src/api/client";
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
      placeholderTextColor="#666666"
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
      placeholderTextColor="#666666"
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
      placeholderTextColor="#666666"
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
            <Text style={{ fontSize: 13, color: "#3b82f6" }}>Providers</Text>
          </Pressable>
        </Link>
        <Link href={"/admin/api-keys" as any} asChild>
          <Pressable className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay border border-surface-border">
            <KeyRound size={14} color="#3b82f6" />
            <Text style={{ fontSize: 13, color: "#3b82f6" }}>API Keys</Text>
          </Pressable>
        </Link>
        <Link href={"/admin/config-state" as any} asChild>
          <Pressable className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay border border-surface-border">
            <Eye size={14} color="#3b82f6" />
            <Text style={{ fontSize: 13, color: "#3b82f6" }}>Config State</Text>
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
            backgroundColor: fbDirty ? "#3b82f6" : "#333",
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
// Chat History extras (section index preview + deviations)
// ---------------------------------------------------------------------------

const SECTION_INDEX_PREVIEW: Record<string, string> = {
  compact: `#1: Database Migration (Mar 5) [database, migration]
#2: API Design (Mar 3) [api, design]
#3: Deploy Pipeline (Mar 1) [deploy, ci-cd]`,
  standard: `#1: Database Migration (Mar 5) [database, migration]
  Fixed PostgreSQL schema issues and updated indexes for vector search
#2: API Design (Mar 3) [api, design]
  Discussed REST endpoint structure for v2 and auth middleware
#3: Deploy Pipeline (Mar 1) [deploy, ci-cd]
  Set up GitHub Actions workflow with staging and production targets`,
  detailed: `#1: Database Migration (Mar 5) [database, migration, postgresql]
  Fixed PostgreSQL schema issues and updated indexes for vector search.
  Resolved conflict between pgvector extension and existing JSONB columns.
  Added new migration for conversation_sections table.
#2: API Design (Mar 3) [api, design, rest]
  Discussed REST endpoint structure for v2 and auth middleware.
  Decided on JWT tokens with refresh rotation. Rate limiting via Redis.`,
};

interface ChatHistoryDeviation {
  channel_id: string;
  channel_name: string;
  deviations: { field: string; global_value: any; channel_value: any }[];
}

function ChatHistoryExtras({ verbosity }: { verbosity: string }) {
  const router = useRouter();
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
      <Section title="Section Index Preview" description={`Example of what the section index looks like in "${verbosity}" mode`}>
        <View style={{
          backgroundColor: "#0d0d0d",
          borderRadius: 8,
          border: "1px solid #2a2a2a",
          padding: 14,
        }}>
          <Text style={{
            fontFamily: "monospace",
            fontSize: 11,
            lineHeight: 18,
            color: "#888",
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
              backgroundColor: "#1a1a1a",
              paddingHorizontal: 14,
              paddingVertical: 10,
              borderRadius: 8,
              border: "1px solid #333",
              alignSelf: "flex-start",
            }}
          >
            <Eye size={14} color="#3b82f6" />
            <Text style={{ color: "#3b82f6", fontSize: 13 }}>Show Deviations</Text>
          </Pressable>
        ) : isLoading ? (
          <ActivityIndicator color="#3b82f6" />
        ) : !data?.channels?.length ? (
          <Text style={{ color: "#666", fontSize: 12 }}>All channels use global defaults.</Text>
        ) : (
          <View style={{ gap: 8 }}>
            {data.channels.map((ch) => (
              <Pressable
                key={ch.channel_id}
                onPress={() => router.push(`/channels/${ch.channel_id}/settings` as any)}
                style={{
                  backgroundColor: "#1a1a1a",
                  borderRadius: 8,
                  border: "1px solid #2a2a2a",
                  padding: 12,
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ color: "#e5e5e5", fontSize: 13, fontWeight: "500", marginBottom: 4 }}>
                    {ch.channel_name}
                  </Text>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                    {ch.deviations.map((d) => (
                      <Text key={d.field} style={{ fontSize: 11, color: "#888" }}>
                        {d.field}: <Text style={{ color: "#f59e0b" }}>{String(d.channel_value)}</Text>
                        {" "}(global: {String(d.global_value)})
                      </Text>
                    ))}
                  </View>
                </View>
                <ChevronRight size={14} color="#666" />
              </Pressable>
            ))}
          </View>
        )}
      </Section>
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
          {!isGlobal && activeSettings.map((item, idx) => (
            <View key={item.key}>
              {idx > 0 && <View className="h-px bg-surface-border" />}
              <SettingRow
                item={item}
                localValue={localValues[item.key]}
                onLocalChange={handleLocalChange}
                onReset={handleReset}
                isResetting={resettingKey === item.key}
              />
            </View>
          ))}

          {/* Chat History extras: memory scheme + section index preview + deviations */}
          {activeGroup === "Chat History" && (
            <>
              <MemorySchemeSection />
              <ChatHistoryExtras
                verbosity={String(localValues["SECTION_INDEX_VERBOSITY"] ?? "standard")}
              />
            </>
          )}
        </RefreshableScrollView>
      </View>
    </View>
  );
}
