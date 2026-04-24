import { useState, useRef, useCallback } from "react";
import { useCompletions } from "../../api/hooks/useModels";
import { useGeneratePrompt } from "../../api/hooks/usePrompts";
import { useThemeTokens } from "../../theme/tokens";
import type { CompletionItem } from "../../types/api";
import { createPortal } from "react-dom";

interface Props {
  value: string;
  onChange: (text: string) => void;
  label?: string;
  placeholder?: string;
  rows?: number;
  helpText?: string;
  generateContext?: string;
  fieldType?: string;
  botId?: string;
  channelId?: string;
}

export function scoreMatch(value: string, label: string, query: string): number {
  const v = value.toLowerCase();
  const l = label.toLowerCase();
  const q = query.toLowerCase();
  const name = v.includes(":") ? v.split(":").slice(1).join(":") : v;
  if (v.startsWith(q)) return 4;
  if (name.startsWith(q)) return 3;
  if (v.includes(q) || l.includes(q)) return 2;
  let hi = 0;
  for (let i = 0; i < q.length; i++) {
    const idx = v.indexOf(q[i], hi);
    if (idx === -1) return 0;
    hi = idx + 1;
  }
  return 1;
}

// TAG_COLORS uses intentional domain-specific dark background colors
// paired with semantic token foregrounds where possible
const TAG_COLORS: Record<string, { bg: string; fg: string }> = {
  skill: { bg: "#1e1b4b", fg: "#4f46e5" },
  pack: { bg: "#312e81", fg: "#a5b4fc" },
  tool: { bg: "#14532d", fg: "#16a34a" },
  "tool-pack": { bg: "#14532d", fg: "#16a34a" },
  knowledge: { bg: "#3b0764", fg: "#7c3aed" },
  bot: { bg: "#1e3a5f", fg: "#38bdf8" },
};

// Skill packs (folder layout: skills/foo/index.md → id "foo", skills/foo/bar.md → id "foo/bar")
// arrive flat from the API. Cluster children under their pack's index entry, with the
// index pulled to the top of its group, so the picker visually groups them.
const SKILL_PREFIX = "skill:";

function isSkill(it: CompletionItem): boolean {
  return it.value.startsWith(SKILL_PREFIX);
}

function skillIdOf(it: CompletionItem): string {
  return it.value.slice(SKILL_PREFIX.length);
}

function packPathOf(skillId: string): string {
  const i = skillId.lastIndexOf("/");
  return i > 0 ? skillId.slice(0, i) : "";
}

