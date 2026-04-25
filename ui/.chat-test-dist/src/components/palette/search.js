import { useCallback, useMemo } from "react";
import { useUIStore } from "../../stores/ui";
import { fuzzyMatch } from "./fuzzy";
import { categoryRank } from "./admin-items.js";
import { shouldSkipRecentPage } from "../../lib/recentPages";
import { resolveRecentPaletteItem } from "./recent";
export function shouldIncludePaletteBrowseItem(item) {
    return !item.hideFromBrowse;
}
export function shouldIncludePaletteSearchItem(item) {
    return !item.hideFromSearch;
}
export function scorePaletteSearchItems(items, query, recencyBonus = new Map(), searchLimit = 30) {
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
export function getCollapsiblePaletteBrowseSection(item) {
    if (item.id.startsWith("tool-"))
        return "tools";
    if (item.id.startsWith("policy-"))
        return "policies";
    if (item.id.startsWith("trace-"))
        return "traces";
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
export function usePaletteSearch(allItems, query, { currentHref, recentLimit = 20, searchLimit = 30, isAdmin = true }) {
    const recentPages = useUIStore((s) => s.recentPages);
    const channelNameById = useMemo(() => {
        const channelItems = allItems.filter((item) => item.category === "Channels"
            && typeof item.href === "string"
            && item.href.startsWith("/channels/")
            && !item.href.slice("/channels/".length).includes("/"));
        return new Map(channelItems.map((item) => [
            item.href.slice("/channels/".length),
            item.label.replace(/^Chat · /, "").replace(/^#/, ""),
        ]));
    }, [allItems]);
    const resolveRecent = useCallback((rp) => {
        const navigableItems = allItems.filter((item) => typeof item.href === "string");
        return resolveRecentPaletteItem(rp, navigableItems, { channelNameById });
    }, [allItems, channelNameById]);
    const parentLabels = useMemo(() => {
        const set = new Set();
        for (const it of allItems)
            if (!it.hint?.startsWith("Edit"))
                set.add(it.label);
        return set;
    }, [allItems]);
    const isSubPage = useCallback((it) => it.hint != null && parentLabels.has(it.hint), [parentLabels]);
    const totalRecents = useMemo(() => {
        let count = 0;
        for (const rp of recentPages) {
            if (shouldSkipRecentPage(rp, currentHref, isAdmin))
                continue;
            if (resolveRecent(rp))
                count++;
        }
        return count;
    }, [recentPages, currentHref, resolveRecent, isAdmin]);
    const scored = useMemo(() => {
        if (!query.trim()) {
            const recentItems = [];
            const recentHrefs = new Set();
            for (const rp of recentPages) {
                if (recentItems.length >= recentLimit)
                    break;
                if (shouldSkipRecentPage(rp, currentHref, isAdmin))
                    continue;
                const resolved = resolveRecent(rp);
                if (resolved?.href) {
                    recentItems.push({ item: resolved, score: 2, matchIndices: [] });
                    recentHrefs.add(resolved.href);
                }
            }
            const rest = allItems
                .filter((it) => {
                if (!shouldIncludePaletteBrowseItem(it))
                    return false;
                if (isSubPage(it))
                    return false;
                const href = it.href;
                return typeof href !== "string" || !recentHrefs.has(href);
            })
                .map((item) => ({ item, score: 1, matchIndices: [] }));
            return [...recentItems, ...rest];
        }
        const allItemsByHref = new Set(allItems.map((it) => it.href).filter((href) => typeof href === "string"));
        const syntheticRecents = [];
        for (const rp of recentPages) {
            if (shouldSkipRecentPage(rp, currentHref, isAdmin))
                continue;
            if (allItemsByHref.has(rp.href))
                continue;
            const resolved = resolveRecent(rp);
            if (resolved?.href)
                syntheticRecents.push(resolved);
        }
        const searchPool = [...allItems.filter(shouldIncludePaletteSearchItem), ...syntheticRecents];
        const recencyBonus = new Map();
        let bonusSlot = 0;
        for (const rp of recentPages) {
            if (bonusSlot >= 3)
                break;
            if (shouldSkipRecentPage(rp, currentHref, isAdmin))
                continue;
            recencyBonus.set(rp.href, 15 - bonusSlot * 5);
            bonusSlot++;
        }
        return scorePaletteSearchItems(searchPool, query, recencyBonus, searchLimit);
    }, [query, allItems, recentPages, currentHref, resolveRecent, isSubPage, recentLimit, searchLimit, isAdmin]);
    const isEmpty = !query.trim();
    const groups = useMemo(() => {
        const out = [];
        const catMap = new Map();
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
