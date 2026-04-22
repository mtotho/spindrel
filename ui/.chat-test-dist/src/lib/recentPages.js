import { canonicalizePaletteHref, isRecordablePaletteHref } from "./paletteRoutes.js";
const LEGACY_SCRATCH_SESSION_RE = /^\/channels\/[^/]+\/session\/[^/?#]+$/;
const CHANNEL_ROUTE_RE = /^\/channels\/([^/?#]+)$/;
const CHANNEL_SESSION_ROUTE_RE = /^\/channels\/([^/]+)\/session\/([^/?#]+)$/;
const CHANNEL_THREAD_ROUTE_RE = /^\/channels\/([^/]+)\/threads\/([^/?#]+)$/;
export function buildRecentHref(pathname, search = "", hash = "") {
    return `${pathname}${search ?? ""}${hash ?? ""}`;
}
export function migrateRecentPage(page) {
    const href = LEGACY_SCRATCH_SESSION_RE.test(page.href)
        ? `${page.href}?scratch=true`
        : page.href;
    return { ...page, href: canonicalizePaletteHref(href), version: 2 };
}
export function shouldSkipRecentPage(page, currentHref, isAdmin) {
    const href = canonicalizePaletteHref(page.href);
    if (href === canonicalizePaletteHref(currentHref))
        return true;
    if (!isAdmin && page.href.startsWith("/admin/"))
        return true;
    if (!isRecordablePaletteHref(href))
        return true;
    return false;
}
export function formatSessionRecentLabel(channelName, sessionLabel) {
    const trimmed = sessionLabel?.trim();
    return `${trimmed || "Session"} · #${channelName}`;
}
export function formatThreadRecentLabel(channelName) {
    return `Thread · #${channelName}`;
}
export function splitRecentHref(href) {
    const [pathAndSearch] = href.split("#", 1);
    const queryIndex = pathAndSearch.indexOf("?");
    if (queryIndex === -1) {
        return {
            pathname: pathAndSearch,
            searchParams: new URLSearchParams(),
        };
    }
    return {
        pathname: pathAndSearch.slice(0, queryIndex),
        searchParams: new URLSearchParams(pathAndSearch.slice(queryIndex + 1)),
    };
}
export function parseChannelRecentRoute(href) {
    const { pathname, searchParams } = splitRecentHref(href);
    const sessionMatch = pathname.match(CHANNEL_SESSION_ROUTE_RE);
    if (sessionMatch) {
        return {
            kind: "session",
            channelId: sessionMatch[1],
            sessionId: sessionMatch[2],
            isScratch: searchParams.get("scratch") === "true",
        };
    }
    const threadMatch = pathname.match(CHANNEL_THREAD_ROUTE_RE);
    if (threadMatch) {
        return {
            kind: "thread",
            channelId: threadMatch[1],
            threadSessionId: threadMatch[2],
        };
    }
    const channelMatch = pathname.match(CHANNEL_ROUTE_RE);
    if (channelMatch) {
        return {
            kind: "channel",
            channelId: channelMatch[1],
        };
    }
    return null;
}
