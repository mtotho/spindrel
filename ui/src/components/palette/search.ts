import { useCallback, useMemo } from "react";
import { useUIStore, type RecentPage } from "../../stores/ui";
import type { PaletteItem, ScoredItem } from "./types";
import { fuzzyMatch } from "./fuzzy";
import { categoryRank } from "./admin-items.js";
import { shouldSkipRecentPage } from "../../lib/recentPages";
import { resolveRecentPaletteItem, type RecentPaletteItemCandidate } from "./recent";

export interface PaletteSearchOptions {
  /** Current page href — excluded from Recent to avoid self-link. */
  currentHref: string;
  /** Cap on Recent entries included when no query. */
  recentLimit?: number;
  /** Cap on search-result entries returned when query is non-empty. */
  searchLimit?: number;
  /** Whether admin-only recent targets should be shown. */
  isAdmin?: boolean;
  /** Active surface owning this palette session. Drives canvas-aware grouping. */
  surface?: "canvas" | null;
  /** Channel ids that exist as spatial nodes on the canvas — only meaningful
   *  when `surface === "canvas"`. Channels in this set are re-badged into
   *  the "On the map" group and given a small ranking boost. */
  onMapChannelIds?: Set<string>;
}

export interface PaletteSearchResult {
  scored: ScoredItem[];
  /** Category → ordered entries, for grouped rendering. */
  groups: { category: string; items: ScoredItem[] }[];
  /** Full count of valid recents (for "show more" toggles). */
  totalRecents: number;
  /** True when the query is empty (browse mode). */
  isEmpty: boolean;
}

export function shouldIncludePaletteBrowseItem(item: PaletteItem): boolean {
  return !item.hideFromBrowse;
}

export function shouldIncludePaletteSearchItem(item: PaletteItem): boolean {
  return !item.hideFromSearch;
}

export function scorePaletteSearchItems(
  items: PaletteItem[],
  query: string,
  recencyBonus: Map<string, number> = new Map(),
  searchLimit = 30,
): ScoredItem[] {
  return items
    .map((item) => {
      const [labelScore, labelIndices] = fuzzyMatch(query, item.label);
      const [hintScore] = item.hint ? fuzzyMatch(query, item.hint) : [0, []];
      const [catScore] = fuzzyMatch(query, item.category);
      const [searchTextScore] = item.searchText ? fuzzyMatch(query, item.searchText) : [0, []];
      const bestScore = Math.max(labelScore, hintScore * 0.5, catScore * 0.3, searchTextScore * 0.9);
      const bonus = item.href ? recencyBonus.get(item.href) ?? 0 : 0;
      return {
        item,
        score: bestScore + bonus,
        matchIndices: labelScore >= hintScore * 0.5 ? labelIndices : [],
      };
    })
    .filter((r) => r.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, searchLimit);
}

export type CollapsiblePaletteBrowseSection = "tools" | "policies" | "traces";

export function getCollapsiblePaletteBrowseSection(item: PaletteItem): CollapsiblePaletteBrowseSection | null {
  if (item.id.startsWith("tool-")) return "tools";
  if (item.id.startsWith("policy-")) return "policies";
  if (item.id.startsWith("trace-")) return "traces";
  return null;
}

/**
 * Score, group, and order palette items for a given query.
 *
 * Empty query → browse mode: Recent pinned at top, remaining items ordered by
 * CATEGORY_ORDER, sub-pages (hint refers to a parent label) pruned.
 *
 * Non-empty query → fuzzy-ranked flat list with recency bonuses applied.
 */
