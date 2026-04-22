import { resolvePaletteRoute } from "../../lib/paletteRoutes.js";
export function resolveRecentPaletteItem(recentPage, allItems, { channelNameById } = {}) {
    const exact = allItems.find((item) => item.href === recentPage.href);
    const route = resolvePaletteRoute(recentPage.href, {
        channelNameById,
        recentLabel: recentPage.label ?? exact?.label,
        itemHint: exact?.hint ?? recentPage.hint,
    });
    if (!route)
        return null;
    return {
        id: `recent-${route.canonicalHref}`,
        label: route.label,
        href: route.canonicalHref,
        hint: exact?.hint ?? recentPage.hint ?? route.hint,
        icon: route.icon,
        category: "Recent",
    };
}
