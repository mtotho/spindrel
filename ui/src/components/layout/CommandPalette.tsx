import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import ReactDOM from "react-dom";
import {
  ChevronDown,
  ChevronUp,
  CornerDownLeft,
  Search,
  X,
} from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useThemeTokens } from "../../theme/tokens";
import { useUIStore } from "../../stores/ui";
import { usePaletteActions } from "../../stores/paletteActions";
import { buildRecentHref } from "../../lib/recentPages";
import { normalizePalettePathInput, resolvePaletteRoute } from "../../lib/paletteRoutes.js";
import { useIsAdmin } from "../../hooks/useScope";
import { SpindrelLogo } from "./SpindrelLogo";
import { HighlightedLabel } from "../palette/HighlightedLabel";
import { usePaletteItems } from "../palette/items";
import {
  getCollapsiblePaletteBrowseSection,
  usePaletteSearch,
  type CollapsiblePaletteBrowseSection,
} from "../palette/search";
import type { PaletteItem, ScoredItem } from "../palette/types";

const COLLAPSIBLE_BROWSE_LABELS: Record<CollapsiblePaletteBrowseSection, string> = {
  tools: "Tools",
  policies: "Policies",
  traces: "Traces",
};

export function useCommandPaletteShortcut() {
  const openPalette = useUIStore((s) => s.openPalette);
  const closePalette = useUIStore((s) => s.closePalette);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        const isOpen = useUIStore.getState().paletteOpen;
        if (isOpen) closePalette();
        else openPalette();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [openPalette, closePalette]);
}

export interface CommandPaletteContentProps {
  variant: "modal" | "inline";
  onAfterSelect?: (item: PaletteItem) => void;
  autoFocus?: boolean;
  showInlineClose?: boolean;
  onEscape?: () => void;
}