export function usePaletteSearch(
  allItems: PaletteItem[],
  query: string,
  {
    currentHref,
    recentLimit = 20,
    searchLimit = 30,
    isAdmin = true,
    surface = null,
    onMapChannelIds,
  }: PaletteSearchOptions,
): PaletteSearchResult {
  // When the spatial canvas owns the palette session, channel items whose id
  // exists as a spatial node are re-badged into the "On the map" group so the
  // user can see at-a-glance which tiles are reachable on the canvas. The
  // re-badge is per-render only — we never mutate the input items.
  const sourceItems = useMemo(() => {
    if (surface !== "canvas" || !onMapChannelIds || onMapChannelIds.size === 0) {
      return allItems;
    }
    return allItems.map((it) => {
      if (it.category !== "Channels") return it;
      if (typeof it.href !== "string") return it;
      const tail = it.href.startsWith("/channels/") ? it.href.slice("/channels/".length) : "";
      if (!tail || tail.includes("/")) return it;
      if (!onMapChannelIds.has(tail)) return it;
      return { ...it, category: "On the map" };
    });
  }, [allItems, surface, onMapChannelIds]);

  const recentPages = useUIStore((s) => s.recentPages);
  const channelNameById = useMemo(
    () => {
      const channelItems = allItems.filter(
        (item): item is PaletteItem & { href: string } =>
          item.category === "Channels"
          && typeof item.href === "string"
          && item.href.startsWith("/channels/")
          && !item.href.slice("/channels/".length).includes("/"),
      );
      return new Map(
        channelItems.map((item) => [
          item.href.slice("/channels/".length),
          item.label.replace(/^Chat · /, "").replace(/^#/, ""),
        ]),
      );
    },
    [allItems],
  );

  const resolveRecent = useCallback(
    (rp: RecentPage): PaletteItem | null => {
      const navigableItems = allItems.filter(
        (item): item is RecentPaletteItemCandidate => typeof item.href === "string",
      );
      return resolveRecentPaletteItem(rp, navigableItems, { channelNameById });
    },
    [allItems, channelNameById],
  );

  const parentLabels = useMemo(() => {
    const set = new Set<string>();
    for (const it of allItems) if (!it.hint?.startsWith("Edit")) set.add(it.label);
    return set;
  }, [allItems]);

  const isSubPage = useCallback(
    (it: PaletteItem) => it.hint != null && parentLabels.has(it.hint),
    [parentLabels],
  );

  const totalRecents = useMemo(() => {
    let count = 0;
    for (const rp of recentPages) {
      if (shouldSkipRecentPage(rp, currentHref, isAdmin)) continue;
      if (resolveRecent(rp)) count++;
    }
    return count;
  }, [recentPages, currentHref, resolveRecent, isAdmin]);

  const scored = useMemo<ScoredItem[]>(() => {
    if (!query.trim()) {
      const recentItems: ScoredItem[] = [];
      const recentHrefs = new Set<string>();
      for (const rp of recentPages) {
        if (recentItems.length >= recentLimit) break;
        if (shouldSkipRecentPage(rp, currentHref, isAdmin)) continue;
        const resolved = resolveRecent(rp);
        if (resolved?.href) {
          recentItems.push({ item: resolved, score: 2, matchIndices: [] });
          recentHrefs.add(resolved.href);
        }
      }
      const rest = sourceItems
        .filter((it) => {
          if (!shouldIncludePaletteBrowseItem(it)) return false;
          if (isSubPage(it)) return false;
          const href = it.href;
          return typeof href !== "string" || !recentHrefs.has(href);
        })
        .map((item) => ({ item, score: 1, matchIndices: [] as number[] }));
      return [...recentItems, ...rest];
    }

    const allItemsByHref = new Set(
      sourceItems.map((it) => it.href).filter((href): href is string => typeof href === "string"),
    );
    const syntheticRecents: PaletteItem[] = [];
    for (const rp of recentPages) {
      if (shouldSkipRecentPage(rp, currentHref, isAdmin)) continue;
      if (allItemsByHref.has(rp.href)) continue;
      const resolved = resolveRecent(rp);
      if (resolved?.href) syntheticRecents.push(resolved);
    }
    const searchPool = [...sourceItems.filter(shouldIncludePaletteSearchItem), ...syntheticRecents];

    const recencyBonus = new Map<string, number>();
    let bonusSlot = 0;
    for (const rp of recentPages) {
      if (bonusSlot >= 3) break;
      if (shouldSkipRecentPage(rp, currentHref, isAdmin)) continue;
      recencyBonus.set(rp.href, 15 - bonusSlot * 5);
      bonusSlot++;
    }

    return scorePaletteSearchItems(searchPool, query, recencyBonus, searchLimit);
  }, [query, sourceItems, recentPages, currentHref, resolveRecent, isSubPage, recentLimit, searchLimit, isAdmin]);

  const isEmpty = !query.trim();

  const groups = useMemo(() => {
    const out: { category: string; items: ScoredItem[] }[] = [];
    const catMap = new Map<string, ScoredItem[]>();
    for (const s of scored) {
      const cat = s.item.category;
      let arr = catMap.get(cat);
      if (!arr) {
        arr = [];
        catMap.set(cat, arr);
        out.push({ category: cat, items: arr });
      }
      arr.push(s);
    }
    if (isEmpty) {
      out.sort((a, b) => categoryRank(a.category) - categoryRank(b.category));
    }
    return out;
  }, [scored, isEmpty]);

  return { scored, groups, totalRecents, isEmpty };
}
