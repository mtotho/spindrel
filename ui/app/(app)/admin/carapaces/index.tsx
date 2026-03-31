import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator, TextInput } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { Plus, Search, Layers, ChevronRight, HelpCircle } from "lucide-react";
import { Link } from "expo-router";
import { CarapaceHelpModal } from "./CarapaceHelpModal";
import type { Carapace } from "@/src/types/api";

export default function CarapacesPage() {
  const t = useThemeTokens();
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

  return (
    <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh}>
      <MobileHeader title="Carapaces" />
      <View style={{ padding: 16, maxWidth: 960 }}>
        <Text style={{ color: t.textDim, fontSize: 12, marginBottom: 12 }}>
          Composable expertise bundles — tools, skills, and behavioral instructions packaged for reuse.
        </Text>

        {/* Search + Help + New */}
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 16 }}>
          <View
            style={{
              flex: 1,
              flexDirection: "row",
              alignItems: "center",
              backgroundColor: t.inputBg,
              borderRadius: 8,
              paddingHorizontal: 10,
              height: 36,
              borderWidth: 1,
              borderColor: t.inputBorder,
            }}
          >
            <Search size={14} color={t.textMuted} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search carapaces..."
              placeholderTextColor={t.textDim}
              style={{ flex: 1, marginLeft: 8, color: t.inputText, fontSize: 13 }}
            />
          </View>
          <Pressable
            onPress={() => setShowHelp(true)}
            style={{ padding: 6, borderRadius: 6 }}
            accessibilityLabel="Help — what are carapaces?"
          >
            <HelpCircle size={18} color={t.textDim} />
          </Pressable>
          <Link href={"/admin/carapaces/new" as any} asChild>
            <Pressable
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                backgroundColor: t.accent,
                paddingHorizontal: 12,
                paddingVertical: 8,
                borderRadius: 8,
              }}
            >
              <Plus size={14} color="#fff" />
              <Text style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>New</Text>
            </Pressable>
          </Link>
        </View>

        {isLoading ? (
          <ActivityIndicator style={{ marginTop: 40 }} />
        ) : filtered.length === 0 ? (
          <View style={{ alignItems: "center", paddingTop: 60 }}>
            <Layers size={32} color={t.textMuted} />
            <Text style={{ color: t.textMuted, marginTop: 12, fontSize: 14 }}>
              {search
                ? "No carapaces match your search."
                : "No carapaces yet. Create one to get started."}
            </Text>
          </View>
        ) : (
          <View style={{ gap: 8 }}>
            {filtered.map((c) => (
              <CarapaceCard key={c.id} carapace={c} t={t} />
            ))}
          </View>
        )}
      </View>

      {showHelp && <CarapaceHelpModal onClose={() => setShowHelp(false)} />}
    </RefreshableScrollView>
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
