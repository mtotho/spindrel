import { useState, useMemo } from "react";
import { View, ActivityIndicator, useWindowDimensions } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useRouter } from "expo-router";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { Search, Plug, X } from "lucide-react";
import {
  useIntegrations,
  type IntegrationItem,
} from "@/src/api/hooks/useIntegrations";
import { StatusBadge, CapBadge, formatUptime } from "./components";

// ---------------------------------------------------------------------------
// Integration row
// ---------------------------------------------------------------------------

function IntegrationRow({ item, isWide }: { item: IntegrationItem; isWide: boolean }) {
  const t = useThemeTokens();
  const router = useRouter();

  const envSetCount = item.env_vars.filter((v) => v.is_set).length;
  const ps = item.process_status;
  const isRunning = ps?.status === "running";

  return (
    <button
      onClick={() => router.push(`/admin/integrations/${item.id}` as any)}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: isWide ? "12px 16px" : "10px 12px",
        background: t.inputBg,
        borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
        transition: "border-color 0.15s",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = t.accent; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = t.surfaceRaised; }}
    >
      {/* Top line: name, status, caps, process */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Plug size={14} color={t.textMuted} style={{ flexShrink: 0 }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>{item.name}</span>
        <StatusBadge status={item.status} />

        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {item.has_router && <CapBadge label="router" active />}
          {item.has_dispatcher && <CapBadge label="dispatcher" active />}
          {item.has_hooks && <CapBadge label="hooks" active />}
          {item.has_tools && <CapBadge label="tools" active />}
          {item.has_skills && <CapBadge label="skills" active />}
          {item.has_carapaces && <CapBadge label="carapaces" active />}
        </div>

        {item.has_process && (
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto", flexShrink: 0 }}>
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: 4,
                background: isRunning ? "#22c55e" : "#6b7280",
                flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 11, fontWeight: 500, color: isRunning ? "#22c55e" : t.textDim }}>
              {isRunning ? "Running" : "Stopped"}
            </span>
            {isRunning && ps?.uptime_seconds != null && (
              <span style={{ fontSize: 10, color: t.textDim }}>{formatUptime(ps.uptime_seconds)}</span>
            )}
          </div>
        )}
      </div>

      {/* Bottom line: source, webhook, env summary */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", paddingLeft: 22 }}>
        <span
          style={{
            fontSize: 9,
            fontWeight: 600,
            padding: "1px 5px",
            borderRadius: 3,
            background: "rgba(107,114,128,0.08)",
            color: t.textDim,
            textTransform: "uppercase",
            letterSpacing: 0.3,
          }}
        >
          {item.source}
        </span>
        {item.webhook && (
          <span style={{ fontSize: 11, color: t.textDim }}>
            <span style={{ color: t.textDim }}>Webhook: </span>
            <code style={{ fontFamily: "monospace", fontSize: 10, color: t.textMuted }}>{item.webhook.path}</code>
          </span>
        )}
        {item.env_vars.length > 0 && (
          <span style={{ fontSize: 10, color: envSetCount === item.env_vars.length ? "#22c55e" : t.textDim }}>
            {envSetCount}/{item.env_vars.length} vars set
          </span>
        )}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main list screen
// ---------------------------------------------------------------------------

export default function IntegrationsScreen() {
  const t = useThemeTokens();
  const { data, isLoading, isError } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");

  // Deduplicate and split packages
  const all = useMemo(() => {
    if (!data?.integrations) return undefined;
    return [...new Map(data.integrations.map((i) => [i.id, i])).values()];
  }, [data]);

  const filtered = useMemo(() => {
    if (!all) return { ready: [], needsSetup: [], packages: [] };
    const q = search.toLowerCase().trim();
    const match = (i: IntegrationItem) =>
      !q || i.name.toLowerCase().includes(q) || i.id.toLowerCase().includes(q);

    const integrations = all.filter((i) => i.source !== "package" && match(i));
    const packages = all.filter((i) => i.source === "package" && match(i));

    return {
      ready: integrations.filter((i) => i.status === "ready"),
      needsSetup: integrations.filter((i) => i.status !== "ready"),
      packages,
    };
  }, [all, search]);

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

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

  const isEmpty = !all || all.length === 0;
  const noResults = all && all.length > 0 && filtered.ready.length === 0 && filtered.needsSetup.length === 0 && filtered.packages.length === 0;

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Integrations" />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{
          padding: isWide ? 20 : 12,
          gap: isWide ? 10 : 8,
          maxWidth: 860,
        }}
      >
        {/* Search bar */}
        {!isEmpty && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 12px",
              background: t.inputBg,
              border: `1px solid ${t.inputBorder}`,
              borderRadius: 8,
            }}
          >
            <Search size={14} color={t.textDim} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search integrations..."
              style={{
                background: "none",
                border: "none",
                outline: "none",
                color: t.text,
                fontSize: 13,
                flex: 1,
              }}
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 2,
                  display: "flex",
                  alignItems: "center",
                  flexShrink: 0,
                }}
              >
                <X size={14} color={t.textDim} />
              </button>
            )}
          </div>
        )}

        {isError && (
          <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: "#ef4444" }}>
            Failed to load integrations.
          </div>
        )}

        {!isError && isEmpty && (
          <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: t.textDim }}>
            No integrations discovered.
          </div>
        )}

        {noResults && (
          <div style={{ padding: 40, textAlign: "center", fontSize: 13, color: t.textDim }}>
            No integrations match "{search}".
          </div>
        )}

        {filtered.ready.length > 0 && (
          <>
            {sectionHeader(`Ready (${filtered.ready.length})`)}
            {filtered.ready.map((item) => (
              <IntegrationRow key={item.id} item={item} isWide={isWide} />
            ))}
          </>
        )}

        {filtered.needsSetup.length > 0 && (
          <>
            {sectionHeader(`Needs Setup (${filtered.needsSetup.length})`)}
            {filtered.needsSetup.map((item) => (
              <IntegrationRow key={item.id} item={item} isWide={isWide} />
            ))}
          </>
        )}

        {filtered.packages.length > 0 && (
          <>
            {sectionHeader(`Packages (${filtered.packages.length})`)}
            {filtered.packages.map((item) => (
              <IntegrationRow key={item.id} item={item} isWide={isWide} />
            ))}
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}