export function CommandPaletteContent({
  variant,
  onAfterSelect,
  autoFocus,
  showInlineClose = false,
  onEscape,
}: CommandPaletteContentProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const location = useLocation();
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const isAdmin = useIsAdmin();
  const currentHref = buildRecentHref(location.pathname, location.search, location.hash);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const closeMobileSidebar = useUIStore((s) => s.closeMobileSidebar);
  const recordPageVisit = useUIStore((s) => s.recordPageVisit);
  const registeredActions = usePaletteActions((s) => s.actions);
  const shouldAutoFocus = autoFocus ?? (variant === "modal");
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [recentsExpanded, setRecentsExpanded] = useState(false);
  const [expandedBrowseSections, setExpandedBrowseSections] = useState<Set<CollapsiblePaletteBrowseSection>>(
    () => new Set(),
  );
  const isKeyboardNav = useRef(false);

  useEffect(() => {
    if (shouldAutoFocus) {
      const a = requestAnimationFrame(() => {
        const b = requestAnimationFrame(() => inputRef.current?.focus());
        return () => cancelAnimationFrame(b);
      });
      return () => cancelAnimationFrame(a);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sharedItems = usePaletteItems();
  const actionItems = useMemo<PaletteItem[]>(
    () =>
      registeredActions.map((action) => ({
        id: action.id,
        label: action.label,
        hint: action.hint,
        icon: action.icon,
        category: action.category,
        onSelect: action.onSelect,
      })),
    [registeredActions],
  );

  const exactPathItem = useMemo<PaletteItem | null>(() => {
    if (!query.trim()) return null;
    const normalized = normalizePalettePathInput(query);
    if (!normalized) return null;
    const route = resolvePaletteRoute(normalized);
    if (!route) return null;
    return {
      id: `open-path-${route.canonicalHref}`,
      label: `Open path · ${route.canonicalHref}`,
      hint: route.label,
      href: route.canonicalHref,
      icon: route.icon,
      category: route.category,
      routeKind: route.routeKind,
    };
  }, [query]);

  const allItems = useMemo(
    () => [...actionItems, ...sharedItems, ...(exactPathItem ? [exactPathItem] : [])],
    [actionItems, exactPathItem, sharedItems],
  );

  const { groups, scored, totalRecents } = usePaletteSearch(allItems, query, {
    currentHref,
    recentLimit: recentsExpanded ? 20 : 5,
    searchLimit: 30,
    isAdmin,
  });

  const isBrowseMode = !query.trim();
  const showRecentsToggle = !query.trim() && totalRecents > 5;

  const groupedResults = useMemo(() => {
    let flatIndex = 0;
    let showMoreToggleIndex = -1;
    const flat: Array<
      | { kind: "item"; scored: ScoredItem }
      | { kind: "recents-toggle" }
      | { kind: "collapsed-section"; section: CollapsiblePaletteBrowseSection }
    > = [];
    const indexedGroups = groups.map((group) => {
      const sectionCounts = new Map<CollapsiblePaletteBrowseSection, number>();
      const entries: Array<{ scored: ScoredItem; flatIndex: number }> = [];
      const collapsedToggles: Array<{ section: CollapsiblePaletteBrowseSection; count: number; flatIndex: number }> = [];

      for (const scoredItem of group.items) {
        const section = isBrowseMode ? getCollapsiblePaletteBrowseSection(scoredItem.item) : null;
        if (section) sectionCounts.set(section, (sectionCounts.get(section) ?? 0) + 1);
        if (section && !expandedBrowseSections.has(section)) {
          continue;
        }
        const entry = { scored: scoredItem, flatIndex };
        flat.push({ kind: "item", scored: scoredItem });
        flatIndex += 1;
        entries.push(entry);
      }

      for (const [section, count] of sectionCounts) {
        const entry = { section, count, flatIndex };
        flat.push({ kind: "collapsed-section", section });
        flatIndex += 1;
        collapsedToggles.push(entry);
      }

      if (group.category === "Recent" && showRecentsToggle) {
        showMoreToggleIndex = flatIndex;
        flat.push({ kind: "recents-toggle" });
        flatIndex += 1;
      }
      return { category: group.category, items: entries, collapsedToggles };
    });

    return { groups: indexedGroups, totalCount: flatIndex, flat, showMoreToggleIndex };
  }, [expandedBrowseSections, groups, isBrowseMode, showRecentsToggle]);

  const toggleBrowseSection = useCallback((section: CollapsiblePaletteBrowseSection) => {
    setExpandedBrowseSections((current) => {
      const next = new Set(current);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  }, []);

  useEffect(() => {
    if (query.trim()) setRecentsExpanded(false);
  }, [query]);

  useEffect(() => {
    setSelectedIndex((idx) => Math.max(0, Math.min(idx, Math.max(groupedResults.totalCount - 1, 0))));
  }, [groupedResults.totalCount]);

  useEffect(() => {
    if (!listRef.current || !isKeyboardNav.current) return;
    const el = listRef.current.querySelector(`[data-idx="${selectedIndex}"]`) as HTMLElement | null;
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const go = useCallback(
    (item: PaletteItem, href: string) => {
      recordPageVisit(href);
      onAfterSelect?.(item);
      closeMobileSidebar();
      const hashIdx = href.indexOf("#");
      if (hashIdx >= 0) {
        const path = href.slice(0, hashIdx);
        const hash = href.slice(hashIdx);
        navigate(path);
        requestAnimationFrame(() => {
          window.location.hash = hash;
        });
      } else {
        navigate(href);
      }
      setQuery("");
      setSelectedIndex(0);
    },
    [closeMobileSidebar, navigate, onAfterSelect, recordPageVisit],
  );

  const selectItem = useCallback(
    (item: PaletteItem) => {
      if (item.onSelect) {
        onAfterSelect?.(item);
        closeMobileSidebar();
        item.onSelect();
        return;
      }
      if (item.href) go(item, item.href);
    },
    [closeMobileSidebar, go, onAfterSelect],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (variant === "inline" && query) {
          setQuery("");
          setSelectedIndex(0);
        } else {
          onEscape?.();
        }
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        isKeyboardNav.current = true;
        setSelectedIndex((idx) => (groupedResults.totalCount > 0 ? Math.min(idx + 1, groupedResults.totalCount - 1) : 0));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        isKeyboardNav.current = true;
        setSelectedIndex((idx) => Math.max(idx - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (selectedIndex === groupedResults.showMoreToggleIndex) {
          setRecentsExpanded((value) => !value);
          return;
        }
        const entry = groupedResults.flat[selectedIndex];
        if (!entry) return;
        if (entry.kind === "collapsed-section") {
          toggleBrowseSection(entry.section);
          return;
        }
        if (entry.kind === "item") selectItem(entry.scored.item);
      }
    },
    [groupedResults, onEscape, query, selectedIndex, selectItem, toggleBrowseSection, variant],
  );

  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
  const modKey = isMac ? "\u2318" : "Ctrl";

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        background: "transparent",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 10,
          padding: isMobile ? "12px 12px" : "14px 16px",
          paddingTop: isMobile ? "max(12px, env(safe-area-inset-top))" : 14,
          borderBottom: `1px solid ${t.surfaceBorder}`,
        }}
      >
        <span
          style={{
            flexShrink: 0,
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            color: t.textMuted,
          }}
          aria-label="Spindrel"
        >
          <SpindrelLogo size={isMobile ? 20 : 18} />
        </span>
        <span style={{ flexShrink: 0, display: "flex", flexDirection: "row" }}>
          <Search size={isMobile ? 18 : 16} color={t.textDim} />
        </span>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSelectedIndex(0);
          }}
          onKeyDown={onKeyDown}
          placeholder={isMobile ? "Search or browse..." : "Search channels, bots, settings..."}
          style={{
            flex: 1,
            background: "none",
            border: "none",
            outline: "none",
            fontSize: isMobile ? 16 : 15,
            color: t.text,
            fontFamily: "inherit",
            minWidth: 0,
          }}
        />
        {showInlineClose ? (
          <button
            onClick={() => onEscape?.()}
            aria-label="Close"
            style={{
              flexShrink: 0,
              width: 36,
              height: 36,
              borderRadius: 8,
              background: "transparent",
              border: "none",
              color: t.textMuted,
              fontSize: 14,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 0,
            }}
          >
            <X size={20} color={t.textMuted} />
          </button>
        ) : variant === "modal" && !isMobile ? (
          <kbd
            style={{
              fontSize: 11,
              color: t.textDim,
              background: t.surface,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4,
              padding: "2px 6px",
              flexShrink: 0,
            }}
          >
            esc
          </kbd>
        ) : null}
      </div>

      <div
        ref={listRef}
        className="scroll-subtle"
        style={{
          overflow: "auto",
          flex: 1,
          padding: "4px 0",
        }}
      >
        {scored.length === 0 && query.trim() && (
          <div
            style={{
              padding: "32px 16px",
              textAlign: "center",
              fontSize: 13,
              color: t.textDim,
            }}
          >
            No results for &ldquo;{query}&rdquo;
          </div>
        )}
        {groupedResults.groups.map((group) => (
          <div key={group.category}>
            <div
              style={{
                padding: isMobile ? "10px 16px 4px" : "8px 18px 4px",
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: 0.3,
                color: t.textDim,
                textTransform: "uppercase",
              }}
            >
              {group.category}
            </div>
            {group.items.map(({ scored: scoredItem, flatIndex }) => {
              const { item, matchIndices } = scoredItem;
              const Icon = item.icon;
              const selected = flatIndex === selectedIndex;
              return (
                <div
                  key={item.id}
                  data-idx={flatIndex}
                  onClick={() => selectItem(item)}
                  onMouseMove={() => {
                    isKeyboardNav.current = false;
                    setSelectedIndex(flatIndex);
                  }}
                  style={{
                    display: "flex",
                    flexDirection: "row",
                    alignItems: "center",
                    gap: isMobile ? 12 : 10,
                    padding: isMobile ? "12px 14px" : "7px 14px",
                    minHeight: isMobile ? 48 : undefined,
                    margin: "0 6px",
                    borderRadius: 6,
                    cursor: "pointer",
                    backgroundColor: selected ? t.accentSubtle : "transparent",
                    transition: "background-color 80ms ease",
                  }}
                >
                  <span style={{ flexShrink: 0, display: "flex", flexDirection: "row" }}>
                    <Icon size={isMobile ? 18 : 16} color={selected ? t.accent : t.textDim} />
                  </span>
                  <span
                    style={{
                      flex: 1,
                      fontSize: isMobile ? 15 : 14,
                      color: selected ? t.text : t.textMuted,
                      fontWeight: selected ? 500 : 400,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    <HighlightedLabel
                      text={item.label}
                      indices={matchIndices}
                      color={selected ? t.text : t.textMuted}
                      accentColor={t.accent}
                    />
                  </span>
                  {item.hint && (
                    <span
                      style={{
                        fontSize: 12,
                        color: t.textDim,
                        whiteSpace: "nowrap",
                        flexShrink: 0,
                      }}
                    >
                      {item.hint}
                    </span>
                  )}
                  {selected && (
                    <span style={{ flexShrink: 0, display: "flex", flexDirection: "row" }}>
                      <CornerDownLeft size={12} color={t.textDim} />
                    </span>
                  )}
                </div>
              );
            })}
            {group.category === "Recent" && showRecentsToggle && (
              <div
                data-idx={groupedResults.showMoreToggleIndex}
                onClick={() => setRecentsExpanded((value) => !value)}
                onMouseMove={() => {
                  isKeyboardNav.current = false;
                  setSelectedIndex(groupedResults.showMoreToggleIndex);
                }}
                style={{
                  display: "flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 10,
                  padding: "7px 14px",
                  margin: "0 6px",
                  borderRadius: 6,
                  cursor: "pointer",
                  backgroundColor: groupedResults.showMoreToggleIndex === selectedIndex ? t.accentSubtle : "transparent",
                  transition: "background-color 80ms ease",
                }}
              >
                <span style={{ flexShrink: 0, display: "flex", flexDirection: "row" }}>
                  {recentsExpanded ? <ChevronUp size={14} color={t.textDim} /> : <ChevronDown size={14} color={t.textDim} />}
                </span>
                <span
                  style={{
                    flex: 1,
                    fontSize: 13,
                    color: t.textDim,
                  }}
                >
                  {recentsExpanded ? "Show less" : `Show more (${totalRecents - 5})`}
                </span>
              </div>
            )}
            {group.collapsedToggles.map(({ section, count, flatIndex }) => {
              const selected = flatIndex === selectedIndex;
              const expanded = expandedBrowseSections.has(section);
              return (
                <div
                  key={`collapsed-${section}`}
                  data-idx={flatIndex}
                  onClick={() => toggleBrowseSection(section)}
                  onMouseMove={() => {
                    isKeyboardNav.current = false;
                    setSelectedIndex(flatIndex);
                  }}
                  style={{
                    display: "flex",
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 10,
                    padding: "7px 14px",
                    margin: "0 6px",
                    borderRadius: 6,
                    cursor: "pointer",
                    backgroundColor: selected ? t.accentSubtle : "transparent",
                    transition: "background-color 80ms ease",
                  }}
                >
                  <span style={{ flexShrink: 0, display: "flex", flexDirection: "row" }}>
                    {expanded ? <ChevronUp size={14} color={t.textDim} /> : <ChevronDown size={14} color={t.textDim} />}
                  </span>
                  <span
                    style={{
                      flex: 1,
                      fontSize: 13,
                      color: t.textDim,
                    }}
                  >
                    {expanded ? `Collapse ${COLLAPSIBLE_BROWSE_LABELS[section]}` : `Show ${COLLAPSIBLE_BROWSE_LABELS[section]} (${count})`}
                  </span>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {variant === "modal" && !isMobile && (
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 16,
            padding: "8px 16px",
            borderTop: `1px solid ${t.surfaceBorder}`,
            fontSize: 11,
            color: t.textDim,
          }}
        >
          <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Kbd t={t}>&uarr;</Kbd>
            <Kbd t={t}>&darr;</Kbd>
            navigate
          </span>
          <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Kbd t={t}>&crarr;</Kbd>
            open
          </span>
          <span style={{ marginLeft: "auto", display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Kbd t={t}>{modKey}+K</Kbd>
            toggle
          </span>
        </div>
      )}
    </div>
  );
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useThemeTokens();
  const columns = useResponsiveColumns();
  const isMobile = columns === "single";
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setVisible(true));
      });
    } else {
      setVisible(false);
      const timer = setTimeout(() => setMounted(false), 180);
      return () => clearTimeout(timer);
    }
  }, [open]);

  if (!mounted || typeof document === "undefined") return null;

  const shellStyle: CSSProperties = isMobile
    ? {
        position: "fixed",
        inset: 0,
        zIndex: 10031,
        background: t.surface,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(8px)",
        transition: visible
          ? "opacity 160ms ease-out, transform 160ms ease-out"
          : "opacity 120ms ease-in, transform 120ms ease-in",
      }
    : {
        position: "fixed",
        top: "min(20%, 160px)",
        left: "50%",
        width: 560,
        maxWidth: "92vw",
        maxHeight: "min(70vh, 480px)",
        zIndex: 10031,
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 12,
        boxShadow: "0 16px 48px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.04) inset",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        opacity: visible ? 1 : 0,
        transform: visible
          ? "translate(-50%, 0) scale(1)"
          : "translate(-50%, -8px) scale(0.98)",
        transition: visible
          ? "opacity 160ms ease-out, transform 160ms ease-out"
          : "opacity 120ms ease-in, transform 120ms ease-in",
      };

  return ReactDOM.createPortal(
    <>
      {!isMobile && (
        <div
          onClick={onClose}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            backdropFilter: "blur(4px)",
            WebkitBackdropFilter: "blur(4px)",
            zIndex: 10030,
            opacity: visible ? 1 : 0,
            transition: "opacity 160ms ease-out",
          }}
        />
      )}
      <div style={shellStyle}>
        <CommandPaletteContent
          variant="modal"
          autoFocus
          onAfterSelect={onClose}
          onEscape={onClose}
          showInlineClose={isMobile}
        />
      </div>
    </>,
    document.body,
  );
}

function Kbd({ t, children }: { t: ReturnType<typeof useThemeTokens>; children: React.ReactNode }) {
  return (
    <kbd
      style={{
        background: t.surface,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 3,
        padding: "1px 5px",
        fontSize: 10,
        fontFamily: "inherit",
        lineHeight: "16px",
      }}
    >
      {children}
    </kbd>
  );
}
