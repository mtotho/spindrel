import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "expo-router";
import { useHashTab } from "@/src/hooks/useHashTab";
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
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, RotateCcw, Check, Sun, Moon, ChevronDown } from "lucide-react";
import { MemorySchemeSection } from "@/src/components/settings/MemorySchemeSection";
import { apiFetch } from "@/src/api/client";
import { useThemeStore } from "@/src/stores/theme";
import { useThemeTokens } from "@/src/theme/tokens";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { type FallbackModelEntry } from "@/src/components/shared/FallbackModelList";
import { Section } from "@/src/components/shared/FormControls";
import {
  useSettings,
  useUpdateSettings,
  useResetSetting,
  SettingItem,
  SettingsGroup,
} from "@/src/api/hooks/useSettings";
import { ServerStatusBar } from "@/src/components/settings/ServerStatusBar";
import { GlobalSection } from "@/src/components/settings/GlobalSection";
import { ModelTiersSection } from "@/src/components/settings/ModelTiersSection";
import { ChatHistoryExtras } from "@/src/components/settings/ChatHistoryExtras";
import { BotOverridesList } from "@/src/components/settings/BotOverridesList";
import { FlushPromptOverrideWarning } from "@/src/components/settings/FlushPromptOverrideWarning";
import { FileModeOnlyBanner } from "@/src/components/settings/FileModeOnlyBanner";
import { MemoryHygieneGroupBanner } from "@/src/components/settings/MemoryHygieneGroupBanner";
import { BackupSection } from "@/src/components/settings/BackupSection";
import { InfoBanner } from "@/src/components/shared/SettingsControls";

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
  const t = useThemeTokens();
  return (
    <Switch
      value={value}
      onValueChange={onChange}
      disabled={item.read_only}
      trackColor={{ false: t.surfaceBorder, true: t.accent }}
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
  const [showBuiltin, setShowBuiltin] = useState(false);

  return (
    <View style={{ width: "100%", gap: 8 }}>
      <TextInput
        className="bg-surface border border-surface-border rounded px-3 py-3 text-text text-sm"
        value={value}
        onChangeText={onChange}
        editable={!item.read_only}
        placeholder={item.builtin_default ? "(using built-in default)" : "(empty)"}
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
      {item.builtin_default && !value && (
        <View
          className="bg-surface border border-surface-border rounded overflow-hidden"
        >
          <Pressable
            onPress={() => setShowBuiltin(!showBuiltin)}
            className="flex-row items-center gap-2 px-3 py-2"
          >
            <ChevronDown
              size={12}
              color="#9ca3af"
              style={{ transform: showBuiltin ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
            />
            <Text className="text-text-muted text-xs font-semibold">
              Built-in Default
            </Text>
            <View className="bg-purple-500/20 px-1.5 py-0.5 rounded">
              <Text className="text-purple-400 text-[9px] font-medium">
                active
              </Text>
            </View>
          </Pressable>
          {showBuiltin && (
            <View className="px-3 pb-3">
              <View className="bg-surface-overlay rounded p-3">
                <Text
                  className="text-text-muted text-[11px]"
                  style={{
                    fontFamily: "monospace",
                    lineHeight: 18,
                    // @ts-ignore — web-only
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {item.builtin_default}
                </Text>
              </View>
            </View>
          )}
        </View>
      )}
    </View>
  );
}

function ModelField({
  item,
  value,
  selectedProviderId,
  onChange,
}: {
  item: SettingItem;
  value: string;
  selectedProviderId?: string;
  onChange: (model: string, providerId?: string | null) => void;
}) {
  return (
    <View style={{ maxWidth: 400 }}>
      <LlmModelDropdown
        value={value}
        selectedProviderId={selectedProviderId}
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
  providerValue,
  onLocalChange,
  onReset,
  isResetting,
}: {
  item: SettingItem;
  localValue: any;
  providerValue?: string;
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
      // Derive the paired provider_id key (e.g. COMPACTION_MODEL → COMPACTION_MODEL_PROVIDER_ID)
      // Special cases for legacy naming without _MODEL_ in the provider key
      const providerKey = item.key === "IMAGE_GENERATION_MODEL"
        ? "IMAGE_GENERATION_PROVIDER_ID"
        : item.key === "CONTEXTUAL_RETRIEVAL_MODEL"
        ? "CONTEXTUAL_RETRIEVAL_PROVIDER_ID"
        : item.key + "_PROVIDER_ID";
      return (
        <ModelField
          item={item}
          value={String(localValue ?? "")}
          selectedProviderId={providerValue}
          onChange={(model, pid) => {
            onLocalChange(item.key, model);
            onLocalChange(providerKey, pid ?? "");
          }}
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
// Display name mapping (rebrand without changing backend keys)
// ---------------------------------------------------------------------------
const GROUP_DISPLAY_NAMES: Record<string, string> = {
  "Memory Hygiene": "Dreaming",
};
function groupDisplayName(key: string) {
  return GROUP_DISPLAY_NAMES[key] ?? key;
}

// ---------------------------------------------------------------------------
// Pointer to Learning Center > Dreaming (replaces the old DreamingBotList).
// Per-bot toggles + run history live in /admin/learning#Dreaming so there's
// only one place to manage dreaming.
// ---------------------------------------------------------------------------
function DreamingLearningCenterPointer() {
  const t = useThemeTokens();
  const router = useRouter();
  return (
    <div style={{ marginTop: 20 }}>
      <InfoBanner
        variant="info"
        icon={<Moon size={14} color={t.purple} />}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
            Manage per-bot dreaming in the Learning Center
          </span>
          <span style={{ fontSize: 11, color: t.textMuted, lineHeight: "17px" }}>
            Toggle dreaming per bot, trigger runs on demand, and review the
            full run history with skipped/failed details.
          </span>
          <button
            onClick={() => router.push("/admin/learning#Dreaming" as any)}
            style={{
              alignSelf: "flex-start",
              marginTop: 4,
              padding: "5px 12px",
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 500,
              cursor: "pointer",
              background: t.purpleSubtle,
              color: t.purple,
              border: `1px solid ${t.purpleBorder}`,
            }}
          >
            Open Learning Center → Dreaming
          </button>
        </div>
      </InfoBanner>
    </div>
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
            {groupDisplayName(g.group)}
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
// Appearance section
// ---------------------------------------------------------------------------

const GLOBAL_GROUP = "Global";
const BACKUP_GROUP = "Backup";

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
          trackColor={{ false: t.surfaceBorder, true: t.accent }}
          thumbColor="#fff"
        />
      </View>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Settings screen
// ---------------------------------------------------------------------------

export default function SettingsScreen() {
  const t = useThemeTokens();
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
    () => [
      { group: GLOBAL_GROUP, settings: [] as SettingItem[] },
      ...groups,
      { group: BACKUP_GROUP, settings: [] as SettingItem[] },
    ],
    [groups]
  );
  const groupNames = useMemo(() => allGroups.map((g) => g.group), [allGroups]);
  const [activeGroup, setActiveGroup] = useHashTab<string>(GLOBAL_GROUP, groupNames);
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
      // Also reset the paired provider_id when resetting a model setting
      const item = groups.flatMap((g) => g.settings).find((s) => s.key === key);
      if (item?.widget === "model") {
        const providerKey = key === "IMAGE_GENERATION_MODEL"
          ? "IMAGE_GENERATION_PROVIDER_ID"
          : key === "CONTEXTUAL_RETRIEVAL_MODEL"
          ? "CONTEXTUAL_RETRIEVAL_PROVIDER_ID"
          : key + "_PROVIDER_ID";
        resetMutation.mutate(providerKey);
      }
      resetMutation.mutate(key, {
        onSettled: () => setResettingKey(null),
      });
    },
    [resetMutation, groups]
  );

  const isGlobal = activeGroup === GLOBAL_GROUP;
  const isBackup = activeGroup === BACKUP_GROUP;
  const activeSettings = groups.find((g) => g.group === activeGroup)?.settings ?? [];

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator size="large" color={t.accent} />
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

      {/* Server Status Bar */}
      <View style={{ paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4 }}>
        <ServerStatusBar />
      </View>

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
                    {groupDisplayName(g.group)}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          )}

          {/* Group title */}
          <Text className="text-text font-semibold text-lg mb-2">
            {groupDisplayName(activeGroup)}
          </Text>

          {/* Appearance section — shown in Global group */}
          {isGlobal && <AppearanceSection />}

          {/* Global section (fallback models + config state link) */}
          {isGlobal && (
            <>
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
              <ModelTiersSection />
            </>
          )}

          {/* Backup section */}
          {isBackup && <BackupSection />}

          {/* Settings */}
          {!isGlobal && !isBackup && activeSettings.filter((s: any) => !s.ui_hidden).map((item, idx) => {
            const FILE_MODE_KEYS = new Set(["SECTION_INDEX_COUNT", "SECTION_INDEX_VERBOSITY"]);
            const historyMode = String(localValues["DEFAULT_HISTORY_MODE"] ?? "file");
            const isFileModeOnly = FILE_MODE_KEYS.has(item.key);
            const dimmed = isFileModeOnly && historyMode !== "file";

            return (
              <View key={item.key} style={dimmed ? { opacity: 0.4 } : undefined}>
                {idx > 0 && <View className="h-px bg-surface-border" />}
                {item.key === "MEMORY_FLUSH_DEFAULT_PROMPT" && <FlushPromptOverrideWarning />}
                {item.key === "MEMORY_HYGIENE_ENABLED" && <MemoryHygieneGroupBanner />}
                {item.key === "SECTION_INDEX_COUNT" && (
                  <FileModeOnlyBanner historyMode={historyMode} />
                )}
                <SettingRow
                  item={item}
                  localValue={localValues[item.key]}
                  providerValue={item.widget === "model" ? String(localValues[
                    item.key === "IMAGE_GENERATION_MODEL"
                      ? "IMAGE_GENERATION_PROVIDER_ID"
                      : item.key === "CONTEXTUAL_RETRIEVAL_MODEL"
                      ? "CONTEXTUAL_RETRIEVAL_PROVIDER_ID"
                      : item.key + "_PROVIDER_ID"
                  ] ?? "") : undefined}
                  onLocalChange={handleLocalChange}
                  onReset={handleReset}
                  isResetting={resettingKey === item.key}
                />
              </View>
            );
          })}

          {/* Dreaming: memory scheme defaults + pointer to Learning Center.
              Per-bot toggles + run history live in Learning Center > Dreaming
              (single canonical management surface). */}
          {activeGroup === "Memory Hygiene" && (
            <>
              <MemorySchemeSection />
              <DreamingLearningCenterPointer />
            </>
          )}

          {/* Bot overrides for Attachments / Model Elevation */}
          {(activeGroup === "Attachments" || activeGroup === "Model Elevation") && (
            <BotOverridesList group={activeGroup} />
          )}

          {/* Chat History extras: section index preview + deviations (file mode only) */}
          {activeGroup === "Chat History" && (
            <>
              {String(localValues["DEFAULT_HISTORY_MODE"] ?? "file") === "file" && (
                <ChatHistoryExtras
                  verbosity={String(localValues["SECTION_INDEX_VERBOSITY"] ?? "standard")}
                />
              )}
            </>
          )}
        </RefreshableScrollView>
      </View>
    </View>
  );
}
