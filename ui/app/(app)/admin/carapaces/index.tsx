import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { Plus, Search, Layers, ChevronRight, HelpCircle } from "lucide-react";
import { Link, useRouter } from "expo-router";
import { CarapaceHelpModal } from "./CarapaceHelpModal";
import type { Carapace } from "@/src/types/api";

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "subheader"; key: string; label: string; count: number }
  | { type: "card"; key: string; carapace: Carapace };

function SectionHeader({ label, count, level }: { label: string; count: number; level: number }) {
  const t = useThemeTokens();
  const isSubheader = level > 0;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: `${isSubheader ? 8 : 14}px 0 ${isSubheader ? 4 : 6}px ${isSubheader ? 16 : 0}px`,
    }}>
      <span style={{
        fontSize: isSubheader ? 10 : 11,
        fontWeight: 600,
        color: isSubheader ? t.textDim : t.textMuted,
        textTransform: "uppercase",
        letterSpacing: 1,
      }}>
        {label}
      </span>
      <span style={{ fontSize: 10, color: t.textDim, fontWeight: 500 }}>
        {count}
      </span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

export default function CarapacesPage() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: carapaces, isLoading } = useCarapaces();
  const { refreshing, onRefresh } = usePageRefresh([["carapaces"]]);
  const [search, setSearch] = useState("");
  const [showHelp, setShowHelp] = useState(false);

  const filtered = useMemo(() => {
    if (!carapaces) return [];
    const q = search.toLowerCase();
    if (!q) return carapaces;
    return carapaces.filter(
      (c) =>
        c.id.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        (c.description || "").toLowerCase().includes(q) ||
        c.tags.some((tag) => tag.toLowerCase().includes(q))
    );
  }, [carapaces, search]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filtered.length) return [];

    const manual: Carapace[] = [];
    const core: Carapace[] = [];
    const integrationMap = new Map<string, Carapace[]>();

    for (const c of filtered) {
      if (c.source_type === "manual") manual.push(c);
      else if (c.source_type === "integration") {
        const intName = c.source_path?.match(/^integrations\/([^/]+)\//)?.[1] ?? "other";
        const list = integrationMap.get(intName);
        if (list) list.push(c); else integrationMap.set(intName, [c]);
      } else core.push(c);
    }

    const items: RenderItem[] = [];
    const addGroup = (key: string, label: string, list: Carapace[]) => {
      if (!list.length) return;
      items.push({ type: "header", key, label, count: list.length });
      for (const c of list) items.push({ type: "card", key: c.id, carapace: c });
    };

    addGroup("manual", "User Added", manual);
    addGroup("core", "Core", core);

    const intKeys = [...integrationMap.keys()].sort();
    if (intKeys.length) {
      const totalInt = intKeys.reduce((n, k) => n + integrationMap.get(k)!.length, 0);
      items.push({ type: "header", key: "integrations", label: "Integrations", count: totalInt });
      for (const k of intKeys) {
        const list = integrationMap.get(k)!;
        items.push({ type: "subheader", key: `int-${k}`, label: fmtIntName(k), count: list.length });
        for (const c of list) items.push({ type: "card", key: c.id, carapace: c });
      }
    }

    return items;
  }, [filtered]);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Carapaces (Expertise)"
        right={
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => setShowHelp(true)}
              title="What are carapaces?"
              style={{
                display: "flex", alignItems: "center",
                padding: "6px 8px", fontSize: 12,
                border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                background: "transparent", color: t.textMuted, cursor: "pointer",
              }}
            >
              <HelpCircle size={14} />
            </button>
            <button
              onClick={() => router.push("/admin/carapaces/new" as any)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: "none", borderRadius: 6,
                background: t.accent, color: "#fff", cursor: "pointer",
              }}
            >
              <Plus size={14} />
              New
            </button>
          </div>
        }
      />

      {/* Pinned search bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "8px 16px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px",
          maxWidth: 300, flex: 1,
        }}>
          <Search size={13} color={t.textDim} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter carapaces..."
            style={{
              background: "none", border: "none", outline: "none",
              color: t.text, fontSize: 12, flex: 1, width: "100%",
            }}
          />
        </div>
        {carapaces && carapaces.length > 0 && (
          <span style={{ fontSize: 11, color: t.textDim, whiteSpace: "nowrap" }}>
            {search && filtered.length !== carapaces.length
              ? `${filtered.length} / ${carapaces.length}`
              : carapaces.length}{" "}
            carapaces
          </span>
        )}
      </div>

      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color={t.accent} />
        </View>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }}>
          <View style={{ padding: 16, maxWidth: 960 }}>
            {(!carapaces || carapaces.length === 0) && (
              <View style={{ alignItems: "center", paddingTop: 60 }}>
                <Layers size={32} color={t.textMuted} />
                <Text style={{ color: t.textMuted, marginTop: 12, fontSize: 14 }}>
                  No carapaces yet. Create one to get started.
                </Text>
              </View>
            )}
            {carapaces && carapaces.length > 0 && filtered.length === 0 && (
              <View style={{ alignItems: "center", paddingTop: 60 }}>
                <Text style={{ color: t.textDim, fontSize: 13 }}>
                  No carapaces match "{search}"
                </Text>
              </View>
            )}
            {renderItems.map((item) =>
              item.type === "header" ? (
                <SectionHeader key={item.key} label={item.label} count={item.count} level={0} />
              ) : item.type === "subheader" ? (
                <SectionHeader key={item.key} label={item.label} count={item.count} level={1} />
              ) : (
                <View key={item.key} style={{ marginBottom: 8 }}>
                  <CarapaceCard carapace={item.carapace} t={t} />
                </View>
              ),
            )}
          </View>
        </RefreshableScrollView>
      )}

      {showHelp && <CarapaceHelpModal onClose={() => setShowHelp(false)} />}
    </View>
  );
}

function CarapaceCard({ carapace: c, t }: { carapace: Carapace; t: ThemeTokens }) {
  return (
    <Link href={`/admin/carapaces/${c.id}` as any} asChild>
      <Pressable
        style={{
          backgroundColor: t.surfaceRaised,
          borderRadius: 10,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          padding: 14,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <View style={{ flex: 1 }}>
            {/* Name + source badge */}
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Layers size={16} color={t.accent} />
              <Text style={{ color: t.text, fontWeight: "600", fontSize: 14 }}>
                {c.name}
              </Text>
              {c.source_type !== "manual" && (
                <View
                  style={{
                    backgroundColor: t.accentSubtle,
                    borderWidth: 1,
                    borderColor: t.accentBorder,
                    paddingHorizontal: 6,
                    paddingVertical: 1,
                    borderRadius: 4,
                  }}
                >
                  <Text style={{ color: t.accent, fontSize: 10 }}>{c.source_type}</Text>
                </View>
              )}
            </View>

            {/* Description */}
            {c.description ? (
              <Text
                style={{ color: t.textMuted, fontSize: 12, marginTop: 4 }}
                numberOfLines={1}
              >
                {c.description}
              </Text>
            ) : null}

            {/* Metadata row */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 8,
                marginTop: 6,
                flexWrap: "wrap",
              }}
            >
              {c.local_tools.length > 0 && (
                <Text style={{ color: t.textDim, fontSize: 11 }}>
                  {c.local_tools.length} tool{c.local_tools.length !== 1 ? "s" : ""}
                </Text>
              )}
              {c.skills.length > 0 && (
                <Text style={{ color: t.textDim, fontSize: 11 }}>
                  {c.skills.length} skill{c.skills.length !== 1 ? "s" : ""}
                </Text>
              )}
              {c.includes.length > 0 && (
                <Text style={{ color: t.textDim, fontSize: 11 }}>
                  includes: {c.includes.join(", ")}
                </Text>
              )}
              {c.tags.length > 0 && (
                <View style={{ flexDirection: "row", gap: 4 }}>
                  {c.tags.map((tag) => (
                    <View
                      key={tag}
                      style={{
                        backgroundColor: t.purpleSubtle,
                        borderWidth: 1,
                        borderColor: t.purpleBorder,
                        paddingHorizontal: 5,
                        paddingVertical: 1,
                        borderRadius: 3,
                      }}
                    >
                      <Text style={{ color: t.purple, fontSize: 10 }}>{tag}</Text>
                    </View>
                  ))}
                </View>
              )}
            </View>
          </View>
          <ChevronRight size={16} color={t.textMuted} />
        </View>
      </Pressable>
    </Link>
  );
}
