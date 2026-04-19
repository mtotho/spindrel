// Composer-mounted "skills in context" chip + popover.
// Count = unique(latest assistant message's metadata.active_skills ∪ @skill: tags currently typed in composer).
// Click opens a popover listing what's loaded + a "Drop a skill" picker that
// inserts @skill:<id> into the composer at the cursor — same path as typing the tag manually.

import { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Sparkles, Plus, X } from "lucide-react";

import { useThemeTokens } from "../../theme/tokens";
import { useChatStore } from "../../stores/chat";
import { parseSkillTags } from "../../lib/skillTags";
import { SkillPicker } from "../shared/SkillPicker";

interface ContextChipProps {
  channelId?: string;
  /** Composer text — used to count not-yet-sent @skill: tags. */
  composerText: string;
  /** Bot id — scopes the picker query to that bot's catalog. */
  botId?: string;
  /** Insert "@skill:<id> " at cursor in the composer. */
  onInsertSkillTag: (skillId: string) => void;
  /** Match the surrounding toolbar button height. */
  size?: number;
}

type LoadedEntry = {
  id: string;
  name: string;
  /** "queued" if from composer text, "loaded" if from latest assistant message. */
  origin: "loaded" | "queued";
  /** For loaded entries: index distance back from the most-recent message
   *  containing this skill's get_skill call. Undefined for queued. */
  msgsAgo?: number;
};

export function ContextChip({
  channelId,
  composerText,
  botId,
  onInsertSkillTag,
  size = 36,
}: ContextChipProps) {
  const t = useThemeTokens();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const pickerAnchorRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pos, setPos] = useState({ bottom: 0, left: 0 });

  const messages = useChatStore((s) => (channelId ? s.getChannel(channelId).messages : []));

  const { entries, count } = useMemo(
    () => deriveEntries(messages, composerText),
    [messages, composerText],
  );

  // Close popover on outside click. Picker has its own outside-click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        popoverRef.current && !popoverRef.current.contains(target) &&
        // Don't close if click landed inside the picker portal.
        !(target as HTMLElement).closest?.("[data-skill-picker]")
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pickerOpen) setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, pickerOpen]);

  const togglePopover = () => {
    if (!triggerRef.current) {
      setOpen((v) => !v);
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    setPos({
      bottom: window.innerHeight - rect.top + 8,
      left: Math.max(12, Math.min(rect.left - 120, window.innerWidth - 320 - 12)),
    });
    setOpen((v) => !v);
  };

  const empty = count === 0;
  const loadedIds = useMemo(() => entries.map((e) => e.id), [entries]);

  return (
    <>
      <button
        ref={triggerRef}
        className="input-action-btn"
        onClick={togglePopover}
        aria-label={
          empty
            ? "No skills currently in context. Click to drop one in."
            : `${count} skill${count === 1 ? "" : "s"} in context. Click for details.`
        }
        aria-expanded={open}
        title={
          empty
            ? "No skills loaded — click to drop one in"
            : `${count} skill${count === 1 ? "" : "s"} in context`
        }
        style={{
          width: size,
          height: size,
          flexShrink: 0,
          opacity: empty ? 0.5 : 1,
          position: "relative",
        }}
      >
        <Sparkles
          size={16}
          color={empty ? t.textDim : t.purple}
          strokeWidth={empty ? 2 : 2.5}
        />
        {!empty && (
          <span
            style={{
              position: "absolute",
              top: 2,
              right: 2,
              minWidth: 14,
              height: 14,
              padding: "0 3px",
              borderRadius: 7,
              background: t.purple,
              color: "#fff",
              fontSize: 9,
              fontWeight: 700,
              lineHeight: "14px",
              textAlign: "center",
            }}
          >
            {count}
          </span>
        )}
      </button>

      {open &&
        ReactDOM.createPortal(
          <div
            ref={popoverRef}
            role="dialog"
            aria-label="Skills in context"
            className="fixed z-[10000] flex flex-col rounded-lg border shadow-xl"
            style={{
              bottom: pos.bottom,
              left: pos.left,
              width: 320,
              maxHeight: "min(420px, 70vh)",
              backgroundColor: t.surfaceRaised,
              borderColor: t.surfaceBorder,
            }}
          >
            <div
              className="flex flex-row items-center justify-between px-3 py-2"
              style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
            >
              <div className="flex flex-row items-center gap-1.5">
                <Sparkles size={12} color={t.purple} />
                <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
                  Skills in context
                </span>
                <span style={{ fontSize: 10, color: t.textDim }}>{count}</span>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="bg-transparent border-none cursor-pointer p-1 rounded hover:bg-surface-overlay"
              >
                <X size={12} color={t.textDim} />
              </button>
            </div>

            <div className="overflow-y-auto" style={{ flex: 1 }}>
              {entries.length === 0 ? (
                <div
                  className="px-3 py-4 text-center"
                  style={{ fontSize: 11, color: t.textDim }}
                >
                  Nothing loaded yet.
                  <br />
                  Drop a skill below to inject it on the next turn.
                </div>
              ) : (
                entries.map((e) => <EntryRow key={`${e.origin}:${e.id}`} entry={e} />)
              )}
            </div>

            <div
              className="px-3 py-2 flex flex-row items-center"
              style={{ borderTop: `1px solid ${t.surfaceBorder}` }}
            >
              <button
                ref={pickerAnchorRef}
                onClick={() => setPickerOpen(true)}
                className="flex flex-row items-center gap-1.5 px-2 py-1 rounded-md cursor-pointer transition-colors hover:bg-surface-overlay"
                style={{
                  background: "transparent",
                  border: `1px dashed ${t.surfaceBorder}`,
                  fontSize: 11,
                  color: t.text,
                  width: "100%",
                  justifyContent: "center",
                }}
              >
                <Plus size={11} color={t.textDim} />
                <span>Drop a skill</span>
                <span style={{ fontSize: 9, color: t.textDim, fontFamily: "monospace" }}>
                  @skill:
                </span>
              </button>
            </div>
          </div>,
          document.body,
        )}

      <div data-skill-picker>
        <SkillPicker
          anchorRef={pickerAnchorRef}
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          onSelect={(id) => {
            onInsertSkillTag(id);
            // Keep the popover open so user can see the queued chip update.
          }}
          botId={botId}
          alreadyLoaded={loadedIds}
        />
      </div>
    </>
  );
}

