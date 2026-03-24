import { useState } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useRouter } from "expo-router";
import { Plus, Zap, ZapOff, ExternalLink } from "lucide-react";
import { useProviders, useTestProvider, type ProviderItem } from "@/src/api/hooks/useProviders";
import { MobileMenuButton } from "@/src/components/layout/MobileMenuButton";

const TYPE_COLORS: Record<string, { bg: string; fg: string }> = {
  litellm: { bg: "rgba(59,130,246,0.15)", fg: "#93c5fd" },
  openai: { bg: "rgba(16,185,129,0.15)", fg: "#6ee7b7" },
  anthropic: { bg: "rgba(249,115,22,0.15)", fg: "#fdba74" },
  "anthropic-subscription": { bg: "rgba(168,85,247,0.15)", fg: "#c4b5fd" },
};

function TypeBadge({ type }: { type: string }) {
  const c = TYPE_COLORS[type] || { bg: "rgba(100,100,100,0.15)", fg: "#999" };
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: c.bg, color: c.fg, whiteSpace: "nowrap",
    }}>
      {type}
    </span>
  );
}

function ProviderCard({ provider, onPress, isWide }: { provider: ProviderItem; onPress: () => void; isWide: boolean }) {
  const testMut = useTestProvider();
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const handleTest = (e: React.MouseEvent) => {
    e.stopPropagation();
    setTestResult(null);
    testMut.mutate(provider.id, {
      onSuccess: (r) => setTestResult(r),
      onError: (err) => setTestResult({ ok: false, message: (err as any)?.message || "Failed" }),
    });
  };

  return (
    <button
      onClick={onPress}
      style={{
        display: "flex", flexDirection: "column", gap: 10,
        padding: isWide ? "16px 20px" : "12px 14px",
        background: "#111", borderRadius: 10,
        border: `1px solid ${provider.is_enabled ? "#1a1a1a" : "#2a1a1a"}`,
        cursor: "pointer", textAlign: "left", width: "100%",
        opacity: provider.is_enabled ? 1 : 0.6,
      }}
    >
      {/* Top row: name + type + enabled */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 8, height: 8, borderRadius: 4, flexShrink: 0,
          background: provider.is_enabled ? "#22c55e" : "#ef4444",
        }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: "#e5e5e5", flex: 1 }}>
          {provider.display_name}
        </span>
        <TypeBadge type={provider.provider_type} />
      </div>

      {/* Info row */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 11, color: "#666" }}>
        <span style={{ fontFamily: "monospace" }}>{provider.id}</span>
        {provider.base_url && (
          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <ExternalLink size={10} />
            {provider.base_url.replace(/^https?:\/\//, "").slice(0, 30)}
          </span>
        )}
        {provider.has_api_key && <span style={{ color: "#555" }}>API key set</span>}
      </div>

      {/* Rate limits */}
      {(provider.tpm_limit || provider.rpm_limit) && (
        <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#555" }}>
          {provider.tpm_limit && <span>TPM: {provider.tpm_limit.toLocaleString()}</span>}
          {provider.rpm_limit && <span>RPM: {provider.rpm_limit.toLocaleString()}</span>}
        </div>
      )}

      {/* Test button + result */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
        <button
          onClick={handleTest}
          disabled={testMut.isPending}
          style={{
            padding: "4px 12px", fontSize: 11, fontWeight: 600,
            border: "1px solid #333", borderRadius: 5,
            background: "transparent", color: "#999", cursor: "pointer",
          }}
        >
          {testMut.isPending ? "Testing..." : "Test Connection"}
        </button>
        {testResult && (
          <span style={{
            fontSize: 11, fontWeight: 600,
            color: testResult.ok ? "#86efac" : "#fca5a5",
          }}>
            {testResult.ok ? "\u2713" : "\u2717"} {testResult.message}
          </span>
        )}
      </div>
    </button>
  );
}

export default function ProvidersScreen() {
  const router = useRouter();
  const { data: providers, isLoading } = useProviders();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px",
        borderBottom: "1px solid #333", gap: 8,
      }}>
        <MobileMenuButton />
        {isWide && (
          <span style={{ color: "#e5e5e5", fontSize: 14, fontWeight: 700 }}>Providers</span>
        )}
        <div style={{ flex: 1 }} />
        <button
          onClick={() => router.push("/admin/providers/new" as any)}
          style={{
            display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
            padding: isWide ? "6px 14px" : "6px 8px", fontSize: 12, fontWeight: 600,
            border: "none", borderRadius: 6,
            background: "#3b82f6", color: "#fff", cursor: "pointer",
          }}
        >
          <Plus size={14} />
          {isWide && "New Provider"}
        </button>
      </div>

      {/* Cards */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        padding: isWide ? 20 : 12,
        gap: isWide ? 12 : 10,
      }}>
        {(!providers || providers.length === 0) && (
          <div style={{
            padding: 40, textAlign: "center", fontSize: 13,
          }}>
            <div style={{ color: "#555", marginBottom: 8 }}>No providers configured.</div>
            <div style={{ color: "#444", fontSize: 12 }}>
              The server will use the <code style={{ color: "#666" }}>LITELLM_BASE_URL</code> / <code style={{ color: "#666" }}>LITELLM_API_KEY</code> from your .env file as the default provider.
            </div>
          </div>
        )}

        {/* Grid on wide, stack on mobile */}
        <div style={{
          display: "grid",
          gridTemplateColumns: isWide ? "repeat(auto-fill, minmax(380px, 1fr))" : "1fr",
          gap: isWide ? 12 : 10,
        }}>
          {providers?.map((p) => (
            <ProviderCard
              key={p.id}
              provider={p}
              isWide={isWide}
              onPress={() => router.push(`/admin/providers/${p.id}` as any)}
            />
          ))}
        </div>

        {/* Env fallback info */}
        {providers && providers.length > 0 && (
          <div style={{
            padding: 12, fontSize: 11, color: "#444", borderTop: "1px solid #1a1a1a",
            marginTop: 8,
          }}>
            Bots with no provider assigned will use the .env <code style={{ color: "#555" }}>LITELLM_BASE_URL</code> fallback.
          </div>
        )}
      </ScrollView>
    </View>
  );
}
