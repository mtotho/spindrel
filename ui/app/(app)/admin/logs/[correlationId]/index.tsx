import { useState } from "react";
import { View, Text, Pressable, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft, ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import { useTrace, type TraceEvent } from "@/src/api/hooks/useLogs";
import { useThemeTokens } from "@/src/theme/tokens";

// ---------------------------------------------------------------------------
// Colors
// ---------------------------------------------------------------------------
const DOT_COLORS: Record<string, string> = {
  tool_call:            "#4f46e5",
  memory_injection:     "#7c3aed",
  skill_context:        "#0d9488",
  knowledge_context:    "#2563eb",
  tool_retrieval:       "#ca8a04",
  context_compressed:   "#65a30d",
  context_breakdown:    "#0891b2",
  token_usage:          "#999",
  error:                "#dc2626",
  harness:              "#d97706",
  response:             "#16a34a",
  message:              "#4f46e5",
};

const BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  tool_call:            { bg: "rgba(99,102,241,0.12)",  fg: "#4f46e5" },
  memory_injection:     { bg: "rgba(168,85,247,0.12)",  fg: "#9333ea" },
  skill_context:        { bg: "rgba(20,184,166,0.12)",  fg: "#0d9488" },
  knowledge_context:    { bg: "rgba(59,130,246,0.12)",  fg: "#2563eb" },
  tool_retrieval:       { bg: "rgba(234,179,8,0.12)",   fg: "#ca8a04" },
  context_compressed:   { bg: "rgba(132,204,22,0.12)",  fg: "#65a30d" },
  context_breakdown:    { bg: "rgba(6,182,212,0.12)",   fg: "#0891b2" },
  token_usage:          { bg: "rgba(107,114,128,0.12)", fg: "#6b7280" },
  error:                { bg: "rgba(239,68,68,0.12)",   fg: "#dc2626" },
  harness:              { bg: "rgba(234,179,8,0.12)",   fg: "#b45309" },
  response:             { bg: "rgba(34,197,94,0.12)",   fg: "#16a34a" },
  message:              { bg: "rgba(99,102,241,0.12)",  fg: "#4f46e5" },
};

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3 } as any);
}

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function getEventType(ev: TraceEvent): string {
  if (ev.kind === "tool_call") return "tool_call";
  if (ev.kind === "message") return "message";
  return ev.event_type || "trace_event";
}

function getEventLabel(ev: TraceEvent): string {
  if (ev.kind === "tool_call") return ev.tool_name || "tool_call";
  if (ev.kind === "message") return ev.role === "user" ? "User Message" : "Assistant Response";
  return ev.event_name || ev.event_type || "event";
}

