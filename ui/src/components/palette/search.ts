import { useCallback, useMemo } from "react";
import { useUIStore, type RecentPage } from "../../stores/ui";
import type { PaletteItem, ScoredItem } from "./types";
import { fuzzyMatch } from "./fuzzy";
import { categoryRank } from "./admin-items";
import { resolveRouteMetadata } from "./route-meta";

export interface PaletteSearchOptions {
  /** Current page href — excluded from Recent to avoid self-link. */
  currentHref: string;
  /** Cap on Recent entries included when no query. */
  recentLimit?: number;
  /** Cap on search-result entries returned when query is non-empty. */
  searchLimit?: number;
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
  { currentHref, recentLimit = 20, searchLimit = 30 }: PaletteSearchOptions,
): PaletteSearchResult {
  const recentPages = useUIStore((s) => s.recentPages);

  const resolveRecent = useCallback(
    (rp: RecentPage): PaletteItem | null => {
      const match = allItems.find((it) => it.href === rp.href);
      if (match) return match;
      const meta = resolveRouteMetadata(rp.href);
      if (!meta) return null;
      const baseLabel = meta.fallbackLabel.split(":")[0];
      const label = rp.label ? `${baseLabel}: ${rp.label}` : meta.fallbackLabel;
      return {
        id: `recent-${rp.href}`,
        label,
        hint: meta.category,
        href: rp.href,
        icon: meta.icon,
        category: meta.category,
      };
    },
    [allItems],
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
      if (rp.href === currentHref) continue;
      if (resolveRecent(rp)) count++;
    }
    return count;
  }, [recentPages, currentHref, resolveRecent]);

  const scored = useMemo<ScoredItem[]>(() => {
    if (!query.trim()) {
      // Pin recents at the top as their own "Recent" category, but also keep
      // them in their original category so users can find them where they
      // expect (e.g. a recently-opened channel still appears under Channels).
      const recentItems: ScoredItem[] = [];
      for (const rp of recentPages) {
        if (recentItems.length >= recentLimit) break;
        if (rp.href === currentHref) continue;
        const resolved = resolveRecent(rp);
        if (resolved) {
          recentItems.push({ item: { ...resolved, category: "Recent" }, score: 2, matchIndices: [] });
        }
      }
      const rest = allItems
        .filter((it) => !isSubPage(it))
        .map((item) => ({ item, score: 1, matchIndices: [] as number[] }));
      return [...recentItems, ...rest];
    }

    const allItemsByHref = new Set(allItems.map((it) => it.href));
    const syntheticRecents: PaletteItem[] = [];
    for (const rp of recentPages) {
      if (allItemsByHref.has(rp.href)) continue;
      const resolved = resolveRecent(rp);
      if (resolved) syntheticRecents.push(resolved);
    }
    const searchPool = [...allItems, ...syntheticRecents];

    const recencyBonus = new Map<string, number>();
    let bonusSlot = 0;
    for (const rp of recentPages) {
      if (bonusSlot >= 3) break;
      if (rp.href === currentHref) continue;
      recencyBonus.set(rp.href, 15 - bonusSlot * 5);
      bonusSlot++;
    }

    return searchPool
      .map((item) => {
        const [labelScore, labelIndices] = fuzzyMatch(query, item.label);
        const [hintScore] = item.hint ? fuzzyMatch(query, item.hint) : [0, []];
        const [catScore] = fuzzyMatch(query, item.category);
        const bestScore = Math.max(labelScore, hintScore * 0.5, catScore * 0.3);
        const bonus = recencyBonus.get(item.href) ?? 0;
        return {
          item,
          score: bestScore + bonus,
          matchIndices: labelScore >= hintScore * 0.5 ? labelIndices : [],
        };
      })
      .filter((r) => r.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, searchLimit);
  }, [query, allItems, recentPages, currentHref, resolveRecent, isSubPage, recentLimit, searchLimit]);

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
