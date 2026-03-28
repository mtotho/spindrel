import { useState } from "react";
import { ActivityIndicator } from "react-native";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useChannelContextBreakdown } from "@/src/api/hooks/useChannels";
import { Section, EmptyState } from "@/src/components/shared/FormControls";
import { apiFetch } from "@/src/api/client";
import { useQuery } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Category & source badge colors (only used by this tab)
// ---------------------------------------------------------------------------
const CATEGORY_COLORS: Record<string, { bar: string; dot: string }> = {
  static:       { bar: "#3b82f6", dot: "#60a5fa" },
  rag:          { bar: "#22c55e", dot: "#4ade80" },
  conversation: { bar: "#f59e0b", dot: "#d97706" },
  compaction:   { bar: "#a855f7", dot: "#9333ea" },
};

const SOURCE_BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  channel: { bg: "#1e3a5f", fg: "#2563eb" },
  bot:     { bg: "#365314", fg: "#65a30d" },
  global:  { bg: "#333",    fg: "#999"    },
};

const ROLE_COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  system:    { bg: "#0d1117", fg: "#8b949e", border: "#1e3a5f" },
  user:      { bg: "#111a11", fg: "#a3d9a5", border: "#2d5a30" },
  assistant: { bg: "#1a1117", fg: "#d4a0c8", border: "#5b2350" },
  tool:      { bg: "#1a1700", fg: "#c9b87c", border: "#5b4f1e" },
};

