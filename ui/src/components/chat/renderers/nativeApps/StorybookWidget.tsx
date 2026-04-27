import { useEffect, useMemo, useRef, useState } from "react";
import { Settings, BookOpen, Send } from "lucide-react";
import { useBots } from "@/src/api/hooks/useBots";
import {
  PreviewCard,
  type NativeAppRendererProps,
  useNativeEnvelopeState,
} from "./shared";
import { WidgetSettingsDrawer, WidgetSettingsSection } from "./WidgetSettingsDrawer";
import {
  GameDirectiveSection,
  GameParticipantsSection,
  GamePhaseSection,
  GameTurnLogSection,
  type GameDirective,
  type GamePhase,
} from "./games/GameSettingsSections";

interface Stanza {
  actor: string;
  text: string;
  ts?: string;
  sentences?: number;
}

interface TurnLogEntry {
  actor: string;
  ts: string;
  action: string;
  args?: Record<string, unknown>;
  reasoning?: string | null;
  summary?: string | null;
}

interface StorybookState {
  game_type?: string;
  phase?: GamePhase;
  participants?: string[];
  last_actor?: string | null;
  round?: number;
  turn_log?: TurnLogEntry[];
  title?: string;
  genre?: string;
  stanza_cap?: number;
  sentence_cap_per_turn?: number;
  stanzas?: Stanza[];
  directive?: GameDirective | null;
}

const ACTOR_USER = "__user__";

function countSentences(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  const matches = trimmed.match(/[.!?]+(?:\s|$)/g);
  if (!matches) return 1;
  return /[.!?]\s*$/.test(trimmed) ? matches.length : matches.length + 1;
}

