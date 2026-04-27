import { useEffect, useState, type ReactNode } from "react";
import { Play, Square, RotateCcw, Pause } from "lucide-react";
import { WidgetSettingsSection } from "../WidgetSettingsDrawer";

export type GamePhase = "setup" | "playing" | "ended";

export interface GameDirective {
  theme: string;
  success_criteria?: string | null;
  set_by?: string;
  set_at?: string;
}

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
              className={
                "flex flex-row items-center gap-2 px-2 py-1.5 rounded text-[12px] text-left transition-colors " +
                (active
                  ? "bg-surface-raised text-text"
                  : "hover:bg-surface text-text-dim")
              }
            >
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: active ? color : "transparent", border: `1px solid ${color}` }}
                aria-hidden="true"
              />
              <span className="w-6 text-center">{emoji}</span>
              <span className="flex-1 truncate">{b.name}</span>
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
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-[11px] font-medium bg-accent text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-accent/90"
          >
            <Play size={11} />
            {startLabel}
          </button>
        )}
        {phase === "playing" && (
          <>
            {allowAdvanceRound && onAdvanceRound && (
              <button
                type="button"
                onClick={onAdvanceRound}
                className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-[11px] border border-surface-border hover:bg-surface"
              >
                <RotateCcw size={11} />
                Advance round
              </button>
            )}
            <button
              type="button"
              onClick={() => onSetPhase("ended")}
              className="inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-[11px] border border-surface-border text-text-dim hover:text-text"
            >
              <Square size={11} />
              End
            </button>
          </>
        )}
        {phase === "ended" && (
          <button
            type="button"
            onClick={() => onSetPhase("playing")}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-[11px] border border-surface-border hover:bg-surface"
          >
            <Pause size={11} />
            Resume
          </button>
        )}
      </div>
    </WidgetSettingsSection>
  );
}

// ── Directive ──────────────────────────────────────────────────────────────

interface DirectiveSectionProps {
  directive: GameDirective | null | undefined;
  busy?: boolean;
  /** Plain-text guidance under the textarea. */
  hint?: ReactNode;
  /** Placeholder for the theme textarea. */
  placeholder?: string;
  onSave: (theme: string, successCriteria?: string) => void;
  onClear: () => void;
}

export function GameDirectiveSection({
  directive,
  busy = false,
  hint,
  placeholder = "e.g. build a sea-glass cathedral, tall and translucent",
  onSave,
  onClear,
}: DirectiveSectionProps) {
  const initialTheme = directive?.theme ?? "";
  const initialCriteria = directive?.success_criteria ?? "";
  const [theme, setTheme] = useState(initialTheme);
  const [criteria, setCriteria] = useState(initialCriteria);

  // Re-sync when an external write (e.g. another tab) updates state.
  useEffect(() => {
    setTheme(initialTheme);
    setCriteria(initialCriteria);
  }, [initialTheme, initialCriteria]);

  const dirty = theme.trim() !== initialTheme.trim() || criteria.trim() !== initialCriteria.trim();
  const canSave = theme.trim().length > 0 && dirty && !busy;

  return (
    <WidgetSettingsSection
      label="Directive"
      hint={hint ?? (directive ? "set" : "open")}
    >
      <div className="flex flex-col gap-1.5">
        <textarea
          value={theme}
          onChange={(e) => setTheme(e.target.value)}
          placeholder={placeholder}
          rows={2}
          className="w-full resize-none rounded border border-surface-border bg-surface px-2 py-1.5 text-[12px] leading-snug placeholder:text-text-dim focus:outline-none focus:border-accent"
        />
        <input
          type="text"
          value={criteria}
          onChange={(e) => setCriteria(e.target.value)}
          placeholder="Optional success criteria"
          className="w-full rounded border border-surface-border bg-surface px-2 py-1.5 text-[11px] placeholder:text-text-dim focus:outline-none focus:border-accent"
        />
        <div className="flex flex-row gap-1.5">
          <button
            type="button"
            disabled={!canSave}
            onClick={() => onSave(theme.trim(), criteria.trim() || undefined)}
            className="flex-1 px-2 py-1.5 rounded text-[11px] font-medium bg-accent text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-accent/90"
          >
            {directive ? "Update" : "Set directive"}
          </button>
          {directive && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setTheme("");
                setCriteria("");
                onClear();
              }}
              className="px-2 py-1.5 rounded text-[11px] border border-surface-border text-text-dim hover:text-text"
            >
              Clear
            </button>
          )}
        </div>
      </div>
    </WidgetSettingsSection>
  );
}