export function clusterSkillPacks(items: CompletionItem[]): CompletionItem[] {
  if (items.length < 2) return items;
  const skillIds = new Set(items.filter(isSkill).map(skillIdOf));
  type Entry = { item: CompletionItem; origIdx: number; groupKey: string; isPackIndex: boolean };
  const entries: Entry[] = items.map((item, origIdx) => {
    if (!isSkill(item)) {
      return { item, origIdx, groupKey: `_other_${origIdx}`, isPackIndex: false };
    }
    const id = skillIdOf(item);
    const pack = packPathOf(id);
    const isPackChild = pack !== "" && skillIds.has(pack);
    const isPackIndex = items.some(
      (o) => o !== item && isSkill(o) && packPathOf(skillIdOf(o)) === id,
    );
    return { item, origIdx, groupKey: isPackChild ? pack : id, isPackIndex };
  });

  const groupOrder: string[] = [];
  const grouped = new Map<string, Entry[]>();
  for (const e of entries) {
    if (!grouped.has(e.groupKey)) {
      grouped.set(e.groupKey, []);
      groupOrder.push(e.groupKey);
    }
    grouped.get(e.groupKey)!.push(e);
  }
  const out: CompletionItem[] = [];
  for (const key of groupOrder) {
    const arr = grouped.get(key)!;
    arr.sort((a, b) => {
      if (a.isPackIndex !== b.isPackIndex) return a.isPackIndex ? -1 : 1;
      return a.origIdx - b.origIdx;
    });
    for (const e of arr) out.push(e.item);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Generate button (shared between inline + fullscreen + standalone)
// ---------------------------------------------------------------------------
export function GenerateButton({
  generateContext,
  fieldType,
  botId,
  channelId,
  value,
  onChange,
  size = "small",
}: {
  generateContext?: string;
  fieldType?: string;
  botId?: string;
  channelId?: string;
  value: string;
  onChange: (text: string) => void;
  size?: "small" | "normal";
}) {
  const gen = useGeneratePrompt();
  const [flash, setFlash] = useState<"success" | "error" | null>(null);
  const [showGuidance, setShowGuidance] = useState(false);
  const [guidance, setGuidance] = useState("");
  const btnRef = useRef<HTMLButtonElement>(null);

  const handleGenerate = useCallback((guidanceText: string) => {
    gen.mutate(
      {
        field_type: fieldType || undefined,
        bot_id: botId || undefined,
        channel_id: channelId || undefined,
        context: generateContext || undefined,
        user_input: value,
        guidance: guidanceText || undefined,
      },
      {
        onSuccess: (data) => {
          onChange(data.prompt);
          setFlash("success");
          setShowGuidance(false);
          setGuidance("");
          setTimeout(() => setFlash(null), 1200);
        },
        onError: () => {
          setFlash("error");
          setTimeout(() => setFlash(null), 1500);
        },
      }
    );
  }, [gen, fieldType, botId, channelId, generateContext, value, onChange]);

  const isSmall = size === "small";
  const buttonClass =
    `inline-flex items-center justify-center rounded-md bg-transparent font-semibold transition-colors ` +
    `focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35 disabled:cursor-wait disabled:opacity-60 ` +
    (isSmall ? "min-h-[28px] px-2 text-[11px] " : "min-h-[36px] px-3 text-[12px] ") +
    (flash === "success"
      ? "text-success hover:bg-success/10"
      : flash === "error"
        ? "text-danger hover:bg-danger/10"
        : "text-text-dim hover:bg-surface-overlay/50 hover:text-text-muted");

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        ref={btnRef}
        onClick={() => setShowGuidance(!showGuidance)}
        disabled={gen.isPending}
        className={buttonClass}
      >
        {gen.isPending ? "Generating..." : flash === "success" ? "Done!" : flash === "error" ? "Failed" : "Generate"}
      </button>

      {showGuidance && !gen.isPending && typeof document !== "undefined" && (() => {        return createPortal(
          <>
            <div onClick={() => { setShowGuidance(false); setGuidance(""); }} className="fixed inset-0 z-[10010]" />
            <div
              className="fixed z-[10011] flex w-[300px] flex-col gap-2 rounded-md border border-surface-border bg-surface-raised p-2.5 ring-1 ring-black/10"
              style={{
                top: (btnRef.current?.getBoundingClientRect().bottom ?? 0) + 4,
                left: Math.min(btnRef.current?.getBoundingClientRect().left ?? 0, window.innerWidth - 320),
              }}
            >
              <div className="text-[11px] font-semibold text-text-muted">What should be generated?</div>
              <input
                type="text"
                autoFocus
                value={guidance}
                onChange={(e: any) => setGuidance(e.target.value)}
                onKeyDown={(e: any) => {
                  if (e.key === "Enter") { handleGenerate(guidance); }
                  if (e.key === "Escape") { setShowGuidance(false); setGuidance(""); }
                }}
                placeholder="Optional — describe what you want..."
                className="min-h-[34px] w-full rounded-md bg-input px-2.5 text-[12px] text-text outline-none placeholder:text-text-dim focus:ring-2 focus:ring-accent/25"
              />
              <div className="flex justify-end gap-1.5">
                <button
                  onClick={() => { setShowGuidance(false); setGuidance(""); }}
                  className="min-h-[30px] rounded-md px-2.5 text-[11px] font-semibold text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text-muted"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleGenerate(guidance)}
                  className="min-h-[30px] rounded-md px-2.5 text-[11px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]"
                >
                  Go
                </button>
              </div>
            </div>
          </>,
          document.body
        );
      })()}
    </div>
  );
}

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