// ---------------------------------------------------------------------------
// Context Block — individual collapsible block in the preview
// ---------------------------------------------------------------------------
function ContextBlock({ block, colors, isPlaceholder }: {
  block: { label: string; role: string; content: string };
  colors: { bg: string; fg: string; border: string };
  isPlaceholder: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const truncated = block.content.length > 200 && !open;
  const displayContent = truncated ? block.content.slice(0, 200) + "..." : block.content;

  return (
    <div style={{
      background: colors.bg, border: `1px solid ${colors.border}`,
      borderRadius: 6, overflow: "hidden",
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          width: "100%", padding: "6px 10px", border: "none", cursor: "pointer",
          background: "transparent",
        }}
      >
        <span style={{ fontSize: 10, fontWeight: 700, color: colors.fg, letterSpacing: "0.03em" }}>
          {block.label}
        </span>
        <span style={{ fontSize: 10, color: t.textDim }}>
          {block.content.length.toLocaleString()} chars
          {open ? " \u25b2" : " \u25bc"}
        </span>
      </button>
      <div style={{
        padding: "6px 10px 8px", fontFamily: "monospace", fontSize: 11,
        color: isPlaceholder ? t.textDim : colors.fg,
        fontStyle: isPlaceholder ? "italic" : "normal",
        whiteSpace: "pre-wrap", lineHeight: "1.5",
        maxHeight: open ? "none" : 120, overflow: "hidden",
      }}>
        {displayContent}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Context Preview — renders all injected system messages
// ---------------------------------------------------------------------------
function ContextPreview({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const [includeHistory, setIncludeHistory] = useState(false);
  const [expanded, setExpanded] = useState(true);

  const { data, isLoading } = useQuery({
    queryKey: ["context-preview", channelId, includeHistory],
    queryFn: () => apiFetch<{
      blocks: { label: string; role: string; content: string }[];
      conversation: { label: string; role: string; content: string }[];
      total_chars: number;
      total_tokens_approx: number;
      history_mode: string | null;
    }>(`/api/v1/admin/channels/${channelId}/context-preview?include_history=${includeHistory}`),
  });

  return (
    <Section title="Context Preview">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "5px 12px", fontSize: 11, fontWeight: 600,
            border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
            background: "transparent", color: t.textMuted, cursor: "pointer",
          }}
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {expanded ? "Collapse" : "Expand"}
        </button>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.textMuted, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={includeHistory}
            onChange={(e) => setIncludeHistory(e.target.checked)}
            style={{ accentColor: t.accent }}
          />
          Include conversation messages
        </label>

        {data && (
          <span style={{ fontSize: 11, color: t.textDim, marginLeft: "auto" }}>
            ~{data.total_chars.toLocaleString()} chars / ~{data.total_tokens_approx.toLocaleString()} tokens
          </span>
        )}
      </div>

      {isLoading && <ActivityIndicator color={t.accent} />}

      {expanded && data && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {data.blocks.map((block, i) => {
            const colors = ROLE_COLORS[block.role] || ROLE_COLORS.system;
            const isPlaceholder = block.content.startsWith("[") && block.content.endsWith("]");
            return (
              <ContextBlock key={`sys-${i}`} block={block} colors={colors} isPlaceholder={isPlaceholder} />
            );
          })}

          {data.conversation.length > 0 && (
            <>
              <div style={{
                fontSize: 10, fontWeight: 700, color: t.textDim, letterSpacing: "0.05em",
                textTransform: "uppercase", marginTop: 8, marginBottom: 2,
              }}>
                Conversation Messages ({data.conversation.length})
              </div>
              {data.conversation.map((block, i) => {
                const colors = ROLE_COLORS[block.role] || ROLE_COLORS.system;
                return (
                  <ContextBlock key={`conv-${i}`} block={block} colors={colors} isPlaceholder={false} />
                );
              })}
            </>
          )}
        </div>
      )}

      <div style={{ fontSize: 10, color: t.textDim, fontStyle: "italic", marginTop: 6 }}>
        This preview shows all deterministic injections. RAG-dependent blocks (memories, knowledge, workspace files) vary per query and are shown as placeholders.
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Context Tab
// ---------------------------------------------------------------------------
export function ContextTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useChannelContextBreakdown(channelId);

  if (isLoading) return <ActivityIndicator color={t.accent} />;
  if (!data) return <EmptyState message="No context data available." />;

  const legend = [
    { key: "static", label: "Static", color: CATEGORY_COLORS.static.bar },
    { key: "rag", label: "RAG", color: CATEGORY_COLORS.rag.bar },
    { key: "conversation", label: "Conversation", color: CATEGORY_COLORS.conversation.bar },
    { key: "compaction", label: "Compaction", color: CATEGORY_COLORS.compaction.bar },
  ];

  return (
    <>
      {/* Summary card */}
      <Section title="Summary">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
          {[
            ["Total Tokens", `~${data.total_tokens_approx.toLocaleString()}`],
            ["Total Chars", data.total_chars.toLocaleString()],
            ["Bot", data.bot_id],
            ["Session", data.session_id ? data.session_id.slice(0, 8) + "..." : "none"],
          ].map(([label, val]) => (
            <div key={String(label)} style={{
              padding: "12px 14px", background: t.surfaceRaised, borderRadius: 8, border: `1px solid ${t.surfaceOverlay}`,
            }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: t.text }}>{val}</div>
              <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      </Section>

      {/* Stacked bar */}
      <Section title="Proportions">
        <div style={{ display: "flex", height: 28, borderRadius: 6, overflow: "hidden", background: t.surfaceRaised }}>
          {data.categories
            .filter((c) => c.percentage > 0)
            .map((c) => (
              <div
                key={c.key}
                title={`${c.label}: ${c.percentage}%`}
                style={{
                  width: `${c.percentage}%`,
                  background: CATEGORY_COLORS[c.category]?.bar || t.textDim,
                  minWidth: c.percentage > 0.5 ? 3 : 0,
                }}
              />
            ))}
        </div>
        <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
          {legend.map((l) => (
            <div key={l.key} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: t.textMuted }}>
              <div style={{ width: 8, height: 8, borderRadius: 4, background: l.color }} />
              {l.label}
            </div>
          ))}
        </div>
      </Section>

      {/* Category list */}
      <Section title="Components">
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {data.categories.map((c) => (
            <div key={c.key} style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "10px 12px", background: t.surfaceRaised, borderRadius: 6, border: `1px solid ${t.surfaceOverlay}`,
            }}>
              <div style={{
                width: 8, height: 8, borderRadius: 4, flexShrink: 0,
                background: CATEGORY_COLORS[c.category]?.dot || t.textDim,
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{c.label}</div>
                <div style={{ fontSize: 11, color: t.textDim, marginTop: 1 }}>{c.description}</div>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>~{c.tokens_approx.toLocaleString()} tok</div>
                <div style={{ fontSize: 11, color: t.textDim }}>{c.percentage}%</div>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* Compaction state */}
      {data.compaction && (
        <Section title="Compaction">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
            {[
              ["Enabled", data.compaction.enabled ? "Yes" : "No"],
              ["Has Summary", data.compaction.has_summary ? `Yes (${data.compaction.summary_chars.toLocaleString()} chars)` : "No"],
              ["Total Messages", data.compaction.total_messages],
              ["Since Watermark", data.compaction.messages_since_watermark],
              ["Interval", data.compaction.compaction_interval],
              ["Keep Turns", data.compaction.compaction_keep_turns],
              ["Turns Until Next", data.compaction.turns_until_next ?? "N/A"],
            ].map(([label, val]) => (
              <div key={String(label)} style={{
                padding: "10px 12px", background: t.surfaceRaised, borderRadius: 8, border: `1px solid ${t.surfaceOverlay}`,
              }}>
                <div style={{ fontSize: 16, fontWeight: 600, color: t.text }}>{String(val)}</div>
                <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Context compression (ephemeral, per-turn) */}
      {data.compression && (
        <Section title="Context Compression">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
            {[
              ["Enabled", data.compression.enabled ? "Yes" : "No"],
              ["Model", data.compression.model || "\u2014"],
              ["Threshold", `${data.compression.threshold.toLocaleString()} chars`],
              ["Keep Turns", data.compression.keep_turns],
              ["Conv. Chars", data.compression.conversation_chars.toLocaleString()],
              ["Would Compress", data.compression.would_compress ? "Yes" : "No"],
            ].map(([label, val]) => (
              <div key={String(label)} style={{
                padding: "10px 12px", background: t.surfaceRaised, borderRadius: 8, border: `1px solid ${t.surfaceOverlay}`,
              }}>
                <div style={{
                  fontSize: 16, fontWeight: 600,
                  color: label === "Would Compress" && data.compression.would_compress ? "#4ade80" : t.text,
                }}>{String(val)}</div>
                <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic", marginTop: 8 }}>
            Compression is ephemeral \u2014 it summarises older conversation via a cheap model each turn without modifying stored messages.
          </div>
        </Section>
      )}

      {/* RAG Re-ranking */}
      {data.reranking && (
        <Section title="RAG Re-ranking">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }}>
            {[
              ["Enabled", data.reranking.enabled ? "Yes" : "No"],
              ["Model", data.reranking.model || "\u2014"],
              ["Threshold", `${data.reranking.threshold_chars.toLocaleString()} chars`],
              ["Max Chunks", data.reranking.max_chunks],
              ["RAG Chars", data.reranking.total_rag_chars.toLocaleString()],
              ["Would Rerank", data.reranking.would_rerank ? "Yes" : "No"],
            ].map(([label, val]) => (
              <div key={String(label)} style={{
                padding: "10px 12px", background: t.surfaceRaised, borderRadius: 8, border: `1px solid ${t.surfaceOverlay}`,
              }}>
                <div style={{
                  fontSize: 16, fontWeight: 600,
                  color: label === "Would Rerank" && data.reranking.would_rerank ? "#4ade80" : t.text,
                }}>{String(val)}</div>
                <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic", marginTop: 8 }}>
            Re-ranking uses an LLM to filter RAG chunks across all sources, keeping only the most relevant for the query.
          </div>
        </Section>
      )}

      {/* Effective settings */}
      {data.effective_settings && (
        <Section title="Effective Settings">
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {Object.entries(data.effective_settings).map(([key, setting]) => {
              const badge = SOURCE_BADGE_COLORS[setting.source] || SOURCE_BADGE_COLORS.global;
              return (
                <div key={key} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "8px 12px", background: t.surfaceRaised, borderRadius: 6, border: `1px solid ${t.surfaceOverlay}`,
                }}>
                  <span style={{ fontSize: 12, color: t.textMuted, fontFamily: "monospace" }}>{key}</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 12, color: t.text }}>{String(setting.value)}</span>
                    <span style={{
                      fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4,
                      background: badge.bg, color: badge.fg,
                    }}>
                      {setting.source}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* Disclaimer */}
      <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic", marginTop: 4 }}>
        {data.disclaimer}
      </div>

      {/* Full context preview */}
      <ContextPreview channelId={channelId} />
    </>
  );
}
