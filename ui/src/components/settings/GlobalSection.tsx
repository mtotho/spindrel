import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Link } from "expo-router";
import { Save, Check, Server, KeyRound, Eye } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section } from "@/src/components/shared/FormControls";
import {
  FallbackModelList,
  type FallbackModelEntry,
} from "@/src/components/shared/FallbackModelList";

export function GlobalSection({
  fbModels,
  onFbChange,
  onFbSave,
  fbDirty,
  fbSaving,
  fbSaved,
  fbError,
  fbLoading,
}: {
  fbModels: FallbackModelEntry[];
  onFbChange: (v: FallbackModelEntry[]) => void;
  onFbSave: () => void;
  fbDirty: boolean;
  fbSaving: boolean;
  fbSaved: boolean;
  fbError: boolean;
  fbLoading: boolean;
}) {
  const t = useThemeTokens();
  return (
    <View>
      <View
        style={{
          flexDirection: "row",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 16,
        }}
      >
        <Link href={"/admin/providers" as any} asChild>
          <Pressable className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay border border-surface-border">
            <Server size={14} color={t.accent} />
            <Text className="text-accent" style={{ fontSize: 13 }}>
              Providers
            </Text>
          </Pressable>
        </Link>
        <Link href={"/admin/api-keys" as any} asChild>
          <Pressable className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay border border-surface-border">
            <KeyRound size={14} color={t.accent} />
            <Text className="text-accent" style={{ fontSize: 13 }}>
              API Keys
            </Text>
          </Pressable>
        </Link>
        <Link href={"/admin/config-state" as any} asChild>
          <Pressable className="flex-row items-center gap-2 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay border border-surface-border">
            <Eye size={14} color={t.accent} />
            <Text className="text-accent" style={{ fontSize: 13 }}>
              Config State
            </Text>
          </Pressable>
        </Link>
      </View>

      <Section title="Global Fallback Models">
        <Text
          className="text-text-dim text-xs"
          style={{ marginBottom: 12 }}
        >
          Catch-all fallback chain appended after channel/bot fallbacks. When
          all per-channel and per-bot fallbacks are exhausted, these models are
          tried in order.
        </Text>

        {fbLoading ? (
          <ActivityIndicator color={t.accent} />
        ) : (
          <FallbackModelList value={fbModels} onChange={onFbChange} />
        )}
      </Section>

      <View
        style={{
          marginTop: 20,
          flexDirection: "row",
          gap: 12,
          alignItems: "center",
        }}
      >
        <Pressable
          onPress={onFbSave}
          disabled={!fbDirty || fbSaving}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            backgroundColor: fbDirty ? t.accent : "rgba(128,128,128,0.3)",
            paddingHorizontal: 16,
            paddingVertical: 8,
            borderRadius: 8,
            opacity: fbDirty ? 1 : 0.5,
          }}
        >
          {fbSaving ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : fbSaved ? (
            <Check size={14} color="#fff" />
          ) : (
            <Save size={14} color="#fff" />
          )}
          <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>
            {fbSaved ? "Saved" : "Save"}
          </Text>
        </Pressable>
        {fbError && (
          <Text style={{ color: t.danger, fontSize: 12 }}>
            Failed to save
          </Text>
        )}
      </View>
    </View>
  );
}
