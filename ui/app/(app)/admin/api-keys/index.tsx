import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { Plus, Key } from "lucide-react";
import { useApiKeys, type ApiKeyItem } from "@/src/api/hooks/useApiKeys";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";

function ScopeBadge({ scope }: { scope: string }) {
  const t = useThemeTokens();
  const isAdmin = scope === "admin";
  return (
    <span
      style={{
        padding: "1px 6px",
        borderRadius: 3,
        fontSize: 10,
        fontWeight: 600,
        background: isAdmin ? t.dangerSubtle : t.accentSubtle,
        color: isAdmin ? t.danger : t.accent,
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
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Key size={14} color={t.accent} />
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
            background: apiKey.is_active ? t.success : t.textDim,
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
          display: "flex", flexDirection: "row",
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
  const navigate = useNavigate();
  const { data: apiKeys, isLoading } = useApiKeys();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="API Keys"
        right={
          <button
            onClick={() => navigate("/admin/api-keys/new")}
            style={{
              display: "flex", flexDirection: "row",
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
            <div className="flex items-center justify-center py-20">
              <Spinner color={t.accent} />
            </div>
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
                    navigate(`/admin/api-keys/${k.id}`)
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
    </div>
  );
}
