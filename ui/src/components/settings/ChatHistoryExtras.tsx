import { useState } from "react";
import { Eye, ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
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
  const navigate = useNavigate();
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
    <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Section Index Preview */}
      <Section
        title="Section Index Preview"
        description={`System message injected into the bot's context each turn ("${verbosity}" verbosity)`}
      >
        <div
          style={{
            backgroundColor: t.surface,
            borderRadius: 8,
            border: `1px solid ${t.surfaceOverlay}`,
            padding: 14,
          }}
        >
          <span
            style={{
              fontFamily: "monospace",
              fontSize: 11,
              lineHeight: "18px",
              color: t.textMuted,
              whiteSpace: "pre-wrap",
            }}
          >
            {preview}
          </span>
        </div>
      </Section>

      {/* Show Deviations */}
      <Section
        title="Channel Deviations"
        description="Channels with chat history settings that differ from these global defaults"
      >
        {!showDeviations ? (
          <button
            onClick={() => setShowDeviations(true)}
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              backgroundColor: t.surfaceRaised,
              paddingLeft: 14,
              paddingRight: 14,
              paddingTop: 10,
              paddingBottom: 10,
              borderRadius: 8,
              border: `1px solid ${t.surfaceBorder}`,
              alignSelf: "flex-start",
              cursor: "pointer",
            }}
          >
            <Eye size={14} color={t.accent} />
            <span style={{ color: t.accent, fontSize: 13 }}>
              Show Deviations
            </span>
          </button>
        ) : isLoading ? (
          <div className="chat-spinner" />
        ) : !data?.channels?.length ? (
          <span style={{ color: t.textDim, fontSize: 12 }}>
            All channels use global defaults.
          </span>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.channels.map((ch) => (
              <button
                key={ch.channel_id}
                onClick={() =>
                  navigate(
                    `/channels/${ch.channel_id}/settings`
                  )
                }
                style={{
                  backgroundColor: t.surfaceRaised,
                  borderRadius: 8,
                  border: `1px solid ${t.surfaceOverlay}`,
                  padding: 12,
                  display: "flex",
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "space-between",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <div style={{ flex: 1 }}>
                  <span
                    style={{
                      color: t.text,
                      fontSize: 13,
                      fontWeight: 500,
                      marginBottom: 4,
                      display: "block",
                    }}
                  >
                    {ch.channel_name}
                  </span>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "row",
                      flexWrap: "wrap",
                      gap: 6,
                    }}
                  >
                    {ch.deviations.map((d) => (
                      <span
                        key={d.field}
                        style={{ fontSize: 11, color: t.textMuted }}
                      >
                        {d.field}:{" "}
                        <span style={{ color: "#f59e0b" }}>
                          {String(d.channel_value)}
                        </span>{" "}
                        (global: {String(d.global_value)})
                      </span>
                    ))}
                  </div>
                </div>
                <ChevronRight size={14} color={t.textDim} />
              </button>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
