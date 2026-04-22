import test from "node:test";
import assert from "node:assert/strict";
import { buildRecentHref, migrateRecentPage, shouldSkipRecentPage, } from "../../lib/recentPages.js";
import { resolveRecentPaletteItem } from "./recent.js";
function makeRecent(href, label) {
    return { href, label };
}
function makeItem(overrides) {
    return {
        id: overrides.id,
        label: overrides.label,
        href: overrides.href,
        icon: overrides.icon ?? (() => null),
        category: overrides.category ?? "Channels",
        hint: overrides.hint,
        lastMessageAt: overrides.lastMessageAt ?? null,
    };
}
test("buildRecentHref preserves search and hash", () => {
    assert.equal(buildRecentHref("/channels/channel-1/session/session-1", "?scratch=true", "#notes"), "/channels/channel-1/session/session-1?scratch=true#notes");
});
test("migrateRecentPage upgrades legacy session hrefs to scratch routes", () => {
    assert.deepEqual(migrateRecentPage(makeRecent("/channels/channel-1/session/session-1")), makeRecent("/channels/channel-1/session/session-1?scratch=true"));
});
test("resolveRecentPaletteItem formats untitled session recents without guids", () => {
    const resolved = resolveRecentPaletteItem(makeRecent("/channels/channel-1/session/session-1?scratch=true"), [], { channelNameById: new Map([["channel-1", "quality-assurance"]]) });
    assert.deepEqual(resolved && {
        label: resolved.label,
        hint: resolved.hint,
        href: resolved.href,
        category: resolved.category,
    }, {
        label: "Session · #quality-assurance",
        hint: "Session",
        href: "/channels/channel-1/session/session-1?scratch=true",
        category: "Channels",
    });
});
test("resolveRecentPaletteItem formats titled session recents without adding a guid prefix", () => {
    const resolved = resolveRecentPaletteItem(makeRecent("/channels/channel-1/session/session-1?scratch=true", "Inbox cleanup · #quality-assurance"), [], { channelNameById: new Map([["channel-1", "quality-assurance"]]) });
    assert.deepEqual(resolved && {
        label: resolved.label,
        hint: resolved.hint,
        href: resolved.href,
        category: resolved.category,
    }, {
        label: "Inbox cleanup · #quality-assurance",
        hint: "Session",
        href: "/channels/channel-1/session/session-1?scratch=true",
        category: "Channels",
    });
});
test("shouldSkipRecentPage treats a full href with search as the current page", () => {
    const currentHref = buildRecentHref("/channels/channel-1/session/session-1", "?scratch=true");
    assert.equal(shouldSkipRecentPage(makeRecent("/channels/channel-1/session/session-1?scratch=true"), currentHref, true), true);
});
test("resolveRecentPaletteItem still prefers exact palette items when present", () => {
    const exactItem = makeItem({
        id: "ch-channel-1",
        label: "quality-assurance",
        href: "/channels/channel-1",
        hint: "slack",
    });
    const resolved = resolveRecentPaletteItem(makeRecent("/channels/channel-1", "stale label"), [exactItem], { channelNameById: new Map([["channel-1", "quality-assurance"]]) });
    assert.equal(resolved?.label, "quality-assurance");
    assert.equal(resolved?.hint, "slack");
});