// ---------------------------------------------------------------------------
// Autocomplete dropdown (portal-based)
// ---------------------------------------------------------------------------
export function AutocompleteMenu({
  show,
  items,
  activeIdx,
  menuPos,
  onSelect,
  onHover,
  onClose,
  anchor,
  chatMode = "default",
}: {
  show: boolean;
  items: CompletionItem[];
  activeIdx: number;
  menuPos: { top: number; left: number; width: number };
  onSelect: (item: CompletionItem) => void;
  onHover: (i: number) => void;
  onClose: () => void;
  anchor?: "top" | "bottom";
  chatMode?: "default" | "terminal";
}) {
  const t = useThemeTokens();
  const isTerminal = chatMode === "terminal";
  if (!show || items.length === 0 || typeof document === "undefined") return null;  const posStyle: React.CSSProperties =
    anchor === "bottom"
      ? { bottom: window.innerHeight - menuPos.top }
      : { top: menuPos.top };

  // Per-row pack metadata derived from the (already clustered) item list.
  const skillIdsInList = new Set(items.filter(isSkill).map(skillIdOf));
  const childCounts = new Map<string, number>();
  for (const it of items) {
    if (!isSkill(it)) continue;
    const pack = packPathOf(skillIdOf(it));
    if (pack && skillIdsInList.has(pack)) {
      childCounts.set(pack, (childCounts.get(pack) ?? 0) + 1);
    }
  }
  const packMeta = items.map((it) => {
    if (!isSkill(it)) return { isPackIndex: false, isPackChild: false, packPath: "" };
    const id = skillIdOf(it);
    const pack = packPathOf(id);
    const isPackChild = pack !== "" && skillIdsInList.has(pack);
    const isPackIndex = items.some(
      (o) => o !== it && isSkill(o) && packPathOf(skillIdOf(o)) === id,
    );
    return { isPackIndex, isPackChild, packPath: isPackChild ? pack : "" };
  });

  return createPortal(
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 10010 }} />
      <div
        className={[
          "fixed z-[10011] overflow-y-auto bg-surface-raised max-h-[240px]",
          isTerminal
            ? "rounded-none border-t border-surface-border/60"
            : "rounded-md border border-surface-border",
        ].join(" ")}
        style={{
          ...posStyle,
          left: menuPos.left,
          width: menuPos.width,
        }}
      >
        {items.map((item, i) => {
          const hasPrefix = item.value.includes(":");
          const prefix = hasPrefix ? item.value.split(":")[0] : "";
          const path = hasPrefix ? item.value.split(":").slice(1).join(":") : item.value;
          const leaf = path.split("/").filter(Boolean).pop() || path;
          const hasSubPath = path !== leaf;
          const isActive = i === activeIdx;
          const meta = packMeta[i];
          const badgeKey = meta.isPackIndex ? "pack" : prefix;
          const badgeText = meta.isPackIndex ? "PACK" : prefix;
          const colors = TAG_COLORS[badgeKey] || { bg: "#374151", fg: t.contentText };
          const childCount = meta.isPackIndex ? (childCounts.get(skillIdOf(item)) ?? 0) : 0;
          const packIndent = meta.isPackChild ? 18 : 0;
          const skillBg = TAG_COLORS.skill.bg;
          return (
            <div
              key={item.value}
              onMouseDown={(e) => { e.preventDefault(); onSelect(item); }}
              onMouseEnter={() => onHover(i)}
              className={[
                "flex flex-row items-start gap-[9px] cursor-pointer relative py-[7px] pr-3 transition-colors duration-100",
                isActive ? "bg-surface-overlay/60" : "bg-transparent",
              ].join(" ")}
              style={{ paddingLeft: 12 + packIndent }}
            >
              {meta.isPackChild && (
                <span
                  aria-hidden
                  style={{
                    position: "absolute",
                    left: 16,
                    top: 4,
                    bottom: 4,
                    width: 2,
                    borderRadius: 1,
                    background: skillBg,
                    opacity: 0.8,
                  }}
                />
              )}
              {prefix && (
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 3,
                  background: colors.bg, color: colors.fg,
                  textTransform: "uppercase", letterSpacing: "0.05em",
                  marginTop: 1, flexShrink: 0,
                  minWidth: 38, textAlign: "center",
                }}>
                  {badgeText}
                </span>
              )}
              <div className="flex flex-col min-w-0 flex-1 gap-[1px]">
                <span
                  className="text-[13px] text-text overflow-hidden text-ellipsis whitespace-nowrap"
                  style={{
                    fontWeight: meta.isPackIndex ? 700 : 600,
                    fontFamily: isTerminal ? TERMINAL_FONT_STACK : undefined,
                  }}
                >
                  {leaf}
                </span>
                {meta.isPackIndex && childCount > 0 ? (
                  <span
                    className="text-[11px] font-medium overflow-hidden text-ellipsis whitespace-nowrap"
                    style={{ color: TAG_COLORS.pack.fg }}
                  >
                    Index only · {childCount} sub-skill{childCount === 1 ? "" : "s"} loaded on demand
                  </span>
                ) : hasSubPath && !meta.isPackChild ? (
                  <span
                    className="text-[10px] text-text-dim overflow-hidden text-ellipsis whitespace-nowrap"
                    style={{ fontFamily: TERMINAL_FONT_STACK }}
                  >
                    {path}
                  </span>
                ) : null}
                {item.description ? (
                  <span
                    className="text-[11px] text-text-dim overflow-hidden text-ellipsis whitespace-nowrap"
                    style={{ fontFamily: isTerminal ? TERMINAL_FONT_STACK : undefined }}
                  >
                    {item.description}
                  </span>
                ) : (!hasSubPath && item.label !== item.value) ? (
                  <span
                    className="text-[11px] text-text-dim overflow-hidden text-ellipsis whitespace-nowrap"
                    style={{ fontFamily: isTerminal ? TERMINAL_FONT_STACK : undefined }}
                  >
                    {item.label}
                  </span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </>,
    document.body
  );
}

// ---------------------------------------------------------------------------
// Shared autocomplete hook (used by both inline LlmPrompt and FullscreenEditor)
// ---------------------------------------------------------------------------
function usePromptAutocomplete(
  textareaRef: React.RefObject<HTMLTextAreaElement | null>,
  containerRef: React.RefObject<HTMLDivElement | null>,
  value: string,
  onChange: (text: string) => void,
  completions: CompletionItem[] | undefined,
) {
  const [showMenu, setShowMenu] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 0 });
  const [atStart, setAtStart] = useState(-1);
  const [filtered, setFiltered] = useState<CompletionItem[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);

  const handleInput = useCallback(
    (text: string) => {
      onChange(text);
      const ta = textareaRef.current;
      if (!ta || !completions) return;
      const pos = ta.selectionStart;
      const before = text.substring(0, pos);
      const atIdx = before.lastIndexOf("@");
      if (atIdx === -1 || (atIdx > 0 && /\w/.test(before[atIdx - 1]))) { setShowMenu(false); return; }
      const query = before.substring(atIdx + 1);
      if (/\s/.test(query)) { setShowMenu(false); return; }
      setAtStart(atIdx);
      const scored = completions.map((c) => ({ c, s: scoreMatch(c.value, c.label, query) }))
        .filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.c).slice(0, 10);
      const clustered = clusterSkillPacks(scored);
      setActiveIdx(0);
      setFiltered(clustered);
      if (scored.length > 0 && containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setMenuPos({ top: rect.bottom + 2, left: rect.left, width: Math.min(rect.width, 500) });
        setShowMenu(true);
      } else { setShowMenu(false); }
    },
    [completions, onChange, textareaRef, containerRef]
  );

  const selectItem = useCallback(
    (item: CompletionItem) => {
      const ta = textareaRef.current;
      if (!ta) return;
      const before = value.substring(0, atStart);
      const after = value.substring(ta.selectionStart);
      onChange(before + "@" + item.value + " " + after);
      setShowMenu(false);
      requestAnimationFrame(() => {
        const cur = atStart + item.value.length + 2;
        ta.selectionStart = ta.selectionEnd = cur;
        ta.focus();
      });
    },
    [value, atStart, onChange, textareaRef]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, onEscapeFallback?: () => void) => {
      if (e.key === "Escape" && !showMenu) { onEscapeFallback?.(); return; }
      if (!showMenu) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(i + 1, filtered.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, 0)); }
      else if (e.key === "Enter" || e.key === "Tab") { if (filtered.length > 0) { e.preventDefault(); selectItem(filtered[activeIdx]); } }
      else if (e.key === "Escape") { setShowMenu(false); }
    },
    [showMenu, filtered, activeIdx, selectItem]
  );

  return { showMenu, setShowMenu, menuPos, filtered, activeIdx, setActiveIdx, handleInput, selectItem, handleKeyDown };
}

