import { useState, useMemo, useEffect } from "react";
import { View, Text, Pressable, ScrollView, TextInput as RNTextInput } from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft, ArrowRight, Check, Search } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useBots } from "@/src/api/hooks/useBots";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";
import {
  useCreateChannel,
  useGlobalActivatableIntegrations,
  useChannelCategories,
} from "@/src/api/hooks/useChannels";
import { Section, SelectInput, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { TemplateCardGrid } from "@/src/components/channels/TemplateCardGrid";
import { IntegrationActivationList } from "@/src/components/channels/IntegrationActivationList";

type WizardStep = "basics" | "template" | "integrations";

export default function NewChannelScreen() {
  const router = useRouter();
  const goBack = useGoBack("/");
  const theme = useThemeTokens();
  const params = useLocalSearchParams<{ templateId?: string }>();
  const { data: bots } = useBots();
  const { data: templates } = usePromptTemplates(undefined, "workspace_schema");
  const { data: activatableIntegrations } = useGlobalActivatableIntegrations();
  const { data: existingCategories } = useChannelCategories();
  const createChannel = useCreateChannel();

  // Form state
  const [step, setStep] = useState<WizardStep>("basics");
  const [name, setName] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [useBotMode, setUseBotMode] = useState(false);
  const [botId, setBotId] = useState("default");
  const [category, setCategory] = useState("");
  const [isPrivate, setIsPrivate] = useState(false);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [enabledIntegrations, setEnabledIntegrations] = useState<string[]>([]);
  const [templateFilter, setTemplateFilter] = useState("");

  // Pre-select template from query param (e.g., from home page onboarding)
  useEffect(() => {
    if (params.templateId && templates?.some((tpl) => tpl.id === params.templateId)) {
      setTemplateId(params.templateId);
    }
  }, [params.templateId, templates]);

  const workspaceEnabled = templateId !== null;

  const botOptions = useMemo(
    () => (bots ?? []).map((b) => ({ label: b.name, value: b.id })),
    [bots],
  );

  // Category autocomplete suggestions
  const categorySuggestions = useMemo(() => {
    if (!existingCategories || !category) return [];
    return existingCategories.filter(
      (c) => c.toLowerCase().includes(category.toLowerCase()) && c !== category,
    );
  }, [existingCategories, category]);

  const filteredTemplates = useMemo(() => {
    if (!templates) return [];
    if (!templateFilter.trim()) return templates;
    const q = templateFilter.toLowerCase();
    return templates.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.description ?? "").toLowerCase().includes(q),
    );
  }, [templates, templateFilter]);

  const hasActivatable = (activatableIntegrations?.length ?? 0) > 0;

  const handleToggleIntegration = (intType: string) => {
    setEnabledIntegrations((prev) =>
      prev.includes(intType)
        ? prev.filter((x) => x !== intType)
        : [...prev, intType],
    );
  };

  /** Advance from template step to next step or create */
  const handleTemplateNext = () => {
    if (hasActivatable) {
      setStep("integrations");
    } else {
      handleSubmit();
    }
  };

  /** Build shared request body from common fields */
  const buildBody = () => {
    const body: Parameters<typeof createChannel.mutateAsync>[0] = {
      name: name.trim(),
      bot_id: useBotMode ? botId : "default",
      private: isPrivate,
    };
    if (!useBotMode && selectedModel) {
      body.model_override = selectedModel;
    }
    if (category.trim()) {
      body.category = category.trim();
    }
    return body;
  };

  const handleQuickCreate = async () => {
    if (!name.trim() || createChannel.isPending) return;
    try {
      const channel = await createChannel.mutateAsync(buildBody());
      router.push(`/channels/${channel.id}` as any);
    } catch {
      // mutation error handled by react-query
    }
  };

  const handleSubmit = async () => {
    if (!name.trim() || createChannel.isPending) return;
    try {
      const body = buildBody();
      if (templateId) {
        body.channel_workspace_enabled = true;
        body.workspace_schema_template_id = templateId;
      }
      if (enabledIntegrations.length > 0) {
        body.activate_integrations = enabledIntegrations;
      }
      const channel = await createChannel.mutateAsync(body);
      router.push(`/channels/${channel.id}` as any);
    } catch {
      // mutation error handled by react-query
    }
  };

  const canProceed = name.trim().length > 0;

  const errorBanner = createChannel.isError ? (
    <Text className="text-red-400 text-xs" style={{ marginTop: 8 }}>
      {createChannel.error instanceof Error ? createChannel.error.message : "Failed to create channel"}
    </Text>
  ) : null;

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border">
        <Pressable
          onPress={goBack}
          className="items-center justify-center rounded-md hover:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
        >
          <ArrowLeft size={20} color={theme.textMuted} />
        </Pressable>
        <Text className="text-text font-semibold text-sm flex-1">New Channel</Text>
        {/* Step indicator */}
        <View className="flex-row items-center gap-1.5">
          {(["basics", "template", "integrations"] as WizardStep[])
            .filter((s) => s !== "integrations" || hasActivatable)
            .map((s) => (
              <View
                key={s}
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: step === s ? theme.accent : theme.surfaceBorder,
                }}
              />
            ))}
        </View>
      </View>

      {/* Step 1: Basics */}
      {step === "basics" && (
        <ScrollView
          className="flex-1"
          contentContainerStyle={{ padding: 20, maxWidth: 520 }}
          keyboardShouldPersistTaps="handled"
        >
          <View style={{ gap: 16 }}>
            <Section title="Channel Name">
              <TextInput
                value={name}
                onChangeText={setName}
                placeholder="my-channel"
              />
            </Section>

            {/* Model picker */}
            {!useBotMode && (
              <Section title="Model">
                <LlmModelDropdown
                  value={selectedModel}
                  onChange={(modelId) => setSelectedModel(modelId)}
                  placeholder="Default (from bot)"
                  allowClear
                />
              </Section>
            )}

            {/* Bot mode toggle */}
            <Pressable
              onPress={() => setUseBotMode(!useBotMode)}
              className="flex-row items-center gap-2"
            >
              <Text className="text-text-muted text-xs underline">
                {useBotMode ? "Pick a model instead" : "Or use an existing bot"}
              </Text>
            </Pressable>

            {useBotMode && (
              <Section title="Bot">
                <SelectInput
                  value={botId}
                  onChange={setBotId}
                  options={botOptions}
                />
              </Section>
            )}

            {/* Category */}
            <Section title="Category (optional)">
              <TextInput
                value={category}
                onChangeText={setCategory}
                placeholder="e.g. Work, Personal, Projects"
              />
              {categorySuggestions.length > 0 && (
                <View className="flex-row flex-wrap gap-1.5" style={{ marginTop: 6 }}>
                  {categorySuggestions.slice(0, 5).map((cat) => (
                    <Pressable
                      key={cat}
                      onPress={() => setCategory(cat)}
                      style={{
                        backgroundColor: theme.surfaceBorder,
                        paddingHorizontal: 8,
                        paddingVertical: 3,
                        borderRadius: 4,
                      }}
                    >
                      <Text style={{ fontSize: 11, color: theme.textMuted }}>{cat}</Text>
                    </Pressable>
                  ))}
                </View>
              )}
            </Section>

            <Toggle
              value={isPrivate}
              onChange={setIsPrivate}
              label="Private"
              description="Only visible to you"
            />

            {/* Action buttons */}
            <View style={{ gap: 10, marginTop: 8 }}>
              <Pressable
                onPress={() => canProceed && setStep("template")}
                disabled={!canProceed}
                style={{
                  backgroundColor: canProceed ? theme.accent : theme.surfaceBorder,
                  paddingHorizontal: 20,
                  paddingVertical: 12,
                  borderRadius: 8,
                  alignItems: "center",
                  flexDirection: "row",
                  justifyContent: "center",
                  gap: 8,
                  opacity: canProceed ? 1 : 0.5,
                }}
              >
                <Text style={{ color: canProceed ? "#fff" : theme.textDim, fontSize: 14, fontWeight: "600" }}>
                  Continue
                </Text>
                <ArrowRight size={16} color={canProceed ? "#fff" : theme.textDim} />
              </Pressable>

              <Pressable
                onPress={handleQuickCreate}
                disabled={!canProceed || createChannel.isPending}
                style={{
                  borderWidth: 1,
                  borderColor: theme.surfaceBorder,
                  paddingHorizontal: 20,
                  paddingVertical: 10,
                  borderRadius: 8,
                  alignItems: "center",
                }}
              >
                <Text className="text-text-muted text-sm">
                  {createChannel.isPending ? "Creating..." : "Quick Create (skip wizard)"}
                </Text>
              </Pressable>
            </View>
          </View>
          {errorBanner}
        </ScrollView>
      )}

      {/* Step 2: Template — pinned header + scrollable cards + sticky footer */}
      {step === "template" && (
        <View style={{ flex: 1 }}>
          {/* Fixed header + search */}
          <View style={{ padding: 20, paddingBottom: 12, maxWidth: 520 }}>
            <Text className="text-text font-semibold text-sm">Choose a Template</Text>
            <Text className="text-text-muted text-xs" style={{ marginTop: 4 }}>
              Templates organize your workspace with structured files and schemas.
            </Text>
            {(templates?.length ?? 0) > 4 && (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  backgroundColor: theme.surfaceOverlay,
                  borderWidth: 1,
                  borderColor: theme.surfaceBorder,
                  borderRadius: 6,
                  paddingHorizontal: 8,
                  paddingVertical: 6,
                  marginTop: 12,
                }}
              >
                <Search size={13} color={theme.textDim} />
                <RNTextInput
                  value={templateFilter}
                  onChangeText={setTemplateFilter}
                  placeholder="Search templates..."
                  placeholderTextColor={theme.textDim}
                  style={{ flex: 1, color: theme.text, fontSize: 12 }}
                />
              </View>
            )}
          </View>

          {/* Scrollable template cards */}
          <ScrollView
            style={{ flex: 1 }}
            contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 12, maxWidth: 520 }}
            keyboardShouldPersistTaps="handled"
          >
            <TemplateCardGrid
              templates={filteredTemplates}
              selectedId={templateId}
              onSelect={(id) => setTemplateId(id === templateId ? null : id)}
              highlightIntegrations={enabledIntegrations}
              hideSkip
            />
          </ScrollView>

          {/* Sticky footer */}
          <View
            style={{
              borderTopWidth: 1,
              borderColor: theme.surfaceBorder,
              paddingHorizontal: 20,
              paddingVertical: 14,
              maxWidth: 520,
            }}
          >
            {errorBanner}
            <View style={{ flexDirection: "row", gap: 10 }}>
              <Pressable
                onPress={() => setStep("basics")}
                style={{
                  borderWidth: 1,
                  borderColor: theme.surfaceBorder,
                  paddingHorizontal: 20,
                  paddingVertical: 10,
                  borderRadius: 8,
                  alignItems: "center",
                  flex: 1,
                }}
              >
                <Text className="text-text-muted text-sm">Back</Text>
              </Pressable>

              <Pressable
                onPress={handleTemplateNext}
                disabled={createChannel.isPending}
                style={{
                  backgroundColor: theme.accent,
                  paddingHorizontal: 20,
                  paddingVertical: 12,
                  borderRadius: 8,
                  alignItems: "center",
                  flexDirection: "row",
                  justifyContent: "center",
                  gap: 8,
                  flex: 1,
                }}
              >
                {!hasActivatable && <Check size={16} color="#fff" />}
                <Text style={{ color: "#fff", fontSize: 14, fontWeight: "600" }}>
                  {createChannel.isPending
                    ? "Creating..."
                    : hasActivatable
                      ? templateId ? "Continue" : "Skip — no workspace"
                      : templateId ? "Create Channel" : "Create without workspace"}
                </Text>
                {hasActivatable && <ArrowRight size={16} color="#fff" />}
              </Pressable>
            </View>
          </View>
        </View>
      )}

      {/* Step 3: Integrations — scrollable content + sticky footer */}
      {step === "integrations" && (
        <View style={{ flex: 1 }}>
          <ScrollView
            style={{ flex: 1 }}
            contentContainerStyle={{ padding: 20, maxWidth: 520 }}
            keyboardShouldPersistTaps="handled"
          >
            <View style={{ gap: 16 }}>
              <View>
                <Text className="text-text font-semibold text-sm">Activate Integrations</Text>
                <Text className="text-text-muted text-xs" style={{ marginTop: 4 }}>
                  Integrations inject specialized tools and skills into your channel.
                </Text>
              </View>

              <IntegrationActivationList
                integrations={activatableIntegrations ?? []}
                enabled={enabledIntegrations}
                onToggle={handleToggleIntegration}
                workspaceEnabled={workspaceEnabled}
              />
            </View>
          </ScrollView>

          {/* Sticky footer */}
          <View
            style={{
              borderTopWidth: 1,
              borderColor: theme.surfaceBorder,
              paddingHorizontal: 20,
              paddingVertical: 14,
              maxWidth: 520,
            }}
          >
            {errorBanner}
            <View style={{ flexDirection: "row", gap: 10 }}>
              <Pressable
                onPress={() => setStep("template")}
                style={{
                  borderWidth: 1,
                  borderColor: theme.surfaceBorder,
                  paddingHorizontal: 20,
                  paddingVertical: 10,
                  borderRadius: 8,
                  alignItems: "center",
                  flex: 1,
                }}
              >
                <Text className="text-text-muted text-sm">Back</Text>
              </Pressable>

              <Pressable
                onPress={handleSubmit}
                disabled={createChannel.isPending}
                style={{
                  backgroundColor: theme.accent,
                  paddingHorizontal: 20,
                  paddingVertical: 12,
                  borderRadius: 8,
                  alignItems: "center",
                  flexDirection: "row",
                  justifyContent: "center",
                  gap: 8,
                  flex: 1,
                }}
              >
                <Check size={16} color="#fff" />
                <Text style={{ color: "#fff", fontSize: 14, fontWeight: "600" }}>
                  {createChannel.isPending ? "Creating..." : "Create Channel"}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      )}
    </View>
  );
}
