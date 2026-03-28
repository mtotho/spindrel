import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus, Key } from "lucide-react";
import { useApiKeys, type ApiKeyItem } from "@/src/api/hooks/useApiKeys";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";

function ScopeBadge({ scope }: { scope: string }) {
  const isAdmin = scope === "admin";
  return (
    <span
      style={{
        padding: "1px 6px",
        borderRadius: 3,
        fontSize: 10,
        fontWeight: 600,
        background: isAdmin ? "rgba(239,68,68,0.15)" : "rgba(59,130,246,0.12)",
        color: isAdmin ? "#dc2626" : "#2563eb",
        whiteSpace: "nowrap",
      }}
    >
      {scope}
    </span>
  );
}

function ApiKeyCard({
  apiKey,
  onPress,
}: {
  apiKey: ApiKeyItem;
  onPress: () => void;
}) {
  const t = useThemeTokens();
  const lastUsed = apiKey.last_used_at
    ? new Date(apiKey.last_used_at).toLocaleDateString()
    : "Never";

  return (
    <button
      onClick={onPress}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "16px 20px",
        background: t.inputBg,
        borderRadius: 10,
        border: `1px solid ${t.surfaceOverlay}`,
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Key size={14} color="#2563eb" />
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: t.text,
            flex: 1,
          }}
        >
          {apiKey.name}
        </span>
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            background: apiKey.is_active ? "#22c55e" : t.textDim,
          }}
        />
      </div>

      <div
        style={{
          fontFamily: "monospace",
          fontSize: 12,
          color: t.textDim,
          letterSpacing: 0.5,
        }}
      >
        {apiKey.key_prefix}...
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 4,
        }}
      >
        {apiKey.scopes.slice(0, 6).map((s) => (
          <ScopeBadge key={s} scope={s} />
        ))}
        {apiKey.scopes.length > 6 && (
          <span style={{ fontSize: 10, color: t.textDim }}>
            +{apiKey.scopes.length - 6} more
          </span>
        )}
      </div>

      <div style={{ fontSize: 11, color: t.textDim }}>Last used: {lastUsed}</div>
    </button>
  );
}

export default function ApiKeysScreen() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: apiKeys, isLoading } = useApiKeys();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="API Keys"
        right={
          <button
            onClick={() => router.push("/admin/api-keys/new" as any)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 14px",
              borderRadius: 6,
              background: t.accent,
              border: "none",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
              color: "#fff",
            }}
          >
            <Plus size={14} /> New Key
          </button>
        }
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh}>
        <div style={{ padding: 20, maxWidth: 1200, margin: "0 auto" }}>
          {isLoading ? (
            <View className="items-center justify-center py-20">
              <ActivityIndicator color={t.accent} />
            </View>
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: isWide
                  ? "repeat(auto-fill, minmax(380px, 1fr))"
                  : "1fr",
                gap: 12,
              }}
            >
              {apiKeys?.map((k) => (
                <ApiKeyCard
                  key={k.id}
                  apiKey={k}
                  onPress={() =>
                    router.push(`/admin/api-keys/${k.id}` as any)
                  }
                />
              ))}
              {apiKeys?.length === 0 && (
                <div
                  style={{
                    padding: 40,
                    textAlign: "center",
                    color: t.textDim,
                    fontSize: 14,
                  }}
                >
                  No API keys yet. Create one to get started.
                </div>
              )}
            </div>
          )}
        </div>
      </RefreshableScrollView>
    </View>
  );
}
