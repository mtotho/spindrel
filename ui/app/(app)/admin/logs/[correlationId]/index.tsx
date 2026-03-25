import { useState } from "react";
import { View, Text, Pressable, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useGoBack } from "@/src/hooks/useGoBack";
import { ArrowLeft, ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import { useTrace, type TraceEvent } from "@/src/api/hooks/useLogs";

// ---------------------------------------------------------------------------
// Colors
// ---------------------------------------------------------------------------
const DOT_COLORS: Record<string, string> = {
  tool_call:            "#a5b4fc",
  memory_injection:     "#d8b4fe",
  skill_context:        "#5eead4",
  knowledge_context:    "#93c5fd",
  tool_retrieval:       "#fde047",
  context_compressed:   "#bef264",
  context_breakdown:    "#67e8f9",
  token_usage:          "#999",
  error:                "#fca5a5",
  harness:              "#fbbf24",
  response:             "#86efac",
  message:              "#a5b4fc",
};

const BADGE_COLORS: Record<string, { bg: string; fg: string }> = {
  tool_call:            { bg: "#312e81", fg: "#a5b4fc" },
  memory_injection:     { bg: "#3b0764", fg: "#d8b4fe" },
  skill_context:        { bg: "#134e4a", fg: "#5eead4" },
  knowledge_context:    { bg: "#1e3a5f", fg: "#93c5fd" },
  tool_retrieval:       { bg: "#713f12", fg: "#fde047" },
  context_compressed:   { bg: "#365314", fg: "#bef264" },
  context_breakdown:    { bg: "#164e63", fg: "#67e8f9" },
  token_usage:          { bg: "#333",    fg: "#999"    },
  error:                { bg: "#7f1d1d", fg: "#fca5a5" },
  harness:              { bg: "#78350f", fg: "#fbbf24" },
  response:             { bg: "#166534", fg: "#86efac" },
  message:              { bg: "#312e81", fg: "#a5b4fc" },
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
  const { correlationId } = useLocalSearchParams<{ correlationId: string }>();
  const goBack = useGoBack("/admin/logs");
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const { data, isLoading } = useTrace(correlationId);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    if (!data) return;
    navigator.clipboard.writeText(formatTraceForCopy(data));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color="#3b82f6" />
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
        borderBottom: "1px solid #2a2a2a",
      }}>
        <Pressable onPress={goBack} style={{ padding: 4 }}>
          <ArrowLeft size={18} color="#999" />
        </Pressable>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#e5e5e5" }}>Request Trace</div>
          <div style={{ fontSize: 11, color: "#555", fontFamily: "monospace" }}>
            {correlationId}
          </div>
        </div>
        <button
          onClick={handleCopy}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 12px", borderRadius: 6, border: "none", cursor: "pointer",
            background: copied ? "rgba(34,197,94,0.15)" : "#1a1a1a",
            color: copied ? "#22c55e" : "#999", fontSize: 12,
          }}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      {/* Metadata bar */}
      <div style={{
        display: "flex", gap: 16, padding: isMobile ? "8px 12px" : "8px 20px",
        borderBottom: "1px solid #1a1a1a", flexWrap: "wrap", fontSize: 12,
      }}>
        {data.bot_id && (
          <span><span style={{ color: "#555" }}>Bot: </span><span style={{ color: "#999" }}>{data.bot_id}</span></span>
        )}
        {data.session_id && (
          <span><span style={{ color: "#555" }}>Session: </span><span style={{ color: "#999", fontFamily: "monospace", fontSize: 11 }}>{data.session_id.substring(0, 12)}...</span></span>
        )}
        {data.client_id && (
          <span><span style={{ color: "#555" }}>Client: </span><span style={{ color: "#999" }}>{data.client_id}</span></span>
        )}
        {data.time_range_start && data.time_range_end && (
          <span><span style={{ color: "#555" }}>Duration: </span><span style={{ color: "#999" }}>
            {fmtTime(data.time_range_start)} — {fmtTime(data.time_range_end)}
          </span></span>
        )}
      </div>

      {/* Timeline */}
      <ScrollView className="flex-1" contentContainerStyle={{ padding: isMobile ? 12 : 20 }}>
        <div style={{
          position: "relative", paddingLeft: 24,
          borderLeft: "2px solid #2a2a2a", marginLeft: 8,
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
  const [expanded, setExpanded] = useState(false);
  const evType = getEventType(ev);
  const label = getEventLabel(ev);
  const dotColor = DOT_COLORS[evType] ?? "#666";
  const badge = BADGE_COLORS[evType] ?? { bg: "#333", fg: "#999" };
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
          background: isUser ? "#818cf8" : "#86efac",
          border: "2px solid #0a0a0a",
        }} />
        <div style={{
          background: isUser ? "rgba(99,102,241,0.08)" : "rgba(34,197,94,0.06)",
          border: `1px solid ${isUser ? "rgba(99,102,241,0.2)" : "rgba(34,197,94,0.15)"}`,
          borderRadius: 8, padding: "10px 14px",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: isUser ? "#a5b4fc" : "#86efac" }}>
              {isUser ? "User" : "Assistant"}
            </span>
            <span style={{ fontSize: 10, color: "#555" }}>{fmtTime(ev.created_at)}</span>
          </div>
          <div style={{
            fontSize: 13, color: "#d4d4d4", whiteSpace: "pre-wrap", wordBreak: "break-word",
            maxHeight: expanded ? undefined : 200, overflow: expanded ? undefined : "hidden",
          }}>
            {ev.content || "[empty]"}
          </div>
          {(ev.content?.length ?? 0) > 400 && (
            <button
              onClick={() => setExpanded(!expanded)}
              style={{ background: "none", border: "none", color: "#666", cursor: "pointer", fontSize: 11, marginTop: 4 }}
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
        background: dotColor, border: "2px solid #0a0a0a",
      }} />

      <div style={{
        background: "#111", border: "1px solid #2a2a2a", borderRadius: 8,
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
          <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: "#e5e5e5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {label}
            {ev.count != null && <span style={{ color: "#555", marginLeft: 6, fontSize: 10 }}>({ev.count} items)</span>}
            {ev.kind === "tool_call" && ev.tool_type && (
              <span style={{ color: "#555", marginLeft: 6, fontSize: 10 }}>[{ev.tool_type}]</span>
            )}
            {evType === "context_compressed" && ev.data && (
              <span style={{ color: "#555", marginLeft: 6, fontSize: 10 }}>
                {ev.data.original_chars ?? "?"}→{ev.data.compressed_chars ?? "?"} chars
              </span>
            )}
            {evType === "token_usage" && ev.data && (
              <span style={{ color: "#555", marginLeft: 6, fontSize: 10 }}>
                {ev.data.prompt_tokens ?? "?"}+{ev.data.completion_tokens ?? "?"}={ev.data.total_tokens ?? "?"}
              </span>
            )}
          </span>

          {/* Duration + time */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {ev.duration_ms != null && (
              <span style={{ fontSize: 10, color: "#666" }}>{fmtDuration(ev.duration_ms)}</span>
            )}
            <span style={{ fontSize: 10, color: "#555" }}>{fmtTime(ev.created_at)}</span>
            {isExpandable && (
              expanded
                ? <ChevronDown size={14} color="#555" />
                : <ChevronRight size={14} color="#555" />
            )}
          </div>
        </div>

        {/* Error banner (always visible) */}
        {ev.error && (
          <div style={{
            background: "rgba(127,29,29,0.2)", padding: "6px 12px",
            fontSize: 12, color: "#fca5a5", borderTop: "1px solid #2a2a2a",
          }}>
            {ev.error}
          </div>
        )}

        {/* Expanded details */}
        {expanded && (
          <div style={{ borderTop: "1px solid #2a2a2a" }}>
            {ev.arguments && Object.keys(ev.arguments).length > 0 && (
              <DetailSection title="Arguments">
                <pre style={{ fontSize: 11, color: "#999", whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
                  {JSON.stringify(ev.arguments, null, 2)}
                </pre>
              </DetailSection>
            )}
            {ev.result && (
              <DetailSection title="Result">
                <pre style={{ fontSize: 11, color: "#999", whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
                  {ev.result}
                </pre>
              </DetailSection>
            )}
            {ev.data && evType === "context_breakdown" && Array.isArray(ev.data.breakdown) ? (
              <DetailSection title="Context Breakdown">
                <table style={{ fontSize: 11, color: "#999", borderCollapse: "collapse", width: "100%" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: "2px 8px", color: "#666", fontWeight: 600 }}>Role</th>
                      <th style={{ textAlign: "right", padding: "2px 8px", color: "#666", fontWeight: 600 }}>Msgs</th>
                      <th style={{ textAlign: "right", padding: "2px 8px", color: "#666", fontWeight: 600 }}>Chars</th>
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
                <pre style={{ fontSize: 11, color: "#999", whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}>
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
  return (
    <div style={{ padding: "8px 12px", borderBottom: "1px solid #1a1a1a" }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: "#555", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
        {title}
      </div>
      {children}
    </div>
  );
}
