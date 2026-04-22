import { Hash, MessageCircle } from "lucide-react";
import { formatSessionRecentLabel, formatThreadRecentLabel, parseChannelRecentRoute, } from "../../lib/recentPages.js";
import { resolveRouteMetadata } from "./route-meta.js";
function buildItem(href, label, hint, icon, category) {
    return {
        id: `recent-${href}`,
        label,
        href,
        hint,
        icon,
        category,
    };
}
export function resolveRecentPaletteItem(recentPage, allItems, { channelNameById } = {}) {
    const exact = allItems.find((item) => item.href === recentPage.href);
    if (exact)
        return exact;
    const parsed = parseChannelRecentRoute(recentPage.href);
    if (parsed?.kind === "session") {
        const channelName = channelNameById?.get(parsed.channelId);
        const label = recentPage.label?.trim()
            || (channelName ? formatSessionRecentLabel(channelName) : "Session");
        return buildItem(recentPage.href, label, "Session", Hash, "Channels");
    }
    if (parsed?.kind === "thread") {
        const channelName = channelNameById?.get(parsed.channelId);
        const label = recentPage.label?.trim()
            || (channelName ? formatThreadRecentLabel(channelName) : "Thread");
        return buildItem(recentPage.href, label, "Thread", MessageCircle, "Channels");
    }
    if (parsed?.kind === "channel") {
        const channelName = recentPage.label?.trim() || channelNameById?.get(parsed.channelId) || "Channel";
        return buildItem(recentPage.href, channelName, "Channel", Hash, "Channels");
    }
    const meta = resolveRouteMetadata(recentPage.href);
    if (!meta)
        return null;
    const baseLabel = meta.fallbackLabel.split(":")[0];
    const label = recentPage.label?.trim()
        ? `${baseLabel}: ${recentPage.label.trim()}`
        : meta.fallbackLabel;
    return buildItem(recentPage.href, label, meta.category, meta.icon, meta.category);
}
