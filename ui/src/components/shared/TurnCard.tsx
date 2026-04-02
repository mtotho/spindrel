import { AlertTriangle, Clock, Zap } from "lucide-react";
import { ToolCallsList } from "./ToolCallsList";
import { formatTimeCompact, formatDateShort, formatDuration, formatTokens } from "@/src/utils/time";
import { useThemeTokens } from "@/src/theme/tokens";
import type { TurnSummary } from "@/src/api/hooks/useTurns";

export interface TurnCardProps {
  turn: TurnSummary;
  isMobile: boolean;
  bots?: { id: string; name?: string }[];
  onPress: (correlationId: string) => void;
  showBotBadge?: boolean;
  showChannelBadge?: boolean;
}

export function TurnCard({
  turn, isMobile, bots, onPress,
  showBotBadge = true, showChannelBadge = true,
}: TurnCardProps) {
  const t = useThemeTokens();
  const botName = bots?.find((b) => b.id === turn.bot_id)?.name || turn.bot_id || "";

  return (
    <div
      onClick={() => onPress(turn.correlation_id)}
      style={{
        padding: isMobile ? "10px 12px" : "12px 20px",
        borderBottom: `1px solid ${t.surfaceRaised}`,
        cursor: "pointer",
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = t.surfaceRaised)}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {/* Header line: time + bot + channel + error badge */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        fontSize: 11, color: t.textDim, marginBottom: 4,
      }}>
        <span>{formatDateShort(turn.created_at)} {formatTimeCompact(turn.created_at)}</span>
        {showBotBadge && botName && (
          <span style={{
            background: "rgba(99,102,241,0.1)", color: "#4f46e5",
            padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 600,
          }}>{botName}</span>
        )}
        {showChannelBadge && turn.channel_name && (
          <span style={{
            background: "rgba(20,184,166,0.1)", color: "#0d9488",
            padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 600,
          }}>{turn.channel_name}</span>
        )}
        {turn.model && !isMobile && (
          <span style={{ fontSize: 10, color: t.textDim }}>{turn.model}</span>
        )}
        {turn.has_error && (
          <span style={{
            display: "flex", alignItems: "center", gap: 3,
            background: t.dangerSubtle, color: t.danger,
            padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 600,
          }}>
            <AlertTriangle size={10} /> Error
          </span>
        )}
      </div>

      {/* User message */}
      <div style={{
        fontSize: 13, color: t.text, lineHeight: "1.4",
        overflow: "hidden",
        display: "-webkit-box",
        WebkitLineClamp: 3,
        WebkitBoxOrient: "vertical",
      }}>
        {turn.user_message || "(no message)"}
      </div>

      {/* Response preview */}
      {turn.response_preview && (
        <div style={{
          fontSize: 12, color: t.textMuted, marginTop: 4,
          lineHeight: "1.4",
          overflow: "hidden",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}>
          {turn.response_preview}
        </div>
      )}

      {/* Tool calls */}
      <ToolCallsList toolCalls={turn.tool_calls} />

      {/* Errors */}
      {turn.errors.length > 0 && (
        <div style={{ marginTop: 6 }}>
          {turn.errors.map((err, i) => (
            <div key={i} style={{
              fontSize: 11, color: t.danger, background: t.dangerSubtle,
              padding: "4px 8px", borderRadius: 4, marginTop: 2,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {err.event_name && <span style={{ fontWeight: 600 }}>{err.event_name}: </span>}
              {err.message || "Unknown error"}
            </div>
          ))}
        </div>
      )}

      {/* Stats line */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        marginTop: 6, fontSize: 10, color: t.textDim,
      }}>
        {turn.duration_ms != null && (
          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <Clock size={10} /> {formatDuration(turn.duration_ms)}
          </span>
        )}
        {turn.total_tokens > 0 && (
          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
            <Zap size={10} /> {formatTokens(turn.total_tokens)} tokens
          </span>
        )}
        {turn.iterations > 0 && (
          <span>{turn.iterations} iter</span>
        )}
      </div>
    </div>
  );
}
