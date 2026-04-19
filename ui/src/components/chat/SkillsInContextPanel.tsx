// Shared skill-context panel: loaded skills + optional catalog drop-in search.
// Used by the mobile-header ContextChip and by the desktop composer's + menu.
// Does NOT own the portal/positioning — the caller wraps this in whatever
// popover shell it needs.

import { useMemo, useState } from "react";
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

export type LoadedEntry = {
  id: string;
  name: string;
  origin: "loaded" | "queued";
  msgsAgo?: number;
};

export interface UseSkillsInContextArgs {
  channelId?: string;
  composerText?: string;
}

/** Derives the loaded+queued skill count from chat messages + composer text.
 *  Cheap — no network. Safe to call from any composer button that just needs a badge count. */
export function useSkillsInContext({
  channelId,
  composerText = "",
}: UseSkillsInContextArgs): { entries: LoadedEntry[]; count: number } {
  const messages = useChatStore((s) => (channelId ? s.getChannel(channelId).messages : []));
  return useMemo(() => deriveEntries(messages, composerText), [messages, composerText]);
}

export interface SkillsInContextPanelProps {
  channelId?: string;
  composerText?: string;
  botId?: string;
  /** Provide to enable the drop-a-skill catalog at the bottom. Omit for view-only. */
  onInsertSkillTag?: (skillId: string) => void;
  /** Called when the close (×) button inside the panel header is pressed. */
  onClose: () => void;
}

/** Panel contents: header, loaded entries, optional catalog search + list.
 *  Caller owns the portal + positioning + outside-click handling. */
export function SkillsInContextPanel({
  channelId,
  composerText = "",
  botId,
  onInsertSkillTag,
  onClose,
}: SkillsInContextPanelProps) {
  const t = useThemeTokens();
  const [search, setSearch] = useState("");
  const canDrop = !!onInsertSkillTag;

  const { entries, count } = useSkillsInContext({ channelId, composerText });
  const loadedSet = useMemo(() => new Set(entries.map((e) => e.id)), [entries]);

  const { data: skills = [], isLoading } = useSkills(canDrop ? { sort: "recent" } : undefined);
  const { data: enrolledSkills = [] } = useEnrolledSkills(canDrop ? botId : undefined);
  const enrolledSet = useMemo(
    () => new Set(enrolledSkills.map((e) => e.skill_id)),
    [enrolledSkills],
  );

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
          ...(s.triggers ?? []).flatMap((tr) => tokenize(tr)),
        ].join(" ");
        return queryTokens.every((qt) => haystack.includes(qt));
      });
    }
    const enrolled: SkillItem[] = [];
    const other: SkillItem[] = [];
    for (const s of pool) {
      (enrolledSet.has(s.id) ? enrolled : other).push(s);
    }
    return [...enrolled, ...other].slice(0, 80);
  }, [skills, search, enrolledSet]);

  return (
    <div className="flex flex-col h-full">
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
          onClick={() => { setSearch(""); onClose(); }}
          aria-label="Close"
          className="bg-transparent border-none cursor-pointer p-1 rounded"
          style={{ display: "flex", alignItems: "center" }}
        >
          <X size={12} color={t.textDim} />
        </button>
      </div>

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
    </div>
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