function relativeTime(iso?: string): string {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return "";
  const delta = Date.now() - ts;
  const sec = Math.round(delta / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

export function StorybookWidget({
  envelope,
  dashboardPinId,
  channelId,
  t,
}: NativeAppRendererProps) {
  const { currentPayload, dispatchNativeAction } = useNativeEnvelopeState(
    envelope,
    "core/game_storybook",
    channelId,
    dashboardPinId,
  );
  const widgetInstanceId = currentPayload.widget_instance_id;
  const state = (currentPayload.state ?? {}) as StorybookState;
  const phase: GamePhase = state.phase ?? "setup";
  const title = (state.title ?? "").trim();
  const genre = (state.genre ?? "").trim();
  const stanzaCap = state.stanza_cap ?? 12;
  const sentenceCap = state.sentence_cap_per_turn ?? 3;
  const stanzas = state.stanzas ?? [];
  const participants = state.participants ?? [];
  const turnLog = state.turn_log ?? [];
  const round = state.round ?? 0;
  const lastActor = state.last_actor ?? null;
  const directive = state.directive ?? null;

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const draftRef = useRef<HTMLTextAreaElement | null>(null);
  const columnRef = useRef<HTMLDivElement | null>(null);

  const { data: bots } = useBots();
  const botById = useMemo(() => {
    const map = new Map<string, { id: string; name: string }>();
    (bots ?? []).forEach((b) => map.set(b.id, { id: b.id, name: b.name ?? b.id }));
    return map;
  }, [bots]);
  const availableBots = useMemo(() => Array.from(botById.values()), [botById]);

  const userIsParticipant =
    participants.includes(ACTOR_USER) || participants.length === 0;

  // Whose turn is it? Bot turn order is implicit (anyone can go) but the
  // user can compose any time the game is playing. Show the textarea when
  // the game is playing and either it's the user's "first move" of the
  // round (last_actor !== ACTOR_USER) OR the user is just an observer
  // adding their own stanza.
  const userTurnHinted = phase === "playing" && lastActor !== ACTOR_USER;

  // Auto-scroll to the latest stanza on update.
  useEffect(() => {
    if (!columnRef.current) return;
    columnRef.current.scrollTop = columnRef.current.scrollHeight;
  }, [stanzas.length]);

  if (!widgetInstanceId) {
    return (
      <PreviewCard
        title="Storybook"
        description="Round-robin story completer. Pin to begin."
        t={t}
      />
    );
  }

  async function runAction(
    action: string,
    args: Record<string, unknown>,
    busyKey = action,
  ) {
    setBusy(busyKey);
    setError(null);
    try {
      await dispatchNativeAction(action, args);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  function toggleParticipant(botId: string) {
    const next = participants.includes(botId)
      ? participants.filter((id) => id !== botId)
      : [...participants, botId];
    void runAction("set_participants", { bot_ids: next });
  }

  async function submitDraft() {
    const text = draft.trim();
    if (!text) return;
    const sentences = countSentences(text);
    if (sentences > sentenceCap) {
      setError(`That's ${sentences} sentences — the cap is ${sentenceCap}. Trim it down.`);
      return;
    }
    await runAction("add_stanza", { text }, "add_stanza");
    setDraft("");
  }

  const sentenceCount = countSentences(draft);

  const actorMeta = useMemo(() => {
    const out: Record<string, { name?: string; color?: string }> = {};
    for (const id of participants) {
      out[id] = { name: botById.get(id)?.name };
    }
    return out;
  }, [participants, botById]);

  const speciesByBotId = useMemo(() => {
    const map: Record<string, { color?: string; emoji?: string; food?: number }> = {};
    for (const id of participants) {
      map[id] = { emoji: "✒︎" };
    }
    return map;
  }, [participants]);

  return (
    <div className="storybook-stage relative flex flex-col w-full h-full min-h-0 overflow-hidden bg-surface-raised">
      {/* Top header bar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-surface-border/60 flex-shrink-0">
        <BookOpen size={14} className="text-text-dim flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-[12px] font-medium truncate text-text">
            {title || "Untitled"}
          </div>
          <div className="text-[10px] text-text-dim truncate">
            {genre ? `${genre} · ` : ""}
            stanza {stanzas.length}/{stanzaCap}
            {phase === "playing" ? ` · round ${round}` : ` · ${phase}`}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="p-1.5 rounded text-text-dim hover:text-text hover:bg-surface transition-colors"
          aria-label="Settings"
        >
          <Settings size={14} />
        </button>
      </div>

      {/* Directive banner */}
      {directive && (
        <div className="px-3 py-1.5 bg-accent/5 border-b border-accent/20 text-[11px] text-text-dim flex-shrink-0">
          <span className="font-medium text-accent">Directive:</span> {directive.theme}
          {directive.success_criteria && (
            <span className="italic"> — {directive.success_criteria}</span>
          )}
        </div>
      )}

      {/* Manuscript column */}
      <div
        ref={columnRef}
        className="flex-1 min-h-0 overflow-y-auto px-6 py-5"
        style={{ fontFamily: "Georgia, 'Iowan Old Style', serif" }}
      >
        <div className="max-w-prose mx-auto">
          {phase === "setup" && stanzas.length === 0 && (
            <div className="text-center text-text-dim text-[13px] italic">
              {participants.length === 0
                ? "Add at least one participant to begin writing."
                : "Press Start in settings to begin the story."}
            </div>
          )}
          {stanzas.map((stanza, i) => {
            const isUser = stanza.actor === ACTOR_USER;
            const name = isUser ? "You" : (botById.get(stanza.actor)?.name ?? stanza.actor);
            return (
              <div key={i} className="mb-5 last:mb-2">
                <div className="flex items-center gap-2 mb-1 text-[10px] uppercase tracking-wider text-text-dim font-sans">
                  <span className="font-medium text-text">{name}</span>
                  <span className="text-text-dim/60">·</span>
                  <span>round {Math.floor(i / Math.max(1, participants.length || 1)) + 1}</span>
                  {stanza.ts && (
                    <>
                      <span className="text-text-dim/60">·</span>
                      <span>{relativeTime(stanza.ts)}</span>
                    </>
                  )}
                </div>
                <p className="text-[14px] leading-relaxed text-text whitespace-pre-wrap">
                  {stanza.text}
                </p>
              </div>
            );
          })}
          {phase === "ended" && (
            <div className="mt-6 pt-4 border-t border-surface-border text-center text-[11px] uppercase tracking-widest text-text-dim font-sans">
              ◆ End ◆
            </div>
          )}
        </div>
      </div>

      {/* Composer */}
      {phase === "playing" && userIsParticipant && (
        <div className="border-t border-surface-border/60 bg-surface flex-shrink-0">
          {error && (
            <div className="px-3 py-1.5 text-[11px] text-danger bg-danger/10 border-b border-danger/30">
              {error}
            </div>
          )}
          <div className="flex items-end gap-2 px-3 py-2">
            <textarea
              ref={draftRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  void submitDraft();
                }
              }}
              placeholder={
                userTurnHinted
                  ? "Continue the story — 1–" + sentenceCap + " sentence(s)…"
                  : "Add to the story when you're ready…"
              }
              rows={2}
              className="flex-1 resize-none rounded border border-surface-border bg-surface-raised px-2 py-1.5 text-[13px] text-text placeholder:text-text-dim focus:outline-none focus:border-accent"
              style={{ fontFamily: "Georgia, 'Iowan Old Style', serif" }}
            />
            <div className="flex flex-col items-end gap-1 flex-shrink-0">
              <span
                className={
                  "text-[10px] font-mono " +
                  (sentenceCount > sentenceCap ? "text-danger" : "text-text-dim")
                }
              >
                {sentenceCount}/{sentenceCap}
              </span>
              <button
                type="button"
                disabled={!draft.trim() || busy === "add_stanza" || sentenceCount > sentenceCap}
                onClick={() => void submitDraft()}
                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded text-[11px] font-medium bg-accent text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-accent/90"
              >
                <Send size={11} />
                Send
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Settings drawer */}
      <WidgetSettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        kicker="Storybook"
        title={
          phase === "setup"
            ? "Setup"
            : phase === "playing"
              ? `Playing · round ${round}`
              : "Ended"
        }
      >
        <WidgetSettingsSection label="Title">
          <input
            type="text"
            defaultValue={title}
            onBlur={(e) => {
              const next = e.target.value.trim();
              if (next !== title) void runAction("set_title", { title: next });
            }}
            placeholder="The Lighthouse Keeper's Cat"
            className="w-full rounded border border-surface-border bg-surface px-2 py-1.5 text-[12px] text-text placeholder:text-text-dim focus:outline-none focus:border-accent"
          />
        </WidgetSettingsSection>

        <WidgetSettingsSection label="Genre" hint="optional">
          <input
            type="text"
            defaultValue={genre}
            onBlur={(e) => {
              const next = e.target.value.trim();
              if (next !== genre) void runAction("set_genre", { genre: next });
            }}
            placeholder="cozy mystery"
            className="w-full rounded border border-surface-border bg-surface px-2 py-1.5 text-[12px] text-text placeholder:text-text-dim focus:outline-none focus:border-accent"
          />
        </WidgetSettingsSection>

        <GameDirectiveSection
          directive={directive}
          busy={busy === "set_directive"}
          placeholder="e.g. ends with a quiet reveal; Marta keeps a secret"
          onSave={(theme, success_criteria) =>
            void runAction(
              "set_directive",
              success_criteria ? { theme, success_criteria } : { theme },
            )
          }
          onClear={() => void runAction("set_directive", { theme: "" })}
        />

        <GameParticipantsSection
          bots={availableBots}
          participants={participants}
          speciesByBotId={speciesByBotId}
          onToggle={toggleParticipant}
          defaultEmoji="✒︎"
          defaultColor="#9c8a6b"
        />

        <GamePhaseSection
          phase={phase}
          participantCount={participants.length}
          busy={busy === "set_phase"}
          startLabel="Start writing"
          allowAdvanceRound={false}
          onSetPhase={(next) => void runAction("set_phase", { phase: next })}
        />

        <WidgetSettingsSection label="Caps">
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-0.5 text-[10px] text-text-dim">
              <span className="uppercase tracking-wide">Stanzas total</span>
              <input
                type="number"
                min={1}
                max={60}
                defaultValue={stanzaCap}
                onBlur={(e) => {
                  const next = Math.max(1, Math.min(60, Math.floor(Number(e.target.value)) || stanzaCap));
                  if (next !== stanzaCap) void runAction("set_stanza_cap", { count: next });
                }}
                className="rounded border border-surface-border bg-surface px-2 py-1 text-[12px] text-text font-mono focus:outline-none focus:border-accent"
              />
            </label>
            <label className="flex flex-col gap-0.5 text-[10px] text-text-dim">
              <span className="uppercase tracking-wide">Sentences/turn</span>
              <input
                type="number"
                min={1}
                max={6}
                defaultValue={sentenceCap}
                onBlur={(e) => {
                  const next = Math.max(1, Math.min(6, Math.floor(Number(e.target.value)) || sentenceCap));
                  if (next !== sentenceCap) void runAction("set_sentence_cap", { count: next });
                }}
                className="rounded border border-surface-border bg-surface px-2 py-1 text-[12px] text-text font-mono focus:outline-none focus:border-accent"
              />
            </label>
          </div>
        </WidgetSettingsSection>

        {stanzas.length > 0 && (
          <WidgetSettingsSection label="Last stanza">
            <button
              type="button"
              onClick={() => void runAction("delete_last_stanza", {})}
              disabled={busy === "delete_last_stanza"}
              className="px-2 py-1.5 rounded text-[11px] border border-surface-border text-text-dim hover:text-text hover:bg-surface disabled:opacity-40"
            >
              Pop the last stanza off
            </button>
          </WidgetSettingsSection>
        )}

        <GameTurnLogSection log={turnLog} actorMeta={actorMeta} />
      </WidgetSettingsDrawer>
    </div>
  );
}
