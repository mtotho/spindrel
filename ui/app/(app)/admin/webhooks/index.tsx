import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { Plus, Webhook } from "lucide-react";
import { useWebhooks, type WebhookEndpointItem } from "@/src/api/hooks/useWebhooks";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";

function EventBadge({ event }: { event: string }) {
  const t = useThemeTokens();
  return (
    <span
      style={{
        padding: "1px 6px",
        borderRadius: 3,
        fontSize: 10,
        fontWeight: 600,
        background: t.accentSubtle,
        color: t.accent,
        whiteSpace: "nowrap",
      }}
    >
      {event}
    </span>
  );
}

function WebhookCard({
  webhook,
  onPress,
}: {
  webhook: WebhookEndpointItem;
  onPress: () => void;
}) {
  const t = useThemeTokens();
  const truncatedUrl =
    webhook.url.length > 50 ? webhook.url.slice(0, 50) + "..." : webhook.url;

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
        <Webhook size={14} color={t.accent} />
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: t.text,
            flex: 1,
          }}
        >
          {webhook.name}
        </span>
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            background: webhook.is_active ? t.success : t.textDim,
          }}
        />
      </div>

      <div
        style={{
          fontFamily: "monospace",
          fontSize: 12,
          color: t.textDim,
          letterSpacing: 0.3,
        }}
      >
        {truncatedUrl}
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 4,
        }}
      >
        {webhook.events.length === 0 ? (
          <span style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>
            All events
          </span>
        ) : (
          <>
            {webhook.events.slice(0, 4).map((e) => (
              <EventBadge key={e} event={e} />
            ))}
            {webhook.events.length > 4 && (
              <span style={{ fontSize: 10, color: t.textDim }}>
                +{webhook.events.length - 4} more
              </span>
            )}
          </>
        )}
      </div>
    </button>
  );
}

export default function WebhooksScreen() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: webhooks, isLoading } = useWebhooks();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Webhooks"
        right={
          <button
            onClick={() => router.push("/admin/webhooks/new" as any)}
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
            <Plus size={14} /> New Webhook
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
              {webhooks?.map((w) => (
                <WebhookCard
                  key={w.id}
                  webhook={w}
                  onPress={() =>
                    router.push(`/admin/webhooks/${w.id}` as any)
                  }
                />
              ))}
              {webhooks?.length === 0 && (
                <div
                  style={{
                    padding: 40,
                    textAlign: "center",
                    color: t.textDim,
                    fontSize: 14,
                  }}
                >
                  No webhook endpoints yet. Create one to start receiving event
                  notifications.
                </div>
              )}
            </div>
          )}
        </div>
      </RefreshableScrollView>
    </View>
  );
}
