import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useHashTab } from "@/src/hooks/useHashTab";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, RotateCcw, Check, Sun, Moon, ChevronDown } from "lucide-react";
import { MemorySchemeSection } from "@/src/components/settings/MemorySchemeSection";
import { apiFetch } from "@/src/api/client";
import { useThemeStore } from "@/src/stores/theme";
import { useThemeTokens } from "@/src/theme/tokens";
import { PageHeader } from "@/src/components/layout/PageHeader";
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
    <input
      type="checkbox"
      checked={value}
      onChange={(e) => onChange(e.target.checked)}
      disabled={item.read_only}
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
    <div className="flex flex-row flex-wrap gap-1.5">
      {item.options!.map((opt) => (
        <button
          type="button"
          key={opt}
          onClick={() => !item.read_only && onChange(opt)}
          className={`px-3 py-1.5 rounded border ${
            value === opt
              ? "bg-accent/20 border-accent"
              : "bg-surface border-surface-border"
          }`}
        >
          <span
            className={`text-xs ${
              value === opt ? "text-accent font-medium" : "text-text-muted"
            }`}
          >
            {opt}
          </span>
        </button>
      ))}
    </div>
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
    <input
      className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm"
      style={{ maxWidth: 200 }}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      readOnly={item.read_only}
      type="number"
      placeholder={item.nullable ? "(none)" : undefined}
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
    <input
      className="bg-surface border border-surface-border rounded px-3 py-2 text-text text-sm flex-1"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      readOnly={item.read_only}
      placeholder="(empty)"
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
    <div style={{ display: "flex", width: "100%", gap: 8 }}>
      <textarea
        className="bg-surface border border-surface-border rounded px-3 py-3 text-text text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        readOnly={item.read_only}
        placeholder={item.builtin_default ? "(using built-in default)" : "(empty)"}
        rows={16}
        style={{
          minHeight: 300,
          width: "100%",
          fontFamily: "monospace",
          lineHeight: "20px",
          resize: "vertical",
        }}
      />
      {item.builtin_default && !value && (
        <div
          className="bg-surface border border-surface-border rounded overflow-hidden"
        >
          <button
            type="button"
            onClick={() => setShowBuiltin(!showBuiltin)}
            className="flex flex-row items-center gap-2 px-3 py-2"
          >
            <ChevronDown
              size={12}
              color="#9ca3af"
              style={{ transform: showBuiltin ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
            />
            <span className="text-text-muted text-xs font-semibold">
              Built-in Default
            </span>
            <div className="bg-purple-500/20 px-1.5 py-0.5 rounded">
              <span className="text-purple-400 text-[9px] font-medium">
                active
              </span>
            </div>
          </button>
          {showBuiltin && (
            <div className="px-3 pb-3">
              <div className="bg-surface-overlay rounded p-3">
                <span
                  className="text-text-muted text-[11px]"
                  style={{
                    fontFamily: "monospace",
                    lineHeight: "18px",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {item.builtin_default}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
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
    <div style={{ maxWidth: 400 }}>
      <LlmModelDropdown
        value={value}
        selectedProviderId={selectedProviderId}
        onChange={onChange}
        placeholder="Select model..."
        allowClear
      />
    </div>
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
    <div style={{ maxWidth: 400 }}>
      <LlmModelDropdown
        value={value}
        onChange={onChange}
        placeholder="Select embedding model..."
        allowClear
        variant="embedding"
      />
    </div>
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
    <div className="flex py-3 gap-2">
      <div className="flex flex-row items-center gap-2 flex-wrap">
        <span className="text-text text-sm font-medium">{item.label}</span>
        {item.overridden && (
          <div className="bg-accent/20 px-1.5 py-0.5 rounded">
            <span className="text-accent text-[10px] font-medium">overridden</span>
          </div>
        )}
        {item.read_only && (
          <div className="bg-surface-overlay px-1.5 py-0.5 rounded">
            <span className="text-text-dim text-[10px]">read-only</span>
          </div>
        )}
      </div>
      <span className="text-text-dim text-xs">{item.description}</span>
      <div className="flex flex-row items-center gap-2">
        {renderField()}
        {item.overridden && !item.read_only && (
          <button
            type="button"
            onClick={() => onReset(item.key)}
            disabled={isResetting}
            className="flex flex-row items-center gap-1 px-2 py-1.5 rounded border border-surface-border hover:bg-surface-overlay"
          >
            {isResetting ? (
              <Spinner size={16} color="#9ca3af" />
            ) : (
              <RotateCcw size={12} color="#9ca3af" />
            )}
            <span className="text-text-muted text-xs">Reset</span>
          </button>
        )}
      </div>
    </div>
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
  const navigate = useNavigate();
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
            onClick={() => navigate("/admin/learning#Dreaming")}
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
    <div className="flex flex-col gap-0.5">
      {groups.map((g) => (
        <button
          type="button"
          key={g.group}
          onClick={() => onSelect(g.group)}
          className={`text-left px-3 py-2 rounded ${
            activeGroup === g.group ? "bg-accent/15" : "hover:bg-surface-overlay"
          }`}
        >
          <span
            className={`text-sm ${
              activeGroup === g.group
                ? "text-accent font-medium"
                : "text-text-muted"
            }`}
          >
            {groupDisplayName(g.group)}
          </span>
        </button>
      ))}
    </div>
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
      <div
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 4px",
          display: "flex",
        }}
      >
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
          {mode === "dark" ? (
            <Moon size={18} color={t.textMuted} />
          ) : (
            <Sun size={18} color={t.textMuted} />
          )}
          <span className="text-text text-sm">
            {mode === "dark" ? "Dark mode" : "Light mode"}
          </span>
        </div>
        <input
          type="checkbox"
          checked={mode === "dark"}
          onChange={toggle}
        />
      </div>
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
  const { width } = useWindowSize();
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
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner size={32} color={t.accent} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center p-4">
        <span className="text-red-400 text-sm">
          Failed to load settings: {error instanceof Error ? error.message : "Unknown error"}
        </span>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Settings"
        right={
          <div className="flex flex-row items-center gap-2">
            {saved && (
              <div className="flex flex-row items-center gap-1">
                <Check size={14} color="#22c55e" />
                <span className="text-green-400 text-xs">Saved</span>
              </div>
            )}
            {changedKeys.length > 0 && (
              <button
                type="button"
                onClick={handleSave}
                disabled={updateMutation.isPending}
                className="flex bg-accent rounded px-3 py-1.5 flex-row items-center gap-1.5"
              >
                {updateMutation.isPending ? (
                  <Spinner size={16} color="#fff" />
                ) : (
                  <Save size={14} color="#fff" />
                )}
                <span className="text-white text-sm font-medium">Save</span>
              </button>
            )}
          </div>
        }
      />

      {/* Server Status Bar */}
      <div style={{ padding: "12px 16px 4px 16px" }}>
        <ServerStatusBar />
      </div>

      <div className="flex flex-1 flex-row">
        {/* Desktop group nav */}
        {isDesktop && (
          <div
            className="border-r border-surface-border p-3"
            style={{ width: 200 }}
          >
            <GroupNav
              groups={allGroups}
              activeGroup={activeGroup}
              onSelect={setActiveGroup}
            />
          </div>
        )}

        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1 p-4" contentContainerStyle={{ maxWidth: 640 }}>
          {/* Mobile group selector */}
          {!isDesktop && (
            <div
              className="mb-4 overflow-auto"
              style={{ display: "flex", flexDirection: "row", gap: 6 }}
            >
              {allGroups.map((g) => (
                <button
                  type="button"
                  key={g.group}
                  onClick={() => setActiveGroup(g.group)}
                  className={`px-3 py-1.5 rounded-full border ${
                    activeGroup === g.group
                      ? "bg-accent/20 border-accent"
                      : "border-surface-border"
                  }`}
                >
                  <span
                    className={`text-xs ${
                      activeGroup === g.group
                        ? "text-accent font-medium"
                        : "text-text-muted"
                    }`}
                  >
                    {groupDisplayName(g.group)}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Group title */}
          <span className="text-text font-semibold text-lg mb-2">
            {groupDisplayName(activeGroup)}
          </span>

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
              <div key={item.key} style={dimmed ? { opacity: 0.4 } : undefined}>
                {idx > 0 && <div className="h-px bg-surface-border" />}
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
              </div>
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
      </div>
    </div>
  );
}
