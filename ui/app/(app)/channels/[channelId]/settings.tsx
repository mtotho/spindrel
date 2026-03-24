import { useCallback, useState, useEffect } from "react";
import { View, Text, Pressable, ScrollView, Switch } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { ArrowLeft, Check } from "lucide-react";
import {
  useChannelSettings,
  useUpdateChannelSettings,
  useChannel,
} from "@/src/api/hooks/useChannels";
import { useBot } from "@/src/api/hooks/useBots";
import { useBots } from "@/src/api/hooks/useBots";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import type { ChannelSettings } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Tiny form helpers
// ---------------------------------------------------------------------------

function Section({ title, description, children }: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <View className="bg-surface-raised border border-surface-border rounded-lg p-4 gap-3">
      <View>
        <Text className="text-text text-sm font-semibold">{title}</Text>
        {description && (
          <Text className="text-text-dim text-xs mt-0.5">{description}</Text>
        )}
      </View>
      {children}
    </View>
  );
}

function FormRow({ label, description, children }: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <View className="gap-1">
      <Text className="text-text-dim text-xs">{label}</Text>
      {children}
      {description && (
        <Text className="text-text-dim/70 text-[10px]">{description}</Text>
      )}
    </View>
  );
}

function TextInput({ value, onChangeText, placeholder, type = "text" }: {
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e: any) => onChangeText(e.target?.value ?? "")}
      placeholder={placeholder}
      style={{
        background: "#111111",
        border: "1px solid #333333",
        borderRadius: 8,
        padding: "6px 12px",
        color: "#e5e5e5",
        fontSize: 13,
        width: "100%",
        outline: "none",
      }}
    />
  );
}

function Toggle({ value, onChange, label, description }: {
  value: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
}) {
  return (
    <Pressable
      onPress={() => onChange(!value)}
      className="flex-row items-start gap-3 py-1"
    >
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ false: "#333333", true: "#3b82f6" }}
        thumbColor="#e5e5e5"
        style={{ transform: [{ scale: 0.75 }] }}
      />
      <View className="flex-1">
        <Text className="text-text text-xs">{label}</Text>
        {description && (
          <Text className="text-text-dim text-[10px]">{description}</Text>
        )}
      </View>
    </Pressable>
  );
}

