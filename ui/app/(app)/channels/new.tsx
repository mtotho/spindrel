import { useState } from "react";
import { View, Text, Pressable, Switch } from "react-native";
import { useRouter } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useBots } from "@/src/api/hooks/useBots";
import {
  useCreateChannel,
  useAvailableIntegrations,
  useBindIntegration,
} from "@/src/api/hooks/useChannels";
import { Section, FormRow, SelectInput, TextInput } from "@/src/components/shared/FormControls";

export default function NewChannelScreen() {
  const router = useRouter();
  const goBack = useGoBack("/");
  const t = useThemeTokens();
  const { data: bots } = useBots();
  const createChannel = useCreateChannel();
  const { data: availableIntegrations } = useAvailableIntegrations();

  const [name, setName] = useState("");
  const [botId, setBotId] = useState("default");
  const [isPrivate, setIsPrivate] = useState(false);

  // Integration binding (optional)
  const [integrationType, setIntegrationType] = useState("");
  const [integrationClientId, setIntegrationClientId] = useState("");
  const [integrationDisplayName, setIntegrationDisplayName] = useState("");

  const botOptions = (bots ?? []).map((b) => ({ label: b.name, value: b.id }));
  const integrationOptions = [
    { label: "None", value: "" },
    ...(availableIntegrations ?? []).map((i) => ({ label: i.type, value: i.type })),
  ];

  const selectedIntegration = (availableIntegrations ?? []).find(
    (i) => i.type === integrationType
  );
  const binding = selectedIntegration?.binding;

  const handleIntegrationTypeChange = (newType: string) => {
    setIntegrationType(newType);
    setIntegrationClientId("");
    setIntegrationDisplayName("");
  };

  // We need the channelId to bind, so we use a ref to the bind mutation
  // after create. But useBindIntegration needs channelId upfront.
  // Instead, just pass integration/client_id to the create API.
  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      const channel = await createChannel.mutateAsync({
        name: name.trim(),
        bot_id: botId,
        private: isPrivate,
      });

      // If integration selected, bind it after creation
      if (integrationType && integrationClientId.trim()) {
        try {
          const { apiFetch } = await import("@/src/api/client");
          await apiFetch(`/api/v1/channels/${channel.id}/integrations`, {
            method: "POST",
            body: JSON.stringify({
              integration_type: integrationType,
              client_id: integrationClientId.trim(),
              display_name: integrationDisplayName.trim() || undefined,
            }),
          });
        } catch {
          // Channel created but binding failed — user can add it later
        }
      }

      router.push(`/channels/${channel.id}` as any);
    } catch {
      // mutation error handled by react-query
    }
  };

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="flex-row items-center gap-3 px-4 py-3 border-b border-surface-border">
        <Pressable
          onPress={goBack}
          className="items-center justify-center rounded-md hover:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
        >
          <ArrowLeft size={20} color={t.textMuted} />
        </Pressable>
        <Text className="text-text font-semibold text-sm">New Channel</Text>
      </View>

      {/* Form */}
      <View style={{ padding: 20, gap: 16, maxWidth: 480 }}>
        <Section title="Channel Name">
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="my-channel"
          />
        </Section>

        <Section title="Bot">
          <SelectInput
            value={botId}
            onChange={setBotId}
            options={botOptions}
          />
        </Section>

        <View className="flex-row items-center justify-between">
          <View>
            <Text className="text-text text-sm font-medium">Private</Text>
            <Text className="text-text-muted text-xs">Only visible to you</Text>
          </View>
          <Switch
            value={isPrivate}
            onValueChange={setIsPrivate}
            trackColor={{ false: t.surfaceBorder, true: t.accent }}
          />
        </View>

        {/* Integration binding */}
        <Section title="Integration (optional)" description="Bind an external integration to this channel">
          <View className="gap-3">
            <FormRow label="Type">
              <SelectInput
                value={integrationType}
                onChange={handleIntegrationTypeChange}
                options={integrationOptions}
              />
            </FormRow>
            {integrationType !== "" && (
              <>
                <FormRow
                  label="Client ID"
                  description={binding?.client_id_description}
                >
                  <TextInput
                    value={integrationClientId}
                    onChangeText={setIntegrationClientId}
                    placeholder={binding?.client_id_placeholder ?? `${integrationType}:...`}
                  />
                </FormRow>
                <FormRow label="Display Name (optional)">
                  <TextInput
                    value={integrationDisplayName}
                    onChangeText={setIntegrationDisplayName}
                    placeholder={binding?.display_name_placeholder ?? ""}
                  />
                </FormRow>
              </>
            )}
          </View>
        </Section>

        <Pressable
          onPress={handleCreate}
          disabled={!name.trim() || createChannel.isPending}
          style={{
            backgroundColor: name.trim() ? t.accent : t.surfaceBorder,
            paddingHorizontal: 20,
            paddingVertical: 10,
            borderRadius: 8,
            alignItems: "center",
            marginTop: 8,
          }}
        >
          <Text style={{ color: "#fff", fontSize: 14, fontWeight: "600" }}>
            {createChannel.isPending ? "Creating..." : "Create Channel"}
          </Text>
        </Pressable>

        {createChannel.isError && (
          <Text className="text-red-400 text-xs">
            {createChannel.error instanceof Error ? createChannel.error.message : "Failed to create channel"}
          </Text>
        )}
      </View>
    </View>
  );
}
