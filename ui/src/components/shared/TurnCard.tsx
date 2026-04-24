import { AlertTriangle, Clock, Zap } from "lucide-react";
import { ToolCallsList } from "./ToolCallsList";
import { formatTimeCompact, formatDateShort, formatDuration, formatTokens } from "@/src/utils/time";
import { StatusBadge } from "./SettingsControls";
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
  const botName = bots?.find((b) => b.id === turn.bot_id)?.name || turn.bot_id || "";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onPress(turn.correlation_id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onPress(turn.correlation_id);
        }
      }}
      className="w-full rounded-md bg-surface-raised/40 px-3 py-2.5 text-left transition-colors hover:bg-surface-overlay/45 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35"
    >
      <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] text-text-dim">
        <span>{formatDateShort(turn.created_at)} {formatTimeCompact(turn.created_at)}</span>
        {showBotBadge && botName && <StatusBadge label={botName} variant="info" />}
        {showChannelBadge && turn.channel_name && <StatusBadge label={turn.channel_name} variant="neutral" />}
        {turn.model && !isMobile && (
          <span className="text-[10px] text-text-dim">{turn.model}</span>
        )}
        {turn.has_error && (
          <span className="inline-flex items-center gap-1 rounded-full bg-danger/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-danger">
            <AlertTriangle size={10} /> Error
          </span>
        )}
      </div>

      <div className="line-clamp-3 text-[13px] leading-snug text-text">
        {turn.user_message || "(no message)"}
      </div>

      {turn.response_preview && (
        <div className="mt-1 line-clamp-2 text-[12px] leading-snug text-text-muted">
          {turn.response_preview}
        </div>
      )}

      <ToolCallsList toolCalls={turn.tool_calls} />

      {turn.errors.length > 0 && (
        <div className="mt-1.5 flex flex-col gap-1">
          {turn.errors.map((err, i) => (
            <div key={i} className="truncate rounded-md bg-danger/10 px-2 py-1 text-[11px] text-danger">
              {err.event_name && <span className="font-semibold">{err.event_name}: </span>}
              {err.message || "Unknown error"}
            </div>
          ))}
        </div>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[10px] text-text-dim">
        {turn.duration_ms != null && (
          <span className="inline-flex items-center gap-1">
            <Clock size={10} /> {formatDuration(turn.duration_ms)}
          </span>
        )}
        {turn.total_tokens > 0 && (
          <span className="inline-flex items-center gap-1">
            <Zap size={10} /> {formatTokens(turn.total_tokens)} tokens
          </span>
        )}
        {turn.iterations > 0 && <span>{turn.iterations} iter</span>}
      </div>
    </div>
  );
}
