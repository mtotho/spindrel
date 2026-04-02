import { View, Text } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";

export function FileModeOnlyBanner({
  historyMode,
}: {
  historyMode: string;
}) {
  const t = useThemeTokens();
  const isFileMode = historyMode === "file";

  return (
    <View style={{ marginTop: 8, marginBottom: 4 }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          marginBottom: 4,
        }}
      >
        <Text style={{ fontSize: 13, fontWeight: "600", color: t.text }}>
          Section Index
        </Text>
        <View
          style={{
            backgroundColor: isFileMode
              ? t.accentSubtle
              : "rgba(100,100,100,0.15)",
            paddingHorizontal: 7,
            paddingVertical: 2,
            borderRadius: 4,
          }}
        >
          <Text
            style={{
              fontSize: 9,
              fontWeight: "700",
              color: isFileMode ? t.accent : t.textDim,
            }}
          >
            file mode only
          </Text>
        </View>
      </View>
      {!isFileMode && (
        <Text style={{ fontSize: 11, color: t.textDim, lineHeight: 17 }}>
          These settings only apply when History Mode is "file". Current mode:
          "{historyMode}".
        </Text>
      )}
    </View>
  );
}
