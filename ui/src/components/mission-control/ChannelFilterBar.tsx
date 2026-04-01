import { View, Text, Pressable } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { channelColor } from "./botColors";

interface Channel {
  id: string;
  name: string;
}

interface ChannelFilterBarProps {
  channels: Channel[];
  value: string | null;
  onChange: (channelId: string | null) => void;
}

const DROPDOWN_THRESHOLD = 5;

export function ChannelFilterBar({
  channels,
  value,
  onChange,
}: ChannelFilterBarProps) {
  const t = useThemeTokens();

  if (channels.length <= 1) return null;

  if (channels.length > DROPDOWN_THRESHOLD) {
    return (
      <View className="flex-row items-center gap-2">
        <View
          style={{
            width: 1,
            height: 16,
            backgroundColor: t.surfaceBorder,
            marginHorizontal: 4,
          }}
        />
        <View
          style={{
            borderWidth: 1,
            borderColor: value ? t.accent : t.surfaceBorder,
            borderRadius: 8,
            backgroundColor: value ? `${t.accent}15` : "transparent",
            overflow: "hidden",
          }}
        >
          <select
            value={value || ""}
            onChange={(e) => onChange(e.target.value || null)}
            style={{
              fontSize: 12,
              color: value ? t.accent : t.textDim,
              backgroundColor: "transparent",
              border: "none",
              outline: "none",
              padding: "4px 8px",
              cursor: "pointer",
              fontWeight: value ? "500" : "400",
            }}
          >
            <option value="">All channels</option>
            {channels.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.name}
              </option>
            ))}
          </select>
        </View>
      </View>
    );
  }

  // Pills for ≤5 channels
  return (
    <>
      <View
        style={{
          width: 1,
          height: 16,
          backgroundColor: t.surfaceBorder,
          marginHorizontal: 4,
        }}
      />
      <Pressable
        onPress={() => onChange(null)}
        className={`rounded-full px-3 py-1 border ${
          !value ? "border-accent bg-accent/10" : "border-surface-border"
        }`}
      >
        <Text
          className={`text-xs ${
            !value ? "text-accent font-medium" : "text-text-muted"
          }`}
        >
          All
        </Text>
      </Pressable>
      {channels.map((ch) => {
        const active = value === ch.id;
        const cc = channelColor(ch.id);
        return (
          <Pressable
            key={ch.id}
            onPress={() => onChange(active ? null : ch.id)}
            className={`rounded-full px-3 py-1 border flex-row items-center gap-1.5 ${
              active ? "border-accent bg-accent/10" : "border-surface-border"
            }`}
          >
            <View
              style={{
                width: 6,
                height: 6,
                borderRadius: 3,
                backgroundColor: cc,
              }}
            />
            <Text
              className={`text-xs ${
                active ? "text-accent font-medium" : "text-text-muted"
              }`}
            >
              {ch.name}
            </Text>
          </Pressable>
        );
      })}
    </>
  );
}