// ---------------------------------------------------------------------------
// Fullscreen modal editor
// ---------------------------------------------------------------------------
function FullscreenEditor({
  value,
  onChange,
  label,
  placeholder,
  generateContext,
  fieldType,
  botId,
  channelId,
  onClose,
}: {
  value: string;
  onChange: (text: string) => void;
  label?: string;
  placeholder?: string;
  generateContext?: string;
  fieldType?: string;
  botId?: string;
  channelId?: string;
  onClose: () => void;
}) {
  const { data: completions } = useCompletions();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const ac = usePromptAutocomplete(textareaRef, containerRef, value, onChange, completions);

  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[10000] flex flex-col bg-surface">
      <div className="flex min-h-[52px] items-center justify-between gap-3 px-4">
        <div className="min-w-0">
          <div className="truncate text-[14px] font-semibold text-text">{label || "Edit Prompt"}</div>
          <div className="text-[11px] text-text-dim">Type @ to insert context tags. Esc closes the editor.</div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {(generateContext || fieldType) && (
            <GenerateButton generateContext={generateContext} fieldType={fieldType} botId={botId} channelId={channelId} value={value} onChange={onChange} size="normal" />
          )}
          <button
            onClick={onClose}
            className="min-h-[36px] rounded-md px-3 text-[12px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]"
          >
            Done
          </button>
        </div>
      </div>

      <div ref={containerRef} className="flex min-h-0 flex-1 flex-col px-4 pb-4">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => ac.handleInput(e.target.value)}
          onKeyDown={((e: React.KeyboardEvent) => ac.handleKeyDown(e, onClose)) as any}
          onBlur={() => setTimeout(() => ac.setShowMenu(false), 200)}
          placeholder={placeholder}
          autoFocus
          className="min-h-0 flex-1 resize-none rounded-md bg-input px-4 py-3 font-mono text-[16px] leading-[1.6] text-text outline-none placeholder:text-text-dim focus:ring-2 focus:ring-accent/25"
        />
        <div className="flex justify-end px-1 pt-1.5">
          <span className="text-[11px] text-text-dim">
            {value.length} chars &middot; ~{Math.ceil(value.length / 4)} tokens
          </span>
        </div>
      </div>

      <AutocompleteMenu
        show={ac.showMenu}
        items={ac.filtered}
        activeIdx={ac.activeIdx}
        menuPos={ac.menuPos}
        onSelect={ac.selectItem}
        onHover={ac.setActiveIdx}
        onClose={() => ac.setShowMenu(false)}
      />
    </div>,
    document.body
  );
}