// ---------------------------------------------------------------------------
// Copy formatter
// ---------------------------------------------------------------------------
function formatTraceForCopy(data: import("@/src/api/hooks/useLogs").TraceDetailResponse): string {
  const lines: string[] = [];

  lines.push(`=== Request Trace ===`);
  lines.push(`Correlation: ${data.correlation_id}`);
  if (data.bot_id) lines.push(`Bot: ${data.bot_id}`);
  if (data.session_id) lines.push(`Session: ${data.session_id}`);
  if (data.client_id) lines.push(`Client: ${data.client_id}`);
  if (data.time_range_start && data.time_range_end) {
    lines.push(`Time: ${fmtTime(data.time_range_start)} — ${fmtTime(data.time_range_end)}`);
  }
  lines.push("");

  for (const ev of data.events) {
    const time = fmtTime(ev.created_at);
    const dur = ev.duration_ms != null ? ` (${fmtDuration(ev.duration_ms)})` : "";

    if (ev.kind === "message") {
      const role = ev.role === "user" ? "USER" : "ASSISTANT";
      lines.push(`--- ${role} [${time}] ---`);
      lines.push(ev.content || "[empty]");
      lines.push("");
    } else if (ev.kind === "tool_call") {
      lines.push(`[${time}]${dur} TOOL: ${ev.tool_name || "unknown"}${ev.tool_type ? ` [${ev.tool_type}]` : ""}`);
      if (ev.arguments && Object.keys(ev.arguments).length > 0) {
        lines.push(`  Args: ${JSON.stringify(ev.arguments, null, 2).split("\n").join("\n  ")}`);
      }
      if (ev.result) {
        const result = ev.result.length > 2000 ? ev.result.substring(0, 2000) + "... [truncated]" : ev.result;
        lines.push(`  Result: ${result}`);
      }
      if (ev.error) lines.push(`  ERROR: ${ev.error}`);
      lines.push("");
    } else {
      const evType = ev.event_type || "trace_event";
      const evName = ev.event_name || ev.event_type || "event";
      lines.push(`[${time}]${dur} ${evType.toUpperCase()}: ${evName}`);
      if (ev.count != null) lines.push(`  Count: ${ev.count}`);
      if (ev.error) lines.push(`  ERROR: ${ev.error}`);
      if (ev.data) {
        lines.push(`  Data: ${JSON.stringify(ev.data, null, 2).split("\n").join("\n  ")}`);
      }
      lines.push("");
    }
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
export default function TraceScreen() {
  const t = useThemeTokens();
  const { correlationId } = useLocalSearchParams<{ correlationId: string }>();
  const goBack = useGoBack("/admin/logs");
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const { data, isLoading } = useTrace(correlationId);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (!data) return;
    const text = formatTraceForCopy(data);
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      // Fallback for non-HTTPS contexts
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  if (!data) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <Text className="text-text-muted">Trace not found.</Text>
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: isMobile ? "10px 12px" : "12px 20px",
        borderBottom: `1px solid ${t.surfaceOverlay}`,
      }}>
        <Pressable onPress={goBack} style={{ padding: 4 }}>
          <ArrowLeft size={18} color={t.textMuted} />
        </Pressable>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Request Trace</div>
          <div style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
            {correlationId}
          </div>
        </div>
        <button
          onClick={handleCopy}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 12px", borderRadius: 6, border: "none", cursor: "pointer",
            background: copied ? "rgba(34,197,94,0.15)" : t.surfaceRaised,
            color: copied ? "#22c55e" : t.textMuted, fontSize: 12,
          }}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      {/* Metadata bar */}
      <div style={{
        display: "flex", gap: 16, padding: isMobile ? "8px 12px" : "8px 20px",
        borderBottom: `1px solid ${t.surfaceRaised}`, flexWrap: "wrap", fontSize: 12,
      }}>
        {data.bot_id && (
          <span><span style={{ color: t.textDim }}>Bot: </span><span style={{ color: t.textMuted }}>{data.bot_id}</span></span>
        )}
        {data.session_id && (
          <span><span style={{ color: t.textDim }}>Session: </span><span style={{ color: t.textMuted, fontFamily: "monospace", fontSize: 11 }}>{data.session_id.substring(0, 12)}...</span></span>
        )}
        {data.client_id && (
          <span><span style={{ color: t.textDim }}>Client: </span><span style={{ color: t.textMuted }}>{data.client_id}</span></span>
        )}
        {data.time_range_start && data.time_range_end && (
          <span><span style={{ color: t.textDim }}>Duration: </span><span style={{ color: t.textMuted }}>
            {fmtTime(data.time_range_start)} — {fmtTime(data.time_range_end)}
          </span></span>
        )}
      </div>

      {/* Timeline */}
      <ScrollView className="flex-1" contentContainerStyle={{ padding: isMobile ? 12 : 20 }}>
        <div style={{
          position: "relative", paddingLeft: 24,
          borderLeft: `2px solid ${t.surfaceOverlay}`, marginLeft: 8,
        }}>
          {data.events.map((ev, i) => (
            <TimelineEvent key={i} event={ev} isMobile={isMobile} />
          ))}
        </div>
      </ScrollView>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Timeline event card
