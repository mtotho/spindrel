// Composer-mounted "skills in context" chip + single popover.
// Count = unique(latest assistant message's metadata.active_skills ∪ @skill: tags currently typed in composer).
// Click opens ONE popover with: loaded skills + inline search + drop-a-skill list.
// Outside click, Escape, and the × all dismiss.

import { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Sparkles, X, Search } from "lucide-react";

import { useThemeTokens } from "../../theme/tokens";
import { useChatStore } from "../../stores/chat";
import { parseSkillTags } from "../../lib/skillTags";
import { useSkills, type SkillItem } from "../../api/hooks/useSkills";
import { useEnrolledSkills } from "../../api/hooks/useEnrolledSkills";
import { tokenize } from "../shared/ToolSelector";

const SOURCE_BADGE: Record<string, { label: string; bg: string; fg: string }> = {
  starter: { label: "starter", bg: "rgba(59,130,246,0.15)", fg: "#2563eb" },
  fetched: { label: "fetched", bg: "rgba(16,185,129,0.15)", fg: "#059669" },
  manual: { label: "manual", bg: "rgba(168,85,247,0.15)", fg: "#9333ea" },
  authored: { label: "authored", bg: "rgba(249,115,22,0.15)", fg: "#ea580c" },
  migration: { label: "migration", bg: "rgba(148,163,184,0.15)", fg: "#64748b" },
  tool: { label: "tool", bg: "rgba(148,163,184,0.15)", fg: "#64748b" },
  file: { label: "file", bg: "rgba(148,163,184,0.15)", fg: "#64748b" },
};

interface ContextChipProps {
  channelId?: string;
  /** Composer text — used to count not-yet-sent @skill: tags. Omit for view-only placements (e.g. header). */
  composerText?: string;
  /** Current bot — enrolled skills sort first and get an "enrolled" marker. */
  botId?: string;
  /** Insert "@skill:<id> " at cursor in the composer. When omitted, the popover becomes view-only — no search / drop-in section. */
  onInsertSkillTag?: (skillId: string) => void;
  /** Match the surrounding toolbar button height. */
  size?: number;
  /** Don't render the chip at all when count is 0. Useful on mobile where toolbar space is tight. */
  hideWhenEmpty?: boolean;
  /** Mobile-friendly popover sizing — near-full-width and taller. */
  compact?: boolean;
  /** Open popover above the chip (default, composer placement) or below (header placement). */
  placement?: "above" | "below";
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
  composerText = "",
  botId,
  onInsertSkillTag,
  size = 36,
  hideWhenEmpty = false,
  compact = false,
  placement = "above",
}: ContextChipProps) {
  const t = useThemeTokens();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number }>({ bottom: 0, left: 0 });
  const [search, setSearch] = useState("");
  const canDrop = !!onInsertSkillTag;

  const messages = useChatStore((s) => (channelId ? s.getChannel(channelId).messages : []));
  const { data: skills = [], isLoading } = useSkills(canDrop ? { sort: "recent" } : undefined);
  const { data: enrolledSkills = [] } = useEnrolledSkills(canDrop ? botId : undefined);
  const enrolledSet = useMemo(
    () => new Set(enrolledSkills.map((e) => e.skill_id)),
    [enrolledSkills],
  );

  const { entries, count } = useMemo(
    () => deriveEntries(messages, composerText),
    [messages, composerText],
  );
  const loadedSet = useMemo(() => new Set(entries.map((e) => e.id)), [entries]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        popoverRef.current && !popoverRef.current.contains(target)
      ) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  const togglePopover = () => {
    if (!triggerRef.current) {
      setOpen((v) => !v);
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    const width = compact ? Math.min(window.innerWidth - 16, 420) : 360;
    const left = compact
      ? Math.max(8, (window.innerWidth - width) / 2)
      : Math.max(12, Math.min(rect.left - width + rect.width, window.innerWidth - width - 12));
    if (placement === "below") {
      setPos({ top: rect.bottom + 8, left });
    } else {
      setPos({ bottom: window.innerHeight - rect.top + 8, left });
    }
    setOpen((v) => !v);
  };

  const filteredSkills = useMemo(() => {
    if (!skills.length) return [];
    let pool = skills;
    if (search.trim()) {
      const queryTokens = tokenize(search);
      pool = pool.filter((s) => {
        const haystack = [
          ...tokenize(s.id),
          ...tokenize(s.name),
          ...tokenize(s.description ?? ""),
          ...(s.triggers ?? []).flatMap((t) => tokenize(t)),
        ].join(" ");
        return queryTokens.every((qt) => haystack.includes(qt));
      });
    }
    // Enrolled first, then the rest (stable within each partition).
    const enrolled: SkillItem[] = [];
    const other: SkillItem[] = [];
    for (const s of pool) {
      (enrolledSet.has(s.id) ? enrolled : other).push(s);
    }
    return [...enrolled, ...other].slice(0, 80);
  }, [skills, search, enrolledSet]);

  const empty = count === 0;
  if (empty && hideWhenEmpty) return null;

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
              top: pos.top,
              bottom: pos.bottom,
              left: pos.left,
              width: compact ? Math.min(window.innerWidth - 16, 420) : 360,
              maxHeight: compact ? "min(60vh, 520px)" : "min(480px, 75vh)",
              backgroundColor: t.surfaceRaised,
              borderColor: t.surfaceBorder,
            }}
          >
            {/* Header */}
            <div
              className="flex flex-row items-center justify-between px-3 py-2 shrink-0"
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
                onClick={() => { setOpen(false); setSearch(""); }}
                aria-label="Close"
                className="bg-transparent border-none cursor-pointer p-1 rounded"
                style={{ display: "flex", alignItems: "center" }}
              >
                <X size={12} color={t.textDim} />
              </button>
            </div>

            {/* Loaded section */}
            {entries.length > 0 ? (
              <div
                className={canDrop ? "shrink-0" : "overflow-y-auto"}
                style={{
                  flex: canDrop ? undefined : 1,
                  borderBottom: canDrop ? `1px solid ${t.surfaceBorder}` : undefined,
                }}
              >
                {entries.map((e) => <EntryRow key={`${e.origin}:${e.id}`} entry={e} />)}
              </div>
            ) : !canDrop ? (
              <div
                className="px-3 py-6 text-center"
                style={{ flex: 1, fontSize: 11, color: t.textDim }}
              >
                No skills loaded. Type <code style={{ fontFamily: "monospace" }}>@skill:</code> in the composer to drop one in.
              </div>
            ) : null}

            {canDrop && (
              <>
                {/* Search */}
                <div
                  className="flex flex-row items-center gap-1.5 px-2 py-2 shrink-0"
                  style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
                >
                  <Search size={12} className="text-text-dim shrink-0 ml-1" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Drop a skill into context…"
                    autoFocus
                    className="flex-1 min-w-0 px-2 py-1 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent"
                  />
                </div>

                {/* Catalog status */}
                <div
                  className="px-3 py-1 text-[10px] shrink-0"
                  style={{ color: t.textDim, borderBottom: `1px solid ${t.surfaceBorder}55` }}
                >
                  {isLoading
                    ? "Loading skills…"
                    : `${filteredSkills.length} of ${skills.length} skill${skills.length === 1 ? "" : "s"}${
                        search.trim() && filteredSkills.length === 80 ? " (showing first 80)" : ""
                      }`}
                </div>

                {/* Catalog list */}
                <div className="overflow-y-auto" style={{ flex: 1 }}>
                  {filteredSkills.length === 0 ? (
                    <div
                      className="px-3 py-4 text-center"
                      style={{ fontSize: 11, color: t.textDim }}
                    >
                      {isLoading ? "" : "No skills match."}
                    </div>
                  ) : (
                    filteredSkills.map((skill) => (
                      <CatalogRow
                        key={skill.id}
                        skill={skill}
                        loaded={loadedSet.has(skill.id)}
                        enrolled={enrolledSet.has(skill.id)}
                        onSelect={() => {
                          onInsertSkillTag!(skill.id);
                          setSearch("");
                        }}
                      />
                    ))
                  )}
                </div>
              </>
            )}
          </div>,
          document.body,
        )}
    </>
  );
}

