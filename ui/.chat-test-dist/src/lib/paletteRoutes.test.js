import test from "node:test";
import assert from "node:assert/strict";
import { canonicalizePaletteHref, normalizePalettePathInput, resolvePaletteRoute, } from "./paletteRoutes.js";
test("canonicalizePaletteHref normalizes route aliases to their durable targets", () => {
    assert.equal(canonicalizePaletteHref("/profile"), "/settings/account");
    assert.equal(canonicalizePaletteHref("/channels"), "/");
    assert.equal(canonicalizePaletteHref("/admin/widget-packages/pkg-1"), "/widgets/dev?id=pkg-1#templates");
    assert.equal(canonicalizePaletteHref("/admin/upcoming"), "/admin/tasks?view=list");
});
test("resolvePaletteRoute marks channel run overlays as valid but not recordable recents", () => {
    const route = resolvePaletteRoute("/channels/channel-1/runs/task-1");
    assert.equal(route?.canonicalHref, "/channels/channel-1/runs/task-1");
    assert.equal(route?.recordable, false);
    assert.equal(route?.routeKind, "channel-run");
});
test("resolvePaletteRoute formats admin detail fallbacks as typed labels instead of naked guids", () => {
    const route = resolvePaletteRoute("/admin/providers/provider-123456789");
    assert.deepEqual(route && {
        label: route.label,
        hint: route.hint,
        category: route.category,
        routeKind: route.routeKind,
    }, {
        label: "Provider · provider…",
        hint: "Configure",
        category: "Configure",
        routeKind: "admin-provider",
    });
});
test("normalizePalettePathInput accepts both raw app paths and copied app urls", () => {
    assert.equal(normalizePalettePathInput("/widgets/dev?id=widget-1#templates"), "/widgets/dev?id=widget-1#templates");
    assert.equal(normalizePalettePathInput("https://app.example.test/admin/logs/trace-1"), "/admin/logs/trace-1");
});
test("normalizePalettePathInput rejects non-route queries", () => {
    assert.equal(normalizePalettePathInput("quality assurance"), null);
    assert.equal(normalizePalettePathInput("widget dashboard"), null);
});
