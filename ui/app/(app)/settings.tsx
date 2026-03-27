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
import { Save, RotateCcw, Check } from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
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
      className="bg-surface border border-surface-border rounded px-3 py-3 text-text text-sm flex-1"
      value={value}
      onChangeText={onChange}
      editable={!item.read_only}
      placeholder="(empty)"
      placeholderTextColor="#666666"
      multiline
      numberOfLines={12}
      style={{
        minHeight: 200,
        textAlignVertical: "top",
        fontFamily: "monospace",
        lineHeight: 20,
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
// Settings screen
// ---------------------------------------------------------------------------

export default function SettingsScreen() {
  const { data, isLoading, error } = useSettings();
  const updateMutation = useUpdateSettings();
  const resetMutation = useResetSetting();
  const { width } = useWindowDimensions();
  const isDesktop = width >= 768;

  const groups = data?.groups ?? [];
  const [activeGroup, setActiveGroup] = useState<string>("");
  const [localValues, setLocalValues] = useState<Record<string, any>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);
  const [resettingKey, setResettingKey] = useState<string | null>(null);

  // Initialize local values from server data
  useEffect(() => {
    if (!groups.length) return;
    if (!activeGroup) setActiveGroup(groups[0].group);
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
              groups={groups}
              activeGroup={activeGroup}
              onSelect={setActiveGroup}
            />
          </View>
        )}

        <ScrollView className="flex-1 p-4" contentContainerStyle={{ maxWidth: 640 }}>
          {/* Mobile group selector */}
          {!isDesktop && (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              className="mb-4"
              contentContainerStyle={{ gap: 6 }}
            >
              {groups.map((g) => (
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

          {/* Settings */}
          {activeSettings.map((item, idx) => (
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
        </ScrollView>
      </View>
    </View>
  );
}
