import type { ReactNode } from "react";
import { WidgetSettingsSection } from "../WidgetSettingsDrawer";

export type GamePhase = "setup" | "playing" | "ended";

const ACTOR_USER = "__user__";

// ── Participants ───────────────────────────────────────────────────────────

export interface ParticipantSpecies {
  emoji?: string;
  color?: string;
  food?: number;
  traits?: string[];
}

export interface AvailableBot {
  id: string;
  name: string;
}

interface ParticipantsSectionProps {
  bots: AvailableBot[];
  participants: string[];
  /** botId → species record (color, emoji, food). */
  speciesByBotId?: Record<string, ParticipantSpecies>;
  onToggle: (botId: string) => void;
  /** Right-aligned hint override; defaults to "N of M". */
  hint?: ReactNode;
  /** Custom label for the picker entries when no species record exists. */
  defaultEmoji?: string;
  /** Custom default color for the active stripe. */
  defaultColor?: string;
}

export function GameParticipantsSection({
  bots,
  participants,
  speciesByBotId = {},
  onToggle,
  hint,
  defaultEmoji = "🌱",
  defaultColor = "#7aa2c8",
}: ParticipantsSectionProps) {
  return (
    <WidgetSettingsSection
      label="Species"
      hint={hint ?? `${participants.length} of ${bots.length}`}
    >
      <div className="flex flex-col gap-1">
        {bots.length === 0 && (
          <span className="text-[11px] text-text-dim italic">No bots configured.</span>
        )}
        {bots.map((b) => {
          const active = participants.includes(b.id);
          const sp = speciesByBotId[b.id];
          const color = sp?.color ?? defaultColor;
          const emoji = sp?.emoji ?? (active ? defaultEmoji : "·");
          return (
            <button
              key={b.id}
              type="button"
              onClick={() => onToggle(b.id)}
              className="flex flex-row items-center gap-2 px-2 py-1.5 rounded text-[12px] text-left transition-colors hover:bg-surface"
              style={{
                background: active ? `${color}1f` : "transparent",
                border: `1px solid ${active ? `${color}66` : "transparent"}`,
              }}
            >
              <span className="w-6 text-center">{emoji}</span>
              <span className="flex-1 truncate" style={{ color: active ? color : undefined }}>
                {b.name}
              </span>
              {active && sp && typeof sp.food === "number" && (
                <span className="text-[10px] text-text-dim">food {sp.food}</span>
              )}
            </button>
          );
        })}
      </div>
    </WidgetSettingsSection>
  );
}

// ── Phase controls ─────────────────────────────────────────────────────────

interface PhaseSectionProps {
  phase: GamePhase;
  participantCount: number;
  busy: boolean;
  /** Render the primary CTA text differently per game (e.g. "Start game"). */
  startLabel?: string;
  /** Whether to show the "advance round" button while playing. Defaults true. */
  allowAdvanceRound?: boolean;
  onSetPhase: (phase: GamePhase) => void;
  onAdvanceRound?: () => void;
}

export function GamePhaseSection({
  phase,
  participantCount,
  busy,
  startLabel = "Start game",
  allowAdvanceRound = true,
  onSetPhase,
  onAdvanceRound,
}: PhaseSectionProps) {
  return (
    <WidgetSettingsSection label="Phase">
      <div className="flex flex-row gap-1.5">
        {phase === "setup" && (
          <button
            type="button"
            disabled={participantCount === 0 || busy}
            onClick={() => onSetPhase("playing")}
            className="flex-1 px-2 py-1.5 rounded text-[11px] font-medium bg-accent text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-accent/90"
          >
            {startLabel}
          </button>
        )}
        {phase === "playing" && (
          <>
            {allowAdvanceRound && onAdvanceRound && (
              <button
                type="button"
                onClick={onAdvanceRound}
                className="flex-1 px-2 py-1.5 rounded text-[11px] border border-surface-border hover:bg-surface"
              >
                Advance round
              </button>
            )}
            <button
              type="button"
              onClick={() => onSetPhase("ended")}
              className="px-2 py-1.5 rounded text-[11px] border border-surface-border text-text-dim hover:text-text"
            >
              End
            </button>
          </>
        )}
        {phase === "ended" && (
          <button
            type="button"
            onClick={() => onSetPhase("playing")}
            className="flex-1 px-2 py-1.5 rounded text-[11px] border border-surface-border hover:bg-surface"
          >
            Resume
          </button>
        )}
      </div>
    </WidgetSettingsSection>
  );
}

// ── Turn log ───────────────────────────────────────────────────────────────

export interface GameTurnLogEntry {
  actor: string;
  action: string;
  reasoning?: string | null;
  summary?: string | null;
  ts?: string;
}

interface TurnLogSectionProps {
  log: GameTurnLogEntry[];
  /** botId → display data so actors render with names + colors. */
  actorMeta?: Record<string, { name?: string; color?: string }>;
  /** Trim to the most recent N entries (newest first). Default 50. */
  limit?: number;
}

export function GameTurnLogSection({ log, actorMeta = {}, limit = 50 }: TurnLogSectionProps) {
  return (
    <WidgetSettingsSection label="Turn log" hint={String(log.length)}>
      <div className="rounded border border-surface-border bg-surface max-h-48 overflow-y-auto">
        {log.length === 0 && (
          <div className="px-2 py-1.5 text-[11px] text-text-dim italic">No turns yet.</div>
        )}
        {[...log].reverse().slice(0, limit).map((entry, i) => {
          const meta = actorMeta[entry.actor];
          const color = meta?.color ?? undefined;
          const actorLabel = entry.actor === ACTOR_USER ? "you" : (meta?.name ?? entry.actor);
          return (
            <div
              key={i}
              className="px-2 py-1 text-[11px] leading-snug border-b border-surface-border/40 last:border-0"
            >
              <span className="font-mono text-[10px] mr-1" style={{ color }}>
                {actorLabel}
              </span>
              <span>{entry.summary || entry.action}</span>
              {entry.reasoning && (
                <span className="text-text-dim italic"> — {entry.reasoning}</span>
              )}
            </div>
          );
        })}
      </div>
    </WidgetSettingsSection>
  );
}