// ---------------------------------------------------------------------------
// Main prompt editor component
// ---------------------------------------------------------------------------
export function PromptEditor({
  value,
  onChange,
  label,
  placeholder = "Enter prompt...",
  rows = 5,
  helpText,
  generateContext,
  fieldType,
  botId,
  channelId,
}: Props) {
  const { data: completions } = useCompletions();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const ac = usePromptAutocomplete(textareaRef, containerRef, value, onChange, completions);
  const minHeight = Math.max(160, rows * 28);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex min-h-[30px] items-center justify-between gap-2">
        <div className="min-w-0">
          {label && <div className="truncate text-[12px] font-medium text-text-muted">{label}</div>}
          <div className="text-[11px] text-text-dim">Type @ to insert tags</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
            {(generateContext || fieldType) && (
              <GenerateButton generateContext={generateContext} fieldType={fieldType} botId={botId} channelId={channelId} value={value} onChange={onChange} />
            )}
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="min-h-[28px] rounded-md bg-transparent px-2 text-[11px] font-semibold text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text-muted"
            >
              Expand
            </button>
        </div>
      </div>
      <div ref={containerRef} className="rounded-md bg-input focus-within:ring-2 focus-within:ring-accent/25">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => ac.handleInput(e.target.value)}
          onKeyDown={((e: React.KeyboardEvent) => ac.handleKeyDown(e)) as any}
          onBlur={() => setTimeout(() => ac.setShowMenu(false), 200)}
          placeholder={placeholder}
          rows={rows}
          style={{ minHeight }}
          className="block w-full resize-y rounded-md bg-transparent px-3 py-2.5 font-mono text-[16px] leading-[1.55] text-text outline-none placeholder:text-text-dim"
        />
      </div>
      <div className="flex items-center justify-between gap-3">
        {helpText ? (
          <span className="min-w-0 text-[11px] text-text-dim">{helpText}</span>
        ) : <span />}
        <span className="shrink-0 text-[11px] text-text-dim">
          {value.length} chars &middot; ~{Math.ceil(value.length / 4)} tokens
        </span>
      </div>

      <AutocompleteMenu
        show={ac.showMenu}
        items={ac.filtered}
        activeIdx={ac.activeIdx}
        menuPos={ac.menuPos}
        onSelect={ac.selectItem}
        onHover={ac.setActiveIdx}
        onClose={() => ac.setShowMenu(false)}
      />

      {expanded && (
        <FullscreenEditor
          value={value}
          onChange={onChange}
          label={label}
          placeholder={placeholder}
          generateContext={generateContext}
          fieldType={fieldType}
          botId={botId}
          channelId={channelId}
          onClose={() => setExpanded(false)}
        />
      )}
    </div>
  );
}

// Backward-compatible name for existing callers.
export function LlmPrompt(props: Props) {
  return <PromptEditor {...props} />;
}