// ---------------------------------------------------------------------------
function TimelineEvent({ event: ev, isMobile }: { event: TraceEvent; isMobile: boolean }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const evType = getEventType(ev);
  const label = getEventLabel(ev);
  const dotColor = DOT_COLORS[evType] ?? t.textDim;
  const badge = BADGE_COLORS[evType] ?? { bg: t.surfaceBorder, fg: t.textMuted };
  const isMessage = ev.kind === "message";
  const isExpandable = !isMessage && !!(ev.arguments || ev.result || ev.error || ev.data);

  // Message cards
  if (isMessage) {
    const isUser = ev.role === "user";
    return (
      <div style={{ position: "relative", marginBottom: 12 }}>
        {/* Dot */}
        <div style={{
          position: "absolute", left: -30, top: 10,
          width: 10, height: 10, borderRadius: 5,
          background: isUser ? "#818cf8" : "#16a34a",
          border: `2px solid ${t.surface}`,
        }} />
        <div style={{
          background: isUser ? "rgba(99,102,241,0.08)" : "rgba(34,197,94,0.06)",
          border: `1px solid ${isUser ? "rgba(99,102,241,0.2)" : "rgba(34,197,94,0.15)"}`,
          borderRadius: 8, padding: "10px 14px",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: isUser ? "#6366f1" : "#16a34a" }}>
              {isUser ? "User" : "Assistant"}
            </span>
            <span style={{ fontSize: 10, color: t.textDim }}>{fmtTime(ev.created_at)}</span>
          </div>
          <div style={{
            fontSize: 13, color: t.contentText, whiteSpace: "pre-wrap", wordBreak: "break-word",
            maxHeight: expanded ? undefined : 200, overflow: expanded ? undefined : "hidden",
          }}>
            {ev.content || "[empty]"}
          </div>
          {(ev.content?.length ?? 0) > 400 && (
            <button
              onClick={() => setExpanded(!expanded)}
              style={{ background: "none", border: "none", color: t.textDim, cursor: "pointer", fontSize: 11, marginTop: 4 }}
            >
              {expanded ? "Show less" : "Show more..."}
            </button>
          )}
        </div>
      </div>
    );
  }

  // Tool call / trace event cards
  return (
    <div style={{ position: "relative", marginBottom: 8 }}>
      {/* Dot */}
      <div style={{
        position: "absolute", left: -30, top: 10,
        width: 10, height: 10, borderRadius: 5,
        background: dotColor, border: `2px solid ${t.surface}`,
      }} />

      <div style={{
        background: t.inputBg, border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8,
        overflow: "hidden",
      }}>
        {/* Header row */}
        <div
          onClick={() => isExpandable && setExpanded(!expanded)}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "8px 12px", cursor: isExpandable ? "pointer" : "default",
          }}
        >
          {/* Badge */}
          <span style={{
            fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4,
            background: badge.bg, color: badge.fg, whiteSpace: "nowrap",
          }}>
            {evType}
          </span>

          {/* Label + inline metadata */}
          <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {label}
            {ev.count != null && <span style={{ color: t.textDim, marginLeft: 6, fontSize: 10 }}>({ev.count} items)</span>}
            {ev.kind === "tool_call" && ev.tool_type && (
              <span style={{ color: t.textDim, marginLeft: 6, fontSize: 10 }}>[{ev.tool_type}]</span>
            )}
            {evType === "context_compressed" && ev.data && (
              <span style={{ color: t.textDim, marginLeft: 6, fontSize: 10 }}>
                {ev.data.original_chars ?? "?"}→{ev.data.compressed_chars ?? "?"} chars
              </span>
            )}
            {evType === "token_usage" && ev.data && (
              <span style={{ color: t.textDim, marginLeft: 6, fontSize: 10 }}>
                {ev.data.prompt_tokens ?? "?"}+{ev.data.completion_tokens ?? "?"}={ev.data.total_tokens ?? "?"}
              </span>
            )}
          </span>

          {/* Duration + time */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {ev.duration_ms != null && (
              <span style={{ fontSize: 10, color: t.textDim }}>{fmtDuration(ev.duration_ms)}</span>
            )}
            <span style={{ fontSize: 10, color: t.textDim }}>{fmtTime(ev.created_at)}</span>
            {isExpandable && (
              expanded
                ? <ChevronDown size={14} color={t.textDim} />
                : <ChevronRight size={14} color={t.textDim} />
            )}
          </div>
        </div>

        {/* Error banner (always visible) */}
        {ev.error && (
          <div style={{
            background: "rgba(127,29,29,0.2)", padding: "6px 12px",
            fontSize: 12, color: "#dc2626", borderTop: `1px solid ${t.surfaceOverlay}`,
          }}>
            {ev.error}
          </div>
        )}

        {/* Expanded details */}
        {expanded && (
          <div style={{ borderTop: "1px solid #2a2a2a" }}>
            {ev.arguments && Object.keys(ev.arguments).length > 0 && (
              <DetailSection title="Arguments">
                <pre style={{ fontSize: 11, color: t.textMuted, whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
                  {JSON.stringify(ev.arguments, null, 2)}
                </pre>
              </DetailSection>
            )}
            {ev.result && (
              <DetailSection title="Result">
                <pre style={{ fontSize: 11, color: t.textMuted, whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
                  {ev.result}
                </pre>
              </DetailSection>
            )}
            {ev.data && evType === "context_breakdown" && Array.isArray(ev.data.breakdown) ? (
              <DetailSection title="Context Breakdown">
                <table style={{ fontSize: 11, color: t.textMuted, borderCollapse: "collapse", width: "100%" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "2px 8px", color: t.textDim, fontWeight: 600 }}>Role</th>
                      <th style={{ textAlign: "right", padding: "2px 8px", color: t.textDim, fontWeight: 600 }}>Msgs</th>
                      <th style={{ textAlign: "right", padding: "2px 8px", color: t.textDim, fontWeight: 600 }}>Chars</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ev.data.breakdown.map((b: any, i: number) => (
                      <tr key={i}>
                        <td style={{ padding: "2px 8px" }}>{b.role ?? b.type ?? "—"}</td>
                        <td style={{ padding: "2px 8px", textAlign: "right" }}>{b.count ?? b.messages ?? "—"}</td>
                        <td style={{ padding: "2px 8px", textAlign: "right" }}>{(b.chars ?? b.characters)?.toLocaleString() ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </DetailSection>
            ) : ev.data && (
              <DetailSection title="Data">
                <pre style={{ fontSize: 11, color: t.textMuted, whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
                  {JSON.stringify(ev.data, null, 2)}
                </pre>
              </DetailSection>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  const t = useThemeTokens();
  return (
    <div style={{ padding: "8px 12px", borderBottom: `1px solid ${t.surfaceRaised}` }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
        {title}
      </div>
      {children}
    </div>
  );
}
