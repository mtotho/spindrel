import { useState } from "react";
import { View, Text, Pressable, Switch } from "react-native";
import { useRouter } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import { useCreateChannel } from "@/src/api/hooks/useChannels";
import { Section, FormRow, SelectInput, TextInput } from "@/src/components/shared/FormControls";

export default function NewChannelScreen() {
  const router = useRouter();
  const goBack = useGoBack("/");
  const { data: bots } = useBots();
  const createChannel = useCreateChannel();

  const [name, setName] = useState("");
  const [botId, setBotId] = useState("default");
  const [isPrivate, setIsPrivate] = useState(false);

  const botOptions = (bots ?? []).map((b) => ({ label: b.name, value: b.id }));

  const handleCreate = async () => {
    if (!name.trim()) return;
    try {
      const channel = await createChannel.mutateAsync({
        name: name.trim(),
        bot_id: botId,
        private: isPrivate,
      });
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
          <ArrowLeft size={20} color="#999" />
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
            trackColor={{ false: "#333", true: "#3b82f6" }}
          />
        </View>

        <Pressable
          onPress={handleCreate}
          disabled={!name.trim() || createChannel.isPending}
          style={{
            backgroundColor: name.trim() ? "#3b82f6" : "#333",
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