// ── Editable world (bounds + blocks-per-turn) ──────────────────────────────

interface WorldEditableSectionProps {
  bounds: { x: number; y: number; z: number };
  blocksPerTurn: number;
  phase: GamePhase;
  totalBlocks: number;
  /** Inclusive bound limits for axis spinners. */
  minAxis?: number;
  maxAxis?: number;
  maxBlocksPerTurn?: number;
  busy?: boolean;
  onSetBounds: (x: number, y: number, z: number) => void;
  onSetBlocksPerTurn: (count: number) => void;
}

export function GameWorldEditableSection({
  bounds,
  blocksPerTurn,
  phase,
  totalBlocks,
  minAxis = 4,
  maxAxis = 64,
  maxBlocksPerTurn = 5,
  busy = false,
  onSetBounds,
  onSetBlocksPerTurn,
}: WorldEditableSectionProps) {
  const boundsLocked = phase !== "setup";
  const [draftX, setDraftX] = useState(bounds.x);
  const [draftY, setDraftY] = useState(bounds.y);
  const [draftZ, setDraftZ] = useState(bounds.z);

  useEffect(() => {
    setDraftX(bounds.x);
    setDraftY(bounds.y);
    setDraftZ(bounds.z);
  }, [bounds.x, bounds.y, bounds.z]);

  const boundsDirty = draftX !== bounds.x || draftY !== bounds.y || draftZ !== bounds.z;
  const clamp = (n: number) => Math.max(minAxis, Math.min(maxAxis, Math.floor(n) || minAxis));

  return (
    <WidgetSettingsSection label="World">
      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-3 gap-1.5">
          {(["x", "y", "z"] as const).map((axis) => {
            const value = axis === "x" ? draftX : axis === "y" ? draftY : draftZ;
            const setter = axis === "x" ? setDraftX : axis === "y" ? setDraftY : setDraftZ;
            return (
              <label key={axis} className="flex flex-col gap-0.5 text-[10px] text-text-dim">
                <span className="uppercase tracking-wide">{axis}</span>
                <input
                  type="number"
                  min={minAxis}
                  max={maxAxis}
                  value={value}
                  disabled={boundsLocked || busy}
                  onChange={(e) => setter(clamp(Number(e.target.value)))}
                  className="rounded border border-surface-border bg-surface px-2 py-1 text-[12px] text-text font-mono disabled:opacity-50 focus:outline-none focus:border-accent"
                />
              </label>
            );
          })}
        </div>
        {!boundsLocked && (
          <button
            type="button"
            disabled={!boundsDirty || busy}
            onClick={() => onSetBounds(clamp(draftX), clamp(draftY), clamp(draftZ))}
            className="px-2 py-1.5 rounded text-[11px] border border-surface-border hover:bg-surface disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Apply bounds
          </button>
        )}
        {boundsLocked && (
          <p className="text-[10px] text-text-dim italic">
            Bounds are locked once the game starts. End and re-setup to change.
          </p>
        )}
        <div className="flex items-center justify-between gap-2 pt-1 border-t border-surface-border/40">
          <label className="flex flex-col gap-0.5 text-[10px] text-text-dim flex-1">
            <span className="uppercase tracking-wide">Blocks per turn</span>
            <input
              type="number"
              min={1}
              max={maxBlocksPerTurn}
              value={blocksPerTurn}
              disabled={busy}
              onChange={(e) => {
                const next = Math.max(1, Math.min(maxBlocksPerTurn, Math.floor(Number(e.target.value)) || 1));
                if (next !== blocksPerTurn) onSetBlocksPerTurn(next);
              }}
              className="rounded border border-surface-border bg-surface px-2 py-1 text-[12px] text-text font-mono focus:outline-none focus:border-accent"
            />
          </label>
          <div className="text-[11px] text-text-dim font-mono pt-3">
            {totalBlocks} placed
          </div>
        </div>
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
