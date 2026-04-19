// Searchable skill picker. Mirrors ToolSelector's portal+tokenize pattern.
// Used by the in-chat ContextPanel "Drop a skill" action; lives in shared/
// so future surfaces can reuse it.

import { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Sparkles, Search } from "lucide-react";

import { useSkills, type SkillItem } from "@/src/api/hooks/useSkills";
import { tokenize } from "./ToolSelector";

const SOURCE_BADGE: Record<string, { label: string; bg: string; fg: string }> = {
  starter: { label: "starter", bg: "rgba(59,130,246,0.15)", fg: "#2563eb" },
  fetched: { label: "fetched", bg: "rgba(16,185,129,0.15)", fg: "#059669" },
  manual: { label: "manual", bg: "rgba(168,85,247,0.15)", fg: "#9333ea" },
  authored: { label: "authored", bg: "rgba(249,115,22,0.15)", fg: "#ea580c" },
  migration: { label: "migration", bg: "rgba(148,163,184,0.15)", fg: "#64748b" },
};

interface SkillPickerProps {
  /** Anchor element to position the popover under. */
  anchorRef: React.RefObject<HTMLElement | null>;
  open: boolean;
  onClose: () => void;
  onSelect: (skillId: string) => void;
  /** Optional: filter to skills enrolled by this bot (still falls back to global catalog). */
  botId?: string;
  /** Skill IDs to mark as already-loaded (rendered with a checkmark / dimmed). */
  alreadyLoaded?: string[];
}

export function SkillPicker({
  anchorRef,
  open,
  onClose,
  onSelect,
  botId,
  alreadyLoaded,
}: SkillPickerProps) {
  const [search, setSearch] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 320 });

  const { data: skills = [], isLoading } = useSkills(
    botId ? { bot_id: botId, sort: "recent" } : { sort: "recent" },
  );

  const loadedSet = useMemo(() => new Set(alreadyLoaded ?? []), [alreadyLoaded]);

  // Position above the anchor (composer mounts the picker below the chat —
  // popover should open upward like the model picker dropdown).
  useEffect(() => {
    if (!open) return;
    if (!anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const width = 360;
    const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12));
    setPos({
      top: rect.top - 8,
      left,
      width,
    });
  }, [open, anchorRef]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        dropdownRef.current && !dropdownRef.current.contains(e.target as Node) &&
        anchorRef.current && !anchorRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, anchorRef, onClose]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  const filtered = useMemo(() => {
    if (!search.trim()) return skills.slice(0, 50);
    const queryTokens = tokenize(search);
    return skills
      .filter((s) => {
        const haystack = [
          ...tokenize(s.id),
          ...tokenize(s.name),
          ...tokenize(s.description ?? ""),
          ...(s.triggers ?? []).flatMap((t) => tokenize(t)),
        ].join(" ");
        return queryTokens.every((qt) => haystack.includes(qt));
      })
      .slice(0, 50);
  }, [skills, search]);

  if (!open) return null;

  return ReactDOM.createPortal(
    <div
      ref={dropdownRef}
      className="fixed bg-surface border border-surface-border rounded-lg shadow-xl z-[10001] flex flex-col overflow-hidden"
      style={{
        bottom: window.innerHeight - pos.top,
        left: pos.left,
        width: pos.width,
        maxHeight: "min(420px, 70vh)",
      }}
    >
      <div className="flex flex-row items-center gap-1.5 p-2 border-b border-surface-border shrink-0">
        <Search size={12} className="text-text-dim shrink-0 ml-1" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Drop a skill into context…"
          autoFocus
          className="flex-1 min-w-0 px-2 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent"
        />
      </div>
      <div className="px-3 py-1 text-[10px] text-text-dim border-b border-surface-border/50 shrink-0">
        {isLoading
          ? "Loading…"
          : `${filtered.length} skill${filtered.length === 1 ? "" : "s"}${
              search.trim() && filtered.length === 50 ? " (showing first 50)" : ""
            }`}
      </div>
      <div className="overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="px-3 py-4 text-[11px] text-text-dim text-center">
            {isLoading ? "" : "No skills found"}
          </div>
        ) : (
          filtered.map((skill) => (
            <SkillRow
              key={skill.id}
              skill={skill}
              loaded={loadedSet.has(skill.id)}
              onSelect={() => {
                onSelect(skill.id);
                onClose();
                setSearch("");
              }}
            />
          ))
        )}
      </div>
    </div>,
    document.body,
  );
}

function SkillRow({
  skill,
  loaded,
  onSelect,
}: {
  skill: SkillItem;
  loaded: boolean;
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
      style={{ opacity: loaded ? 0.55 : 1 }}
    >
      <div className="flex flex-row items-center gap-2">
        <Sparkles size={11} className="text-purple-400 shrink-0" />
        <span className="text-xs font-medium text-text truncate">{skill.name}</span>
        {loaded && (
          <span className="text-[9px] text-text-dim shrink-0">already loaded</span>
        )}
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
