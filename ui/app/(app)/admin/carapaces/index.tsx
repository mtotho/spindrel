import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator, TextInput } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { Plus, Search, Layers, ChevronRight } from "lucide-react";
import { Link } from "expo-router";
import type { Carapace } from "@/src/types/api";

export default function CarapacesPage() {
  const tokens = useThemeTokens();
  const { data: carapaces, isLoading } = useCarapaces();
  const { refreshing, onRefresh } = usePageRefresh([["carapaces"]]);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!carapaces) return [];
    const q = search.toLowerCase();
    if (!q) return carapaces;
    return carapaces.filter(
      (c) =>
        c.id.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        (c.description || "").toLowerCase().includes(q) ||
        c.tags.some((t) => t.toLowerCase().includes(q))
    );
  }, [carapaces, search]);

  return (
    <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh}>
      <MobileHeader title="Carapaces" />
      <View style={{ padding: 16, maxWidth: 960 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 16 }}>
          <View style={{ flex: 1, flexDirection: "row", alignItems: "center", backgroundColor: tokens.surface, borderRadius: 8, paddingHorizontal: 10, height: 36, borderWidth: 1, borderColor: tokens.surfaceBorder }}>
            <Search size={14} color={tokens.textMuted} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search carapaces..."
              placeholderTextColor={tokens.textMuted}
              style={{ flex: 1, marginLeft: 8, color: tokens.text, fontSize: 13 }}
            />
          </View>
          <Link href={"/admin/carapaces/new" as any} asChild>
            <Pressable style={{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: tokens.accent, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8 }}>
              <Plus size={14} color="#fff" />
              <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>New</Text>
            </Pressable>
          </Link>
        </View>

        {isLoading ? (
          <ActivityIndicator style={{ marginTop: 40 }} />
        ) : filtered.length === 0 ? (
          <View style={{ alignItems: "center", paddingTop: 60 }}>
            <Layers size={32} color={tokens.textMuted} />
            <Text style={{ color: tokens.textMuted, marginTop: 12, fontSize: 14 }}>
              {search ? "No carapaces match your search." : "No carapaces yet. Create one to get started."}
            </Text>
          </View>
        ) : (
          <View style={{ gap: 8 }}>
            {filtered.map((c) => (
              <CarapaceCard key={c.id} carapace={c} tokens={tokens} />
            ))}
          </View>
        )}
      </View>
    </RefreshableScrollView>
  );
}

function CarapaceCard({
  carapace: c,
  tokens,
}: {
  carapace: Carapace;
  tokens: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <Link href={`/admin/carapaces/${c.id}` as any} asChild>
      <Pressable
        style={{
          backgroundColor: tokens.surface,
          borderRadius: 10,
          borderWidth: 1,
          borderColor: tokens.surfaceBorder,
          padding: 14,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Layers size={16} color={tokens.accent} />
              <Text style={{ color: tokens.text, fontWeight: "600", fontSize: 14 }}>{c.name}</Text>
              {c.source_type !== "manual" && (
                <View style={{ backgroundColor: "rgba(59,130,246,0.12)", paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4 }}>
                  <Text style={{ color: "#3b82f6", fontSize: 10 }}>{c.source_type}</Text>
                </View>
              )}
            </View>
            {c.description ? (
              <Text style={{ color: tokens.textMuted, fontSize: 12, marginTop: 4 }} numberOfLines={1}>
                {c.description}
              </Text>
            ) : null}
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6 }}>
              {c.local_tools.length > 0 && (
                <Text style={{ color: tokens.textMuted, fontSize: 11 }}>
                  {c.local_tools.length} tool{c.local_tools.length !== 1 ? "s" : ""}
                </Text>
              )}
              {c.skills.length > 0 && (
                <Text style={{ color: tokens.textMuted, fontSize: 11 }}>
                  {c.skills.length} skill{c.skills.length !== 1 ? "s" : ""}
                </Text>
              )}
              {c.includes.length > 0 && (
                <Text style={{ color: tokens.textMuted, fontSize: 11 }}>
                  includes: {c.includes.join(", ")}
                </Text>
              )}
              {c.tags.length > 0 && (
                <View style={{ flexDirection: "row", gap: 4 }}>
                  {c.tags.map((t) => (
                    <View key={t} style={{ backgroundColor: "rgba(168,85,247,0.1)", paddingHorizontal: 5, paddingVertical: 1, borderRadius: 3 }}>
                      <Text style={{ color: "#9333ea", fontSize: 10 }}>{t}</Text>
                    </View>
                  ))}
                </View>
              )}
            </View>
          </View>
          <ChevronRight size={16} color={tokens.textMuted} />
        </View>
      </Pressable>
    </Link>
  );
}