function EntryRow({ entry }: { entry: LoadedEntry }) {
  const t = useThemeTokens();
  return (
    <div
      className="flex flex-col px-3 py-2"
      style={{ borderBottom: `1px solid ${t.surfaceBorder}33` }}
    >
      <div className="flex flex-row items-center gap-1.5">
        <Sparkles
          size={10}
          color={entry.origin === "queued" ? t.accent : t.purple}
        />
        <span
          style={{
            fontSize: 12,
            color: t.text,
            fontWeight: 500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
          }}
          title={entry.id}
        >
          {entry.name}
        </span>
      </div>
      <span
        style={{
          fontSize: 10,
          color: t.textDim,
          marginLeft: 16,
          marginTop: 1,
        }}
      >
        {entry.origin === "queued"
          ? "queued for next turn"
          : entry.msgsAgo === 0 || entry.msgsAgo === undefined
            ? "loaded last turn"
            : `loaded ${entry.msgsAgo} msg${entry.msgsAgo === 1 ? "" : "s"} ago`}
      </span>
    </div>
  );
}

type AnyMessage = {
  role?: string;
  metadata?: Record<string, unknown> | null;
  tool_calls?: Array<{ name?: string; args?: string }>;
};

function deriveEntries(
  messages: AnyMessage[],
  composerText: string,
): { entries: LoadedEntry[]; count: number } {
  // 1. Pull active_skills (+ legacy auto_injected_skills) from the latest assistant
  //    message that carries metadata. Same merge SkillOrb does.
  let active: Array<{ id: string; name: string }> = [];
  let lastAssistantIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "assistant" && m.role !== "bot") continue;
    const meta = (m.metadata ?? {}) as Record<string, unknown>;
    const a = (meta.active_skills as unknown[]) ?? [];
    const aux = (meta.auto_injected_skills as unknown[]) ?? [];
    const merged = [...a, ...aux];
    if (merged.length > 0 || lastAssistantIdx === -1) {
      lastAssistantIdx = i;
      active = normalize(merged);
      if (merged.length > 0) break;
    }
  }

  // 2. Map skill_id → "msgs ago" by scanning history backwards from the end for
  //    each skill's most recent get_skill tool_call. Cheap O(messages * skills).
  const msgsAgo = new Map<string, number>();
  for (const sk of active) {
    let dist = 0;
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role !== "assistant" && m.role !== "bot") continue;
      const calls = m.tool_calls ?? [];
      let found = false;
      for (const tc of calls) {
        if (tc.name !== "get_skill") continue;
        try {
          const args = JSON.parse(tc.args ?? "{}") as { skill_id?: string };
          if (args.skill_id === sk.id) {
            found = true;
            break;
          }
        } catch {
          // ignore
        }
      }
      if (found) {
        msgsAgo.set(sk.id, dist);
        break;
      }
      dist++;
    }
  }

  // 3. Composer-typed @skill: tags → queued entries (dedup against loaded).
  const queuedIds = parseSkillTags(composerText);
  const loadedIds = new Set(active.map((s) => s.id));

  const entries: LoadedEntry[] = [
    ...active.map((s) => ({
      id: s.id,
      name: s.name,
      origin: "loaded" as const,
      msgsAgo: msgsAgo.get(s.id),
    })),
    ...queuedIds
      .filter((id) => !loadedIds.has(id))
      .map((id) => ({
        id,
        name: id,
        origin: "queued" as const,
      })),
  ];

  return { entries, count: entries.length };
}

function normalize(raw: unknown[]): Array<{ id: string; name: string }> {
  const seen = new Set<string>();
  const out: Array<{ id: string; name: string }> = [];
  for (const r of raw) {
    if (!r || typeof r !== "object") continue;
    const o = r as Record<string, unknown>;
    const id = (o.skill_id ?? o.skillId ?? "") as string;
    const name = ((o.skill_name ?? o.skillName ?? id) as string) || id || "skill";
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, name });
  }
  return out;
}
