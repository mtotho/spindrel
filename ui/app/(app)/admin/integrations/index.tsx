import { useState } from "react";
import { View, ActivityIndicator, Platform, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useIntegrations,
  type IntegrationItem,
  type IntegrationEnvVar,
} from "@/src/api/hooks/useIntegrations";
import { Check, X, Copy, ChevronDown, ChevronRight } from "lucide-react";

const STATUS_COLORS: Record<string, { dot: string; label: string; bg: string }> = {
  ready: { dot: "#22c55e", label: "Ready", bg: "rgba(34,197,94,0.12)" },
  partial: { dot: "#eab308", label: "Partial", bg: "rgba(234,179,8,0.12)" },
  not_configured: { dot: "#6b7280", label: "Not Configured", bg: "rgba(107,114,128,0.12)" },
};

function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.not_configured;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 10px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        background: c.bg,
        color: c.dot,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: 4,
          background: c.dot,
          flexShrink: 0,
        }}
      />
      {c.label}
    </span>
  );
}

function EnvVarPill({ v }: { v: IntegrationEnvVar }) {
  const t = useThemeTokens();
  return (
    <span
      title={v.description}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 500,
        background: v.is_set ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)",
        color: v.is_set ? "#22c55e" : "#ef4444",
        fontFamily: "monospace",
      }}
    >
      {v.is_set ? <Check size={10} /> : <X size={10} />}
      {v.key}
      {!v.required && (
        <span style={{ fontSize: 9, color: t.textDim, fontFamily: "sans-serif" }}>
          opt
        </span>
      )}
    </span>
  );
}

function CapBadge({ label, active }: { label: string; active: boolean }) {
  const t = useThemeTokens();
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: "1px 6px",
        borderRadius: 3,
        background: active ? t.accentSubtle : "transparent",
        color: active ? t.accent : t.surfaceBorder,
        border: active ? "none" : `1px solid ${t.surfaceBorder}`,
      }}
    >
      {label}
    </span>
  );
}

function WebhookRow({ webhook }: { webhook: IntegrationItem["webhook"] }) {
  const t = useThemeTokens();
  const [copied, setCopied] = useState(false);
  if (!webhook) return null;

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (Platform.OS === "web" && navigator?.clipboard) {
      navigator.clipboard.writeText(webhook.url);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
      <span style={{ color: t.textDim }}>Webhook:</span>
      <code style={{ color: t.textMuted, fontFamily: "monospace", fontSize: 11 }}>
        {webhook.path}
      </code>
      <button
        onClick={handleCopy}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 2,
          display: "flex",
          alignItems: "center",
        }}
        title="Copy full URL"
      >
        {copied ? (
          <Check size={12} color="#22c55e" />
        ) : (
          <Copy size={12} color={t.textDim} />
        )}
      </button>
    </div>
  );
}

function IntegrationCard({ item, isWide }: { item: IntegrationItem; isWide: boolean }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: isWide ? "16px 20px" : "12px 14px",
        background: t.inputBg,
        borderRadius: 10,
        border: `1px solid ${t.surfaceRaised}`,
      }}
    >
      {/* Header: name + status */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: t.text, flex: 1 }}>
          {item.name}
        </span>
        <StatusBadge status={item.status} />
      </div>

      {/* Env var pills */}
      {item.env_vars.length > 0 && (
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: t.textDim,
              marginBottom: 4,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            Environment Variables
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {item.env_vars.map((v) => (
              <EnvVarPill key={v.key} v={v} />
            ))}
          </div>
        </div>
      )}

      {/* Webhook */}
      <WebhookRow webhook={item.webhook} />

      {/* Capability badges */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <CapBadge label="router" active={item.has_router} />
        <CapBadge label="dispatcher" active={item.has_dispatcher} />
        <CapBadge label="hooks" active={item.has_hooks} />
        <CapBadge label="tools" active={item.has_tools} />
        <CapBadge label="skills" active={item.has_skills} />
      </div>

      {/* README expand */}
      {item.readme && (
        <div>
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              fontSize: 12,
              fontWeight: 600,
              color: t.accent,
            }}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Setup Instructions
          </button>
          {expanded && (
            <pre
              style={{
                marginTop: 8,
                padding: 12,
                background: t.surface,
                borderRadius: 6,
                border: `1px solid ${t.surfaceBorder}`,
                fontSize: 12,
                lineHeight: 1.5,
                color: t.textMuted,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                overflow: "auto",
                maxHeight: 400,
              }}
            >
              {item.readme}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export default function IntegrationsScreen() {
  const t = useThemeTokens();
  const { data, isLoading, isError } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const all = data?.integrations;
  const integrations = all?.filter((i) => i.source !== "package") ?? [];
  const packages = all?.filter((i) => i.source === "package") ?? [];

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const renderGrid = (items: IntegrationItem[]) => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: isWide
          ? "repeat(auto-fill, minmax(400px, 1fr))"
          : "1fr",
        gap: isWide ? 12 : 10,
      }}
    >
      {items.map((item) => (
        <IntegrationCard key={item.id} item={item} isWide={isWide} />
      ))}
    </div>
  );

  const sectionHeader = (label: string) => (
    <div
      style={{
        fontSize: 11,
        fontWeight: 700,
        color: t.textDim,
        textTransform: "uppercase",
        letterSpacing: 0.8,
        marginTop: 4,
      }}
    >
      {label}
    </div>
  );

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Integrations & Packages" />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{
          padding: isWide ? 20 : 12,
          gap: isWide ? 12 : 10,
        }}
      >
        {isError && (
          <div
            style={{
              padding: 40,
              textAlign: "center",
              fontSize: 13,
              color: "#ef4444",
            }}
          >
            Failed to load integrations.
          </div>
        )}

        {!isError && (!all || all.length === 0) && (
          <div
            style={{
              padding: 40,
              textAlign: "center",
              fontSize: 13,
              color: t.textDim,
            }}
          >
            No integrations or packages discovered.
          </div>
        )}

        {integrations.length > 0 && (
          <>
            {sectionHeader("Integrations")}
            {renderGrid(integrations)}
          </>
        )}

        {packages.length > 0 && (
          <>
            {sectionHeader("Packages")}
            {renderGrid(packages)}
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}
