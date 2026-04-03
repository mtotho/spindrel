import { useEffect } from "react";
import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { Shield } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

export function ErrorBanner({ error, onDismiss, onRetry }: { error: string; onDismiss: () => void; onRetry?: () => void }) {
  const t = useThemeTokens();

  useEffect(() => {
    const timer = setTimeout(onDismiss, onRetry ? 30000 : 8000);
    return () => clearTimeout(timer);
  }, [error, onDismiss, onRetry]);

  return (
    <View
      style={{
        paddingHorizontal: 16,
        paddingVertical: 8,
        backgroundColor: t.dangerSubtle,
        borderTopWidth: 1,
        borderTopColor: t.dangerBorder,
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
      }}
    >
      <Text style={{ color: t.danger, fontSize: 13, flex: 1 }}>{error}</Text>
      {onRetry && (
        <Pressable
          onPress={onRetry}
          style={{
            paddingHorizontal: 12,
            paddingVertical: 5,
            backgroundColor: t.danger,
            borderRadius: 4,
          }}
        >
          <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>Retry</Text>
        </Pressable>
      )}
      <Pressable onPress={onDismiss} style={{ paddingHorizontal: 8, paddingVertical: 4 }}>
        <Text style={{ color: t.dangerMuted, fontSize: 12 }}>Dismiss</Text>
      </Pressable>
    </View>
  );
}

export function SecretWarningBanner({ patterns, onDismiss }: { patterns: { type: string }[]; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 15000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  const types = patterns.map((p) => p.type).join(", ");

  return (
    <View className="px-4 py-2 bg-yellow-500/10 border-t border-yellow-500/20 flex-row items-center justify-between gap-2">
      <View className="flex-1">
        <Text className="text-yellow-400 text-sm font-semibold">
          <Shield size={12} /> Secret detected: {types}
        </Text>
        <Text className="text-yellow-400/70 text-xs mt-0.5">
          Consider using{" "}
          <Link href={"/admin/secret-values" as any} className="underline">
            Secrets Manager
          </Link>{" "}
          instead of pasting credentials in chat.
        </Text>
      </View>
      <Pressable onPress={onDismiss} className="px-2 py-1">
        <Text className="text-yellow-400/60 text-xs">Dismiss</Text>
      </Pressable>
    </View>
  );
}