function SelectInput({ value, onChange, options }: {
  value: string;
  onChange: (v: string) => void;
  options: { label: string; value: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e: any) => onChange(e.target?.value ?? "")}
      style={{
        background: "#111111",
        border: "1px solid #333333",
        borderRadius: 8,
        padding: "6px 12px",
        color: "#e5e5e5",
        fontSize: 13,
        width: "100%",
        outline: "none",
      }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Main settings screen
// ---------------------------------------------------------------------------

export default function ChannelSettingsScreen() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const router = useRouter();
  const { data: channel } = useChannel(channelId);
  const { data: bot } = useBot(channel?.bot_id);
  const { data: settings, isLoading } = useChannelSettings(channelId);
  const { data: bots } = useBots();
  const updateMutation = useUpdateChannelSettings(channelId!);

  // Local form state (initialized from server)
  const [form, setForm] = useState<Partial<ChannelSettings>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setForm({
        name: settings.name,
        bot_id: settings.bot_id,
        require_mention: settings.require_mention,
        passive_memory: settings.passive_memory,
        workspace_rag: settings.workspace_rag,
        context_compaction: settings.context_compaction,
        compaction_interval: settings.compaction_interval,
        compaction_keep_turns: settings.compaction_keep_turns,
        memory_knowledge_compaction_prompt: settings.memory_knowledge_compaction_prompt,
        context_compression: settings.context_compression,
        compression_model: settings.compression_model,
        compression_threshold: settings.compression_threshold,
        compression_keep_turns: settings.compression_keep_turns,
        elevation_enabled: settings.elevation_enabled,
        elevation_threshold: settings.elevation_threshold,
        elevated_model: settings.elevated_model,
      });
    }
  }, [settings]);

  const patch = useCallback(
    <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => {
      setForm((f) => ({ ...f, [key]: value }));
      setSaved(false);
    },
    []
  );

  const handleSave = useCallback(async () => {
    await updateMutation.mutateAsync(form);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }, [form, updateMutation]);

  if (isLoading || !settings) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <Text className="text-text-dim text-sm">Loading settings...</Text>
      </View>
    );
  }

  const triStateValue = (v: boolean | undefined | null): string =>
    v === true ? "true" : v === false ? "false" : "";
  const triStateOptions = [
    { label: "Inherit (default)", value: "" },
    { label: "Enabled", value: "true" },
    { label: "Disabled", value: "false" },
  ];

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border">
        <Pressable onPress={() => router.back()} className="p-1">
          <ArrowLeft size={18} color="#999999" />
        </Pressable>
        <View className="flex-1 min-w-0">
          <Text className="text-text font-semibold text-sm" numberOfLines={1}>
            Channel Settings
          </Text>
          <Text className="text-text-dim text-xs" numberOfLines={1}>
            {(channel as any)?.display_name || channel?.name || channel?.client_id}
          </Text>
        </View>
        <Pressable
          onPress={handleSave}
          disabled={updateMutation.isPending}
          className={`flex-row items-center gap-1.5 px-3 py-1.5 rounded-lg ${
            saved ? "bg-green-600/20" : "bg-accent hover:bg-accent-hover"
          }`}
        >
          {saved ? (
            <>
              <Check size={14} color="#22c55e" />
              <Text className="text-green-400 text-xs font-medium">Saved</Text>
            </>
          ) : (
            <Text className="text-white text-xs font-medium">
              {updateMutation.isPending ? "Saving..." : "Save"}
            </Text>
          )}
        </Pressable>
      </View>

      <ScrollView className="flex-1" contentContainerStyle={{ padding: 16, gap: 16, maxWidth: 640 }}>
        {/* Basic Settings */}
        <Section title="General">
          <View className="gap-3">
            <FormRow label="Display Name" description="Label shown in sidebar. Does not affect routing.">
              <TextInput
                value={form.name ?? ""}
                onChangeText={(v) => patch("name", v)}
                placeholder="Channel name"
              />
            </FormRow>
            <FormRow label="Bot">
              <SelectInput
                value={form.bot_id ?? ""}
                onChange={(v) => patch("bot_id", v)}
                options={
                  bots?.map((b) => ({ label: `${b.name} (${b.id})`, value: b.id })) ?? []
                }
              />
            </FormRow>
          </View>
        </Section>

        {/* Behavior */}
        <Section title="Behavior">
          <Toggle
            value={form.require_mention ?? true}
            onChange={(v) => patch("require_mention", v)}
            label="Require @mention"
            description="Only @mentions trigger the bot; other messages stored as context."
          />
          <Toggle
            value={form.passive_memory ?? true}
            onChange={(v) => patch("passive_memory", v)}
            label="Passive memory"
            description="Include passive messages in memory compaction."
          />
          <Toggle
            value={form.workspace_rag ?? true}
            onChange={(v) => patch("workspace_rag", v)}
            label="Workspace RAG"
            description="Auto-inject relevant workspace files into context each turn."
          />
        </Section>

        {/* Compaction */}
        <Section
          title="Compaction"
          description="Auto-summarizes old turns so the context window never fills up."
        >
          <Toggle
            value={form.context_compaction ?? true}
            onChange={(v) => patch("context_compaction", v)}
            label="Enable auto-compaction"
          />
          {form.context_compaction && (
            <View className="gap-3 mt-1">
              <View className="flex-row gap-3">
                <View className="flex-1">
                  <FormRow label="Interval (user turns)">
                    <TextInput
                      value={form.compaction_interval?.toString() ?? ""}
                      onChangeText={(v) => patch("compaction_interval", v ? parseInt(v) || undefined : undefined)}
                      placeholder="default"
                      type="number"
                    />
                  </FormRow>
                </View>
                <View className="flex-1">
                  <FormRow label="Keep Turns">
                    <TextInput
                      value={form.compaction_keep_turns?.toString() ?? ""}
                      onChangeText={(v) => patch("compaction_keep_turns", v ? parseInt(v) || undefined : undefined)}
                      placeholder="default"
                      type="number"
                    />
                  </FormRow>
                </View>
              </View>
              <LlmPrompt
                value={form.memory_knowledge_compaction_prompt ?? ""}
                onChange={(v) => patch("memory_knowledge_compaction_prompt", v || undefined)}
                label="Memory/Knowledge Compaction Prompt"
                placeholder="Leave blank to use the global default prompt..."
                helpText="Given to the bot before summarization. Tags like @tool:save_memory auto-pin those tools during the memory phase."
                rows={4}
              />
            </View>
          )}
        </Section>

        {/* Context Compression */}
        <Section
          title="Context Compression"
          description="Summarises old turns via a cheap model before each LLM call. Leave blank to inherit."
        >
          <View className="gap-3">
            <View className="flex-row gap-3">
              <View className="flex-1">
                <FormRow label="Enable Compression">
                  <SelectInput
                    value={triStateValue(form.context_compression)}
                    onChange={(v) =>
                      patch("context_compression", v === "true" ? true : v === "false" ? false : undefined)
                    }
                    options={triStateOptions}
                  />
                </FormRow>
              </View>
              <View className="flex-1">
                <LlmModelDropdown
                  label="Compression Model"
                  value={form.compression_model ?? ""}
                  onChange={(v) => patch("compression_model", v || undefined)}
                  placeholder="inherit"
                />
              </View>
            </View>
            <View className="flex-row gap-3">
              <View className="flex-1">
                <FormRow label="Trigger Threshold (chars)">
                  <TextInput
                    value={form.compression_threshold?.toString() ?? ""}
                    onChangeText={(v) => patch("compression_threshold", v ? parseInt(v) || undefined : undefined)}
                    placeholder="inherit (20000)"
                    type="number"
                  />
                </FormRow>
              </View>
              <View className="flex-1">
                <FormRow label="Keep Turns (verbatim)">
                  <TextInput
                    value={form.compression_keep_turns?.toString() ?? ""}
                    onChangeText={(v) => patch("compression_keep_turns", v ? parseInt(v) || undefined : undefined)}
                    placeholder="inherit (2)"
                    type="number"
                  />
                </FormRow>
              </View>
            </View>
          </View>
        </Section>

        {/* Model Elevation */}
        <Section
          title="Model Elevation"
          description="Per-channel elevation overrides. Leave blank to inherit from global settings."
        >
          <View className="gap-3">
            <View className="flex-row gap-3">
              <View className="flex-1">
                <FormRow label="Enable Elevation">
                  <SelectInput
                    value={triStateValue(form.elevation_enabled)}
                    onChange={(v) =>
                      patch("elevation_enabled", v === "true" ? true : v === "false" ? false : undefined)
                    }
                    options={triStateOptions}
                  />
                </FormRow>
              </View>
              <View className="flex-1">
                <FormRow label="Threshold (0.0–1.0)">
                  <TextInput
                    value={form.elevation_threshold?.toString() ?? ""}
                    onChangeText={(v) => patch("elevation_threshold", v ? parseFloat(v) || undefined : undefined)}
                    placeholder="inherit"
                    type="number"
                  />
                </FormRow>
              </View>
            </View>
            <LlmModelDropdown
              label="Elevated Model"
              value={form.elevated_model ?? ""}
              onChange={(v) => patch("elevated_model", v || undefined)}
              placeholder="inherit"
            />
          </View>
        </Section>

        {/* Metadata */}
        <View className="opacity-50 gap-1 pb-4">
          <Text className="text-text-dim text-[10px]">
            ID: {settings.id}
          </Text>
          {settings.client_id && (
            <Text className="text-text-dim text-[10px]">
              client_id: {settings.client_id}
            </Text>
          )}
          {settings.integration && (
            <Text className="text-text-dim text-[10px]">
              integration: {settings.integration}
            </Text>
          )}
        </View>
      </ScrollView>
    </View>
  );
}
