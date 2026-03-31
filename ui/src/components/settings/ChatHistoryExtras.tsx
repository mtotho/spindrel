import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { Eye, ChevronRight } from "lucide-react";
import { useRouter } from "expo-router";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section } from "@/src/components/shared/FormControls";

const SECTION_INDEX_HEADER = `Archived conversation history — use read_conversation_history with:
  - A section number (e.g. '3') to read a full transcript
  - 'search:<query>' to find sections by topic
  - 'messages:<query>' to grep raw messages across ALL history
  - 'tool:<id>' to retrieve full output of a summarized tool call`;

const SECTION_INDEX_PREVIEW: Record<string, string> = {
  compact: `${SECTION_INDEX_HEADER}
- #3: Deploy Pipeline (Mar 5) [deploy, ci-cd]
- #2: API Design (Mar 3) [api, design]
- #1: Database Migration (Mar 1) [database, migration]`,
  standard: `${SECTION_INDEX_HEADER}

#3: Deploy Pipeline (Mar 5) [deploy, ci-cd]
  Set up GitHub Actions workflow with staging and production targets.

#2: API Design (Mar 3) [api, design]
  Discussed REST endpoint structure for v2 and auth middleware.

#1: Database Migration (Mar 1) [database, migration]
  Fixed PostgreSQL schema issues and updated indexes for vector search.`,
  detailed: `${SECTION_INDEX_HEADER}

#3: Deploy Pipeline (12 msgs, mar 5, 8:30am — 11:15am) [deploy, ci-cd]
  Set up GitHub Actions workflow with staging and production targets.

#2: API Design (18 msgs, mar 3, 10:00am — 2:45pm) [api, design]
  Discussed REST endpoint structure for v2 and auth middleware.

#1: Database Migration (32 msgs, mar 1, 9:15am — 4:30pm) [database, migration]
  Fixed PostgreSQL schema issues and updated indexes for vector search.`,
};

interface ChatHistoryDeviation {
  channel_id: string;
  channel_name: string;
  deviations: { field: string; global_value: any; channel_value: any }[];
}

export function ChatHistoryExtras({ verbosity }: { verbosity: string }) {
  const router = useRouter();
  const t = useThemeTokens();
  const [showDeviations, setShowDeviations] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["chat-history-deviations"],
    queryFn: () =>
      apiFetch<{ channels: ChatHistoryDeviation[] }>(
        "/api/v1/admin/settings/chat-history-deviations"
      ),
    enabled: showDeviations,
  });

  const preview =
    SECTION_INDEX_PREVIEW[verbosity] || SECTION_INDEX_PREVIEW.standard;

  return (
    <View style={{ marginTop: 16, gap: 16 }}>
      {/* Section Index Preview */}
      <Section
        title="Section Index Preview"
        description={`System message injected into the bot's context each turn ("${verbosity}" verbosity)`}
      >
        <View
          style={{
            backgroundColor: t.surface,
            borderRadius: 8,
            borderWidth: 1,
            borderColor: t.surfaceOverlay,
            padding: 14,
          }}
        >
          <Text
            style={{
              fontFamily: "monospace",
              fontSize: 11,
              lineHeight: 18,
              color: t.textMuted,
              whiteSpace: "pre-wrap",
            } as any}
          >
            {preview}
          </Text>
        </View>
      </Section>

      {/* Show Deviations */}
      <Section
        title="Channel Deviations"
        description="Channels with chat history settings that differ from these global defaults"
      >
        {!showDeviations ? (
          <Pressable
            onPress={() => setShowDeviations(true)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              backgroundColor: t.surfaceRaised,
              paddingHorizontal: 14,
              paddingVertical: 10,
              borderRadius: 8,
              borderWidth: 1,
              borderColor: t.surfaceBorder,
              alignSelf: "flex-start",
            }}
          >
            <Eye size={14} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 13 }}>
              Show Deviations
            </Text>
          </Pressable>
        ) : isLoading ? (
          <ActivityIndicator color={t.accent} />
        ) : !data?.channels?.length ? (
          <Text style={{ color: t.textDim, fontSize: 12 }}>
            All channels use global defaults.
          </Text>
        ) : (
          <View style={{ gap: 8 }}>
            {data.channels.map((ch) => (
              <Pressable
                key={ch.channel_id}
                onPress={() =>
                  router.push(
                    `/channels/${ch.channel_id}/settings` as any
                  )
                }
                style={{
                  backgroundColor: t.surfaceRaised,
                  borderRadius: 8,
                  borderWidth: 1,
                  borderColor: t.surfaceOverlay,
                  padding: 12,
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text
                    style={{
                      color: t.text,
                      fontSize: 13,
                      fontWeight: "500",
                      marginBottom: 4,
                    }}
                  >
                    {ch.channel_name}
                  </Text>
                  <View
                    style={{
                      flexDirection: "row",
                      flexWrap: "wrap",
                      gap: 6,
                    }}
                  >
                    {ch.deviations.map((d) => (
                      <Text
                        key={d.field}
                        style={{ fontSize: 11, color: t.textMuted }}
                      >
                        {d.field}:{" "}
                        <Text style={{ color: "#f59e0b" }}>
                          {String(d.channel_value)}
                        </Text>{" "}
                        (global: {String(d.global_value)})
                      </Text>
                    ))}
                  </View>
                </View>
                <ChevronRight size={14} color={t.textDim} />
              </Pressable>
            ))}
          </View>
        )}
      </Section>
    </View>
  );
}
