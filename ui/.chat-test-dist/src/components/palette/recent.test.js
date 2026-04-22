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
    };
}
test("buildRecentHref preserves search and hash", () => {
    assert.equal(buildRecentHref("/channels/channel-1/session/session-1", "?scratch=true", "#notes"), "/channels/channel-1/session/session-1?scratch=true#notes");
});
test("migrateRecentPage upgrades legacy session hrefs to scratch routes", () => {
    const migrated = migrateRecentPage(makeRecent("/channels/channel-1/session/session-1"));
    assert.equal(migrated.href, "/channels/channel-1/session/session-1?scratch=true");
    assert.equal(migrated.version, 2);
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
        hint: "#quality-assurance",
        href: "/channels/channel-1/session/session-1?scratch=true",
        category: "Recent",
    });
});
test("resolveRecentPaletteItem formats titled session recents as type-first labels", () => {
    const resolved = resolveRecentPaletteItem(makeRecent("/channels/channel-1/session/session-1?scratch=true", "Inbox cleanup · #quality-assurance"), [], { channelNameById: new Map([["channel-1", "quality-assurance"]]) });
    assert.deepEqual(resolved && {
        label: resolved.label,
        hint: resolved.hint,
        href: resolved.href,
        category: resolved.category,
    }, {
        label: "Session · Inbox cleanup",
        hint: "#quality-assurance",
        href: "/channels/channel-1/session/session-1?scratch=true",
        category: "Recent",
    });
});
test("resolveRecentPaletteItem formats channel chat recents as explicit chat destinations", () => {
    const resolved = resolveRecentPaletteItem(makeRecent("/channels/channel-1"), [], { channelNameById: new Map([["channel-1", "quality-assurance"]]) });
    assert.deepEqual(resolved && {
        label: resolved.label,
        hint: resolved.hint,
        category: resolved.category,
    }, {
        label: "Chat · #quality-assurance",
        hint: "Channels",
        category: "Recent",
    });
});
test("shouldSkipRecentPage treats a full href with search as the current page", () => {
    const currentHref = buildRecentHref("/channels/channel-1/session/session-1", "?scratch=true");
    assert.equal(shouldSkipRecentPage(makeRecent("/channels/channel-1/session/session-1?scratch=true"), currentHref, true), true);
});
test("resolveRecentPaletteItem uses exact palette items only as metadata, not as the final recent label", () => {
    const exactItem = makeItem({
        id: "ch-channel-1",
        label: "Chat · #quality-assurance",
        href: "/channels/channel-1",
        hint: "slack",
    });
    const resolved = resolveRecentPaletteItem(makeRecent("/channels/channel-1", "stale label"), [exactItem], { channelNameById: new Map([["channel-1", "quality-assurance"]]) });
    assert.equal(resolved?.label, "Chat · #quality-assurance");
    assert.equal(resolved?.hint, "slack");
    assert.equal(resolved?.category, "Recent");
});