function EntryRow({ entry }: { entry: LoadedEntry }) {
  const t = useThemeTokens();
  return (
    <div
      className="flex flex-col px-3 py-1.5"
      style={{ backgroundColor: t.surface }}
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

function CatalogRow({
  skill,
  loaded,
  enrolled,
  onSelect,
}: {
  skill: SkillItem;
  loaded: boolean;
  enrolled: boolean;
  onSelect: () => void;
}) {
  const badge = SOURCE_BADGE[skill.source_type] ?? {
    label: skill.source_type,
    bg: "rgba(148,163,184,0.15)",
    fg: "#64748b",
  };
  return (
    <button
      onClick={onSelect}
      className="flex flex-col gap-0.5 w-full px-3 py-2 bg-transparent border-none cursor-pointer text-left transition-colors hover:bg-surface-raised"
      style={{ opacity: loaded ? 0.5 : 1 }}
    >
      <div className="flex flex-row items-center gap-2">
        <Sparkles
          size={11}
          className={enrolled ? "text-purple-400 shrink-0" : "text-text-dim shrink-0"}
        />
        <span className="text-xs font-medium text-text truncate">{skill.name}</span>
        {loaded ? (
          <span className="text-[9px] text-text-dim shrink-0">loaded</span>
        ) : enrolled ? (
          <span
            className="text-[9px] font-semibold rounded shrink-0"
            style={{
              padding: "1px 5px",
              background: "rgba(168,85,247,0.15)",
              color: "#9333ea",
            }}
          >
            enrolled
          </span>
        ) : null}
        <span
          className="text-[9px] font-semibold rounded ml-auto shrink-0"
          style={{
            padding: "1px 6px",
            background: badge.bg,
            color: badge.fg,
          }}
        >
          {badge.label}
        </span>
      </div>
      {skill.description && (
        <span className="text-[10px] text-text-dim line-clamp-1 pl-[18px]">
          {skill.description}
        </span>
      )}
    </button>
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
  let active: Array<{ id: string; name: string }> = [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "assistant" && m.role !== "bot") continue;
    const meta = (m.metadata ?? {}) as Record<string, unknown>;
    const a = (meta.active_skills as unknown[]) ?? [];
    const aux = (meta.auto_injected_skills as unknown[]) ?? [];
    const merged = [...a, ...aux];
    if (merged.length > 0) {
      active = normalize(merged);
      break;
    }
  }

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
