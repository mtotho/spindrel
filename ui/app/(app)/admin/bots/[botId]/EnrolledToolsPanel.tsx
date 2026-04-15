import { useState, useMemo } from "react";
import { Search, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useEnrolledTools,
  useUnenrollTool,
  type EnrolledTool,
} from "@/src/api/hooks/useEnrolledTools";
import { AdvancedSection } from "@/src/components/shared/SettingsControls";

const SOURCE_LABELS: Record<string, { label: string; bg: string; fg: string }> = {
  starter: { label: "starter", bg: "rgba(59,130,246,0.15)", fg: "#2563eb" },
  fetched: { label: "fetched", bg: "rgba(16,185,129,0.15)", fg: "#059669" },
  manual: { label: "manual", bg: "rgba(168,85,247,0.15)", fg: "#9333ea" },
};

function SourceBadge({ source }: { source: string }) {
  const cfg = SOURCE_LABELS[source] ?? { label: source, bg: "#eee", fg: "#444" };
  return (
    <span
      style={{
        padding: "1px 6px",
        borderRadius: 3,
        fontSize: 9,
        fontWeight: 600,
        background: cfg.bg,
        color: cfg.fg,
      }}
    >
      {cfg.label}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "never";
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return "—";
  }
}

export function EnrolledToolsPanel({ botId }: { botId: string }) {
  const t = useThemeTokens();
  const { data: enrolled, isLoading } = useEnrolledTools(botId);
  const unenrollMut = useUnenrollTool(botId);
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    if (!enrolled) return [];
    if (!filter) return enrolled;
    const f = filter.toLowerCase();
    return enrolled.filter((e) => e.tool_name.toLowerCase().includes(f));
  }, [enrolled, filter]);

  const grouped = useMemo(() => {
    const groups: Record<string, EnrolledTool[]> = {};
    for (const e of filtered) {
      (groups[e.source] ??= []).push(e);
    }
    return groups;
  }, [filtered]);

  const sourceOrder = ["starter", "manual", "fetched"];
  const orderedGroups = sourceOrder
    .map((src) => [src, grouped[src]] as const)
    .filter(([, list]) => list && list.length > 0);

  return (
    <AdvancedSection title="Working Set (Enrolled Tools)" defaultOpen>
      <div style={{ paddingTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.4 }}>
          Tools the bot has accumulated as its persistent working set. Declared
          tools are enrolled at bot creation; successful tool calls enroll new
          tools automatically; the memory hygiene loop prunes unused ones over
          time.
        </div>

        {isLoading && (
          <div style={{ fontSize: 11, color: t.textDim }}>Loading...</div>
        )}

        {enrolled && enrolled.length === 0 && (
          <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
            No tools enrolled yet. The bot will accrete tools as it uses them.
          </div>
        )}

        {enrolled && enrolled.length > 0 && (
          <>
            <div
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 6,
                background: t.inputBg,
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 6,
                padding: "4px 8px",
              }}
            >
              <Search size={12} color={t.textDim} />
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={`Filter ${enrolled.length} enrolled tool${enrolled.length !== 1 ? "s" : ""}...`}
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: t.text,
                  fontSize: 12,
                }}
              />
            </div>

            {orderedGroups.map(([source, list]) => (
              <div key={source}>
                <div
                  style={{
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    gap: 8,
                    padding: "10px 0 4px",
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      color: t.textMuted,
                      textTransform: "uppercase",
                      letterSpacing: 1,
                    }}
                  >
                    {source}
                  </span>
                  <span style={{ fontSize: 10, color: t.textDim }}>{list.length}</span>
                  <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
                </div>
                {list.map((e) => (
                  <div
                    key={e.tool_name}
                    style={{
                      padding: "6px 4px",
                      borderBottom: `1px solid ${t.surfaceBorder}`,
                      display: "flex", flexDirection: "row",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          display: "flex", flexDirection: "row",
                          alignItems: "center",
                          gap: 6,
                          flexWrap: "wrap",
                        }}
                      >
                        <span
                          style={{
                            fontSize: 12,
                            fontWeight: 500,
                            color: t.text,
                            fontFamily: "monospace",
                          }}
                        >
                          {e.tool_name}
                        </span>
                        <SourceBadge source={e.source} />
                        <span style={{ fontSize: 10, color: t.textDim }}>
                          enrolled {formatDate(e.enrolled_at)}
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={() => unenrollMut.mutate(e.tool_name)}
                      disabled={unenrollMut.isPending}
                      title="Remove from working set"
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 3,
                        fontSize: 10,
                        color: "#dc2626",
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                        padding: "2px 4px",
                      }}
                    >
                      <X size={12} />
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </>
        )}
      </div>
    </AdvancedSection>
  );
}
