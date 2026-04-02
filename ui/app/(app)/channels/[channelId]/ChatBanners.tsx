import { useEffect } from "react";
import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { Shield } from "lucide-react";

export function ErrorBanner({ error, onDismiss }: { error: string; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 8000);
    return () => clearTimeout(timer);
  }, [error, onDismiss]);

  return (
    <Pressable
      onPress={onDismiss}
      className="px-4 py-2 bg-red-500/10 border-t border-red-500/20"
    >
      <Text className="text-red-400 text-sm">{error}</Text>
    </Pressable>
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
